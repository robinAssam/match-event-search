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
2. **Correct small typos** in football words: a word of five letters or more that is one letter away (added,
   missing, changed, or two swapped) from exactly one known word, with the same first letter, is read as that word
   ("conceeding" → "conceding"). Names are never changed, and every correction is reported. The first-letter rule
   keeps ordinary words such as "across" from becoming "cross".
3. **Scope**: "at home" / "away", and an opponent's name ("against Dortmund", "Gladbach"). When the opponent is
   named as the subject ("Bayern's shots"), it is also the team acting.
4. **Split into steps** at connectors: "led to", "leading to", "followed by", "resulting in", "then".
5. **Each step**: the time limit ("within 10 seconds"), "in the same possession", the minute and half, player names
   ("to <player>" is the receiver of a pass), a receiver's role ("to a defender"), a lost pass ("intercepted",
   "cut out" after a pass), then the lexicon.
6. **Lexicon**: 84 entries, each a set of phrases standing for one or more conditions, tried in a fixed order. A matched phrase
   is removed, so its words cannot be used twice: "left back" is read before "left" (a channel), "under pressure"
   before "pressure" (an action), "goal kick" before "goal", "from corners" (the possession started with a corner)
   before "corners" (the corner kicks themselves). Phrases only match whole words, so "across" is not a cross.
7. **Validate** the result against the schema.

Words the parser did not use are returned with the query, so a user (or the evaluation) can see what was ignored.

## Rules that are not just vocabulary

| Situation | Rule |
|---|---|
| No team mentioned | our team, the analyst's point of view; not added when a player is named |
| "we / our / us", "they / their / opponents" | `our_team` true or false |
| "own half" | the acting team's own half |
| "our half", "their half" | depends on who acts: "our turnovers in their half" is the opponent's half, "their turnovers in their half" their own |
| "own box", "our box", "their box" | the same for penalty areas: `in_own_box` is the box the acting team defends, `in_box` the one it attacks; "their shots in our box" is `in_box` |
| "turnovers in our own box" | where the losing action started (a goal kick or pass from our box counts); "opponent regains in our box" is where they won the ball |
| A later step with no team | after a turnover the other team; otherwise the same team |
| A later step with no time limit | same team: the same possession; other team: within 15 s (`DEFAULT_WINDOW_S`), or 30 s for a goal (`DEFAULT_GOAL_WINDOW_S`) |
| "left back" | role group FB on the left, which includes wing backs (stage 2) |
| "midfielders" | role groups DM, CM and AM |
| "defenders" | role groups CB and FB |
| "passes to a defender" | the receiver's role (`recipient_role_group`) |
| "passes that were intercepted" | a lost pass (`turnover`); "interceptions" on their own are the defending action |
| A shared surname | the Leverkusen player if exactly one of the players with that name is ours ("Hofmann" → Jonas Hofmann); otherwise the full name is needed |
| "after the 60th minute", "after 60 minutes" | `minute ≥ 60` |
| "in the last 15 minutes" | `minute ≥ 75` |

Player and team names are built from the data: every full name, and each part of a name (at least three letters)
that belongs to only one player, so "Wirtz", "Grimaldo" and "Hincapié" work. Team names are built the same way,
ignoring words such as "FC" and "Borussia", with a few common names added ("BVB", "Gladbach", "Cologne").

## Found by testing
The question "goalkeeper pass to defender intercepted and led to conceeding goal" first came out as the opposite
(our goalkeeper's passes followed by *our* goals): "conceeding" was misspelt, "defender" and "to a defender" were
unknown, "intercepted" was read as an interception by our goalkeeper, and 15 s was too short. After these fixes it
found Dortmund 1–1 Leverkusen, 80:06: Hrádecký's pass meant for Stanišić lost, Füllkrug scoring 19 s later. The video
showed that goal came from a Dortmund throw-in after the ball went out, so sequences now stop at a dead ball
(stage 4) and the honest answer for the season is none.

## Known limits (still)

- No negation apart from pressure ("not under pressure"); "passes that weren't progressive" is not understood.
- "Or" between different kinds of conditions is not understood (the query format has no OR across fields either).
- No score lines ("when 1-0 up"); only winning, drawing and losing.
- Nicknames that are not part of the StatsBomb name are not known.
- One opponent per question.

The rules were written against the example questions and the tests in
[`test_rule_parser.py`](../../tests/test_rule_parser.py), not against the evaluation questions of stage 7, so that the
evaluation measures how well they carry over to new questions.
