from pathlib import Path

import numpy as np
import pytest

from app.analysis import detector as det
from app.analysis.detector import BALL, PERSON, Detections, detect_with_far_half_tiling

REAL_MODEL = Path(__file__).resolve().parents[2] / "models" / "rfdetr-nano.onnx"


def _dets(boxes, scores, classes) -> Detections:
    return Detections(
        xyxy=np.array(boxes, dtype=np.float32).reshape(-1, 4),
        score=np.array(scores, dtype=np.float32),
        cls=np.array(classes, dtype=np.int8),
    )


class ScriptedDetector:
    """Returns the scripted detections per call: first the full frame, then the tile."""

    def __init__(self, *results: Detections):
        self.results = list(results)
        self.frames: list[np.ndarray] = []

    def detect(self, frame_bgr: np.ndarray) -> Detections:
        self.frames.append(frame_bgr)
        return self.results[len(self.frames) - 1]


def test_detections_empty_has_right_shapes():
    e = Detections.empty()
    assert e.xyxy.shape == (0, 4) and e.xyxy.dtype == np.float32
    assert e.score.shape == (0,)
    assert e.cls.shape == (0,) and e.cls.dtype == np.int8


def test_tiling_merges_duplicate_boxes_with_nms():
    box = [0.40, 0.10, 0.45, 0.30]
    # Tile y is doubled: a frame box with y 0.10-0.30 is y 0.20-0.60 in the tile.
    tile_box = [0.40, 0.20, 0.45, 0.60]
    fake = ScriptedDetector(_dets([box], [0.8], [PERSON]), _dets([tile_box], [0.6], [PERSON]))
    out = detect_with_far_half_tiling(fake, np.zeros((100, 200, 3), np.uint8))
    assert len(out.score) == 1
    assert out.cls[0] == PERSON
    assert out.score[0] == pytest.approx(0.8)
    # Tile is the top half upscaled 2x.
    assert fake.frames[0].shape[:2] == (100, 200)
    assert fake.frames[1].shape[:2] == (100, 400)


def test_tiling_maps_tile_boxes_back_to_frame_coordinates():
    fake = ScriptedDetector(Detections.empty(), _dets([[0.5, 0.5, 0.6, 0.7]], [0.7], [PERSON]))
    out = detect_with_far_half_tiling(fake, np.zeros((100, 200, 3), np.uint8))
    assert len(out.score) == 1
    np.testing.assert_allclose(out.xyxy[0], [0.5, 0.25, 0.6, 0.35], atol=1e-6)


def test_tiling_nms_is_per_class():
    box = [0.4, 0.1, 0.45, 0.3]
    tile_box = [0.4, 0.2, 0.45, 0.6]
    fake = ScriptedDetector(_dets([box], [0.8], [PERSON]), _dets([tile_box], [0.6], [BALL]))
    out = detect_with_far_half_tiling(fake, np.zeros((100, 200, 3), np.uint8))
    assert sorted(out.cls.tolist()) == [PERSON, BALL]


def test_postprocess_filters_classes_and_threshold():
    logits = np.full((1, 4, 91), -10.0, dtype=np.float32)
    logits[0, 0, 1] = 5.0   # person, confident
    logits[0, 1, 37] = 5.0  # sports ball, confident
    logits[0, 2, 1] = -2.0  # person, below threshold
    logits[0, 3, 5] = 5.0   # other class, dropped
    boxes = np.array([[[0.5, 0.5, 0.2, 0.4], [0.1, 0.2, 0.02, 0.04],
                       [0.5, 0.5, 0.1, 0.1], [0.5, 0.5, 0.1, 0.1]]], dtype=np.float32)
    out = det._postprocess(boxes, logits, {"person": 1, "sports ball": 37}, 0.3)
    assert out.cls.tolist() == [PERSON, BALL]
    np.testing.assert_allclose(out.xyxy[0], [0.4, 0.3, 0.6, 0.7], atol=1e-6)
    np.testing.assert_allclose(out.xyxy[1], [0.09, 0.18, 0.11, 0.22], atol=1e-6)
    assert out.score[0] == pytest.approx(1 / (1 + np.exp(-5.0)), rel=1e-5)
    assert out.xyxy.dtype == np.float32 and out.cls.dtype == np.int8


def test_postprocess_nothing_above_threshold_is_empty():
    logits = np.full((1, 2, 91), -10.0, dtype=np.float32)
    boxes = np.zeros((1, 2, 4), dtype=np.float32)
    out = det._postprocess(boxes, logits, {"person": 1, "sports ball": 37}, 0.3)
    assert out.xyxy.shape == (0, 4)


def test_missing_model_raises_clear_error(monkeypatch, tmp_path):
    missing = tmp_path / "nope.onnx"
    monkeypatch.setattr(det.get_settings(), "analysis_model_path", missing)
    with pytest.raises(RuntimeError, match="Detection model not found at .*nope.onnx.*plan 2 Task 5"):
        det.get_detector()


@pytest.mark.model
@pytest.mark.skipif(not REAL_MODEL.exists(), reason="models/rfdetr-nano.onnx not present")
def test_onnx_detector_finds_people_on_real_frame():
    import subprocess

    import cv2

    footage = Path.home() / "vg-footage" / "test-session.mp4"
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "60", "-i", str(footage), "-frames:v", "1",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        check=True, capture_output=True,
    ).stdout
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    out = det.OnnxRfDetr(REAL_MODEL).detect(frame)
    assert int((out.cls == PERSON).sum()) >= 5


def test_tiling_drops_tile_boxes_clipped_by_the_tile_bottom_edge():
    # A player straddling the frame's middle: the tile sees only their top half (box ends on the tile's edge).
    # That clipped box overlaps the full-frame box with IoU < 0.5, so NMS alone would keep a duplicate person.
    full_box = [0.40, 0.40, 0.45, 0.70]
    clipped = [0.40, 0.80, 0.45, 0.999]  # tile-relative; tile is 100 px tall, so within 1 px of the bottom
    fake = ScriptedDetector(_dets([full_box], [0.8], [PERSON]), _dets([clipped], [0.9], [PERSON]))
    out = detect_with_far_half_tiling(fake, np.zeros((100, 200, 3), np.uint8))
    assert len(out.score) == 1
    np.testing.assert_allclose(out.xyxy[0], full_box, atol=1e-6)


def test_tiling_keeps_tile_boxes_that_end_above_the_edge():
    near_edge = [0.10, 0.80, 0.15, 0.97]  # 3 px above the tile's bottom edge
    fake = ScriptedDetector(Detections.empty(), _dets([near_edge], [0.9], [PERSON]))
    out = detect_with_far_half_tiling(fake, np.zeros((100, 200, 3), np.uint8))
    assert len(out.score) == 1
