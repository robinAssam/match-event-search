"""Central configuration. Tag and query parameters will be added here in later stages."""
import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


@dataclass(frozen=True)
class DataConfig:
    """Which StatsBomb open-data season the project is built on.

    Bundesliga 2023/24 (competition 9, season 281) holds all 34 league
    matches of Bayer Leverkusen's unbeaten season (28 wins, 6 draws), every
    one with 360 freeze-frames. One club over a full season matches how a
    club analyst works: "our left back" always means the same team's player.

    focus_team: the team that "our" refers to in questions.
    """

    competition_id: int = 9
    season_id: int = 281
    focus_team: str = "Bayer Leverkusen"


@dataclass(frozen=True)
class PitchConfig:
    """StatsBomb pitch coordinates and their size in metres.

    StatsBomb records every location on a 120 x 80 grid with the acting team
    attacking towards x = 120, and y = 0 on that team's left (StatsBomb Open
    Data Events specification v4; checked in the data: Left Backs average
    y = 13.5, Right Backs y = 67.2). The grid is the same whatever the real
    pitch size, so distances in metres assume FIFA's recommended 105 x 68 m,
    the same size as in spearman-pitch-control.

    box_x, box_y: the penalty area, x >= 102 and 18 <= y <= 62 (StatsBomb
        specification, pitch diagram).
    """

    length: float = 120.0
    width: float = 80.0
    length_m: float = 105.0
    width_m: float = 68.0
    box_x: float = 102.0
    box_y: tuple[float, float] = (18.0, 62.0)


@dataclass(frozen=True)
class TagConfig:
    """Parameters of the tag schema (docs/methodology/02_tagging.md).

    third_lines: x where the defensive, middle and attacking thirds meet;
        three equal thirds of the 120-unit pitch.
    channel_lines: y where the five channels meet: left wing, left half-space,
        centre, right half-space, right wing. The lines are the sides of the
        penalty area (18, 62) and of the six-yard box (30, 50), the usual
        markings for half-spaces.
    progressive_m: how much closer to the centre of the opponent's goal (m) a
        pass or carry must end, for start and end both in the own half,
        in different halves, and both in the opponent's half. Wyscout's
        definitions of a progressive pass and a progressive run
        (dataglossary.wyscout.com/progressive_pass, /progressive_run).
    transition_window_s: an in-possession event is in transition when it is
        at most this long after the team won the ball in open play. Our
        choice; it matches the analyst's question "led to a shot within 10
        seconds".
    set_piece_window_s: events up to this long after a corner, or a free kick
        taken in the attacking third, belong to the set piece. Our choice,
        the same window as for transitions.
    time_bucket_min: length of the time windows within each half (minutes).
    """

    third_lines: tuple[float, float] = (40.0, 80.0)
    channel_lines: tuple[float, float, float, float] = (18.0, 30.0, 50.0, 62.0)
    progressive_m: tuple[float, float, float] = (30.0, 15.0, 10.0)
    transition_window_s: float = 10.0
    set_piece_window_s: float = 10.0
    time_bucket_min: int = 15


@dataclass(frozen=True)
class LLMConfig:
    """The LLM question parser (parser v2, docs/methodology/06_llm_parser.md).

    model: the Anthropic model id, read from the LLM_MODEL environment
        variable (set next to ANTHROPIC_API_KEY). Without it, questions go to
        the rule-based parser.
    effort: how much the model reasons before answering. "medium" is enough
        to translate a question into a small JSON query.
    max_tokens: room for the reasoning and the answer; a query is short.
    retries: after an invalid query, how many times the model is shown the
        validation errors and asked to correct it before the rule-based
        parser takes over.
    """

    model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    effort: str = "medium"
    max_tokens: int = 16000
    retries: int = 1


@dataclass(frozen=True)
class SimilarityConfig:
    """Settings for finding similar situations (docs/methodology/09_similarity.md).

    min_actions: possessions with fewer actions by the team on the ball are
        too short to have a shape (a single clearance, a lost first touch).
    path_points: the ball's route is resampled to this many points, so
        possessions of any length can be compared.
    weights: share of the distance from each part of the vector: the route,
        the tempo, and how the possession started. The outcome (shot, goal) is
        left out on purpose, so similar build-ups can be compared by how they
        ended. Our choice, checked by eye and by how often neighbours start
        the same way (99% against 27% by chance).
    neighbours: `similar` edges per possession in the graph.
    """

    min_actions: int = 3
    path_points: int = 10
    weights: tuple[tuple[str, float], ...] = (("path", 0.6), ("tempo", 0.25), ("start", 0.15))
    neighbours: int = 5
