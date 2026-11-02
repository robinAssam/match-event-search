import numpy as np
import pandas as pd

from match_event_search import describe


def xhaka_pass(**changes):
    """Xhaka's pass into the box before Leverkusen's opening goal of the season."""
    e = dict(minute=22, second=57, player="Granit Xhaka", team="Bayer Leverkusen", our_team=True, action="pass",
             third="attacking", channel="right_half_space", half="opponent", in_box=False, in_own_box=False,
             phase="transition", outcome="success", outcome_detail="Complete", pass_recipient="Victor Okoh Boniface",
             recipient_position="Center Forward", under_pressure=False, game_state="drawing", goals_for=0,
             goals_against=0, since_regain=1.673, xg=np.nan, progressive=True, box_entry=True, turnover=False,
             regain=False, set_piece_type=None, x=85.6, y=54.8, end_x=108.3, end_y=47.5,
             cross=False, through_ball=False, switch=False, cutback=False, key_pass=False, assist=False,
             header=False, counterpress=False)
    e.update(changes)
    return pd.Series(e)


def test_headline():
    assert describe.headline(xhaka_pass()) == "22:57 · Granit Xhaka · pass (Bayer Leverkusen, our team)"


def test_facts():
    facts = dict(describe.facts(xhaka_pass()))
    assert facts["Zone"] == "attacking third, right half space, opponent half"
    assert facts["Meant for"] == "Victor Okoh Boniface (Center Forward)"
    assert facts["Since the regain"] == "1.7 s" and "xG" not in facts


def test_tags_explain_why():
    tags = dict(describe.tags(xhaka_pass()))
    assert tags["progressive"] == "20.6 m closer to goal; 10 m needed"
    assert "box entry" in tags and "turnover" not in tags


def test_own_box():
    assert describe.facts(xhaka_pass(in_own_box=True, third="defensive"))[0][1].endswith("in its own box")
