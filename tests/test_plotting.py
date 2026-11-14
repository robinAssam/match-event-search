import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from match_event_search.plotting import our_view, plot_moment, plot_overview  # noqa: E402


def toy_span():
    return pd.DataFrame({
        "our_team": [False, True, True, True],
        "action": ["pass", "ball_recovery", "carry", "shot"],
        "x": [44.3, 84.5, 108.3, 113.6], "y": [11.7, 60.3, 47.5, 43.8],
        "end_x": [47.3, np.nan, 115.9, 120.0], "end_y": [11.7, np.nan, 48.7, 40.0],
    }, index=["werner", "xhaka", "boniface", "frimpong"])


def test_opponent_events_are_turned_round():
    view = our_view(toy_span())
    assert (view.loc["werner", ["x", "y", "end_x", "end_y"]] == [75.7, 68.3, 72.7, 68.3]).all()
    assert (view.loc["xhaka", ["x", "y"]] == [84.5, 60.3]).all()


def test_plots_draw():
    span = toy_span()
    for fig in (plot_moment(span, ["werner", "frimpong"], title="Opening goal"), plot_overview(span)):
        assert fig.axes
        plt.close(fig)


def test_a_moment_can_be_drawn_up_to_an_event():
    span = toy_span()
    fig = plot_moment(span, ["werner", "frimpong"], upto=2)
    assert fig.axes
    plt.close(fig)


def test_routes_grid_draws_and_removes_spare_pitches():
    from match_event_search.plotting import plot_routes
    route = np.array([[60, 40], [100, 35]])
    fig = plot_routes([route] * 4, ["a", "b", "c", "d"], [True, False, False, True], ncols=3)
    assert len(fig.axes) == 4  # 2 x 3 grid, 2 spare pitches removed
    plt.close(fig)
