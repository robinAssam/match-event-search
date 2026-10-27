"""Load StatsBomb open data, with a permanent local copy of every file.

statsbombpy downloads each file from the StatsBomb open-data repository on
every call (its own cache lives in a temporary folder). Here, every file is
downloaded once into `data/raw/statsbomb/`, byte for byte as published and
with the same folder layout as the repository, and read from disk after that.
statsbombpy still does the parsing, so the tables have its usual columns.

To refresh a file (e.g. `competitions.json` when StatsBomb adds data),
delete it and load again.
"""
import json
import warnings
from dataclasses import dataclass

import pandas as pd
import requests
from statsbombpy import public, sb
from statsbombpy.api_client import NoAuthWarning

from .config import DATA_DIR, DataConfig

OPEN_DATA_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/"
CACHE_DIR = DATA_DIR / "statsbomb"

# Matches whose 360 file shares no event ids with the event file, so no frame
# can be linked to its event. StatsBomb updated these 360 files (May 2026) but
# not the event files (May 2024). Treat them as matches without 360 data.
FRAMES_NOT_LINKED = {3895158, 3895266, 3895309}

# Open data needs no credentials, so statsbombpy's reminder is noise.
warnings.filterwarnings("ignore", category=NoAuthWarning)


def local_path(url: str):
    """Where the file at an open-data URL is stored locally."""
    if not url.startswith(OPEN_DATA_URL):
        raise ValueError(f"not a StatsBomb open-data URL: {url}")
    return CACHE_DIR / url.removeprefix(OPEN_DATA_URL)


def _cached_get_response(url: str):
    path = local_path(url)
    if not path.exists():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file first so an interrupted download never
        # leaves a truncated file behind.
        partial = path.with_suffix(".part")
        partial.write_bytes(response.content)
        partial.replace(path)
    return json.loads(path.read_text(encoding="utf-8"))


# statsbombpy fetches every open-data file through this one function.
public.get_response = _cached_get_response


@dataclass
class Match:
    match_id: int
    info: pd.Series
    events: pd.DataFrame
    frames: pd.DataFrame


def load_matches(config: DataConfig = DataConfig()) -> pd.DataFrame:
    """All matches of the configured season, in date order."""
    matches = sb.matches(competition_id=config.competition_id, season_id=config.season_id)
    return matches.sort_values(["match_date", "kick_off"]).reset_index(drop=True)


def load_events(match_id: int) -> pd.DataFrame:
    """One row per event, in the order StatsBomb recorded them (`index`)."""
    events = sb.events(match_id=match_id)
    return events.sort_values("index").reset_index(drop=True)


def load_frames(match_id: int) -> pd.DataFrame:
    """360 freeze-frames: one row per visible player per event (`id` = event id)."""
    return sb.frames(match_id=match_id)


def load_match(match_id: int, config: DataConfig = DataConfig()) -> Match:
    matches = load_matches(config).set_index("match_id")
    return Match(
        match_id=match_id,
        info=matches.loc[match_id],
        events=load_events(match_id),
        frames=load_frames(match_id),
    )
