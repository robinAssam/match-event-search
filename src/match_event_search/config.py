"""Central configuration. Tag and query parameters will be added here in later stages."""
from dataclasses import dataclass
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
