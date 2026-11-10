"""The session summary.json document."""

SUMMARY_VERSION = 1


def build_summary(
    *,
    duration_ms: int,
    sample_fps: float,
    calibrated: bool,
    quality: dict,
    teams_overview: dict[str, dict],
    intensity: list[dict],
    team_shape: list[dict],
    tracks_total: int,
) -> dict:
    """Assemble summary.json. Distances and speeds come from projected video
    positions, so every block carrying them is flagged "approximate"."""
    return {
        "version": SUMMARY_VERSION,
        "duration_ms": duration_ms,
        "sample_fps": sample_fps,
        "calibrated": calibrated,
        "tracks_total": tracks_total,
        "quality": quality,
        # per team: players_on_pitch_avg, distance_m_total, heatmap
        "teams": {name: {**team, "approximate": True} for name, team in teams_overview.items()},
        "intensity": {"approximate": True, "timeline": intensity},
        "team_shape": team_shape,
    }
