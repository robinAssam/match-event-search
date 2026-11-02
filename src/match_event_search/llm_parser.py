"""Parser v2: an Anthropic model translates the question into the JSON query format.

The model gets the query format, the allowed values of every field (from the
query schema itself), the football conventions of the rule-based parser, and
the names of every team and player, and answers with a JSON query only. The
answer is checked like any other query (schema and names). If it is invalid,
the model is shown the errors and asked once more; if it is still invalid, or
the API cannot be reached, the rule-based parser answers instead, and the
result says so (docs/methodology/06_llm_parser.md).
"""
import json
import re
from dataclasses import dataclass, field

import anthropic
import networkx as nx
import pandas as pd

from .config import DataConfig, LLMConfig
from .query import BOOLEAN_FIELDS, ENUM_FIELDS, NUMBER_FIELDS, TEXT_FIELDS, QueryError, check_names, validate
from .rule_parser import ParseError, Vocabulary, parse_verbose

# Errors from the API call that hand the question to the rule-based parser.
# The SDK raises TypeError when no credentials are configured.
API_ERRORS = (anthropic.APIError, TypeError)

INSTRUCTIONS = """You translate a football analyst's question into a JSON search query over StatsBomb event data \
of {focus}'s 2023/24 Bundesliga season. Reply with the JSON object only: no prose, no code fence.

## Query format
A query has either "event" (conditions on single events) or "sequence" (two or more steps), and optionally \
"matches".
- A filter is an object of conditions on the fields below; all must hold. A value can be one value, a list \
(any of these), or for numbers a range object with "gte", "gt", "lte" and/or "lt".
- {{"event": <filter>}}
- {{"sequence": [{{"filter": <filter>}}, {{"filter": <filter>, "within_s": <seconds>, "same_possession": true, \
"team": "same" | "other", "via": "next" | "same_player"}}, ...]}}. Only later steps have within_s, \
same_possession, team and via, and each later step needs within_s or "same_possession": true. within_s counts \
from the previous step's event. team is relative to the previous step's team. via "same_player" follows only \
the same player's actions.
- "matches": {{"opponent": <team name>, "venue": "home" | "away", "match_id": <id>}}, all optional.

## Fields
True/false: {booleans}
Numbers: {numbers}
Names (exact, from the lists below): {texts}
Fixed values:
{enums}

## How football words map onto fields
- "our", "we", or no team mentioned: "our_team": true (the analyst works for {focus}). "their", "opponent(s)", \
"conceded", "against us": "our_team": false. When a player is named, leave our_team out.
- Roles: role_group GK, CB, FB (full backs and wing backs), DM, CM, AM, W (wingers and wide midfielders), ST, \
with role_side left / centre / right. "Left back" is role_group FB with role_side left. "Defenders" are \
["CB", "FB"]; "midfielders" are ["DM", "CM", "AM"].
- The receiver of a pass: pass_recipient (a name), or recipient_role_group and recipient_role_side \
("passes to a defender").
- A goal is action "shot" with outcome_detail "goal"; shots on target are outcome_detail ["goal", "on_target"].
- A pass that was intercepted, cut out or lost is "turnover": true on that pass. "Interceptions" made by a \
player are action "interception".
- "Lost the ball" is "turnover": true; "won the ball (back)" or "regains" is "regain": true.
- Crosses are action "pass" with "cross": true; the same for through_ball, switch, cutback, key_pass and assist.
- "From corners / free kicks / throw-ins / goal kicks" is play_pattern ("From Corner", ...): the possession \
started that way. The corner kicks themselves are set_piece_type "corner".
- Zones are seen from the acting team: third "attacking" is near the goal that team attacks, half "own" is its \
own half. "Our half" is half "own" for our actions and half "opponent" for theirs.
- minute starts at 0: "after the 60th minute" is {{"gte": 60}}; "the last 15 minutes" is {{"gte": 75}}. \
"Second half" is period 2.
- In a sequence, a step after a turnover is by the other team ("team": "other") unless the question says whose \
it is; otherwise by the same team ("team": "same"). If no time is given: same team, "same_possession": true; \
other team, "within_s": 15, or 30 when the step is a goal.
- A named opponent ("against Bayern", "Bayern's shots") goes in matches.opponent with the full team name; if \
the opponent is the one acting, also "our_team": false.
- Use names exactly as listed below. If the question cannot be expressed in this format, reply \
{{"error": "<why>"}}.

## Teams and players
{teams}

## Examples
Question: progressive passes by the left back after the 60th minute
{{"event": {{"action": "pass", "progressive": true, "role_group": "FB", "role_side": "left", "our_team": true, \
"minute": {{"gte": 60}}}}}}

Question: turnovers in our own half that led to a shot within 10 seconds
{{"sequence": [{{"filter": {{"turnover": true, "our_team": true, "half": "own"}}}}, \
{{"filter": {{"action": "shot"}}, "team": "other", "within_s": 10}}]}}
"""


def system_prompt(tags: pd.DataFrame, data: DataConfig = DataConfig()) -> str:
    """The instructions, with the field vocabulary and every team's players filled in."""
    players = tags.dropna(subset=["player"]).groupby("team").player.unique()
    teams = [data.focus_team] + sorted(t for t in players.index if t != data.focus_team)
    roster = "\n".join(f"{team}{' (our team)' if team == data.focus_team else ''}: "
                       f"{', '.join(sorted(players[team]))}" for team in teams)
    enums = "\n".join(f"- {name}: {', '.join(map(str, values))}" for name, values in ENUM_FIELDS.items())
    return INSTRUCTIONS.format(focus=data.focus_team, booleans=", ".join(BOOLEAN_FIELDS),
                               numbers=", ".join(NUMBER_FIELDS), texts=", ".join(TEXT_FIELDS),
                               enums=enums, teams=roster)


@dataclass
class LLMParse:
    query: dict | None
    parser: str  # "llm", "rules" (the fallback) or "none"
    attempts: int = 0  # requests made to the model
    note: str = ""  # why the rule-based parser answered instead
    unparsed: list = field(default_factory=list)  # from the rule-based parser
    corrected: dict = field(default_factory=dict)  # from the rule-based parser
    usage: dict = field(default_factory=dict)  # tokens over all requests


class LLMParser:
    def __init__(self, g: nx.MultiDiGraph, client=None, config: LLMConfig = LLMConfig()):
        self.g = g
        self.config = config
        self.vocab = Vocabulary.from_tags(g.graph["tags"])
        self.system = system_prompt(g.graph["tags"])
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def parse(self, question: str) -> LLMParse:
        if not self.config.model:
            return self._fallback(question, "no model configured (LLM_MODEL is not set)", 0, {})
        messages = [{"role": "user", "content": question}]
        usage, problem = {}, ""
        for attempt in range(1, self.config.retries + 2):
            try:
                response = self._call(messages)
            except API_ERRORS as error:
                return self._fallback(question, f"the API call failed: {error}", attempt - 1, usage)
            _add_usage(usage, response.usage)
            if response.stop_reason == "refusal":
                return self._fallback(question, "the model declined the request", attempt, usage)
            text = "".join(b.text for b in response.content if b.type == "text")
            try:
                query = read_json(text)
                if set(query) == {"error"}:
                    return self._fallback(question, f"the model could not express it: {query['error']}",
                                          attempt, usage)
                validate(query)
                check_names(query, self.g)
                return LLMParse(query=query, parser="llm", attempts=attempt, usage=usage)
            except (ValueError, QueryError) as error:  # bad JSON, or a query that does not validate
                problem = str(error)
                messages += [
                    {"role": "assistant", "content": [b.to_dict() for b in response.content]},
                    {"role": "user", "content": f"That query is not valid: {problem}. "
                                                "Reply with the corrected JSON only."},
                ]
        return self._fallback(question, f"no valid query after {attempt} attempts ({problem})", attempt, usage)

    def _call(self, messages: list):
        return self.client.beta.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            output_config={"effort": self.config.effort},
            # The instructions are identical for every question, so they are cached.
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            # If the model declines a request, the API retries it on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def _fallback(self, question: str, reason: str, attempts: int, usage: dict) -> LLMParse:
        try:
            parsed = parse_verbose(question, self.vocab)
        except (ParseError, QueryError) as error:
            return LLMParse(query=None, parser="none", attempts=attempts, usage=usage,
                            note=f"{reason}; the rule-based parser could not read it either: {error}")
        return LLMParse(query=parsed.query, parser="rules", attempts=attempts, note=reason,
                        unparsed=parsed.unparsed, corrected=parsed.corrected, usage=usage)


def read_json(text: str) -> dict:
    """The JSON object in a reply, also when it is wrapped in a code fence."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in the reply: {text[:200]!r}")
    query = json.loads(text[start:end + 1])
    if not isinstance(query, dict):
        raise ValueError("the reply is not a JSON object")
    return query


def _add_usage(total: dict, usage):
    for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        total[name] = total.get(name, 0) + (getattr(usage, name, 0) or 0)
