from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.paths import face_dir, model_dir

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
MATCH_THRESHOLD = 0.363
# YuNet's own score. 0.8 means the detector is 80% sure this is a face.
MIN_SCORE = 0.8
# On the 960px preview, a shorter side under 80px is too small to match in other photos.
MIN_FACE_PX = 80
# Sharpness of the face after it is scaled to the recognition size. Below this it is too blurred to reuse.
MIN_SHARPNESS = 80.0

_detector = None
_recognizer = None


def _download(url: str, dest: Path) -> None:
    if dest.is_file() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def ensure_models() -> tuple[Path, Path]:
    folder = model_dir()
    yunet = folder / "face_detection_yunet_2023mar.onnx"
    sface = folder / "face_recognition_sface_2021dec.onnx"
    _download(YUNET_URL, yunet)
    _download(SFACE_URL, sface)
    return yunet, sface


def _engines():
    global _detector, _recognizer
    if _detector is None or _recognizer is None:
        yunet, sface = ensure_models()
        _detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), MIN_SCORE, 0.3, 5000)
        _recognizer = cv2.FaceRecognizerSF.create(str(sface), "")
    return _detector, _recognizer


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return 0.0
    return float(np.dot(left, right) / denom)


def sharpness(face_bgr: np.ndarray) -> float:
    if face_bgr.size == 0:
        return 0.0
    sized = face_bgr
    if sized.shape[0] != 112 or sized.shape[1] != 112:
        sized = cv2.resize(sized, (112, 112), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _crop(image: np.ndarray, box: np.ndarray) -> Image.Image:
    height, width = image.shape[:2]
    x, y, w, h = [int(value) for value in box[:4]]
    pad_x, pad_y = int(w * 0.25), int(h * 0.25)
    x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
    x1, y1 = min(width, x + w + pad_x), min(height, y + h + pad_y)
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        crop = image
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def detect_faces(image_path: Path) -> list[dict]:
    detector, recognizer = _engines()
    encoded = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if image is None:
        return []
    height, width = image.shape[:2]
    scale = 960 / max(height, width)
    if scale < 1:
        image = cv2.resize(image, (int(width * scale), int(height * scale)))
        height, width = image.shape[:2]
    detector.setInputSize((width, height))
    _, found = detector.detect(image)
    if found is None:
        return []
    faces = []
    for box in found:
        score = float(box[14]) if len(box) > 14 else 0.0
        x, y, w, h = [float(value) for value in box[:4]]
        if score < MIN_SCORE or min(w, h) < MIN_FACE_PX:
            continue
        aligned = recognizer.alignCrop(image, box)
        if sharpness(aligned) < MIN_SHARPNESS:
            continue
        feature = recognizer.feature(aligned)
        embedding = np.asarray(feature, dtype=np.float32).reshape(-1)
        faces.append(
            {
                "embedding": embedding,
                "crop": _crop(image, box),
                "box": (
                    max(0.0, x / width),
                    max(0.0, y / height),
                    max(0.01, w / width),
                    max(0.01, h / height),
                ),
            }
        )
    return faces


def assign_cluster(conn, embedding: np.ndarray, crop: Image.Image) -> int:
    best_id = None
    best_score = MATCH_THRESHOLD
    rows = conn.execute("SELECT id, centroid FROM face_clusters").fetchall()
    vector = embedding.astype(np.float32)
    for row in rows:
        centroid = np.frombuffer(row["centroid"], dtype=np.float32)
        score = _cosine(vector, centroid)
        if score >= best_score:
            best_score = score
            best_id = int(row["id"])
    if best_id is None:
        cur = conn.execute(
            "INSERT INTO face_clusters (centroid, count) VALUES (?, 1)",
            (vector.tobytes(),),
        )
        best_id = int(cur.lastrowid)
        crop.save(face_dir() / f"{best_id}.jpg", format="JPEG", quality=85)
        return best_id
    row = conn.execute("SELECT centroid, count FROM face_clusters WHERE id = ?", (best_id,)).fetchone()
    count = int(row["count"])
    centroid = np.frombuffer(row["centroid"], dtype=np.float32)
    updated = (centroid * count + vector) / (count + 1)
    conn.execute(
        "UPDATE face_clusters SET centroid = ?, count = ? WHERE id = ?",
        (updated.astype(np.float32).tobytes(), count + 1, best_id),
    )
    return best_id


def set_avatar(cluster_id: int, image_path: Path, box: tuple[float, float, float, float]) -> None:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    x, y, box_w, box_h = box
    pad_x, pad_y = box_w * 0.25, box_h * 0.25
    left = max(0, int((x - pad_x) * width))
    top = max(0, int((y - pad_y) * height))
    right = min(width, int((x + box_w + pad_x) * width))
    bottom = min(height, int((y + box_h + pad_y) * height))
    if right <= left or bottom <= top:
        left, top, right, bottom = 0, 0, width, height
    image.crop((left, top, right, bottom)).save(face_dir() / f"{cluster_id}.jpg", format="JPEG", quality=85)


def merge_clusters(conn, keep_id: int, drop_id: int) -> int:
    if keep_id == drop_id:
        return keep_id
    keep = conn.execute("SELECT centroid, count, label FROM face_clusters WHERE id = ?", (keep_id,)).fetchone()
    drop = conn.execute("SELECT centroid, count, label FROM face_clusters WHERE id = ?", (drop_id,)).fetchone()
    if keep is None or drop is None:
        raise KeyError("Face not found")
    keep_vec = np.frombuffer(keep["centroid"], dtype=np.float32)
    drop_vec = np.frombuffer(drop["centroid"], dtype=np.float32)
    total = int(keep["count"]) + int(drop["count"])
    merged = ((keep_vec * int(keep["count"])) + (drop_vec * int(drop["count"]))) / max(total, 1)
    label = (keep["label"] or "").strip() or (drop["label"] or "").strip()
    conn.execute("UPDATE faces SET cluster_id = ? WHERE cluster_id = ?", (keep_id, drop_id))
    conn.execute(
        "UPDATE face_clusters SET centroid = ?, count = ?, label = ? WHERE id = ?",
        (merged.astype(np.float32).tobytes(), total, label, keep_id),
    )
    conn.execute("DELETE FROM face_clusters WHERE id = ?", (drop_id,))
    conn.commit()
    (face_dir() / f"{drop_id}.jpg").unlink(missing_ok=True)
    return keep_id


def index_photo_faces(conn, photo_id: int, image_path: Path) -> int:
    from app import db

    found = detect_faces(image_path)
    db.clear_faces(conn, photo_id)
    for face in found:
        cluster_id = assign_cluster(conn, face["embedding"], face["crop"])
        conn.execute(
            "INSERT INTO faces (photo_id, cluster_id, x, y, w, h) VALUES (?, ?, ?, ?, ?, ?)",
            (photo_id, cluster_id, *face["box"]),
        )
    db.mark_faces_done(conn, photo_id)
    conn.commit()
    return len(found)


def attach_boxes(conn, photo_id: int, image_path: Path) -> None:
    from app import db

    rows = conn.execute(
        """
        SELECT faces.id, face_clusters.centroid
        FROM faces
        JOIN face_clusters ON face_clusters.id = faces.cluster_id
        WHERE faces.photo_id = ? AND faces.x IS NULL
        ORDER BY faces.id
        """,
        (photo_id,),
    ).fetchall()
    if not rows or not image_path.is_file():
        return
    found = detect_faces(image_path)
    unused = set(range(len(found)))
    for row in rows:
        centroid = np.frombuffer(row["centroid"], dtype=np.float32)
        best_index = None
        best_score = -1.0
        for index in unused:
            score = _cosine(found[index]["embedding"], centroid)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is None:
            continue
        unused.remove(best_index)
        conn.execute(
            "UPDATE faces SET x = ?, y = ?, w = ?, h = ? WHERE id = ?",
            (*found[best_index]["box"], int(row["id"])),
        )
    conn.commit()
