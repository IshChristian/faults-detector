"""Per-track team assignment from torso colour.

Features are OpenCV 8-bit CIE Lab: L, a and b are all scaled to 0-255 (a and b
carry a +128 offset), not the 0-100 / -128..127 CIE scale. The 12.0 outlier
distance in ``assign_teams`` is Euclidean distance in this space.
Torso crops are RGB uint8 arrays.
"""

import cv2
import numpy as np
from scipy.cluster.vq import kmeans2

MIN_PIXELS = 20
MIN_OUTLIER_DISTANCE = 12.0
OUTLIER_MEDIAN_FACTOR = 2.0
MIN_ELIGIBLE_TRACKS = 4
# Grass on OpenCV's HSV scale (hue 0-179, saturation 0-255).
GRASS_HUE = (35, 85)
GRASS_MIN_SATURATION = 60


def torso_feature(crops: list[np.ndarray]) -> np.ndarray | None:
    """Median Lab (OpenCV 8-bit scale) of the non-grass pixels, or None if < 20 remain."""
    parts = []
    for crop in crops:
        rgb = np.ascontiguousarray(crop, dtype=np.uint8)
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).reshape(-1, 3)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).reshape(-1, 3)
        grass = (
            (hsv[:, 0] >= GRASS_HUE[0])
            & (hsv[:, 0] <= GRASS_HUE[1])
            & (hsv[:, 1] > GRASS_MIN_SATURATION)
        )
        parts.append(lab[~grass])
    if not parts:
        return None
    pixels = np.concatenate(parts)
    if len(pixels) < MIN_PIXELS:
        return None
    return np.median(pixels, axis=0).astype(np.float64)


def assign_teams(
    features: dict[int, np.ndarray | None],
    frames_count: dict[int, int],
    min_frames: int = 10,
) -> dict[int, str]:
    """Cluster eligible tracks into teams "a"/"b"; everything else is "other".

    "a" is the larger cluster; on a tie, the one with the lower L.
    """
    result = {tid: "other" for tid in features}
    eligible = [
        tid
        for tid, feat in features.items()
        if feat is not None and frames_count.get(tid, 0) >= min_frames
    ]
    if len(eligible) < MIN_ELIGIBLE_TRACKS:
        return result

    data = np.array([features[tid] for tid in eligible], dtype=np.float64)
    keep = np.arange(len(eligible))
    while True:
        centres, labels = kmeans2(data[keep], 2, minit="++", seed=0)
        # A singleton cluster is a lone far outlier (referee) that captured a
        # centroid: leave it as "other" and re-cluster the rest.
        singles = [lb for lb in (0, 1) if np.count_nonzero(labels == lb) == 1]
        if not singles or len(keep) - 1 < MIN_ELIGIBLE_TRACKS:
            break
        keep = keep[labels != singles[0]]
    eligible = [eligible[i] for i in keep]
    data = data[keep]
    distances = np.linalg.norm(data - centres[labels], axis=1)

    members: dict[int, list[int]] = {0: [], 1: []}
    for idx, label in enumerate(labels):
        members[int(label)].append(idx)

    kept: dict[int, list[int]] = {0: [], 1: []}
    for label, idxs in members.items():
        if not idxs:
            continue
        limit = max(MIN_OUTLIER_DISTANCE, OUTLIER_MEDIAN_FACTOR * float(np.median(distances[idxs])))
        kept[label] = [i for i in idxs if distances[i] <= limit]

    # Larger cluster is "a"; tie -> lower L (centre channel 0).
    order = sorted((0, 1), key=lambda lb: (-len(members[lb]), centres[lb][0]))
    for name, label in zip(("a", "b"), order):
        for i in kept[label]:
            result[eligible[i]] = name
    return result
