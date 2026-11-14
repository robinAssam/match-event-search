"""Plain-language description of one tagged event, for stepping through a moment in the app."""
import math

import pandas as pd

from .config import TagConfig
from .tagging import PITCH, progress_m

ACTION_LABELS = {"ball_recovery": "ball recovery", "aerial_duel": "aerial duel", "foul_committed": "foul",
                 "foul_won": "foul won", "fifty_fifty": "50/50", "dribbled_past": "dribbled past",
                 "goalkeeper": "goalkeeper action"}
QUALIFIERS = ["cross", "through_ball", "switch", "cutback", "key_pass", "assist", "header", "counterpress"]


def _known(value) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def _words(value: str) -> str:
    return str(value).replace("_", " ")


def headline(e: pd.Series) -> str:
    side = "our team" if e.our_team else "opponent"
    who = e.player if _known(e.player) else e.team
    action = ACTION_LABELS.get(e.action, _words(e.action))
    return f"{int(e.minute)}:{int(e.second):02d}, {who}, {action} ({e.team}, {side})"


def facts(e: pd.Series) -> list[tuple[str, str]]:
    """(label, text) pairs: where, when, how it went."""
    rows = []
    if _known(e.third):
        zone = f"{_words(e.third)} third, {_words(e.channel)}, {_words(e.half)} half"
        if e.in_box:
            zone += ", in the box it attacks"
        elif e.get("in_own_box"):
            zone += ", in its own box"
        rows.append(("Zone", zone))
    if _known(e.phase):
        rows.append(("Phase", _words(e.phase)))
    if _known(e.outcome) or _known(e.outcome_detail):
        detail = f" ({_words(e.outcome_detail)})" if _known(e.outcome_detail) else ""
        rows.append(("Outcome", f"{e.outcome if _known(e.outcome) else ''}{detail}".strip()))
    if _known(e.pass_recipient):
        role = f" ({_words(e.recipient_position)})" if _known(e.get("recipient_position")) else ""
        rows.append(("Meant for", f"{e.pass_recipient}{role}"))
    rows.append(("Under pressure", "yes" if e.under_pressure else "no"))
    rows.append(("Game state", f"{e.game_state} ({int(e.goals_for)}-{int(e.goals_against)} before this event)"))
    if _known(e.since_regain):
        rows.append(("Since the regain", f"{e.since_regain:.1f} s"))
    if _known(e.xg):
        rows.append(("xG", f"{e.xg:.2f}"))
    return rows


def tags(e: pd.Series, config: TagConfig = TagConfig()) -> list[tuple[str, str]]:
    """(tag, why) pairs for the derived and qualifier tags this event has."""
    out = []
    if e.progressive:
        gain = float(progress_m(e.x, e.y, e.end_x, e.end_y))
        own, across, opponent = config.progressive_m
        starts_own, ends_own = e.x < PITCH.length / 2, e.end_x < PITCH.length / 2
        needed = own if starts_own and ends_own else across if starts_own != ends_own else opponent
        out.append(("progressive", f"{gain:.1f} m closer to goal; {needed:.0f} m needed"))
    if e.box_entry:
        out.append(("box entry", "from outside into the penalty area"))
    if e.turnover:
        out.append(("turnover", "the last action before the opponent won the ball in open play"))
    if e.regain:
        out.append(("regain", "the first action after winning the ball in open play"))
    for name in QUALIFIERS:
        if e.get(name):
            out.append((_words(name), ""))
    if _known(e.set_piece_type):
        out.append((_words(e.set_piece_type), "set piece"))
    return out
