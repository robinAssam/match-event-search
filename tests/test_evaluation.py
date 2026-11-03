"""Evaluation tests: the scoring rules, and the approved expected queries scored against themselves."""
import pytest

from match_event_search import graph, loaders
from match_event_search.evaluation import Answer, grade, load_questions, moments, normalise, same_query


def test_normalise_ignores_key_order_list_order_and_one_item_lists():
    a = {"event": {"third": ["middle"], "action": ["shot", "pass"], "minute": {"gte": 60}}}
    b = {"event": {"minute": {"gte": 60.0}, "action": ["pass", "shot"], "third": "middle"}}
    assert normalise(a) == normalise(b) and same_query(a, b)


def test_normalise_keeps_the_order_of_sequence_steps():
    first, second = {"filter": {"turnover": True}}, {"filter": {"action": "shot"}, "within_s": 10}
    assert not same_query({"sequence": [first, second]}, {"sequence": [second, first]})


def test_true_is_not_one():
    assert not same_query({"event": {"progressive": True}}, {"event": {"progressive": 1}})


def test_a_question_that_cannot_be_expressed_is_right_only_when_declined():
    assert grade(Answer(query=None, declined=True), None, g=None)["correct"]
    assert not grade(Answer(query=None, declined=False), None, g=None)["correct"]  # e.g. the API failed
    assert not grade(Answer(query={"event": {"action": "pass"}}), None, g=None)["correct"]


def test_the_question_set():
    questions = load_questions()
    assert [q["id"] for q in questions] == list(range(1, len(questions) + 1))
    assert {"question", "query", "category", "note"} <= set(questions[0])


EVENTS_DIR = loaders.CACHE_DIR / "events"
DOWNLOADED = {int(p.stem) for p in EVENTS_DIR.glob("*.json")} if EVENTS_DIR.exists() else set()
requires_season = pytest.mark.skipif(not DOWNLOADED or not set(loaders.load_matches().match_id) <= DOWNLOADED,
                                     reason="season not downloaded")


@pytest.fixture(scope="module")
def season():
    return graph.season_graph()


@requires_season
def test_every_expected_query_finds_moments_and_scores_itself_as_correct(season):
    for q in load_questions():
        if q["query"] is None:
            continue
        expected = moments(q["query"], season)
        assert expected, q["id"]
        score = grade(Answer(query=q["query"]), q["query"], season, expected)
        assert score["correct"] and score["exact"], q["id"]


@requires_season
def test_a_query_finding_other_moments_is_wrong(season):
    q = load_questions()[0]  # Boniface's shots from outside the box
    expected = moments(q["query"], season)
    score = grade(Answer(query={"event": {"player": "Victor Okoh Boniface", "action": "shot"}}), q["query"], season,
                  expected)
    assert not score["correct"] and score["n_found"] > score["n_expected"]


class FakeLLM:
    def __init__(self, result):
        self.result = result

    def parse(self, question):
        return self.result


def test_v2_alone_counts_a_fallback_as_no_answer():
    from match_event_search.evaluation import answer_v2
    from match_event_search.llm_parser import LLMParse
    rules_query = {"event": {"action": "pass", "our_team": True}}
    declined = LLMParse(query=rules_query, parser="rules", attempts=1, note="the model could not express it: no data")
    alone, with_fallback = answer_v2("passes that broke the line", FakeLLM(declined))
    assert alone.query is None and alone.declined
    assert with_fallback.query == rules_query and not with_fallback.declined

    failed = LLMParse(query=rules_query, parser="rules", attempts=0, note="the API call failed: timeout")
    alone, _ = answer_v2("passes", FakeLLM(failed))
    assert alone.query is None and not alone.declined  # an API failure is not a correct "cannot express"

    answered = LLMParse(query=rules_query, parser="llm", attempts=1, usage={"input_tokens": 7})
    alone, with_fallback = answer_v2("our passes", FakeLLM(answered))
    assert alone.query == with_fallback.query == rules_query and alone.usage == {"input_tokens": 7}
