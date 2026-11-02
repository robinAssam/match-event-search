"""The query format and the engine that runs it on the event graph.

A query is a JSON object with either a single-event filter or a sequence
(docs/methodology/04_query.md):

    {"event": {"action": "pass", "progressive": true, "minute": {"gte": 60}}}

    {"sequence": [
        {"filter": {"turnover": true, "our_team": true, "half": "own"}},
        {"filter": {"action": "shot"}, "team": "other", "within_s": 10}
    ]}

and optionally `"matches": {"opponent": ..., "venue": "home" | "away", "match_id": ...}`.

A filter is a set of conditions on the tag columns, all of which must hold. A
sequence step after the first is searched among the events that follow the
previous step's event: at most `within_s` seconds later and/or in the same
possession, optionally by the `same` or `other` team, along `next` edges or,
with `"via": "same_player"`, along the player's own actions. For each event
matching the first step the engine takes the earliest match of each later step.
"""
from dataclasses import dataclass, field

import jsonschema
import networkx as nx
import pandas as pd

from . import tagging
from .config import DataConfig
from .graph import following

# --- Schema ----------------------------------------------------------------------

BOOLEAN_FIELDS = [
    "cross", "through_ball", "switch", "cutback", "key_pass", "assist", "header",
    "progressive", "box_entry", "turnover", "regain", "in_box", "end_in_box",
    "under_pressure", "counterpress", "our_team", "home", "in_possession",
]
NUMBER_FIELDS = [
    "period", "minute", "second", "t", "since_regain", "goals_for", "goals_against",
    "goal_diff", "xg", "x", "y", "end_x", "end_y",
]
ENUM_FIELDS = {
    "action": tagging.ACTIONS,
    "set_piece_type": tagging.SET_PIECE_TYPES,
    "play_pattern": tagging.PLAY_PATTERNS,
    "third": tagging.THIRDS, "end_third": tagging.THIRDS,
    "channel": tagging.CHANNELS, "end_channel": tagging.CHANNELS,
    "half": tagging.HALVES,
    "phase": tagging.PHASES,
    "position": sorted(tagging.ROLE_GROUPS),
    "role_group": sorted(set(tagging.ROLE_GROUPS.values())),
    "role_side": tagging.ROLE_SIDES,
    "recipient_position": sorted(tagging.ROLE_GROUPS),
    "recipient_role_group": sorted(set(tagging.ROLE_GROUPS.values())),
    "recipient_role_side": tagging.ROLE_SIDES,
    "outcome": tagging.OUTCOMES,
    "game_state": tagging.GAME_STATES,
    "time_bucket": tagging.TIME_BUCKETS,
}
TEXT_FIELDS = ["player", "pass_recipient", "team", "outcome_detail"]


def _one_or_many(item: dict) -> dict:
    return {"oneOf": [item, {"type": "array", "items": item, "minItems": 1}]}


RANGE = {
    "type": "object",
    "properties": {op: {"type": "number"} for op in ("gte", "gt", "lte", "lt")},
    "additionalProperties": False,
    "minProperties": 1,
}

FILTER = {
    "type": "object",
    "properties": {
        **{f: {"type": "boolean"} for f in BOOLEAN_FIELDS},
        **{f: {"oneOf": [*_one_or_many({"type": "number"})["oneOf"], RANGE]} for f in NUMBER_FIELDS},
        **{f: _one_or_many({"enum": values}) for f, values in ENUM_FIELDS.items()},
        **{f: _one_or_many({"type": "string"}) for f in TEXT_FIELDS},
    },
    "additionalProperties": False,
    "minProperties": 1,
}

FIRST_STEP = {
    "type": "object",
    "properties": {"filter": FILTER},
    "required": ["filter"],
    "additionalProperties": False,
}

LATER_STEP = {
    "type": "object",
    "properties": {
        "filter": FILTER,
        "within_s": {"type": "number", "exclusiveMinimum": 0},
        "same_possession": {"type": "boolean"},
        "team": {"enum": ["same", "other"]},
        "via": {"enum": ["next", "same_player"]},
    },
    "required": ["filter"],
    # Without a time limit or the possession as a limit, "followed by" has no end.
    "anyOf": [{"required": ["within_s"]}, {"required": ["same_possession"],
                                            "properties": {"same_possession": {"const": True}}}],
    "additionalProperties": False,
}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Match event search query",
    "type": "object",
    "properties": {
        "event": FILTER,
        "sequence": {"type": "array", "prefixItems": [FIRST_STEP], "items": LATER_STEP, "minItems": 2},
        "matches": {
            "type": "object",
            "properties": {
                "opponent": _one_or_many({"type": "string"}),
                "venue": {"enum": ["home", "away"]},
                "match_id": _one_or_many({"type": "integer"}),
            },
            "additionalProperties": False,
        },
    },
    "oneOf": [{"required": ["event"]}, {"required": ["sequence"]}],
    "additionalProperties": False,
}


class QueryError(ValueError):
    pass


def validate(query: dict):
    """Raise QueryError listing every problem with the query."""
    validator = jsonschema.Draft202012Validator(SCHEMA)
    errors = sorted(validator.iter_errors(query), key=lambda e: list(e.absolute_path))
    if errors:
        raise QueryError("; ".join(_describe(e) for e in errors))


def _describe(error: jsonschema.ValidationError) -> str:
    where = "/".join(str(p) for p in error.absolute_path) or "query"
    if error.validator == "anyOf" and "within_s" in error.validator_value[0].get("required", []):
        return f'{where}: a later step needs "within_s" or "same_possession": true'
    if error.validator == "oneOf" and error.schema is SCHEMA:
        return f'{where}: give either "event" or "sequence"'
    # For oneOf (a value or a list of values), the deepest error that is not
    # about the value's type says what is wrong, e.g. one list item missing
    # from the enum.
    depth = len(error.absolute_path)
    specific = [e for e in error.context
                if len(e.absolute_path) > depth or e.validator not in ("type", "oneOf")]
    if specific:
        error = max(specific, key=lambda e: len(e.absolute_path))
    return f"{'/'.join(str(p) for p in error.absolute_path) or where}: {error.message}"


# --- Engine ----------------------------------------------------------------------

@dataclass
class Match:
    """One moment found: the events matching each step, and every event in between."""
    steps: list
    span: list = field(default_factory=list)


def search(query: dict, g: nx.MultiDiGraph) -> pd.DataFrame:
    """Run a query; one row per moment found, in match order."""
    return results_table(find(query, g), g)


def find(query: dict, g: nx.MultiDiGraph) -> list[Match]:
    validate(query)
    check_names(query, g)
    tags = g.graph["tags"]
    in_scope = tags.match_id.isin(_matches_in_scope(query.get("matches", {}), g))
    if "event" in query:
        hits = tags.index[in_scope & mask(query["event"], tags)]
        return [Match(steps=[e], span=[e]) for e in hits]

    steps = query["sequence"]
    starts = tags.index[in_scope & mask(steps[0]["filter"], tags)]
    candidates = [set(tags.index[mask(step["filter"], tags)]) for step in steps[1:]]
    found = []
    for start in starts:
        chain = [start]
        for step, allowed in zip(steps[1:], candidates):
            nxt = _next_match(g, chain[-1], step, allowed)
            if nxt is None:
                break
            chain.append(nxt)
        else:
            found.append(Match(steps=chain, span=_span(tags, chain[0], chain[-1])))
    return found


def check_names(query: dict, g: nx.MultiDiGraph):
    """Raise QueryError for player or team names that are not in the data.

    The schema cannot list every name, and a misspelt one would silently
    match nothing.
    """
    tags = g.graph["tags"]
    filters = [query["event"]] if "event" in query else [step["filter"] for step in query["sequence"]]
    known = {"player": tags.player, "pass_recipient": tags.player, "team": tags.team}
    problems = []
    for f in filters:
        for name, column in known.items():
            values = f.get(name, [])
            for value in values if isinstance(values, list) else [values]:
                if not column.eq(value).any():
                    problems.append(f"unknown {name} {value!r}")
    opponents = query.get("matches", {}).get("opponent", [])
    for value in opponents if isinstance(opponents, list) else [opponents]:
        if not tags.team.eq(value).any():
            problems.append(f"unknown opponent {value!r}")
    if problems:
        raise QueryError("; ".join(problems))


def mask(conditions: dict, tags: pd.DataFrame) -> pd.Series:
    """Rows of the tag table that meet every condition of a filter."""
    keep = pd.Series(True, index=tags.index)
    for name, wanted in conditions.items():
        column = tags[name]
        if isinstance(wanted, dict):
            ops = {"gte": column.ge, "gt": column.gt, "lte": column.le, "lt": column.lt}
            for op, value in wanted.items():
                keep &= ops[op](value)
        elif isinstance(wanted, list):
            keep &= column.isin(wanted)
        else:
            keep &= column.eq(wanted)
    return keep


def _next_match(g, previous, step, allowed):
    """The earliest event after `previous` that matches a later sequence step."""
    team = g.nodes[previous]["team"]
    for event, _ in following(g, previous, key=step.get("via", "next"),
                              within_s=step.get("within_s"),
                              same_possession=step.get("same_possession", False)):
        if event not in allowed:
            continue
        relation = step.get("team")
        if relation == "same" and g.nodes[event]["team"] != team:
            continue
        if relation == "other" and g.nodes[event]["team"] == team:
            continue
        return event
    return None


def _span(tags, first, last) -> list:
    """Every event from `first` to `last` in the same match, in order."""
    a, b = tags.loc[first], tags.loc[last]
    same_match = tags.match_id.eq(a.match_id)
    return list(tags.index[same_match & tags["index"].between(a["index"], b["index"])])


def _matches_in_scope(scope: dict, g) -> list:
    rows = pd.DataFrame([d for _, d in g.nodes(data=True) if d["kind"] == "match"])
    focus = DataConfig().focus_team
    keep = pd.Series(True, index=rows.index)
    if "opponent" in scope:
        opponents = scope["opponent"] if isinstance(scope["opponent"], list) else [scope["opponent"]]
        keep &= rows.home_team.isin(opponents) | rows.away_team.isin(opponents)
    if "venue" in scope:
        keep &= rows.home_team.eq(focus) if scope["venue"] == "home" else rows.away_team.eq(focus)
    if "match_id" in scope:
        ids = scope["match_id"] if isinstance(scope["match_id"], list) else [scope["match_id"]]
        keep &= rows.match_id.isin(ids)
    return list(rows.match_id[keep])


def results_table(found: list[Match], g) -> pd.DataFrame:
    """One row per moment, built column by column (a broad query finds tens of thousands)."""
    tags = g.graph["tags"]
    columns = ["match", "match_id", "period", "minute", "second", "players", "outcome",
               "duration_s", "steps", "span"]
    if not found:
        return pd.DataFrame(columns=columns)
    first = tags.loc[[m.steps[0] for m in found]].reset_index(drop=True)
    last = tags.loc[[m.steps[-1] for m in found]].reset_index(drop=True)
    labels = {d["match_id"]: f"{d['date']} {d['home_team']} {d['home_score']}-{d['away_score']} {d['away_team']}"
              for _, d in g.nodes(data=True) if d["kind"] == "match"}
    player = tags.player.to_dict()
    table = pd.DataFrame({
        "match": first.match_id.map(labels),
        "match_id": first.match_id,
        "period": first.period,
        "minute": first.minute,
        "second": first.second,
        "players": [", ".join(dict.fromkeys(p for p in map(player.get, m.steps) if isinstance(p, str)))
                    for m in found],
        "outcome": last.outcome_detail.where(last.outcome_detail.map(lambda v: isinstance(v, str)), last.outcome),
        "duration_s": (last.t - first.t).round(1),
        "steps": [m.steps for m in found],
        "span": [m.span for m in found],
    })
    # The match label starts with the date, so this sorts by date and match time.
    return table.sort_values(["match", "period", "minute", "second"], kind="stable").reset_index(drop=True)
