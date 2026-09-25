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
        _detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), 0.8, 0.3, 5000)
        _recognizer = cv2.FaceRecognizerSF.create(str(sface), "")
    return _detector, _recognizer


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return 0.0
    return float(np.dot(left, right) / denom)


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
        aligned = recognizer.alignCrop(image, box)
        feature = recognizer.feature(aligned)
        embedding = np.asarray(feature, dtype=np.float32).reshape(-1)
        faces.append({"embedding": embedding, "crop": _crop(image, box)})
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

    db.clear_faces(conn, photo_id)
    found = detect_faces(image_path)
    for face in found:
        cluster_id = assign_cluster(conn, face["embedding"], face["crop"])
        conn.execute(
            "INSERT INTO faces (photo_id, cluster_id) VALUES (?, ?)",
            (photo_id, cluster_id),
        )
    db.mark_faces_done(conn, photo_id)
    conn.commit()
    return len(found)
