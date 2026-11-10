import numpy as np

from app.analysis.teams import assign_teams, torso_feature

RED = (200, 30, 30)
BLUE = (30, 40, 200)
YELLOW = (230, 220, 30)
GRASS = (30, 140, 30)


def _crop(shirt, grass_rows=4):
    """16x16 RGB crop: shirt colour with a band of grass at the bottom."""
    img = np.zeros((16, 16, 3), np.uint8)
    img[:] = shirt
    if grass_rows:
        img[16 - grass_rows :] = GRASS
    return img


def _jitter(shirt, i):
    return tuple(int(np.clip(c + (i % 3) - 1, 0, 255)) for c in shirt)


def _fixture():
    feats, frames = {}, {}
    colours = {}
    tid = 0
    for shirt, n in ((RED, 6), (BLUE, 6), (YELLOW, 1)):
        for i in range(n):
            tid += 1
            colours[tid] = shirt
            feats[tid] = torso_feature([_crop(_jitter(shirt, i)) for _ in range(5)])
            frames[tid] = 20
    return feats, frames, colours


def test_two_shirt_colours_split_into_a_and_b():
    feats, frames, colours = _fixture()
    teams = assign_teams(feats, frames)
    reds = {teams[t] for t, c in colours.items() if c == RED}
    blues = {teams[t] for t, c in colours.items() if c == BLUE}
    assert len(reds) == 1 and len(blues) == 1
    assert reds != blues
    assert reds | blues == {"a", "b"}
    # 6 vs 6 is a tie: "a" is the cluster with the lower L, i.e. blue
    assert blues == {"a"} and reds == {"b"}
    assert assign_teams(feats, frames) == teams


def test_larger_cluster_is_a():
    feats, frames, colours = _fixture()
    extra = max(feats) + 1
    feats[extra] = torso_feature([_crop(RED)] * 5)
    frames[extra] = 20
    teams = assign_teams(feats, frames)
    assert teams[1] == "a"
    assert teams[7] == "b"


def test_odd_colour_goes_to_other():
    feats, frames, colours = _fixture()
    referee = next(t for t, c in colours.items() if c == YELLOW)
    teams = assign_teams(feats, frames)
    assert teams[referee] == "other"
    assert sorted(set(teams.values())) == ["a", "b", "other"]


def test_grass_pixels_are_ignored():
    mostly_green = _crop(RED, grass_rows=11)  # 69% green
    clean = torso_feature([_crop(RED, grass_rows=0)])
    assert np.allclose(torso_feature([mostly_green]), clean, atol=1)
    feats, frames, colours = _fixture()
    feats[100] = torso_feature([mostly_green] * 5)
    frames[100] = 20
    teams = assign_teams(feats, frames)
    red_id = next(t for t, c in colours.items() if c == RED)
    assert teams[100] == teams[red_id]


def test_all_grass_gives_no_feature():
    assert torso_feature([_crop(GRASS, grass_rows=0)]) is None
    assert torso_feature([]) is None


def test_short_tracks_are_other():
    feats, frames, colours = _fixture()
    frames[1] = 9
    feats[2] = None
    teams = assign_teams(feats, frames)
    assert teams[1] == "other"
    assert teams[2] == "other"
    assert teams[3] != "other"


def test_too_few_tracks_are_all_other():
    feats, frames, _ = _fixture()
    keep = list(feats)[:3]
    teams = assign_teams({t: feats[t] for t in keep}, {t: frames[t] for t in keep})
    assert teams == {t: "other" for t in keep}
