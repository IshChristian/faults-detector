import numpy as np
import pyarrow as pa
import pytest

from app.analysis.metrics import (
    HEATMAP_SHAPE,
    foot_points,
    intensity_timeline,
    is_on_pitch,
    quality,
    team_shape,
    track_metrics,
)
from app.analysis.summary import build_summary
from app.analysis.tracks_io import TRACKS_SCHEMA

PITCH = (105.0, 68.0)


def _line(speeds_ms, fps=10, start=(10.0, 30.0), t0=0):
    """Track with one speed (m/s, along x) per entry, one sample per 1/fps s."""
    t = [t0]
    x = [start[0]]
    for v in speeds_ms:
        t.append(t[-1] + 1000 // fps)
        x.append(x[-1] + v / fps)
    xy = np.column_stack([x, np.full(len(x), start[1])])
    return np.array(t, dtype=np.int64), xy


def test_foot_points_is_bottom_centre():
    rows = {n: [0.0] for n in TRACKS_SCHEMA.names}
    rows.update(video_id=["v"], t_ms=[0], track_id=[1], cls=[0])
    rows.update(x1=[0.2], y1=[0.1], x2=[0.4], y2=[0.9], score=[0.9])
    table = pa.table(rows).cast(TRACKS_SCHEMA)
    np.testing.assert_allclose(foot_points(table), [[0.3, 0.9]], atol=1e-6)


def test_constant_speed_track_distance_and_top_speed():
    t, xy = _line([5.0] * 200)  # 20 s at 5 m/s
    m = track_metrics(t, xy, sprint_kmh=22.0, pitch=PITCH)
    assert m["distance_m"] == pytest.approx(100.0, abs=0.01)
    assert m["top_speed_kmh"] == pytest.approx(18.0, abs=0.01)
    assert m["sprint_count"] == 0
    assert m["band_seconds"]["run"] == pytest.approx(20.0, abs=0.01)
    assert m["band_seconds"]["walk"] == 0
    assert m["samples"] == 201


def test_spike_above_cap_is_excluded():
    t, xy = _line([2.0] * 200)
    clean = track_metrics(t, xy, 22.0, PITCH)
    xy = xy.copy()
    xy[100, 1] += 15.0  # one wild sample
    m = track_metrics(t, xy, 22.0, PITCH)
    assert abs(m["distance_m"] - clean["distance_m"]) < 1.0
    assert m["top_speed_kmh"] < 36.0
    assert m["top_speed_kmh"] == pytest.approx(7.2, abs=0.01)


def test_sprint_needs_one_second_above_threshold():
    short = [1.0] * 30 + [7.0] * 5 + [1.0] * 30  # 0.5 s at 25.2 km/h
    long = [1.0] * 30 + [7.0] * 20 + [1.0] * 30  # 2 s
    assert track_metrics(*_line(short), 20.0, PITCH)["sprint_count"] == 0
    assert track_metrics(*_line(long), 20.0, PITCH)["sprint_count"] == 1


def test_sprint_threshold_is_per_session():
    # 2 s at 17 km/h (4.72 m/s) between walks
    t, xy = _line([1.0] * 30 + [4.72] * 20 + [1.0] * 30)
    assert track_metrics(t, xy, 15.0, PITCH)["sprint_count"] == 1
    assert track_metrics(t, xy, 19.0, PITCH)["sprint_count"] == 0


def test_gaps_break_segments_without_teleport_distance():
    t1, xy1 = _line([2.0] * 49, start=(10.0, 30.0))  # 50 samples, 4.9 s
    t2, xy2 = _line([2.0] * 49, start=(50.0, 30.0), t0=int(t1[-1]) + 3000)
    m = track_metrics(np.concatenate([t1, t2]), np.vstack([xy1, xy2]), 22.0, PITCH)
    assert m["distance_m"] == pytest.approx(2 * 49 * 0.2, abs=0.01)
    assert m["top_speed_kmh"] == pytest.approx(7.2, abs=0.01)


def test_heatmap_sums_to_one_and_lands_in_right_cell():
    t = np.arange(4) * 100
    xy = np.array([[52.5, 34.0], [52.5, 34.0], [np.nan, np.nan], [200.0, -5.0]])
    m = track_metrics(t, xy, 22.0, PITCH)
    hm = np.array(m["heatmap"])
    assert hm.shape == HEATMAP_SHAPE == (13, 20)
    assert hm.sum() == pytest.approx(1.0)
    assert m["samples"] == 3
    assert hm[6, 10] == pytest.approx(2 / 3)
    assert hm[0, 19] == pytest.approx(1 / 3)  # clipped to the corner cell


def test_is_on_pitch_with_margin():
    assert is_on_pitch(np.column_stack([np.linspace(10, 90, 20), np.full(20, -1.5)]), PITCH)
    assert not is_on_pitch(np.column_stack([np.linspace(10, 90, 20), np.full(20, -5.0)]), PITCH)
    assert not is_on_pitch(np.full((3, 2), np.nan), PITCH)


def _team_tracks(n_a, n_b, seconds=10):
    tracks, teams = {}, {}
    for i in range(n_a + n_b):
        t = np.arange(0, seconds * 1000, 100, dtype=np.int64)
        xy = np.column_stack([np.full(len(t), 20.0 + 10 * i), np.full(len(t), 10.0 + 5 * i)])
        tracks[i] = (t, xy)
        teams[i] = "a" if i < n_a else "b"
    return tracks, teams


def test_team_shape_needs_three_players():
    tracks, teams = _team_tracks(3, 2)
    out = team_shape(tracks=tracks, teams=teams, pitch=PITCH)
    assert [w["t_ms"] for w in out] == [0]
    a = out[0]["a"]
    # a players at x 20,30,40 and y 10,15,20; centroid (30, 15)
    assert a["width_m"] == pytest.approx(10.0)
    assert a["depth_m"] == pytest.approx(20.0)
    assert a["compactness_m"] == pytest.approx((2 * np.hypot(10, 5) + 0) / 3)
    assert out[0]["b"] is None


def test_intensity_is_mean_speed_per_10s_window():
    t, xy = _line([2.0] * 100)  # 0-10 s at 7.2 km/h
    t2, xy2 = _line([4.0] * 100, start=(10.0, 40.0))  # 14.4 km/h
    off_t, off_xy = _line([9.0] * 100, start=(10.0, -30.0))  # off pitch, ignored
    tracks = {1: (t, xy), 2: (t2, xy2), 3: (off_t, off_xy)}
    teams = {1: "a", 2: "b", 3: "a"}
    out = intensity_timeline(tracks=tracks, teams=teams, pitch=PITCH)
    assert out[0]["t_ms"] == 0
    assert out[0]["mean_speed_kmh"] == pytest.approx(10.8, abs=0.1)
    # a window with no data yields None
    tracks = {1: (t, xy), 2: (t2 + 30000, xy2)}
    out = intensity_timeline(tracks=tracks, teams={1: "a", 2: "b"}, pitch=PITCH)
    assert [w["t_ms"] for w in out] == [0, 10000, 20000, 30000]
    assert out[1]["mean_speed_kmh"] is None


def test_quality_fraction_and_track_length():
    q = quality([0, 3, 4, 5], [2.0, 4.0], calibrated=True, min_players=4)
    assert q == {"frames_with_min_players": 0.5, "calibrated": True, "mean_track_length_s": 3.0}
    q = quality([], [], calibrated=False, min_players=4)
    assert q["frames_with_min_players"] == 0.0 and q["mean_track_length_s"] == 0.0


def test_summary_marks_distances_approximate():
    s = build_summary(
        duration_ms=60000,
        sample_fps=10.0,
        calibrated=True,
        quality={"frames_with_min_players": 0.9},
        teams_overview={"a": {"players_on_pitch_avg": 9.5, "distance_m_total": 1000.0, "heatmap": []}},
        intensity=[{"t_ms": 0, "mean_speed_kmh": 5.0}],
        team_shape=[],
        tracks_total=12,
        videos=[{"video_id": "v1", "t_offset_ms": 0}],
    )
    assert s["version"] == 1 and s["videos"] == [{"video_id": "v1", "t_offset_ms": 0}]
    assert s["teams"]["a"]["approximate"] is True
    assert s["intensity"]["approximate"] is True
    assert s["intensity"]["timeline"][0]["mean_speed_kmh"] == 5.0
    assert s["duration_ms"] == 60000 and s["tracks_total"] == 12


def _reference_top_speed(t_ms, xy_m, window_ms=1000):
    """Straightforward O(K^2) rolling 1 s mean of kept step speeds (the pre-optimisation algorithm)."""
    from app.analysis.metrics import _steps

    top = 0.0
    for seg_t, _start, end, _dist, _dt, kmh, kept in _steps(t_ms, xy_m):
        if not kept.any():
            continue
        k_end, k_kmh = end[kept], kmh[kept]
        if seg_t[-1] - seg_t[0] < window_ms:
            top = max(top, float(k_kmh.mean()))
            continue
        for te in k_end:
            if te - seg_t[0] < window_ms:
                continue
            in_win = (k_end <= te) & (k_end > te - window_ms)
            top = max(top, float(k_kmh[in_win].mean()))
    return top


def test_top_speed_matches_reference_on_random_track():
    rng = np.random.default_rng(7)
    n = 600
    t = np.cumsum(rng.integers(60, 140, n)).astype(np.int64)
    t[300:] += 2500  # a gap that splits the track into two segments
    xy = np.cumsum(rng.normal(0, 0.45, (n, 2)), axis=0) + [50.0, 30.0]
    xy[100:110] += 40.0  # teleport spikes, dropped by the speed cap
    got = track_metrics(t, xy, 19.0, PITCH)["top_speed_kmh"]
    assert got == pytest.approx(_reference_top_speed(t, xy), rel=1e-9)
    assert got > 0


def test_top_speed_is_fast_on_a_long_track():
    import time

    n = 54_000  # 90 minutes at 10 fps
    t = np.arange(n, dtype=np.int64) * 100
    xy = np.column_stack([np.cumsum(np.full(n, 0.3)) % 100, np.full(n, 30.0)])
    start = time.perf_counter()
    track_metrics(t, xy, 19.0, PITCH)
    assert time.perf_counter() - start < 10


def test_bands_do_not_overlap_when_sprint_threshold_is_below_14():
    t, xy = _line([1.5] * 50 + [2.5] * 50 + [3.5] * 50)  # 5.4, 9 and 12.6 km/h
    m = track_metrics(t, xy, 10.0, PITCH)
    bands = m["band_seconds"]
    assert bands["run"] == 0.0  # [10, 10) is empty
    assert bands["walk"] > 4.0 and bands["jog"] > 4.0 and bands["sprint"] > 4.0  # smoothing blurs the joins
    assert sum(bands.values()) == pytest.approx(15.0)  # moving time, nothing double-counted
