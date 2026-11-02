"""The Streamlit page, run without a browser (skipped if the season is not downloaded)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from match_event_search import loaders

APP = Path(__file__).resolve().parents[1] / "app" / "app.py"
EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = {int(p.stem) for p in EVENTS_DIR.glob("*.json")} if EVENTS_DIR.exists() else set()
pytestmark = pytest.mark.skipif(not DOWNLOADED or not set(loaders.load_matches().match_id) <= DOWNLOADED,
                                reason="season not downloaded")


@pytest.fixture(scope="module")
def app():
    # No model, so choosing the LLM parser never sends a request (or spends money) in tests.
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LLM_MODEL", "")
        yield AppTest.from_file(str(APP), default_timeout=600).run()


def test_page_opens_with_the_first_example(app):
    assert not app.exception
    assert app.subheader[0].value == "105 moments"


def test_a_misspelt_question_is_corrected_and_answered(app):
    app.text_input(key="question").set_value("goalkeeper pass to defender intercepted and led to conceeding goal").run()
    assert not app.exception
    assert app.subheader[0].value == "1 moment"
    assert app.info[0].value == "Read “conceeding” as “conceding”"


def test_an_unreadable_question_shows_an_error(app):
    app.text_input(key="question").set_value("hello there").run()
    assert "nothing recognised" in app.error[0].value


def test_the_llm_parser_without_a_model_falls_back_and_says_so(app):
    app.radio(key="parser").set_value("LLM (v2)").run()
    app.text_input(key="question").set_value("goalkeeper pass to defender intercepted and led to conceeding goal").run()
    assert not app.exception
    assert app.subheader[0].value == "1 moment"
    assert "The LLM parser was not used: no model configured" in app.warning[0].value
