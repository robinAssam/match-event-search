"""Graph tests on a small hand-made match, then on every downloaded match
(skipped if the data is not downloaded)."""
import networkx as nx
import pandas as pd
import pytest

from match_event_search import graph, loaders, tagging
from match_event_search.graph import following, possession_node


def toy_tags():
    """One half with two possessions; player A plays twice in a row, B then C reply."""
    rows = [  # id, possession, team, player, t
        ("e1", 1, "Home", "A", 0.0),
        ("e2", 1, "Home", "A", 1.5),
        ("e3", 1, "Away", "B", 2.0),
        ("e4", 2, "Away", "B", 4.0),
        ("e5", 2, "Away", "C", 9.0),
    ]
    tags = pd.DataFrame(rows, columns=["id", "possession", "team", "player", "t"])
    tags["index"] = range(1, len(tags) + 1)
    tags["match_id"], tags["period"], tags["x"] = 1, 1, 50.0
    tags["possession_team"] = tags.possession.map({1: "Home", 2: "Away"})
    tags["play_pattern"] = "Regular Play"
    matches = pd.DataFrame([{"match_id": 1, "match_date": "2023-08-19", "home_team": "Home",
                             "away_team": "Away", "home_score": 0, "away_score": 0}])
    return graph.build_graph(tags, matches)


def test_hierarchy_from_season_to_event():
    g = toy_tags()
    assert graph.parent(g, "e1") == possession_node(1, 1)
    assert graph.parent(g, possession_node(1, 1)) == graph.half_node(1, 1)
    assert graph.parent(g, graph.half_node(1, 1)) == graph.match_node(1)
    assert graph.parent(g, graph.match_node(1)) == graph.SEASON
    assert graph.events_in(g, graph.SEASON) == ["e1", "e2", "e3", "e4", "e5"]
    assert graph.events_in(g, possession_node(1, 2)) == ["e4", "e5"]


def test_next_edges_carry_time_and_possession_change():
    g = toy_tags()
    assert g.edges["e2", "e3", "next"] == {"dt": 0.5, "same_possession": True}
    assert g.edges["e3", "e4", "next"]["same_possession"] is False


def test_same_player_edges_skip_other_players():
    g = toy_tags()
    assert g.has_edge("e3", "e4", "same_player")  # B, across the possession change
    assert not g.has_edge("e2", "e3", "same_player")
    assert not g.has_edge("e4", "e5", "same_player")


def test_following_stops_at_time_limit_and_possession_change():
    g = toy_tags()
    assert list(following(g, "e1")) == [("e2", 1.5), ("e3", 2.0), ("e4", 4.0), ("e5", 9.0)]
    assert [e for e, _ in following(g, "e1", within_s=4.0)] == ["e2", "e3", "e4"]
    assert [e for e, _ in following(g, "e1", same_possession=True)] == ["e2", "e3"]
    assert [e for e, _ in following(g, "e3", key="same_player")] == ["e4"]


def test_tags_are_kept_in_a_table_by_event_id():
    g = toy_tags()
    assert g.graph["tags"].loc["e3", "player"] == "B"
    assert g.nodes["e3"] == {"kind": "event", "match_id": 1, "period": 1, "t": 2.0,
                             "possession": 1, "team": "Away", "player": "B"}


EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = sorted(int(p.stem) for p in EVENTS_DIR.glob("*.json")) if EVENTS_DIR.exists() else []
requires_data = pytest.mark.skipif(not DOWNLOADED, reason="no matches downloaded")
OPENING_GOAL_MATCH = 3895052


@pytest.fixture(scope="module")
def season():
    tags = pd.concat([tagging.tag_match(m) for m in DOWNLOADED], ignore_index=True)
    return graph.build_graph(tags, loaders.load_matches()), tags


def edges_of(g, key):
    return [(u, v, d) for u, v, k, d in g.edges(keys=True, data=True) if k == key]


@requires_data
def test_every_node_except_the_season_has_one_parent(season):
    g = season[0]
    contains = nx.DiGraph((u, v) for u, v, _ in edges_of(g, "contains"))
    assert nx.is_tree(contains)
    assert set(contains.nodes) == set(g.nodes)


@requires_data
def test_every_located_event_is_a_node_in_its_own_possession(season):
    g, tags = season
    located = tags[tags.x.notna()]
    assert sum(1 for _, d in g.nodes(data=True) if d["kind"] == "event") == len(located)
    for e in located.sample(500, random_state=0).itertuples():
        assert graph.parent(g, e.id) == possession_node(e.match_id, e.possession)


@requires_data
def test_one_next_edge_per_event_except_the_last_of_each_half(season):
    g, tags = season
    located = tags[tags.x.notna()]
    halves = located.groupby(["match_id", "period"]).ngroups
    assert len(edges_of(g, "next")) == len(located) - halves


@requires_data
def test_sequence_edges_go_forward_in_time_within_a_half(season):
    g = season[0]
    for key in ("next", "same_player"):
        for u, v, d in edges_of(g, key):
            assert d["dt"] >= 0
            assert g.nodes[u]["period"] == g.nodes[v]["period"]
            assert g.nodes[u]["match_id"] == g.nodes[v]["match_id"]
            if key == "same_player":
                assert g.nodes[u]["player"] == g.nodes[v]["player"]


@requires_data
def test_opening_goal_follows_the_turnover_after_10_5_seconds(season):
    g, tags = season
    t = tags.set_index("id")
    werner = t[(t.match_id == OPENING_GOAL_MATCH) & t.turnover & (t.player == "Timo Werner")
               & (t.minute == 22)].index[0]
    after = {t.loc[e, "action"] + ":" + t.loc[e, "player"]: s for e, s in following(g, werner, within_s=12)}
    assert after["shot:Jeremie Frimpong"] == pytest.approx(10.52, abs=0.01)
    assert "shot:Jeremie Frimpong" not in {t.loc[e, "action"] + ":" + t.loc[e, "player"]
                                          for e, _ in following(g, werner, within_s=10)}
    # Within Leipzig's possession only Kossonou's block follows; Xhaka's recovery starts a new one.
    assert [t.loc[e, "player"] for e, _ in following(g, werner, same_possession=True)] == ["Odilon Kossonou"]


US_TEAM, OTHER = "Bayer Leverkusen", "Borussia Dortmund"


def test_following_can_stop_when_the_ball_goes_dead():
    """A throw-in starts possession 3: with stop_at_restart the walk ends before it."""
    rows = [("e1", 0.0, 1, US_TEAM), ("e2", 1.0, 2, OTHER), ("e3", 5.0, 3, OTHER), ("e4", 6.0, 3, OTHER)]
    tags = pd.DataFrame(rows, columns=["id", "t", "possession", "team"])
    tags["player"] = ["A", "B", "B", "C"]
    tags["index"], tags["match_id"], tags["period"], tags["x"] = range(1, 5), 1, 1, 50.0
    tags["possession_team"] = tags.team
    tags["play_pattern"] = tags.possession.map({1: "Regular Play", 2: "Regular Play", 3: "From Throw In"})
    matches = pd.DataFrame([{"match_id": 1, "match_date": "2024-04-21", "home_team": US_TEAM, "away_team": OTHER,
                             "home_score": 0, "away_score": 0}])
    g = graph.build_graph(tags, matches)
    assert [e for e, _ in following(g, "e1")] == ["e2", "e3", "e4"]
    assert [e for e, _ in following(g, "e1", stop_at_restart=True)] == ["e2"]
    # Along same_player edges too: B's next action (e3) comes after the throw-in.
    assert [e for e, _ in following(g, "e2", key="same_player", stop_at_restart=True)] == []

