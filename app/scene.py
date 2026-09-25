from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import numpy as np

from app.paths import model_dir

MODEL_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/object_detection_yolox/object_detection_yolox_2022nov.onnx"
CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)

_detector = None


def _model_path() -> Path:
    dest = model_dir() / "object_detection_yolox_2022nov.onnx"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.replace(dest)
    return dest


class _YoloX:
    def __init__(self, model_path: Path) -> None:
        self.net = cv2.dnn.readNet(str(model_path))
        self.input_size = (640, 640)
        self.strides = (8, 16, 32)
        self.conf_threshold = 0.35
        self.nms_threshold = 0.5
        grids = []
        expanded = []
        for stride in self.strides:
            height = self.input_size[0] // stride
            width = self.input_size[1] // stride
            xv, yv = np.meshgrid(np.arange(height), np.arange(width))
            grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
            grids.append(grid)
            expanded.append(np.full((*grid.shape[:2], 1), stride))
        self.grids = np.concatenate(grids, 1)
        self.expanded_strides = np.concatenate(expanded, 1)

    def detect(self, image: np.ndarray) -> list[str]:
        padded, _ratio = self._letterbox(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        blob = np.transpose(padded, (2, 0, 1))[np.newaxis, :, :, :]
        self.net.setInput(blob)
        outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())[0][0]
        boxes, scores, class_ids = self._decode(outputs)
        if not scores:
            return []
        keep = cv2.dnn.NMSBoxesBatched(boxes, scores, class_ids, self.conf_threshold, self.nms_threshold)
        if keep is None or len(keep) == 0:
            return []
        names: list[str] = []
        for index in np.array(keep).reshape(-1):
            label = CLASSES[class_ids[int(index)]]
            if label not in names:
                names.append(label)
        return names

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        target_h, target_w = self.input_size
        padded = np.ones((target_h, target_w, 3), dtype=np.float32) * 114.0
        ratio = min(target_h / image.shape[0], target_w / image.shape[1])
        resized = cv2.resize(image, (int(image.shape[1] * ratio), int(image.shape[0] * ratio))).astype(np.float32)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        return padded, ratio

    def _decode(self, dets: np.ndarray) -> tuple[list, list, list]:
        dets = dets.copy()
        dets[:, :2] = (dets[:, :2] + self.grids) * self.expanded_strides
        dets[:, 2:4] = np.exp(dets[:, 2:4]) * self.expanded_strides
        boxes = np.ones_like(dets[:, :4])
        boxes[:, 0] = dets[:, 0] - dets[:, 2] / 2
        boxes[:, 1] = dets[:, 1] - dets[:, 3] / 2
        boxes[:, 2] = dets[:, 2]
        boxes[:, 3] = dets[:, 3]
        scores = dets[:, 4:5] * dets[:, 5:]
        max_scores = np.amax(scores, axis=1)
        class_ids = np.argmax(scores, axis=1)
        keep = max_scores >= self.conf_threshold
        return boxes[keep].tolist(), max_scores[keep].tolist(), class_ids[keep].astype(int).tolist()


def _engine() -> _YoloX:
    global _detector
    if _detector is None:
        _detector = _YoloX(_model_path())
    return _detector


def detect_scene(image_path: Path) -> str:
    encoded = np.fromfile(str(image_path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if image is None:
        return ""
    return ", ".join(_engine().detect(image))
