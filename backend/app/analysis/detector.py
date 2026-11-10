"""Person/ball detection: the Detector interface, the ONNX RF-DETR runner and far-half tiling."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import onnxruntime as ort

from app.config import get_settings

PERSON, BALL = 0, 1

_NMS_IOU = 0.5


@dataclass(frozen=True)
class Detections:
    xyxy: np.ndarray  # (N, 4) float32, relative 0-1
    score: np.ndarray  # (N,)
    cls: np.ndarray  # (N,) int8, PERSON | BALL

    @staticmethod
    def empty() -> "Detections":
        return Detections(np.zeros((0, 4), np.float32), np.zeros((0,), np.float32), np.zeros((0,), np.int8))


class Detector(Protocol):
    def detect(self, frame_bgr: np.ndarray) -> Detections: ...


def _postprocess(boxes: np.ndarray, logits: np.ndarray, class_ids: dict[str, int], threshold: float) -> Detections:
    """Raw model outputs (1,Q,4 cxcywh normalised; 1,Q,C logits) -> person/ball Detections (xyxy relative)."""
    boxes, logits = boxes[0], logits[0]
    scores = 1.0 / (1.0 + np.exp(-logits.astype(np.float64)))
    parts = []
    for name, ours in (("person", PERSON), ("sports ball", BALL)):
        s = scores[:, class_ids[name]]
        keep = np.flatnonzero(s >= threshold)
        cx, cy, w, h = boxes[keep].astype(np.float64).T
        xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
        parts.append((np.clip(xyxy, 0.0, 1.0), s[keep], np.full(len(keep), ours)))
    xyxy = np.concatenate([p[0] for p in parts]).astype(np.float32).reshape(-1, 4)
    score = np.concatenate([p[1] for p in parts]).astype(np.float32)
    cls = np.concatenate([p[2] for p in parts]).astype(np.int8)
    return Detections(xyxy, score, cls)


class OnnxRfDetr:
    """RF-DETR exported to ONNX; model_path's sibling .json holds the metadata (see Task 12 export)."""

    def __init__(self, model_path: Path, threshold: float = 0.3):
        meta = json.loads(model_path.with_suffix(".json").read_text())
        if meta.get("box_format") != "cxcywh_norm":
            raise RuntimeError(f"Unsupported box_format {meta.get('box_format')!r}")
        self._meta = meta
        self._threshold = threshold
        self._size = int(meta["resolution"])
        self._mean = np.array(meta["mean"], np.float32).reshape(1, 1, 3)
        self._std = np.array(meta["std"], np.float32).reshape(1, 1, 3)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = os.cpu_count() or 1
        self._session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])

    def detect(self, frame_bgr: np.ndarray) -> Detections:
        rgb = cv2.cvtColor(cv2.resize(frame_bgr, (self._size, self._size)), cv2.COLOR_BGR2RGB)
        x = (rgb.astype(np.float32) / 255.0 - self._mean) / self._std
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        boxes, logits = self._session.run(
            [self._meta["boxes_output"], self._meta["logits_output"]], {self._meta["input_name"]: x}
        )
        return _postprocess(boxes, logits, self._meta["class_ids"], self._threshold)


def detect_with_far_half_tiling(detector: Detector, frame_bgr: np.ndarray) -> Detections:
    """Detect on the full frame and on the top half upscaled 2x (far players are small), merged per class by NMS."""
    h, w = frame_bgr.shape[:2]
    full = detector.detect(frame_bgr)
    tile = cv2.resize(frame_bgr[: h // 2], (w * 2, (h // 2) * 2), interpolation=cv2.INTER_LINEAR)
    t = detector.detect(tile)
    # A box ending within 1 px of the tile's bottom edge is clipped (someone straddling the middle of the frame):
    # its IoU with the full-frame box is too low for NMS to merge them, so drop it and keep the full-frame one.
    whole = t.xyxy[:, 3] < 1.0 - 1.0 / tile.shape[0]
    # The tile spans the full width and the top half of the frame: only y shrinks, by 2.
    t_xyxy = t.xyxy[whole].copy()
    t_xyxy[:, [1, 3]] *= 0.5
    xyxy = np.concatenate([full.xyxy, t_xyxy]).astype(np.float32)
    score = np.concatenate([full.score, t.score[whole]]).astype(np.float32)
    cls = np.concatenate([full.cls, t.cls[whole]]).astype(np.int8)
    keep_all: list[int] = []
    for c in (PERSON, BALL):
        idx = np.flatnonzero(cls == c)
        if len(idx) == 0:
            continue
        b = xyxy[idx]
        rects = np.stack([b[:, 0], b[:, 1], b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]], axis=1).tolist()
        kept = cv2.dnn.NMSBoxes(rects, score[idx].tolist(), 0.0, _NMS_IOU)
        keep_all.extend(idx[np.asarray(kept, dtype=int).reshape(-1)].tolist())
    keep = np.array(sorted(keep_all), dtype=int)
    return Detections(xyxy[keep], score[keep], cls[keep])


def get_detector() -> Detector:
    settings = get_settings()
    path = settings.analysis_model_path
    if not path.exists():
        raise RuntimeError(f"Detection model not found at {path}; see plan 2 Task 5")
    return OnnxRfDetr(path, settings.analysis_threshold)
