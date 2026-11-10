"""Pitch calibration: homography from image-relative coordinates (0..1) to pitch metres."""
import math
from collections.abc import Callable, Sequence

import numpy as np


class CalibrationError(ValueError):
    pass


Point = tuple[float, float]

LANDMARKS: dict[str, Callable[[float, float], Point]] = {
    "corner_near_left": lambda L, W: (0.0, 0.0),
    "corner_near_right": lambda L, W: (L, 0.0),
    "corner_far_right": lambda L, W: (L, W),
    "corner_far_left": lambda L, W: (0.0, W),
    "halfway_near": lambda L, W: (L / 2, 0.0),
    "halfway_far": lambda L, W: (L / 2, W),
    "centre_spot": lambda L, W: (L / 2, W / 2),
    "penalty_spot_left": lambda L, W: (11.0, W / 2),
    "penalty_spot_right": lambda L, W: (L - 11.0, W / 2),
}

MIN_IMAGE_TRIANGLE_AREA = 0.002  # fraction of the frame
MIN_PITCH_TRIANGLE_AREA_M2 = 1.0


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _signed_area(pts: Sequence[Point]) -> float:
    """Shoelace formula; positive when the points run counter-clockwise (y up)."""
    n = len(pts)
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2


def _has_collinear_triple(pts: Sequence[Point], min_area: float) -> bool:
    n = len(pts)
    return any(abs(_cross(pts[i], pts[j], pts[k])) / 2 < min_area
               for i in range(n) for j in range(i + 1, n) for k in range(j + 1, n))


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    d1, d2 = _cross(p3, p4, p1), _cross(p3, p4, p2)
    d3, d4 = _cross(p1, p2, p3), _cross(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def _is_simple_quad(pts: Sequence[Point]) -> bool:
    """No two non-adjacent edges cross: for a quad, edge 0-1 vs 2-3 and edge 1-2 vs 3-0."""
    return not (_segments_intersect(pts[0], pts[1], pts[2], pts[3])
                or _segments_intersect(pts[1], pts[2], pts[3], pts[0]))


def _solve_homography(src: Sequence[Point], dst: Sequence[Point]) -> np.ndarray:
    """Exact 4-point DLT in float64 (cv2.getPerspectiveTransform only takes float32, ~1e-5 m error)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    h = np.linalg.solve(np.array(rows, dtype=np.float64), np.array(rhs, dtype=np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def fit_homography(image_pts: list[Point], pitch_pts: list[Point]) -> np.ndarray:
    if len(image_pts) != 4 or len(pitch_pts) != 4:
        raise CalibrationError("Exactly 4 points are needed")
    img = [(float(x), float(y)) for x, y in image_pts]
    pitch = [(float(x), float(y)) for x, y in pitch_pts]
    if not all(math.isfinite(v) and 0.0 <= v <= 1.0 for p in img for v in p):
        raise CalibrationError("Image points must be inside the frame")
    if not all(math.isfinite(v) for p in pitch for v in p):
        raise CalibrationError("Pitch points must be finite numbers")
    if _has_collinear_triple(img, MIN_IMAGE_TRIANGLE_AREA) or _has_collinear_triple(pitch, MIN_PITCH_TRIANGLE_AREA_M2):
        raise CalibrationError("Three of the points are on one line; pick points spread around the pitch")
    img_up = [(x, 1.0 - y) for x, y in img]  # image y grows downward; flip so orientation matches the pitch
    if (not _is_simple_quad(img_up) or not _is_simple_quad(pitch)
            or (_signed_area(img_up) > 0) != (_signed_area(pitch) > 0)):
        raise CalibrationError("The points cross over; click them in the same order as the pitch points")
    return _solve_homography(img, pitch)


def project(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Map N×2 points through H; points behind the camera (homogeneous w <= 0) become NaN."""
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    hom = np.hstack([pts, np.ones((len(pts), 1))]) @ np.asarray(H, dtype=np.float64).T
    w = hom[:, 2]
    out = np.full((len(pts), 2), np.nan)
    ok = w > 0
    out[ok] = hom[ok, :2] / w[ok, None]
    return out
