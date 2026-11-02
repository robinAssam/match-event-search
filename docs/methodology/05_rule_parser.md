# 5. Rule-based parser (v1)

[`rule_parser.py`](../../src/match_event_search/rule_parser.py) turns a question in plain English into the JSON
query format of stage 4, with fixed rules and no model. [`scripts/ask.py`](../../scripts/ask.py) parses a question and
runs it:

```
python scripts/ask.py "regains in the final third that led to a goal"
Query: {"sequence": [{"filter": {"regain": true, "third": "attacking", "our_team": true}},
                     {"filter": {"action": "shot", "outcome_detail": "goal"}, "team": "same", "same_possession": true}]}
2 results
```

## How it works

1. **Normalise**: lower case, accents and possessives removed ("Hincapié's" → "hincapie"), hyphens to spaces
   ("left-back"), ordinals to numbers ("60th" → 60), and spelt-out numbers to digits ("ten seconds", "sixtieth
   minute"). Ordinal words are only converted before "minute", so "first half" and "final third" keep their meaning.
2. **Scope**: "at home" / "away", and an opponent's name ("against Dortmund", "Gladbach"). When the opponent is
   named as the subject ("Bayern's shots"), it is also the team acting.
3. **Split into steps** at connectors: "led to", "leading to", "followed by", "resulting in", "then".
4. **Each step**: the time limit ("within 10 seconds"), "in the same possession", the minute and half, player names
   ("to <player>" is the receiver of a pass), then the lexicon.
5. **Lexicon**: 83 entries, each a set of phrases standing for one or more conditions, tried in a fixed order. A matched phrase
   is removed, so its words cannot be used twice: "left back" is read before "left" (a channel), "under pressure"
   before "pressure" (an action), "goal kick" before "goal", "from corners" (the possession started with a corner)
   before "corners" (the corner kicks themselves). Phrases only match whole words, so "across" is not a cross.
6. **Validate** the result against the schema.

Words the parser did not use are returned with the query, so a user (or the evaluation) can see what was ignored.

## Rules that are not just vocabulary

| Situation | Rule |
|---|---|
| No team mentioned | our team, the analyst's point of view; not added when a player is named |
| "we / our / us", "they / their / opponents" | `our_team` true or false |
| "own half" | the acting team's own half |
| "our half", "their half" | depends on who acts: "our turnovers in their half" is the opponent's half, "their turnovers in their half" their own |
| A later step with no team | after a turnover the other team; otherwise the same team |
| A later step with no time limit | same team: the same possession; other team: within 15 s (`DEFAULT_WINDOW_S`) |
| "left back" | role group FB on the left, which includes wing backs (stage 2) |
| "midfielders" | role groups DM, CM and AM |
| A shared surname | the Leverkusen player if exactly one of the players with that name is ours ("Hofmann" → Jonas Hofmann); otherwise the full name is needed |
| "after the 60th minute", "after 60 minutes" | `minute ≥ 60` |
| "in the last 15 minutes" | `minute ≥ 75` |

Player and team names are built from the data: every full name, and each part of a name (at least three letters)
that belongs to only one player, so "Wirtz", "Grimaldo" and "Hincapié" work. Team names are built the same way,
ignoring words such as "FC" and "Borussia", with a few common names added ("BVB", "Gladbach", "Cologne").

## Known limits

- No negation apart from pressure ("not under pressure"); "passes that weren't progressive" is not understood.
- "Or" between different kinds of conditions is not understood (the query format has no OR across fields either).
- No score lines ("when 1-0 up"); only winning, drawing and losing.
- Nicknames that are not part of the StatsBomb name are not known.
- One opponent per question.

The rules were written against the example questions and the tests in
[`test_rule_parser.py`](../../tests/test_rule_parser.py), not against the evaluation questions of stage 7, so that the
evaluation measures how well they carry over to new questions.
