"""Loader tests. The data checks run on every downloaded match and are skipped
if nothing is downloaded yet: run `python scripts/download_data.py` first."""
import pytest

from match_event_search import loaders
from match_event_search.loaders import OPEN_DATA_URL, load_events, load_frames

EVENTS_DIR = loaders.CACHE_DIR / "events"


def test_local_path_mirrors_repository_layout():
    path = loaders.local_path(OPEN_DATA_URL + "events/123.json")
    assert path == loaders.CACHE_DIR / "events" / "123.json"


def test_local_path_rejects_other_urls():
    with pytest.raises(ValueError):
        loaders.local_path("https://example.com/events/123.json")


def test_file_is_downloaded_once(tmp_path, monkeypatch):
    calls = []

    class Response:
        content = b'[{"id": 1}]'

        def raise_for_status(self):
            pass

    def fake_get(url, timeout):
        calls.append(url)
        return Response()

    monkeypatch.setattr(loaders, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(loaders.requests, "get", fake_get)
    url = OPEN_DATA_URL + "events/1.json"
    assert loaders._cached_get_response(url) == [{"id": 1}]
    assert loaders._cached_get_response(url) == [{"id": 1}]
    assert len(calls) == 1
    assert (tmp_path / "events" / "1.json").exists()


DOWNLOADED = sorted(int(p.stem) for p in EVENTS_DIR.glob("*.json")) if EVENTS_DIR.exists() else []
requires_data = pytest.mark.skipif(not DOWNLOADED, reason="no matches downloaded")


@pytest.fixture(scope="module")
def matches():
    return loaders.load_matches().set_index("match_id")


@pytest.fixture(scope="module", params=DOWNLOADED)
def match(request, matches):
    return matches.loc[request.param], load_events(request.param)


@requires_data
def test_goals_add_up_to_final_score(match):
    info, events = match
    goals = events[(events.type == "Shot") & (events.shot_outcome == "Goal")].team.value_counts()
    own_goals = events[events.type == "Own Goal For"].team.value_counts()
    for team, score in [(info.home_team, info.home_score), (info.away_team, info.away_score)]:
        assert goals.get(team, 0) + own_goals.get(team, 0) == score


@requires_data
def test_locations_are_on_the_120_by_80_pitch(match):
    locations = match[1].location.dropna()
    assert locations.map(lambda l: 0 <= l[0] <= 120 and 0 <= l[1] <= 80).all()


@requires_data
def test_each_team_attacks_left_to_right(match):
    """Every event is recorded from the acting team's own perspective, so both
    teams' shots are at high x. A rare shot from the own half is allowed."""
    shots = match[1][match[1].type == "Shot"]
    in_attacking_half = shots.location.map(lambda l: l[0] > 60)
    assert in_attacking_half.mean() >= 0.95


@requires_data
def test_possessions_are_numbered_in_order(match):
    possession = match[1].possession
    assert possession.iloc[0] == 1
    assert possession.is_monotonic_increasing


@requires_data
def test_two_halves_and_two_starting_elevens(match):
    events = match[1]
    assert set(events.period) == {1, 2}
    lineups = events[events.type == "Starting XI"].tactics
    assert [len(t["lineup"]) for t in lineups] == [11, 11]


@requires_data
@pytest.mark.parametrize("match_id", DOWNLOADED)
def test_most_events_have_a_360_frame(match_id):
    events, frames = load_events(match_id), load_frames(match_id)
    linked = events.id.isin(frames.id).mean()
    if match_id in loaders.FRAMES_NOT_LINKED:
        assert linked == 0  # if this fails, StatsBomb has fixed the files
    else:
        assert linked > 0.8
