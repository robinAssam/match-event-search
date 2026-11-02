"""Query tests: the schema, the engine on a hand-made match, and the example
questions on the real season (skipped if the data is not downloaded)."""
import pandas as pd
import pytest

from match_event_search import graph, loaders, tagging
from match_event_search.query import QueryError, find, search, validate

US, THEM = "Bayer Leverkusen", "Opponent FC"

TURNOVER_TO_SHOT = {"sequence": [
    {"filter": {"turnover": True, "our_team": True, "half": "own"}},
    {"filter": {"action": "shot"}, "team": "other", "within_s": 10},
]}


# --- Schema ----------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    {"event": {"action": "pass", "progressive": True, "role_group": "FB", "role_side": "left",
               "our_team": True, "minute": {"gte": 60}}},
    {"event": {"action": ["pass", "carry"], "minute": [60, 61], "player": "Florian Wirtz"}},
    TURNOVER_TO_SHOT,
    {"sequence": [{"filter": {"regain": True}},
                  {"filter": {"action": "shot"}, "same_possession": True, "via": "same_player"}],
     "matches": {"opponent": "Bayern Munich", "venue": "home"}},
])
def test_valid_queries(query):
    validate(query)


@pytest.mark.parametrize("query, message", [
    ({"event": {"third": "atacking"}}, "'atacking' is not one of"),
    ({"event": {"third": ["middle", "atacking"]}}, "event/third/1"),
    ({"event": {"colour": "red"}}, "'colour' was unexpected"),
    ({"event": {"minute": {"after": 60}}}, "'after' was unexpected"),
    ({"event": {"progressive": "yes"}}, "not of type 'boolean'"),
    ({"event": {}}, "should be non-empty"),
    ({}, 'either "event" or "sequence"'),
    ({"sequence": [{"filter": {"turnover": True}}, {"filter": {"action": "shot"}}]}, '"within_s" or'),
    ({"sequence": [{"filter": {"turnover": True}},
                   {"filter": {"action": "shot"}, "same_possession": False}]}, '"within_s" or'),
    ({"sequence": [{"filter": {"turnover": True}, "within_s": 5},
                   {"filter": {"action": "shot"}, "within_s": 5}]}, "'within_s' was unexpected"),
    ({"sequence": [{"filter": {"turnover": True}}]}, "too short"),
])
def test_invalid_queries_say_what_is_wrong(query, message):
    with pytest.raises(QueryError, match=message):
        validate(query)


# --- Engine on a hand-made match -----------------------------------------------------

def toy_graph():
    """We lose the ball (e1); they win it (e2) and shoot after 9 s (e4); we shoot later (e6)."""
    rows = [  # id, t, possession, team, player, action, extra tags
        ("e1", 0.0, 1, US, "A", "pass", {"turnover": True, "half": "own"}),
        ("e2", 1.0, 2, THEM, "B", "ball_recovery", {"regain": True}),
        ("e3", 4.0, 2, THEM, "C", "pass", {}),
        ("e4", 9.0, 2, THEM, "B", "shot", {"outcome_detail": "on_target"}),
        ("e5", 12.0, 3, US, "A", "pass", {}),
        ("e6", 20.0, 3, US, "D", "shot", {"outcome_detail": "goal"}),
    ]
    tags = pd.DataFrame([{"id": i, "t": t, "possession": p, "team": team, "player": player,
                          "action": action, **extra} for i, t, p, team, player, action, extra in rows])
    tags["turnover"], tags["regain"] = tags.turnover.eq(True), tags.regain.eq(True)
    tags["half"] = tags.half.fillna("opponent")
    tags["index"] = range(1, len(tags) + 1)
    tags["match_id"], tags["period"], tags["x"], tags["play_pattern"] = 1, 1, 50.0, "Regular Play"
    tags["minute"], tags["second"] = 0, tags.t.astype(int)
    tags["possession_team"] = tags.possession.map({1: US, 2: THEM, 3: US})
    tags["our_team"] = tags.team.eq(US)
    tags["outcome"] = None
    matches = pd.DataFrame([{"match_id": 1, "match_date": "2023-08-19", "home_team": US,
                             "away_team": THEM, "home_score": 1, "away_score": 0}])
    return graph.build_graph(tags, matches)


def steps(query, g):
    return [m.steps for m in find(query, g)]


def seq(*later, first=None):
    return {"sequence": [{"filter": first or {"turnover": True}}, *later]}


@pytest.fixture(scope="module")
def toy():
    return toy_graph()


def test_single_event_filters(toy):
    assert steps({"event": {"action": "shot"}}, toy) == [["e4"], ["e6"]]
    assert steps({"event": {"action": ["shot", "ball_recovery"], "our_team": False}}, toy) == [["e2"], ["e4"]]
    assert steps({"event": {"t": {"gt": 4, "lte": 12}}}, toy) == [["e4"], ["e5"]]


def test_time_limit_counts_from_the_previous_step_and_includes_the_limit(toy):
    shot = {"filter": {"action": "shot"}, "team": "other"}
    assert steps(seq({**shot, "within_s": 9}), toy) == [["e1", "e4"]]
    assert steps(seq({**shot, "within_s": 8.9}), toy) == []


def test_team_relative_to_previous_step(toy):
    assert steps(seq({"filter": {"action": "shot"}, "team": "same", "within_s": 30}), toy) == [["e1", "e6"]]


def test_same_possession(toy):
    shot = {"filter": {"action": "shot"}, "same_possession": True}
    assert steps(seq(shot, first={"regain": True}), toy) == [["e2", "e4"]]
    assert steps(seq(shot), toy) == []  # e1's possession ends straight away


def test_earliest_match_is_taken(toy):
    assert steps(seq({"filter": {"action": "pass"}, "within_s": 30}, first={"regain": True}), toy) == [["e2", "e3"]]


def test_via_same_player_skips_other_players(toy):
    query = seq({"filter": {"action": ["pass", "shot"]}, "via": "same_player", "within_s": 10},
                first={"regain": True})
    assert steps(query, toy) == [["e2", "e4"]]


def test_three_steps(toy):
    query = seq({"filter": {"regain": True}, "team": "other", "within_s": 5},
                {"filter": {"action": "shot"}, "team": "same", "within_s": 10})
    assert steps(query, toy) == [["e1", "e2", "e4"]]


def test_results_table_lists_the_moment(toy):
    query = seq({"filter": {"action": "shot"}, "team": "other", "within_s": 10})
    row = search(query, toy).iloc[0]
    assert row.match == f"2023-08-19 {US} 1-0 {THEM}"
    assert row.players == "A, B" and row.outcome == "on_target" and row.duration_s == 9.0
    assert row.span == ["e1", "e2", "e3", "e4"]


def test_match_scope(toy):
    assert len(find({"event": {"action": "shot"}, "matches": {"venue": "home"}}, toy)) == 2
    assert find({"event": {"action": "shot"}, "matches": {"venue": "away"}}, toy) == []


def test_unknown_names_are_reported(toy):
    with pytest.raises(QueryError, match="unknown player 'Wirtz'"):
        find({"event": {"player": "Wirtz"}}, toy)
    with pytest.raises(QueryError, match="unknown opponent 'Bayern'"):
        find({"event": {"action": "shot"}, "matches": {"opponent": "Bayern"}}, toy)


# --- Real data -------------------------------------------------------------------

EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = sorted(int(p.stem) for p in EVENTS_DIR.glob("*.json")) if EVENTS_DIR.exists() else []
all_downloaded = {int(m) for m in loaders.load_matches().match_id} <= set(DOWNLOADED) if DOWNLOADED else False
requires_season = pytest.mark.skipif(not all_downloaded, reason="season not downloaded")


@pytest.fixture(scope="module")
def season():
    return graph.season_graph()


@requires_season
def test_progressive_passes_by_the_left_back_after_60_minutes(season):
    results = search({"event": {"action": "pass", "progressive": True, "role_group": "FB",
                                "role_side": "left", "our_team": True, "minute": {"gte": 60}}}, season)
    assert len(results) == 105
    assert results.players.value_counts()["Alejandro Grimaldo García"] == 84


@requires_season
def test_turnovers_in_our_half_that_led_to_a_shot_within_10_seconds(season):
    assert len(search(TURNOVER_TO_SHOT, season)) == 18


@requires_season
def test_clock_from_the_regain_is_a_three_step_sequence(season):
    query = {"sequence": [
        {"filter": {"turnover": True, "our_team": True, "half": "own"}},
        {"filter": {"regain": True}, "team": "other", "within_s": 30},
        {"filter": {"action": "shot"}, "team": "same", "within_s": 10},
    ]}
    assert len(search(query, season)) == 22


@requires_season
def test_opening_goal_is_10_5_s_after_the_turnover_and_9_1_s_after_the_regain(season):
    def found(*later):
        query = {"sequence": [{"filter": {"turnover": True, "our_team": False, "player": "Timo Werner"}},
                              *later], "matches": {"match_id": 3895052}}
        return [r.outcome for r in search(query, season).itertuples() if r.minute == 22]

    shot = {"filter": {"action": "shot", "our_team": True}}
    assert found({**shot, "within_s": 10}) == []
    assert found({**shot, "within_s": 11}) == ["goal"]
    assert found({"filter": {"regain": True}, "within_s": 30}, {**shot, "within_s": 10}) == ["goal"]
