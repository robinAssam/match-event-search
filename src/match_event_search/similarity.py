"""Find situations like this one: possessions as vectors, compared by distance.

Each possession with enough actions becomes a vector of three parts, each
scaled so it contributes its weight to the distance (SimilarityConfig):

* path:  the ball's route (every action's start, and the end of passes and
         carries), resampled to a fixed number of points, from the side of
         the team on the ball (it always attacks to the right);
* tempo: duration, passes, carries, dribbles, ground gained, and ground
         gained per second;
* start: how the possession started (StatsBomb's play pattern) and whether
         it began with a regain.

The outcome (box entry, shot, goal, xG, lost ball) is kept next to the
vectors, not in them, so the neighbours of a possession show how often that
kind of move ends in a shot or a goal (docs/methodology/09_similarity.md).
"""
import numpy as np
import pandas as pd

from .config import PitchConfig, SimilarityConfig
from .tagging import PLAY_PATTERNS

PITCH = PitchConfig()
# Actions of the team on the ball that move or play it.
SKIP = {"ball_receipt", "pressure"}


def possession_actions(tags: pd.DataFrame) -> pd.DataFrame:
    """The located actions of the team on the ball, in order (tag table indexed by event id)."""
    own = tags[tags.in_possession & tags.x.notna() & ~tags.action.isin(SKIP)]
    return own.sort_values(["match_id", "index"])


def ball_path(actions: pd.DataFrame, points: int) -> np.ndarray:
    """The ball's route resampled to `points` points, as (x, y) on the 120 x 80 pitch."""
    route = []
    for a in actions.itertuples():
        route.append((a.x, a.y))
        if a.action in ("pass", "carry") and not np.isnan(a.end_x):
            route.append((a.end_x, a.end_y))
    route = np.asarray(route, dtype=float)
    steps = np.linspace(0, len(route) - 1, points)
    return np.column_stack([np.interp(steps, np.arange(len(route)), route[:, i]) for i in (0, 1)])


def describe_possession(actions: pd.DataFrame, config: SimilarityConfig = SimilarityConfig()) -> dict:
    """The raw parts of one possession's vector, and its outcome."""
    duration = max(actions.t.iloc[-1] - actions.t.iloc[0], 0.0)
    reached = np.nanmax(np.r_[actions.x.to_numpy(), actions.end_x.to_numpy(dtype=float)])
    gained_m = (reached - actions.x.iloc[0]) * PITCH.length_m / PITCH.length
    shots = actions[actions.action.eq("shot")]
    path = ball_path(actions, config.path_points)
    return {
        "path": (path / [PITCH.length, PITCH.width]).ravel(),
        "tempo": np.array([np.log1p(duration), np.log1p(actions.action.eq("pass").sum()),
                           np.log1p(actions.action.eq("carry").sum()), np.log1p(actions.action.eq("dribble").sum()),
                           gained_m / PITCH.length_m, gained_m / max(duration, 1.0)]),
        "start": np.r_[[actions.play_pattern.iloc[0] == p for p in PLAY_PATTERNS],
                       actions.regain.any()].astype(float),
        "outcome": {"box_entry": bool(actions.box_entry.any()), "shot": len(shots) > 0,
                    "goal": bool(shots.outcome_detail.eq("goal").any()), "xg": float(shots.xg.fillna(0).sum()),
                    "lost_ball": bool(actions.turnover.iloc[-1])},
        "info": {"team": actions.team.iloc[0], "period": int(actions.period.iloc[0]),
                 "minute": int(actions.minute.iloc[0]), "second": int(actions.second.iloc[0]),
                 "actions": len(actions), "duration_s": round(duration, 1),
                 "start": actions.play_pattern.iloc[0], "regain": bool(actions.regain.any()),
                 "first_event": actions.index[0]},
    }


class SimilarityIndex:
    """Vectors of all possessions, and the closest ones to any of them."""

    def __init__(self, tags: pd.DataFrame, config: SimilarityConfig = SimilarityConfig()):
        self.config = config
        rows, keys = [], []
        for (match_id, possession), actions in possession_actions(tags).groupby(["match_id", "possession"]):
            if len(actions) >= config.min_actions:
                rows.append(describe_possession(actions, config))
                keys.append((match_id, possession))
        self.table = pd.DataFrame([{**r["info"], **r["outcome"]} for r in rows],
                                  index=pd.MultiIndex.from_tuples(keys, names=["match_id", "possession"]))
        self.paths = {k: r["path"].reshape(-1, 2) * [PITCH.length, PITCH.width] for k, r in zip(keys, rows)}
        if not rows:
            self.vectors = np.empty((0, 0))
            return
        blocks = []
        for part, weight in config.weights:
            x = np.vstack([r[part] for r in rows])
            if part == "tempo":  # different units: z-scores, damped to the range of the 0-1 parts
                x = (x - x.mean(0)) / (x.std(0) + 1e-9) / 3
            blocks.append(x * np.sqrt(weight / x.shape[1]))
        self.vectors = np.hstack(blocks)

    def __contains__(self, key) -> bool:
        return key in self.table.index

    def similar(self, match_id: int, possession: int, k: int = 10) -> pd.DataFrame:
        """The k closest other possessions, nearest first, with their outcomes and distance."""
        i = self.table.index.get_loc((match_id, possession))
        distance = np.linalg.norm(self.vectors - self.vectors[i], axis=1)
        distance[i] = np.inf
        nearest = np.argsort(distance, kind="stable")[:k]
        return self.table.iloc[nearest].assign(distance=distance[nearest].round(3))

    def all_neighbours(self, k: int):
        """(possession, neighbour, distance) for the k closest neighbours of every possession."""
        keys = list(self.table.index)
        for i, key in enumerate(keys):
            distance = np.linalg.norm(self.vectors - self.vectors[i], axis=1)
            distance[i] = np.inf
            for j in np.argsort(distance, kind="stable")[:k]:
                yield key, keys[j], float(distance[j])


def summary(neighbours: pd.DataFrame) -> str:
    """How the neighbours ended, in one line."""
    n = len(neighbours)
    return (f"{n} similar possessions: {int(neighbours.box_entry.sum())} reached the box, "
            f"{int(neighbours.shot.sum())} ended in a shot ({neighbours.xg.sum():.2f} xG), "
            f"{int(neighbours.goal.sum())} in a goal, {int(neighbours.lost_ball.sum())} in a lost ball")
