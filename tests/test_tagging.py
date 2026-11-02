"""Tagging tests: the rules on hand-made inputs, then the tags on real matches
(skipped if the data is not downloaded)."""
import numpy as np
import pytest

from match_event_search import loaders, tagging
from match_event_search.tagging import (channel, half, in_box, is_progressive, progress_m, role_group,
                                        role_side, third, time_bucket)


def test_thirds_and_halves_include_their_lower_edge():
    assert list(third([0, 39.9, 40, 79.9, 80, 120])) == [
        "defensive", "defensive", "middle", "middle", "attacking", "attacking"]
    assert list(half([59.9, 60])) == ["own", "opponent"]
    assert third([np.nan])[0] is None


def test_channels_follow_the_box_lines():
    assert list(channel([0, 18, 30, 50, 62, 80])) == [
        "left_wing", "left_half_space", "centre", "right_half_space", "right_wing", "right_wing"]


def test_penalty_box():
    assert list(in_box([102, 101.9, 110, 110], [40, 40, 17.9, 62])) == [True, False, False, True]


def test_progressive_thresholds_depend_on_the_halves():
    # Orban's pass in the walkthrough: 27.0 m closer within his own half, needs 30 m.
    assert progress_m(9.8, 17.7, 43.2, 12.1) == pytest.approx(27.0, abs=0.05)
    assert not is_progressive(9.8, 17.7, 43.2, 12.1)
    # Xhaka's pass: 20.6 m closer within the opponent's half, needs 10 m.
    assert progress_m(85.6, 54.8, 108.3, 47.5) == pytest.approx(20.6, abs=0.05)
    assert is_progressive(85.6, 54.8, 108.3, 47.5)
    # Across halfway along the centre line: 15 m needed (17.5 m here, 13.1 m here).
    assert is_progressive(50, 40, 70, 40)
    assert not is_progressive(50, 40, 65, 40)


def test_backwards_pass_is_never_progressive():
    assert not is_progressive(100, 40, 70, 40)


def test_full_backs_include_wing_backs():
    assert role_group("Left Wing Back") == role_group("Left Back") == "FB"
    assert role_side("Left Wing Back") == "left"
    assert role_side("Center Forward") == "centre"
    assert role_group(None) is None


def test_every_statsbomb_position_has_a_role_group():
    assert len(tagging.ROLE_GROUPS) == 25  # all StatsBomb positions except "Substitute"


def test_time_buckets_put_stoppage_time_in_the_last_window():
    assert time_bucket(1, 0) == "0-15"
    assert time_bucket(1, 47) == "30-45+"
    assert time_bucket(2, 45) == "45-60"
    assert time_bucket(2, 61) == "60-75"
    assert time_bucket(2, 94) == "75-90+"


# --- Real data -------------------------------------------------------------------

OPENING_GOAL_MATCH = 3895052  # Leverkusen 3-2 RB Leipzig, 19 August 2023
EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = sorted(int(p.stem) for p in EVENTS_DIR.glob("*.json")) if EVENTS_DIR.exists() else []
requires_match = pytest.mark.skipif(OPENING_GOAL_MATCH not in DOWNLOADED, reason="match not downloaded")


@pytest.fixture(scope="module")
def opening_goal():
    return tagging.tag_match(OPENING_GOAL_MATCH)


def event(tags, player, event_type, minute, second):
    rows = tags[(tags.player == player) & (tags.type == event_type)
                & (tags.minute == minute) & (tags.second == second)]
    assert len(rows) == 1
    return rows.iloc[0]


@requires_match
def test_werners_lost_pass_is_a_turnover_in_leipzigs_own_half(opening_goal):
    werner = event(opening_goal, "Timo Werner", "Pass", 22, 54)
    assert werner.turnover and werner.half == "own" and werner.outcome == "failure"
    assert not werner.our_team


@requires_match
def test_xhakas_recovery_is_the_regain_and_starts_the_clock(opening_goal):
    recovery = event(opening_goal, "Granit Xhaka", "Ball Recovery", 22, 55)
    assert recovery.regain and recovery.since_regain == 0
    assert recovery.phase == "transition" and recovery.third == "attacking"


@requires_match
def test_xhakas_pass_is_progressive_and_enters_the_box(opening_goal):
    xhaka = event(opening_goal, "Granit Xhaka", "Pass", 22, 57)
    assert xhaka.progressive and xhaka.box_entry and xhaka.outcome == "success"


@requires_match
def test_miscontrol_without_losing_the_ball_is_no_turnover(opening_goal):
    miscontrol = event(opening_goal, "Victor Okoh Boniface", "Miscontrol", 23, 0)
    assert miscontrol.outcome == "failure" and not miscontrol.turnover


@requires_match
def test_frimpongs_goal(opening_goal):
    shot = event(opening_goal, "Jeremie Frimpong", "Shot", 23, 4)
    assert shot.outcome_detail == "goal" and shot.in_box
    assert shot.since_regain == pytest.approx(9.08, abs=0.01)
    assert shot.phase == "transition" and shot.game_state == "drawing"
    assert shot.role_group == "FB" and shot.time_bucket == "15-30"


# --- Checks on every downloaded match --------------------------------------------

requires_data = pytest.mark.skipif(not DOWNLOADED, reason="no matches downloaded")


@pytest.fixture(scope="module", params=DOWNLOADED)
def tagged(request):
    info = loaders.load_matches().set_index("match_id").loc[request.param]
    return info, tagging.tag_events(loaders.load_events(request.param), info)


@requires_data
def test_score_after_the_last_event_is_the_final_score(tagged):
    info, tags = tagged
    last = tags.iloc[-1]
    home = (last.goals_for, last.goals_against) if last.home else (last.goals_against, last.goals_for)
    assert home == (info.home_score, info.away_score)


@requires_data
def test_turnovers_and_regains_come_in_pairs(tagged):
    tags = tagged[1]
    assert tags.groupby("possession").turnover.sum().max() <= 1
    # Each turnover is followed by a regain in the next possession, and vice versa.
    assert list(tags.possession[tags.turnover] + 1) == list(tags.possession[tags.regain])
    assert (tags.team[tags.turnover].to_numpy() != tags.team[tags.regain].to_numpy()).all()


@requires_data
def test_every_located_event_has_one_phase(tagged):
    tags = tagged[1]
    located = tags[tags.x.notna()]
    assert located.phase.notna().all()
    with_ball = {"build_up", "progression", "final_third", "transition", "counter_attack", "set_piece"}
    assert set(located.phase[located.in_possession]) <= with_ball
    assert set(located.phase[~located.in_possession]) <= {"counterpress", "high_press", "mid_block", "low_block"}


@requires_data
def test_only_passes_and_carries_are_progressive(tagged):
    tags = tagged[1]
    assert set(tags.action[tags.progressive]) <= {"pass", "carry"}


@requires_match
def test_receiver_role_of_a_lost_goalkeeper_pass():
    tags = tagging.tag_match(3895309)  # Borussia Dortmund 1-1 Leverkusen
    pass_ = event(tags, "Lukáš Hrádecký", "Pass", 80, 6)
    assert pass_.pass_recipient == "Josip Stanišić" and pass_.outcome == "failure"
    assert (pass_.recipient_role_group, pass_.recipient_role_side) == ("FB", "right")


@requires_data
def test_every_named_receiver_has_a_position(tagged):
    tags = tagged[1]
    assert tags.recipient_position[tags.pass_recipient.notna()].notna().all()
