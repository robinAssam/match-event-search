# 4. Query format and engine

A question becomes a JSON query, the football version of placing a legal question in the tree. The format is
explicit so that both parsers (rule-based in stage 5, LLM in stage 6) can produce it and it can be checked before it
runs. [`query.py`](../../src/match_event_search/query.py) holds the JSON Schema and the engine;
[`scripts/search.py`](../../scripts/search.py) runs a query from the command line.

## Format

A query has either `event` (a filter on single events) or `sequence` (two or more steps), and optionally `matches`.

**A filter** is a set of conditions on the tag columns of stage 2, all of which must hold:

| Field type | Fields | Write |
|---|---|---|
| true / false | `progressive`, `turnover`, `regain`, `box_entry`, `cross`, `header`, `in_box`, `under_pressure`, `our_team`, `home`, … | `"progressive": true` |
| one of a fixed list | `action`, `third`, `channel`, `half`, `phase`, `role_group`, `role_side`, `position`, `recipient_role_group`, `recipient_role_side`, `recipient_position`, `outcome`, `game_state`, `time_bucket`, `set_piece_type`, `play_pattern`, `end_third`, `end_channel` | `"third": "attacking"` or `"third": ["middle", "attacking"]` |
| number | `minute`, `period`, `since_regain`, `goal_diff`, `xg`, `x`, `y`, … | `"minute": 60`, `[60, 61]` or `{"gte": 60}` (also `gt`, `lte`, `lt`) |
| name | `player`, `pass_recipient`, `team`, `outcome_detail` | `"player": "Florian Wirtz"` |

**A sequence step** after the first has a `filter` and is searched among the events after the previous step's event:

| Field | Meaning |
|---|---|
| `within_s` | at most this many seconds after the previous step |
| `same_possession` | `true`: still in the previous step's possession |
| `team` | `"same"` or `"other"` team as the previous step |
| `via` | `"next"` (default): every following event; `"same_player"`: only the same player's actions |

Each later step needs `within_s` or `"same_possession": true`, so that "followed by" always ends somewhere.

**Scope**: `"matches": {"opponent": "Bayern Munich", "venue": "home", "match_id": 3895052}`, all optional.

## Examples (whole season)

*"Progressive passes by the left back after the 60th minute"*: 105 passes, 84 of them Grimaldo's.
```json
{"event": {"action": "pass", "progressive": true, "role_group": "FB", "role_side": "left",
           "our_team": true, "minute": {"gte": 60}}}
```

*"Turnovers in our own half that led to a shot within 10 seconds"*: 18 of Leverkusen's 323 turnovers in their own half.
```json
{"sequence": [
  {"filter": {"turnover": true, "our_team": true, "half": "own"}},
  {"filter": {"action": "shot"}, "team": "other", "within_s": 10}
]}
```

## Decisions

1. **`within_s` counts from the previous step.** "A shot within 10 seconds of the turnover" is the literal reading.
   Counting from the regain is a three-step sequence (turnover → regain by the other team → shot by the same team
   within 10 s) and finds 22 instead of 18. Leverkusen's opening goal of the season shows the difference: the shot
   came 10.5 s after Werner's turnover but 9.1 s after Xhaka's regain.
2. **One result per first-step event, with the earliest match of each later step.** If two turnovers lead to the
   same shot, both are results.
3. **Field names are the tag columns**, so the format maps one-to-one onto the schema; turning "left back" into
   `role_group` and `role_side` is the parser's job.
4. **No OR across fields** yet: `"action": ["pass", "shot"]` works, "progressive passes or anything in the box"
   does not. None of the example questions needs it.

`minute` is StatsBomb's minute, which starts at 0: "after the 60th minute" is `{"gte": 60}`, from 60:00 onwards.

## Validation

The schema lists the allowed values of every fixed-list field, taken from the tag schema itself, so a misspelt value
is an error and not a query that silently finds nothing. Errors say where and what, for example
`event/third: 'atacking' is not one of ['defensive', 'middle', 'attacking']`, so the LLM parser can be told what to
fix. Names cannot be listed in the schema; the engine checks them against the data instead (`unknown player
'Wirtz'`).

## Engine

A filter on single events is a vectorised filter on the tag table. For a sequence, the engine finds all events that
match the first step, then from each one walks forward along `next` (or `same_player`) edges with `following()` from
stage 3, adding up the time, until the time limit or the end of the possession, and takes the first event that
matches the next step and team. Each example question runs in under 0.1 s on the season.

Each result row gives the match, the half, minute and second of the first step, the players of the steps, the
outcome of the last step, the time from first to last step, the event ids of the steps and every event in between
(`span`), which the interface will plot.

The tests in [`test_query.py`](../../tests/test_query.py) check the rules on a hand-made match with known times
(the time limit is inclusive, earliest match, same and other team, same possession, same player) and the example
questions on the real season.
