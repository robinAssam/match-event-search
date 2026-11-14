"""Pitch plots of search results (mplsoccer, StatsBomb coordinates).

Every event is stored from the acting team's point of view (stage 1), so to
show both teams on one pitch the opponent's events are turned round:
(x, y) -> (120 - x, 80 - y). Plots are drawn from our team's side, attacking
left to right.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mplsoccer import Pitch

from .config import PitchConfig

PITCH = PitchConfig()
OUR_COLOUR, THEIR_COLOUR = "#534AB7", "#D85A30"
SKIP = {"ball_receipt"}  # drawn as the end of the pass instead


def our_view(events: pd.DataFrame) -> pd.DataFrame:
    """Coordinates of all events from our team's side of the pitch."""
    out = events.copy()
    theirs = ~out.our_team.astype(bool)
    for col, size in (("x", PITCH.length), ("end_x", PITCH.length), ("y", PITCH.width), ("end_y", PITCH.width)):
        out.loc[theirs, col] = size - out.loc[theirs, col]
    return out


def _pitch():
    return Pitch(pitch_type="statsbomb", line_color="#9a9a9a", pitch_color="white", linewidth=1, line_zorder=1)


def moment_events(span: pd.DataFrame) -> pd.DataFrame:
    """The events of a moment that are drawn, in order (ball receipts are the ends of passes)."""
    return span[~span.action.isin(SKIP) & span.x.notna()]


def plot_moment(span: pd.DataFrame, steps: list, title: str = "", upto: int | None = None):
    """One result: every event from the first step to the last, the steps numbered.

    With `upto`, only the first `upto` drawn events are shown and the last of
    them is highlighted, so the move can be followed event by event.
    """
    events = our_view(moment_events(span))
    current = None
    if upto is not None:
        events = events.iloc[:upto]
        current = events.index[-1]
    pitch = _pitch()
    fig, ax = pitch.draw(figsize=(9, 6))
    for e in events.itertuples():
        colour = OUR_COLOUR if e.our_team else THEIR_COLOUR
        is_step = e.Index in steps if current is None else e.Index == current
        alpha, width = (1.0, 2.2) if is_step else (0.45, 1.2)
        has_end = not np.isnan(e.end_x)
        if e.action == "pass" and has_end:
            pitch.arrows(e.x, e.y, e.end_x, e.end_y, ax=ax, color=colour, alpha=alpha, width=width,
                         headwidth=4, headlength=4, zorder=3)
        elif e.action == "carry" and has_end:
            pitch.lines(e.x, e.y, e.end_x, e.end_y, ax=ax, color=colour, alpha=alpha, lw=width,
                        linestyle="--", zorder=2)
        elif e.action == "shot" and has_end:
            pitch.lines(e.x, e.y, e.end_x, e.end_y, ax=ax, color=colour, alpha=alpha, lw=width, zorder=2)
            pitch.scatter(e.x, e.y, ax=ax, marker="*", s=420 if is_step else 200, color=colour,
                          edgecolors="black", linewidths=0.6, zorder=5)
            continue
        if e.action == "pressure":
            pitch.scatter(e.x, e.y, ax=ax, s=90 if is_step else 30, marker="x", color=colour, alpha=alpha, zorder=4)
        else:
            pitch.scatter(e.x, e.y, ax=ax, s=90 if is_step else 30, marker="o", color=colour, alpha=alpha,
                          edgecolors="white", zorder=4)
    for number, step in enumerate(steps, 1):
        if step in events.index:
            e = events.loc[step]
            pitch.annotate(str(number), (e.x, e.y), xytext=(e.x + 1.8, e.y - 2.4), ax=ax, fontsize=11,
                           fontweight="bold", color="black", zorder=6)
    if current is not None:
        e = events.loc[current]
        pitch.scatter(e.x, e.y, ax=ax, s=380, marker="o", facecolors="none", edgecolors="#1D9E75",
                      linewidths=2, zorder=7)
    ax.set_title(title, fontsize=11)
    _legend(ax)
    return fig


def plot_overview(first_steps: pd.DataFrame, title: str = ""):
    """Where every result started (the first step), our team's side attacking right."""
    events = our_view(first_steps[first_steps.x.notna()])
    pitch = _pitch()
    fig, ax = pitch.draw(figsize=(9, 6))
    for ours, colour in ((True, OUR_COLOUR), (False, THEIR_COLOUR)):
        part = events[events.our_team.astype(bool) == ours]
        if len(part):
            pitch.scatter(part.x, part.y, ax=ax, s=45, color=colour, alpha=0.7, edgecolors="white", zorder=3)
    ax.set_title(title, fontsize=11)
    _legend(ax)
    return fig


def _legend(ax):
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=OUR_COLOUR, label="Our team"),
               plt.Line2D([], [], marker="o", linestyle="", color=THEIR_COLOUR, label="Opponent")]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=2, frameon=False, fontsize=9)


def plot_routes(routes: list, titles: list, shots: list, ncols: int = 3):
    """Small pitches with the ball's route of each possession (from the side of the team on the ball).

    routes: arrays of (x, y) points; shots: whether each possession ended in a shot (a star at its end).
    """
    nrows = -(-len(routes) // ncols)
    pitch = _pitch()
    fig, axs = pitch.grid(nrows=nrows, ncols=ncols, figheight=2.6 * nrows, title_height=0, endnote_height=0,
                          axis=False, grid_height=0.95)
    for ax, route, title, shot in zip(np.ravel(axs), routes, titles, shots):
        pitch.plot(route[:, 0], route[:, 1], ax=ax, color=OUR_COLOUR, lw=2, alpha=0.85, zorder=3)
        pitch.scatter(route[0, 0], route[0, 1], ax=ax, s=50, color="#1D9E75", zorder=4)
        if shot:
            pitch.scatter(route[-1, 0], route[-1, 1], ax=ax, marker="*", s=180, color=THEIR_COLOUR, zorder=5)
        ax.set_title(title, fontsize=8)
    for ax in np.ravel(axs)[len(routes):]:
        ax.remove()
    return fig
