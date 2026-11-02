"""Rule-based parser tests. Most use a small hand-made vocabulary; the last ones
run parsed questions on the real season (skipped if it is not downloaded)."""
import pandas as pd
import pytest

from match_event_search import graph, loaders
from match_event_search.query import search
from match_event_search.rule_parser import (DEFAULT_GOAL_WINDOW_S, DEFAULT_WINDOW_S, ParseError, Vocabulary,
                                            _aliases, _one_edit_apart, correct_spelling, normalise, parse,
                                            parse_verbose)

VOCAB = Vocabulary(
    players={"florian wirtz": "Florian Wirtz", "wirtz": "Florian Wirtz",
             "grimaldo": "Alejandro Grimaldo García", "boniface": "Victor Okoh Boniface",
             "xhaka": "Granit Xhaka"},
    teams={"bayern": "Bayern Munich", "bayern munich": "Bayern Munich", "dortmund": "Borussia Dortmund"},
)


def test_normalise():
    assert normalise("Wirtz’s left-back passes after the 60th minute!") == "wirtz left back passes after the 60 minute"
    assert normalise("Hincapié") == "hincapie"
    assert normalise("within 2.5 seconds.") == "within 2.5 seconds"


@pytest.mark.parametrize("text, expected", [
    ("within ten seconds", "within 10 seconds"),
    ("after the sixtieth minute", "after the 60 minute"),
    ("after the seventy-fifth minute", "after the 75 minute"),
    ("in the first fifteen minutes", "in the first 15 minutes"),
    ("in the first half", "in the first half"),  # ordinals only before "minute"
    ("final third", "final third"),
])
def test_number_words(text, expected):
    assert normalise(text) == expected


def test_name_parts_point_to_one_player_and_shared_parts_prefer_our_player():
    aliases = _aliases(["Jonas Hofmann", "Philipp Hofmann", "Florian Wirtz", "Florian Neuhaus"],
                       prefer={"Jonas Hofmann", "Florian Wirtz"})
    assert aliases["wirtz"] == "Florian Wirtz"
    assert aliases["hofmann"] == "Jonas Hofmann"  # shared, but only one of ours
    assert aliases["florian"] == "Florian Wirtz"
    assert aliases["philipp hofmann"] == "Philipp Hofmann"


def test_shared_part_without_a_preferred_player_is_dropped():
    assert "hofmann" not in _aliases(["Jonas Hofmann", "Philipp Hofmann"], prefer=set())


def test_vocabulary_from_tags():
    tags = pd.DataFrame({"player": ["Florian Wirtz", "Leroy Sané", None],
                         "team": ["Bayer Leverkusen", "Bayern Munich", "Bayern Munich"]})
    vocab = Vocabulary.from_tags(tags)
    assert vocab.players["sane"] == "Leroy Sané"
    assert vocab.teams["bayern"] == "Bayern Munich" and "bayer leverkusen" not in vocab.teams


# --- The two example questions -------------------------------------------------------

def test_progressive_passes_by_the_left_back_after_the_60th_minute():
    assert parse("Progressive passes by the left back after the 60th minute", VOCAB) == {"event": {
        "minute": {"gte": 60}, "role_group": "FB", "role_side": "left", "progressive": True,
        "action": "pass", "our_team": True}}


def test_turnovers_in_our_own_half_that_led_to_a_shot_within_10_seconds():
    assert parse("Turnovers in our own half that led to a shot within 10 seconds", VOCAB) == {"sequence": [
        {"filter": {"turnover": True, "our_team": True, "half": "own"}},
        {"filter": {"action": "shot"}, "within_s": 10.0, "team": "other"}]}


# --- Single rules -------------------------------------------------------------------

def event(question):
    return parse(question, VOCAB)["event"]


@pytest.mark.parametrize("question, expected", [
    ("left wing back crosses", {"role_group": "FB", "role_side": "left", "action": "pass", "cross": True}),
    ("passes by the centre backs", {"role_group": "CB", "action": "pass"}),
    ("shots on target", {"action": "shot", "outcome_detail": ["goal", "on_target"]}),
    ("headed goals", {"header": True, "action": "shot", "outcome_detail": "goal"}),
    ("our corners", {"set_piece_type": "corner"}),
    ("shots from corners", {"play_pattern": "From Corner", "action": "shot"}),
    ("goal kicks", {"set_piece_type": "goal_kick"}),
    ("passes not under pressure", {"under_pressure": False, "action": "pass"}),
    ("unsuccessful passes under pressure", {"under_pressure": True, "outcome": "failure", "action": "pass"}),
    ("pressing", {"action": "pressure"}),
    ("counterpressing", {"counterpress": True}),
    ("high press regains", {"regain": True, "phase": "high_press"}),
    ("dribbles in the box", {"action": "dribble", "in_box": True}),
    ("passes into the box", {"box_entry": True, "action": "pass"}),
    ("carries in the left half space", {"action": "carry", "channel": "left_half_space"}),
    ("passes from the right", {"action": "pass", "channel": ["right_wing", "right_half_space"]}),
    ("passes in the final third", {"action": "pass", "third": "attacking"}),
    ("tackles when we were losing", {"action": "tackle", "game_state": "losing"}),
])
def test_phrases(question, expected):
    assert event(question) == {**expected, "our_team": True}


@pytest.mark.parametrize("question, minute, period", [
    ("shots after the 75th minute", {"gte": 75}, None),
    ("shots after 75 minutes", {"gte": 75}, None),
    ("shots before the 30th minute", {"lt": 30}, None),
    ("shots between the 30th and 45th minute", {"gte": 30, "lt": 45}, None),
    ("shots in the last 15 minutes", {"gte": 75}, None),
    ("shots in the first 10 minutes", {"lt": 10}, None),
    ("shots in the second half", None, 2),
])
def test_time(question, minute, period):
    f = event(question)
    assert f.get("minute") == minute and f.get("period") == period


def test_words_are_matched_whole():
    with pytest.raises(ParseError):
        parse("across the pitch", VOCAB)  # no "cross"


def test_players_and_receivers():
    assert event("Grimaldo passes to Boniface") == {
        "pass_recipient": "Victor Okoh Boniface", "player": "Alejandro Grimaldo García", "action": "pass"}
    assert event("Florian Wirtz dribbles")["player"] == "Florian Wirtz"


# --- Teams, halves and scope ---------------------------------------------------------

def test_our_team_unless_the_question_says_otherwise():
    assert event("shots")["our_team"] is True
    assert event("their shots")["our_team"] is False
    assert event("shots conceded")["our_team"] is False
    assert "our_team" not in event("Xhaka passes")  # the player says whose


@pytest.mark.parametrize("question, our_team, half", [
    ("turnovers in our own half", True, "own"),
    ("their turnovers in their own half", False, "own"),
    ("our turnovers in their half", True, "opponent"),
    ("opponent turnovers in our half", False, "opponent"),
    ("turnovers in the opposition half", True, "opponent"),
])
def test_halves_depend_on_who_is_acting(question, our_team, half):
    f = event(question)
    assert (f["our_team"], f["half"]) == (our_team, half)


def test_opponent_and_venue():
    q = parse("progressive carries against Dortmund at home", VOCAB)
    assert q["matches"] == {"venue": "home", "opponent": "Borussia Dortmund"}
    assert q["event"]["our_team"] is True
    q = parse("Bayern's shots", VOCAB)  # the opponent is the team acting
    assert q["matches"] == {"opponent": "Bayern Munich"} and q["event"]["our_team"] is False


# --- Sequences ------------------------------------------------------------------------

def test_after_a_turnover_the_next_step_is_the_other_team_within_the_default_window():
    q = parse("turnovers that led to a shot", VOCAB)
    assert q["sequence"][1] == {"filter": {"action": "shot"}, "team": "other", "within_s": DEFAULT_WINDOW_S}


def test_otherwise_the_next_step_is_our_team_in_the_same_possession():
    q = parse("crosses from the right followed by a headed shot", VOCAB)
    assert q["sequence"][1] == {"filter": {"header": True, "action": "shot"}, "team": "same",
                                "same_possession": True}


def test_three_steps():
    q = parse("turnovers that led to a regain that led to a goal within 10 seconds", VOCAB)
    assert [s["filter"] for s in q["sequence"]] == [
        {"turnover": True, "our_team": True}, {"regain": True}, {"action": "shot", "outcome_detail": "goal"}]
    assert q["sequence"][2]["within_s"] == 10.0


# --- Errors and leftovers ------------------------------------------------------------------

def test_nothing_recognised_is_an_error():
    with pytest.raises(ParseError, match="nothing recognised"):
        parse("hello there", VOCAB)


def test_unused_words_are_reported():
    assert parse_verbose("Wirtz dribbles across the pitch", VOCAB).unparsed == ["across", "pitch"]


# --- On the real season ------------------------------------------------------------------

EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = {int(p.stem) for p in EVENTS_DIR.glob("*.json")} if EVENTS_DIR.exists() else set()
requires_season = pytest.mark.skipif(not DOWNLOADED or not set(loaders.load_matches().match_id) <= DOWNLOADED,
                                     reason="season not downloaded")


@pytest.fixture(scope="module")
def season():
    g = graph.season_graph()
    return g, Vocabulary.from_tags(g.graph["tags"])


@requires_season
def test_real_names_are_recognised(season):
    vocab = season[1]
    assert parse("Wirtz dribbles", vocab)["event"]["player"] == "Florian Wirtz"
    assert parse("Hincapié passes", vocab)["event"]["player"] == "Piero Martín Hincapié Reyna"
    assert parse("shots against Gladbach", vocab)["matches"]["opponent"] == "Borussia Mönchengladbach"


@requires_season
def test_example_questions_find_the_same_moments_as_the_hand_written_queries(season):
    g, vocab = season
    assert len(search(parse("Progressive passes by the left back after the 60th minute", vocab), g)) == 105
    assert len(search(parse("Turnovers in our own half that led to a shot within 10 seconds", vocab), g)) == 18


# --- Fixes after testing: defenders, receivers, "intercepted", typos, goal window ----------

def test_defenders_are_centre_backs_and_full_backs():
    assert event("passes by defenders")["role_group"] == ["CB", "FB"]


def test_receiver_role():
    f = event("goalkeeper passes to a defender")
    assert f["role_group"] == "GK" and f["recipient_role_group"] == ["CB", "FB"]
    f = event("passes to the left back")
    assert (f["recipient_role_group"], f["recipient_role_side"]) == ("FB", "left")
    assert "role_group" not in f


def test_an_intercepted_pass_is_a_turnover_but_interceptions_are_an_action():
    assert event("passes that were intercepted") == {"turnover": True, "action": "pass", "our_team": True}
    assert event("interceptions") == {"action": "interception", "our_team": True}


def test_conceding_forms():
    for question in ("goals conceded", "conceding a goal", "conceded goals", "concede goals"):
        assert event(question) == {"action": "shot", "outcome_detail": "goal", "our_team": False}


def test_misspellings_one_letter_off_are_corrected_and_reported():
    parsed = parse_verbose("progresive pases leading to conceeding goal", VOCAB)
    assert parsed.corrected == {"progresive": "progressive", "pases": "passes", "conceeding": "conceding"}
    assert parsed.query["sequence"][0]["filter"] == {"progressive": True, "action": "pass", "our_team": True}


def test_names_and_short_words_are_not_corrected():
    assert parse_verbose("Wirtz dribbles", VOCAB).corrected == {}
    assert correct_spelling("shoot", protected=set()) == ("shoot", {})  # known word
    assert correct_spelling("pas", protected=set()) == ("pas", {})  # too short to guess
    assert correct_spelling("across", protected=set()) == ("across", {})  # first letter differs from "cross"


def test_one_edit_apart():
    assert _one_edit_apart("conceeding", "conceding")  # extra letter
    assert _one_edit_apart("dribbels", "dribbles")  # swapped neighbours
    assert _one_edit_apart("crosses", "crasses")  # changed letter
    assert not _one_edit_apart("cross", "crosses")


def test_a_goal_after_the_ball_changes_team_gets_a_longer_window():
    q = parse("goalkeeper passes intercepted that led to conceding a goal", VOCAB)
    assert q["sequence"][1] == {"filter": {"action": "shot", "outcome_detail": "goal", "our_team": False},
                                "within_s": DEFAULT_GOAL_WINDOW_S}


@requires_season
def test_the_goalkeeper_question_finds_the_dortmund_goal(season):
    g, vocab = season
    results = search(parse("goalkeeper pass to defender intercepted and led to conceeding goal", vocab), g)
    assert len(results) == 1
    assert results.iloc[0].match.startswith("2024-04-21 Borussia Dortmund") and results.iloc[0].minute == 80


@pytest.mark.parametrize("question, our_team, box", [
    ("turnovers in our own box", True, "in_own_box"),
    ("turnovers in our box", True, "in_own_box"),
    ("opponent turnovers in their own box", False, "in_own_box"),
    ("their shots in our box", False, "in_box"),  # the box they attack
    ("our shots in their box", True, "in_box"),
    ("opponent regains in our box", False, "in_box"),
])
def test_boxes_depend_on_who_is_acting(question, our_team, box):
    f = event(question)
    assert f["our_team"] is our_team and f[box] is True
    assert ({"in_box", "in_own_box"} - {box}).isdisjoint(f)


@requires_season
def test_turnovers_in_our_own_box_that_led_to_a_goal_conceded(season):
    g, vocab = season
    results = search(parse("Turnovers in our own box that led to goal conceeded", vocab), g)
    assert [(r.match[:10], r.minute) for r in results.itertuples()] == [("2024-04-21", 80)]
