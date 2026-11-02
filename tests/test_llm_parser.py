"""LLM parser tests with a simulated API client: no requests are sent and nothing is spent."""
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pandas as pd
import pytest

from match_event_search import graph
from match_event_search.config import LLMConfig
from match_event_search.llm_parser import LLMParser, read_json, system_prompt
from match_event_search.query import ENUM_FIELDS

US, THEM = "Bayer Leverkusen", "Opponent FC"
CONFIG = LLMConfig(model="test-model", effort="medium", max_tokens=1000, retries=1)
SHOTS = {"event": {"action": "shot", "our_team": True}}


def toy_graph():
    tags = pd.DataFrame({
        "id": ["e1", "e2", "e3"], "t": [0.0, 1.0, 2.0], "possession": [1, 1, 2],
        "team": [US, US, THEM], "player": ["Florian Wirtz", "Granit Xhaka", "Leroy Sané"],
        "action": ["pass", "shot", "pass"], "our_team": [True, True, False],
    })
    tags["index"] = range(1, 4)
    tags["match_id"], tags["period"], tags["x"], tags["play_pattern"] = 1, 1, 50.0, "Regular Play"
    tags["possession_team"] = tags.team
    matches = pd.DataFrame([{"match_id": 1, "match_date": "2023-08-19", "home_team": US, "away_team": THEM,
                             "home_score": 0, "away_score": 0}])
    return graph.build_graph(tags, matches)


class Block(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


def reply(text, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=100,
                            cache_creation_input_tokens=0)
    content = [Block(type="thinking", thinking="", signature="sig"), Block(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


class FakeClient:
    """Answers each request with the next reply (or raises it, if it is an exception)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(json.loads(json.dumps(request)))  # a copy, as sent
        answer = self.replies.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture(scope="module")
def g():
    return toy_graph()


def parser(g, *replies, config=CONFIG):
    client = FakeClient(*replies)
    return LLMParser(g, client=client, config=config), client


def test_a_valid_answer_is_used(g):
    p, client = parser(g, reply(json.dumps(SHOTS)))
    result = p.parse("our shots")
    assert (result.parser, result.attempts, result.query) == ("llm", 1, SHOTS)
    request = client.requests[0]
    assert request["model"] == "test-model" and request["output_config"] == {"effort": "medium"}
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["fallbacks"] == "default" and request["messages"] == [{"role": "user", "content": "our shots"}]
    assert result.usage == {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                            "cache_creation_input_tokens": 0}


def test_an_invalid_answer_is_corrected_after_seeing_the_error(g):
    p, client = parser(g, reply('{"event": {"third": "atacking"}}'), reply(json.dumps(SHOTS)))
    result = p.parse("our shots")
    assert (result.parser, result.attempts, result.query) == ("llm", 2, SHOTS)
    second = client.requests[1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"][0]["type"] == "thinking"  # echoed unchanged
    assert "'atacking' is not one of" in second[2]["content"]
    assert result.usage["input_tokens"] == 20


def test_an_unknown_name_counts_as_invalid(g):
    p, client = parser(g, reply('{"event": {"player": "Wirtz"}}'),
                       reply('{"event": {"player": "Florian Wirtz"}}'))
    result = p.parse("Wirtz")
    assert result.query == {"event": {"player": "Florian Wirtz"}}
    assert "unknown player 'Wirtz'" in client.requests[1]["messages"][2]["content"]


def test_still_invalid_after_the_retry_falls_back_to_the_rules(g):
    p, client = parser(g, reply("not json"), reply('{"event": {}}'))
    result = p.parse("our shots")
    assert result.parser == "rules" and result.attempts == 2
    assert result.query == {"event": {"action": "shot", "our_team": True}}
    assert result.note.startswith("no valid query after 2 attempts")


def test_a_code_fence_is_accepted():
    assert read_json('```json\n{"event": {"action": "shot"}}\n```') == {"event": {"action": "shot"}}
    with pytest.raises(ValueError):
        read_json("I cannot help with that")


def test_the_model_saying_it_cannot_falls_back(g):
    p, _ = parser(g, reply('{"error": "no data on weather"}'))
    result = p.parse("shots in the rain")
    assert result.parser == "rules" and result.query == {"event": {"action": "shot", "our_team": True}}
    assert result.note == "the model could not express it: no data on weather"


@pytest.mark.parametrize("error", [
    TypeError("Could not resolve authentication method."),
    anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.example.invalid")),
])
def test_api_errors_fall_back_to_the_rules(g, error):
    p, _ = parser(g, error)
    result = p.parse("our shots")
    assert result.parser == "rules" and result.attempts == 0
    assert result.note.startswith("the API call failed")


def test_a_refusal_falls_back(g):
    p, _ = parser(g, reply("", stop_reason="refusal"))
    assert p.parse("our shots").note == "the model declined the request"


def test_without_a_model_no_request_is_made(g):
    p, client = parser(g, config=LLMConfig(model=""))
    result = p.parse("our shots")
    assert result.parser == "rules" and "LLM_MODEL" in result.note and client.requests == []


def test_nothing_readable_by_either_parser(g):
    p, _ = parser(g, reply("nonsense"), reply("nonsense"))
    result = p.parse("hello there")
    assert result.parser == "none" and result.query is None
    assert "could not read it either" in result.note


def test_the_instructions_list_every_value_and_name(g):
    prompt = system_prompt(g.graph["tags"])
    assert all(str(v) in prompt for values in ENUM_FIELDS.values() for v in values)
    assert "Bayer Leverkusen (our team): Florian Wirtz, Granit Xhaka" in prompt
    assert "Opponent FC: Leroy Sané" in prompt
