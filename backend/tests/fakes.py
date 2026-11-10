"""Test doubles shared across analysis tests."""

from collections.abc import Callable, Sequence

import numpy as np

from app.analysis.detector import BALL, PERSON, Detections


def make_detections(boxes: Sequence[tuple[float, float, float, float]], cls: Sequence[int], score: float = 0.9) -> Detections:
    """Build Detections from relative xyxy boxes and per-box classes."""
    return Detections(
        np.asarray(boxes, np.float32).reshape(-1, 4),
        np.full(len(boxes), score, np.float32),
        np.asarray(cls, np.int8),
    )


class ScriptedDetector:
    """Detector returning scripted Detections per call index (0 for the first frame, 1 for the next, ...).

    `script` is either a list of Detections (indices past the end yield no detections) or a callable
    `frame_index -> Detections`.
    """

    def __init__(self, script: Sequence[Detections] | Callable[[int], Detections]):
        self._script = script
        self.calls = 0

    def detect(self, frame_bgr: np.ndarray) -> Detections:
        i = self.calls
        self.calls += 1
        if callable(self._script):
            return self._script(i)
        return self._script[i] if i < len(self._script) else Detections.empty()


def two_players_and_ball(i: int) -> Detections:
    """Two players moving right at a constant speed plus a ball moving right, as a function of frame index."""
    dx = 0.01 * i
    boxes = [(0.10 + dx, 0.30, 0.18 + dx, 0.60), (0.40 + dx, 0.50, 0.48 + dx, 0.80), (0.20 + dx, 0.70, 0.22 + dx, 0.73)]
    return make_detections(boxes, [PERSON, PERSON, BALL])
