"""Turn raw StatsBomb events into the tag schema (docs/methodology/02_tagging.md).

`tag_events` returns one row per event: identifiers, coordinates and one or
more columns for each of the nine tag families:

1. action      `action`, qualifiers (`cross`, `through_ball`, `switch`,
               `cutback`, `key_pass`, `assist`, `header`), `set_piece_type`,
               derived `progressive`, `box_entry`, `turnover`, `regain`
2. zone        `third`, `channel`, `half`, `in_box`, and `end_*` for the end
               point of passes, carries and shots
3. phase       `phase`
4. role        `position`, `role_group`, `role_side`
5. pressure    `under_pressure`, `counterpress`
6. outcome     `outcome` (success / failure / None), `outcome_detail`
7. game state  `goals_for`, `goals_against`, `goal_diff`, `game_state`
8. time        `period`, `minute`, `second`, `t`, `time_bucket`, `since_regain`
9. team        `team`, `our_team`, `home`, `in_possession`

Coordinates (`x`, `y`, `end_x`, `end_y`) stay in StatsBomb's 120 x 80 grid
from the acting team's point of view, so zones need no flipping.
"""
import numpy as np
import pandas as pd

from .config import DataConfig, PitchConfig, TagConfig

PITCH = PitchConfig()

# Possessions that start this way began with the ball won in open play.
OPEN_PLAY_STARTS = {"Regular Play", "From Counter"}

# Events in which a player plays or tries to win the ball. A turnover is the
# losing team's last one of these, a regain the winning team's first.
BALL_ACTIONS = {
    "Pass", "Carry", "Dribble", "Shot", "Miscontrol", "Dispossessed", "Duel",
    "Clearance", "Error", "Block", "Ball Recovery", "Interception",
    "Goal Keeper", "50/50", "Shield",
}

SET_PIECE_PASSES = {"Corner", "Free Kick", "Throw-in", "Goal Kick", "Kick Off"}

OPTIONAL_COLUMNS = [
    "pass_end_location", "carry_end_location", "shot_end_location", "pass_recipient",
    "shot_statsbomb_xg", "pass_type", "shot_type", "pass_outcome", "shot_outcome",
    "dribble_outcome", "duel_type", "duel_outcome", "interception_outcome", "50_50",
    "ball_receipt_outcome", "ball_recovery_recovery_failure", "goalkeeper_type",
    "pass_cross", "pass_through_ball", "pass_switch", "pass_cut_back", "pass_shot_assist",
    "pass_goal_assist", "pass_body_part", "shot_body_part", "clearance_head",
    "under_pressure", "counterpress",
]

ACTION_NAMES = {
    "Ball Receipt*": "ball_receipt",
    "Goal Keeper": "goalkeeper",
    "50/50": "fifty_fifty",
    "Foul Committed": "foul_committed",
    "Foul Won": "foul_won",
}

ROLE_GROUPS = {
    "Goalkeeper": "GK",
    "Center Back": "CB", "Left Center Back": "CB", "Right Center Back": "CB",
    "Left Back": "FB", "Right Back": "FB", "Left Wing Back": "FB", "Right Wing Back": "FB",
    "Center Defensive Midfield": "DM", "Left Defensive Midfield": "DM", "Right Defensive Midfield": "DM",
    "Center Midfield": "CM", "Left Center Midfield": "CM", "Right Center Midfield": "CM",
    "Center Attacking Midfield": "AM", "Left Attacking Midfield": "AM", "Right Attacking Midfield": "AM",
    "Left Wing": "W", "Right Wing": "W", "Left Midfield": "W", "Right Midfield": "W",
    "Center Forward": "ST", "Left Center Forward": "ST", "Right Center Forward": "ST",
    "Secondary Striker": "ST",
}


# --- Zones ---------------------------------------------------------------------

def third(x, config: TagConfig = TagConfig()):
    lo, hi = config.third_lines
    return _bins(x, [lo, hi], ["defensive", "middle", "attacking"])


def channel(y, config: TagConfig = TagConfig()):
    return _bins(y, list(config.channel_lines),
                 ["left_wing", "left_half_space", "centre", "right_half_space", "right_wing"])


def half(x):
    return _bins(x, [PITCH.length / 2], ["own", "opponent"])


def in_box(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    lo, hi = PITCH.box_y
    return (x >= PITCH.box_x) & (y >= lo) & (y <= hi)


def _bins(values, edges, labels):
    """Label each value by the interval it falls in; edges belong to the upper interval."""
    values = np.asarray(values, dtype=float)
    out = np.array(labels, dtype=object)[np.searchsorted(edges, values, side="right")]
    out[np.isnan(values)] = None
    return out


# --- Progressive passes and carries ------------------------------------------------

def metres_to_goal(x, y):
    """Distance (m) to the centre of the goal the acting team attacks."""
    dx = (PITCH.length - np.asarray(x, dtype=float)) * PITCH.length_m / PITCH.length
    dy = (PITCH.width / 2 - np.asarray(y, dtype=float)) * PITCH.width_m / PITCH.width
    return np.hypot(dx, dy)


def progress_m(x, y, end_x, end_y):
    """How much closer to the opponent's goal (m) the ball ends up."""
    return metres_to_goal(x, y) - metres_to_goal(end_x, end_y)


def is_progressive(x, y, end_x, end_y, config: TagConfig = TagConfig()):
    """Wyscout's rule: 30 m closer within the own half, 15 m across halves, 10 m in the opponent's half."""
    own, across, opponent = config.progressive_m
    starts_own = np.asarray(x, dtype=float) < PITCH.length / 2
    ends_own = np.asarray(end_x, dtype=float) < PITCH.length / 2
    needed = np.where(starts_own & ends_own, own, np.where(starts_own != ends_own, across, opponent))
    return progress_m(x, y, end_x, end_y) >= needed


# --- Roles and time ------------------------------------------------------------

def role_group(position):
    return ROLE_GROUPS.get(position) if isinstance(position, str) else None


def role_side(position):
    if not isinstance(position, str):
        return None
    return "left" if position.startswith("Left") else "right" if position.startswith("Right") else "centre"


def time_bucket(period, minute, config: TagConfig = TagConfig()):
    """15-minute windows; the last one of each half includes stoppage time."""
    size = config.time_bucket_min
    if period not in (1, 2):
        return "extra_time"
    start = 45 * (period - 1)
    first = min(max(minute - start, 0) // size, 45 // size - 1)
    lo = start + first * size
    hi = lo + size
    return f"{lo}-{hi}+" if hi == start + 45 else f"{lo}-{hi}"


# --- Tagging -------------------------------------------------------------------

def tag_events(events: pd.DataFrame, match_info: pd.Series,
               config: TagConfig = TagConfig(), data: DataConfig = DataConfig()) -> pd.DataFrame:
    """Tag the events of one match (as returned by `loaders.load_events`)."""
    ev = events.sort_values("index").reset_index(drop=True)
    # statsbombpy only creates a column if some event in the match uses it.
    ev = ev.reindex(columns=ev.columns.union(OPTIONAL_COLUMNS, sort=False))
    out = pd.DataFrame({
        "id": ev.id, "index": ev["index"], "match_id": ev.match_id,
        "period": ev.period, "minute": ev.minute, "second": ev.second,
        "timestamp": ev.timestamp, "t": ev.timestamp.map(_seconds),
        "possession": ev.possession, "possession_team": ev.possession_team,
        "play_pattern": ev.play_pattern, "team": ev.team, "player": ev.player,
        "type": ev.type,
    })
    out["x"], out["y"] = _xy(ev.location)
    end = ev.pass_end_location.combine_first(ev.carry_end_location).combine_first(ev.shot_end_location)
    out["end_x"], out["end_y"] = _xy(end)
    out["pass_recipient"] = ev.pass_recipient
    out["xg"] = ev.shot_statsbomb_xg

    # 9. Team
    out["our_team"] = ev.team.eq(data.focus_team)
    out["home"] = ev.team.eq(match_info.home_team)
    out["in_possession"] = ev.team.eq(ev.possession_team)

    # 1. Action
    out["action"] = ev.type.map(_action_name)
    out.loc[ev.type.eq("Duel") & ev.duel_type.eq("Tackle"), "action"] = "tackle"
    out.loc[ev.type.eq("Duel") & ev.duel_type.eq("Aerial Lost"), "action"] = "aerial_duel"
    out["cross"] = ev.pass_cross.eq(True)
    out["through_ball"] = ev.pass_through_ball.eq(True)
    out["switch"] = ev.pass_switch.eq(True)
    out["cutback"] = ev.pass_cut_back.eq(True)
    out["key_pass"] = ev.pass_shot_assist.eq(True)
    out["assist"] = ev.pass_goal_assist.eq(True)
    out["header"] = ev.pass_body_part.eq("Head") | ev.shot_body_part.eq("Head") | ev.clearance_head.eq(True)
    set_piece_pass = ev.pass_type.where(ev.pass_type.isin(SET_PIECE_PASSES))
    set_piece_shot = ev.shot_type.where(ev.shot_type.isin({"Free Kick", "Penalty"}))
    out["set_piece_type"] = set_piece_pass.combine_first(set_piece_shot).map(_snake, na_action="ignore")

    # 2. Zone
    out["third"], out["channel"], out["half"] = third(out.x, config), channel(out.y, config), half(out.x)
    out["in_box"] = in_box(out.x, out.y)
    out["end_third"], out["end_channel"] = third(out.end_x, config), channel(out.end_y, config)
    out["end_in_box"] = in_box(out.end_x, out.end_y)

    # 4. Role
    out["position"] = ev.position
    out["role_group"] = ev.position.map(role_group)
    out["role_side"] = ev.position.map(role_side)

    # 5. Pressure
    out["under_pressure"] = ev.under_pressure.eq(True)
    out["counterpress"] = ev.counterpress.eq(True)

    # 6. Outcome
    out["outcome"], out["outcome_detail"] = _outcomes(ev)

    # 7. Game state
    _add_game_state(out, match_info)

    # 8. Time
    out["time_bucket"] = [time_bucket(p, m, config) for p, m in zip(out.period, out.minute)]

    # Derived actions
    open_play_pass = ev.type.eq("Pass") & ~ev.pass_type.isin(SET_PIECE_PASSES)
    moves_ball = (open_play_pass | ev.type.eq("Carry")) & out.end_x.notna()
    out["progressive"] = moves_ball & is_progressive(out.x, out.y, out.end_x, out.end_y, config)
    completed = ev.type.eq("Carry") | (ev.type.eq("Pass") & out.outcome.eq("success"))
    out["box_entry"] = completed & ~out.in_box & out.end_in_box
    _add_turnovers(out)

    # 3. Phase (needs regains)
    out["phase"] = _phases(out, config)
    return out


def _seconds(timestamp: str) -> float:
    h, m, s = timestamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _xy(locations: pd.Series):
    x = locations.map(lambda l: l[0] if isinstance(l, list) else np.nan)
    y = locations.map(lambda l: l[1] if isinstance(l, list) else np.nan)
    return x.astype(float), y.astype(float)


def _snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _action_name(event_type: str) -> str:
    return ACTION_NAMES.get(event_type, _snake(event_type))


def _outcomes(ev: pd.DataFrame):
    """success / failure / None, and the StatsBomb outcome it comes from."""
    t = ev.type
    fifty = ev["50_50"].map(lambda d: d["outcome"]["name"] if isinstance(d, dict) else None)
    shot_detail = ev.shot_outcome.map({
        "Goal": "goal", "Saved": "on_target", "Saved to Post": "on_target",
        "Off T": "off_target", "Wayward": "off_target", "Post": "off_target",
        "Saved Off Target": "off_target", "Blocked": "blocked",
    })
    duel_detail = ev.duel_outcome.where(ev.duel_type.eq("Tackle"), "Lost")
    won = lambda s: s.str.startswith(("Won", "Success"), na=False) & ~s.eq("Success To Opposition")

    pass_known = ~ev.pass_outcome.isin({"Unknown", "Injury Clearance"})
    rules = [  # (applies, success, detail)
        (t.eq("Pass") & pass_known, ev.pass_outcome.isna(), ev.pass_outcome.fillna("Complete")),
        (t.eq("Shot"), ev.shot_outcome.eq("Goal"), shot_detail),
        (t.eq("Dribble"), ev.dribble_outcome.eq("Complete"), ev.dribble_outcome),
        (t.eq("Duel"), won(duel_detail), duel_detail),
        (t.eq("Interception"), won(ev.interception_outcome), ev.interception_outcome),
        (t.eq("50/50"), won(fifty), fifty),
        (t.eq("Ball Receipt*"), ev.ball_receipt_outcome.isna(), ev.ball_receipt_outcome.fillna("Complete")),
        (t.eq("Ball Recovery"), ~ev.ball_recovery_recovery_failure.eq(True), None),
        (t.isin({"Miscontrol", "Dispossessed", "Error", "Dribbled Past"}), pd.Series(False, index=ev.index), None),
    ]
    outcome = pd.Series(None, index=ev.index, dtype=object)
    detail = pd.Series(None, index=ev.index, dtype=object)
    for applies, success, det in rules:
        outcome[applies] = np.where(success[applies], "success", "failure")
        if det is not None:
            detail[applies] = det[applies]
    keeper = t.eq("Goal Keeper")
    detail[keeper] = ev.goalkeeper_type[keeper]
    return outcome, detail


def _add_game_state(out: pd.DataFrame, match_info: pd.Series):
    """Score before each event, from the acting team's point of view."""
    goal = (out.type.eq("Shot") & out.outcome_detail.eq("goal")) | out.type.eq("Own Goal For")
    home_goals = (goal & out.team.eq(match_info.home_team)).astype(int)
    away_goals = (goal & out.team.eq(match_info.away_team)).astype(int)
    home_before = home_goals.cumsum() - home_goals
    away_before = away_goals.cumsum() - away_goals
    out["goals_for"] = np.where(out.home, home_before, away_before)
    out["goals_against"] = np.where(out.home, away_before, home_before)
    out["goal_diff"] = out.goals_for - out.goals_against
    out["game_state"] = np.select([out.goal_diff > 0, out.goal_diff < 0], ["winning", "losing"], "drawing")


def _add_turnovers(out: pd.DataFrame):
    """Mark open-play turnovers and regains, and time since the regain.

    A possession is lost in open play when the team played the ball in it,
    the next possession is the other team's and starts in open play, and the
    lost possession did not end in a shot. The turnover is the losing team's
    last ball action in it, the regain the winning team's first ball action
    in the next possession. Requiring a ball action excludes possessions such
    as a dropped ball, after which nobody lost the ball.
    """
    on_ball = out.in_possession & out.type.isin(BALL_ACTIONS)
    g = out.groupby("possession")
    poss = pd.DataFrame({"team": g.possession_team.first(), "pattern": g.play_pattern.first()})
    poss["shot"] = (out.in_possession & out.type.eq("Shot")).groupby(out.possession).any()
    poss["had_ball"] = on_ball.groupby(out.possession).any()
    next_team, next_pattern = poss.team.shift(-1), poss.pattern.shift(-1)
    poss["lost"] = (poss.had_ball & next_team.notna() & next_team.ne(poss.team)
                    & next_pattern.isin(OPEN_PLAY_STARTS) & ~poss.shot)
    poss["won"] = poss.lost.shift(1, fill_value=False)

    lost = out.possession.map(poss.lost) & on_ball
    won = out.possession.map(poss.won) & on_ball
    out["turnover"] = False
    out.loc[out.index[lost].to_series().groupby(out.possession[lost]).last(), "turnover"] = True
    out["regain"] = False
    first_regain = out.index[won].to_series().groupby(out.possession[won]).first()
    out.loc[first_regain, "regain"] = True

    regain_t = out.t[first_regain].set_axis(out.possession[first_regain])
    regain_index = out["index"][first_regain].set_axis(out.possession[first_regain])
    after = out.in_possession & (out["index"] >= out.possession.map(regain_index))
    out["since_regain"] = (out.t - out.possession.map(regain_t)).where(after)


def _phases(out: pd.DataFrame, config: TagConfig):
    """One phase per event, by priority (docs/methodology/02_tagging.md)."""
    restart = out[out.in_possession].groupby("possession").agg(x0=("x", "first"), t0=("t", "first"))
    since_restart = out.t - out.possession.map(restart.t0)
    restart_x = out.possession.map(restart.x0)
    set_piece = (out.play_pattern.eq("From Corner")
                 | (out.play_pattern.eq("From Free Kick") & (restart_x >= config.third_lines[1])))
    by_third = {"defensive": "build_up", "middle": "progression", "attacking": "final_third"}
    by_third_out = {"attacking": "high_press", "middle": "mid_block", "defensive": "low_block"}
    with_ball = np.select(
        [set_piece & (since_restart <= config.set_piece_window_s),
         out.play_pattern.eq("From Counter"),
         out.since_regain <= config.transition_window_s],
        ["set_piece", "counter_attack", "transition"],
        out.third.map(by_third).fillna("").to_numpy(),
    )
    without_ball = np.where(out.counterpress, "counterpress", out.third.map(by_third_out).fillna("").to_numpy())
    phase = pd.Series(np.where(out.in_possession, with_ball, without_ball), index=out.index)
    return phase.where(out.x.notna() & phase.ne(""))


def tag_match(match_id: int, data: DataConfig = DataConfig(), config: TagConfig = TagConfig()) -> pd.DataFrame:
    from .loaders import load_events, load_matches
    info = load_matches(data).set_index("match_id").loc[match_id]
    return tag_events(load_events(match_id), info, config, data)


def tag_season(data: DataConfig = DataConfig(), config: TagConfig = TagConfig()) -> pd.DataFrame:
    from .loaders import load_matches
    return pd.concat([tag_match(m, data, config) for m in load_matches(data).match_id], ignore_index=True)
