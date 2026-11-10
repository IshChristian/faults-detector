"""Per-track and team metrics from projected pitch positions (metres)."""

from collections.abc import Mapping

import numpy as np
import pyarrow as pa

SPEED_CAP_KMH = 36.0
WALK_MAX_KMH = 7.0
JOG_MAX_KMH = 14.0
GAP_BREAK_S = 1.0
SMOOTH_WINDOW = 5  # samples
SPRINT_MIN_S = 1.0
PITCH_MARGIN_M = 2.0
ON_PITCH_MIN_FRACTION = 0.5
HEATMAP_SHAPE = (13, 20)  # rows across the width, columns along the length
WINDOW_S = 10
TOP_SPEED_WINDOW_S = 1.0
MIN_TEAM_TRACKS = 3

TrackArrays = tuple[np.ndarray, np.ndarray]  # (t_ms (N,), xy_m (N, 2))


def foot_points(table: pa.Table) -> np.ndarray:
    """Bottom-centre of each box as an (N, 2) array of relative image coordinates."""
    x1 = table.column("x1").to_numpy().astype(float)
    x2 = table.column("x2").to_numpy().astype(float)
    y2 = table.column("y2").to_numpy().astype(float)
    return np.column_stack([(x1 + x2) / 2.0, y2])


def _smooth(xy: np.ndarray) -> np.ndarray:
    """Centred moving average; the window shrinks symmetrically at the edges."""
    n = len(xy)
    half = SMOOTH_WINDOW // 2
    out = np.empty_like(xy)
    for i in range(n):
        h = min(half, i, n - 1 - i)
        out[i] = xy[i - h : i + h + 1].mean(axis=0)
    return out


def _segments(t_ms: np.ndarray, xy_m: np.ndarray):
    """Yield (t_ms, smoothed xy) for each gap-free run of non-NaN samples."""
    t_ms = np.asarray(t_ms, dtype=np.int64)
    xy_m = np.asarray(xy_m, dtype=float)
    ok = ~np.isnan(xy_m).any(axis=1)
    t_ms, xy_m = t_ms[ok], xy_m[ok]
    if len(t_ms) == 0:
        return
    order = np.argsort(t_ms, kind="stable")
    t_ms, xy_m = t_ms[order], xy_m[order]
    cuts = np.flatnonzero(np.diff(t_ms) > GAP_BREAK_S * 1000) + 1
    for lo, hi in zip(np.r_[0, cuts], np.r_[cuts, len(t_ms)]):
        yield t_ms[lo:hi], _smooth(xy_m[lo:hi])


def _steps(t_ms: np.ndarray, xy_m: np.ndarray):
    """Per-segment step data: (seg_t, step_start_ms, step_end_ms, dist_m, dt_s, kmh, kept)."""
    for seg_t, seg_xy in _segments(t_ms, xy_m):
        if len(seg_t) < 2:
            continue
        dt = np.diff(seg_t) / 1000.0
        dist = np.linalg.norm(np.diff(seg_xy, axis=0), axis=1)
        valid = dt > 0
        kmh = np.where(valid, dist / np.where(valid, dt, 1.0) * 3.6, np.inf)
        yield seg_t, seg_t[:-1], seg_t[1:], dist, dt, kmh, kmh <= SPEED_CAP_KMH


def _heatmap(xy_m: np.ndarray, pitch: tuple[float, float]) -> np.ndarray:
    rows, cols = HEATMAP_SHAPE
    hm = np.zeros(HEATMAP_SHAPE)
    pts = xy_m[~np.isnan(xy_m).any(axis=1)]
    if len(pts) == 0:
        return hm
    c = np.clip((pts[:, 0] / pitch[0] * cols).astype(int), 0, cols - 1)
    r = np.clip((pts[:, 1] / pitch[1] * rows).astype(int), 0, rows - 1)
    np.add.at(hm, (r, c), 1.0)
    return hm / len(pts)


def track_metrics(
    t_ms: np.ndarray, xy_m: np.ndarray, sprint_kmh: float, pitch: tuple[float, float]
) -> dict:
    """Distance, speed bands, sprints, mean position and heatmap for one track.

    Bands are [lo, hi) in km/h; a sprint is a run of consecutive kept steps
    at or above `sprint_kmh` lasting at least SPRINT_MIN_S. Steps above the
    speed cap are excluded from distance, bands, top speed and end any run.
    """
    xy_m = np.asarray(xy_m, dtype=float)
    distance = 0.0
    bands = {"walk": 0.0, "jog": 0.0, "run": 0.0, "sprint": 0.0}
    top = 0.0
    sprints = 0
    for seg_t, _start, end, dist, dt, kmh, kept in _steps(t_ms, xy_m):
        distance += float(dist[kept].sum())
        for lo, hi, name in (
            (0.0, WALK_MAX_KMH, "walk"),
            (WALK_MAX_KMH, JOG_MAX_KMH, "jog"),
            (JOG_MAX_KMH, sprint_kmh, "run"),
            (sprint_kmh, np.inf, "sprint"),
        ):
            bands[name] += float(dt[kept & (kmh >= lo) & (kmh < hi)].sum())
        if kept.any():
            k_end, k_kmh = end[kept], kmh[kept]
            if seg_t[-1] - seg_t[0] < TOP_SPEED_WINDOW_S * 1000:
                top = max(top, float(k_kmh.mean()))
            else:
                for te in k_end:
                    if te - seg_t[0] < TOP_SPEED_WINDOW_S * 1000:
                        continue
                    in_win = (k_end <= te) & (k_end > te - TOP_SPEED_WINDOW_S * 1000)
                    top = max(top, float(k_kmh[in_win].mean()))
        run = 0.0
        for fast, ok, step_dt in zip(kmh >= sprint_kmh, kept, dt):
            if ok and fast:
                run += step_dt
                continue
            sprints += run >= SPRINT_MIN_S - 1e-9
            run = 0.0
        sprints += run >= SPRINT_MIN_S - 1e-9
    valid = ~np.isnan(xy_m).any(axis=1)
    return {
        "distance_m": distance,
        "top_speed_kmh": top,
        "band_seconds": bands,
        "sprint_count": int(sprints),
        "avg_x_m": float(xy_m[valid, 0].mean()) if valid.any() else None,
        "avg_y_m": float(xy_m[valid, 1].mean()) if valid.any() else None,
        "heatmap": _heatmap(xy_m, pitch).tolist(),
        "samples": int(valid.sum()),
    }


def is_on_pitch(xy_m: np.ndarray, pitch: tuple[float, float]) -> bool:
    """True when >= ON_PITCH_MIN_FRACTION of non-NaN points lie within the pitch plus margin."""
    pts = np.asarray(xy_m, dtype=float)
    pts = pts[~np.isnan(pts).any(axis=1)]
    if len(pts) == 0:
        return False
    m = PITCH_MARGIN_M
    inside = (
        (pts[:, 0] >= -m)
        & (pts[:, 0] <= pitch[0] + m)
        & (pts[:, 1] >= -m)
        & (pts[:, 1] <= pitch[1] + m)
    )
    return bool(inside.mean() >= ON_PITCH_MIN_FRACTION)


def _team_tracks(
    tracks: Mapping[int, TrackArrays], teams: Mapping[int, str], pitch: tuple[float, float]
) -> dict[int, tuple[str, TrackArrays]]:
    """On-pitch tracks that belong to team 'a' or 'b'."""
    return {
        tid: (teams[tid], (np.asarray(t), np.asarray(xy, dtype=float)))
        for tid, (t, xy) in tracks.items()
        if teams.get(tid) in ("a", "b") and is_on_pitch(xy, pitch)
    }


def team_shape(
    *,
    tracks: Mapping[int, TrackArrays],
    teams: Mapping[int, str],
    pitch: tuple[float, float],
    window_s: int = WINDOW_S,
) -> list[dict]:
    """Team shape per window.

    `tracks` maps track_id to (t_ms, xy_m); `teams` maps track_id to "a"/"b"
    (other values and unmapped tracks are ignored). Returns one entry per
    window from 0 to the last sample: {"t_ms", "a", "b"}, where each team is
    {"width_m" (y range), "depth_m" (x range), "compactness_m" (mean distance
    to centroid)} of the tracks' mean positions in that window, or None when
    fewer than MIN_TEAM_TRACKS on-pitch tracks have samples there.
    """
    w_ms = window_s * 1000
    members = _team_tracks(tracks, teams, pitch)
    if not members:
        return []
    last = max(int(t.max()) for _, (t, _) in members.values() if len(t))
    out = []
    for start in range(0, last // w_ms * w_ms + 1, w_ms):
        entry: dict = {"t_ms": start, "a": None, "b": None}
        for team in ("a", "b"):
            means = []
            for tm, (t, xy) in members.values():
                if tm != team:
                    continue
                sel = (t >= start) & (t < start + w_ms) & ~np.isnan(xy).any(axis=1)
                if sel.any():
                    means.append(xy[sel].mean(axis=0))
            if len(means) >= MIN_TEAM_TRACKS:
                pts = np.array(means)
                centroid = pts.mean(axis=0)
                entry[team] = {
                    "width_m": float(np.ptp(pts[:, 1])),
                    "depth_m": float(np.ptp(pts[:, 0])),
                    "compactness_m": float(np.linalg.norm(pts - centroid, axis=1).mean()),
                }
        out.append(entry)
    return out


def intensity_timeline(
    *,
    tracks: Mapping[int, TrackArrays],
    teams: Mapping[int, str],
    pitch: tuple[float, float],
    window_s: int = WINDOW_S,
) -> list[dict]:
    """Mean kept step speed (km/h) per window over on-pitch team a/b tracks.

    Same inputs as `team_shape`. A step belongs to the window of its start
    time. Returns [{"t_ms": window_start, "mean_speed_kmh": float | None}]
    for every window from 0 to the last step; None where no steps fall.
    """
    w_ms = window_s * 1000
    starts, speeds = [], []
    for _tm, (t, xy) in _team_tracks(tracks, teams, pitch).values():
        for _seg, step_start, _end, _dist, _dt, kmh, kept in _steps(t, xy):
            starts.append(step_start[kept])
            speeds.append(kmh[kept])
    if not starts or sum(len(s) for s in starts) == 0:
        return []
    starts_all, speeds_all = np.concatenate(starts), np.concatenate(speeds)
    idx = starts_all // w_ms
    return [
        {
            "t_ms": int(i * w_ms),
            "mean_speed_kmh": float(speeds_all[idx == i].mean()) if (idx == i).any() else None,
        }
        for i in range(int(idx.max()) + 1)
    ]


def quality(
    persons_per_frame: list[int],
    track_lengths_s: list[float],
    calibrated: bool,
    min_players: int,
) -> dict:
    n = len(persons_per_frame)
    frames = sum(1 for p in persons_per_frame if p >= min_players) / n if n else 0.0
    mean_len = float(np.mean(track_lengths_s)) if track_lengths_s else 0.0
    return {
        "frames_with_min_players": frames,
        "calibrated": calibrated,
        "mean_track_length_s": mean_len,
    }
