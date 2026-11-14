"""Similar situations: the vectors on hand-made possessions, then the index on the real season."""
import numpy as np
import pandas as pd
import pytest

from match_event_search import graph, loaders
from match_event_search.config import SimilarityConfig
from match_event_search.similarity import SimilarityIndex, ball_path, describe_possession, summary


def possession(match_id, number, xs, ys, pattern="Regular Play", regain=True, shot=False, start_t=0.0):
    """A possession of passes along the given points, one second apart, ending in a shot if asked."""
    n = len(xs) - 1
    rows = []
    for i in range(n):
        is_shot = shot and i == n - 1
        rows.append({"match_id": match_id, "possession": number, "index": number * 100 + i, "t": start_t + i,
                     "team": "Bayer Leverkusen", "period": 1, "minute": 10, "second": i, "in_possession": True,
                     "action": "shot" if is_shot else "pass", "x": xs[i], "y": ys[i],
                     "end_x": np.nan if is_shot else xs[i + 1], "end_y": np.nan if is_shot else ys[i + 1],
                     "play_pattern": pattern, "regain": regain and i == 0, "box_entry": False,
                     "turnover": False, "xg": 0.3 if is_shot else np.nan,
                     "outcome_detail": "goal" if is_shot else "Complete"})
    return rows


def toy_tags():
    rows = (possession(1, 1, [60, 80, 100, 110], [40, 30, 35, 40], shot=True)       # counter through the middle
            + possession(1, 2, [61, 81, 101, 111], [41, 31, 36, 41], shot=False)    # the same route, no shot
            + possession(1, 3, [10, 20, 30, 40], [10, 10, 12, 15], pattern="From Goal Kick", regain=False))
    tags = pd.DataFrame(rows)
    return tags.set_index(pd.Index([f"e{i}" for i in range(len(tags))], name="id"))


def test_the_route_is_resampled_from_first_to_last_point():
    actions = toy_tags().query("possession == 1")
    path = ball_path(actions, points=10)
    assert path.shape == (10, 2)
    assert tuple(path[0]) == (60, 40) and tuple(path[-1]) == (100, 35)  # the shot, which adds no end point


def test_outcome_and_start_are_described():
    d = describe_possession(toy_tags().query("possession == 1"))
    assert d["outcome"] == {"box_entry": False, "shot": True, "goal": True, "xg": 0.3, "lost_ball": False}
    assert d["info"]["regain"] and d["info"]["actions"] == 3


def test_the_same_move_is_nearest_whatever_its_outcome():
    index = SimilarityIndex(toy_tags(), SimilarityConfig(min_actions=3))
    nearest = index.similar(1, 1, k=2)
    assert list(nearest.index) == [(1, 2), (1, 3)]  # itself is never returned
    assert nearest.distance.iloc[0] < nearest.distance.iloc[1]
    assert not nearest.loc[(1, 2)].shot  # the outcome did not count


def test_short_possessions_are_left_out_and_every_one_gets_k_neighbours():
    index = SimilarityIndex(toy_tags(), SimilarityConfig(min_actions=4))
    assert len(index.table) == 0
    index = SimilarityIndex(toy_tags())
    assert len(list(index.all_neighbours(2))) == 3 * 2


def test_summary_line():
    index = SimilarityIndex(toy_tags())
    assert summary(index.similar(1, 2, k=2)) == ("2 similar possessions: 0 reached the box, 1 ended in a shot "
                                                 "(0.30 xG), 1 in a goal, 0 in a lost ball")


EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = {int(p.stem) for p in EVENTS_DIR.glob("*.json")} if EVENTS_DIR.exists() else set()
requires_season = pytest.mark.skipif(not DOWNLOADED or not set(loaders.load_matches().match_id) <= DOWNLOADED,
                                     reason="season not downloaded")


@pytest.fixture(scope="module")
def season():
    return graph.season_graph()


@requires_season
def test_every_indexed_possession_has_five_similar_edges(season):
    index = season.graph["similarity"]
    similar = [(u, v) for u, v, k in season.edges(keys=True) if k == "similar"]
    assert len(similar) == len(index.table) * SimilarityConfig().neighbours
    assert all(u.startswith("possession:") and v.startswith("possession:") and u != v for u, v in similar)


@requires_season
def test_neighbours_start_the_same_way_far_more_often_than_by_chance(season):
    index = season.graph["similarity"]
    starts = (index.table.start + index.table.regain.astype(str)).to_numpy()
    same, chance = [], []
    for i in range(0, len(index.table), 25):
        nearest = index.similar(*index.table.index[i], k=10)
        same.append((nearest.start + nearest.regain.astype(str) == starts[i]).mean())
        chance.append((starts == starts[i]).mean())
    assert np.mean(same) > 0.9 > 0.5 > np.mean(chance)


@requires_season
def test_the_opening_goal_is_compared_with_quick_attacks_after_a_regain(season):
    nearest = season.graph["similarity"].similar(3895052, 44, k=10)  # Leverkusen 3-2 Leipzig, 22:55
    assert nearest.regain.all() and nearest.start.eq("Regular Play").all()
    assert nearest.duration_s.max() < 20
