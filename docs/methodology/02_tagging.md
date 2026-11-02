# 2. Tagging

[`tagging.py`](../../src/match_event_search/tagging.py) turns each StatsBomb event into an "atom" with tags in nine
families, the football version of the law project's 9-label schema. All thresholds are in
[`config.py`](../../src/match_event_search/config.py) with their sources. Season numbers come from
[`scripts/summarise_tags.py`](../../scripts/summarise_tags.py) (results in [`outputs/tagging/`](../../outputs/tagging)).

## The schema

| # | Family | Columns | Source |
|---|---|---|---|
| 1 | Action | `action` (pass, carry, shot, tackle, aerial_duel, …); qualifiers `cross`, `through_ball`, `switch`, `cutback`, `key_pass`, `assist`, `header`; `set_piece_type`; derived `progressive`, `box_entry`, `turnover`, `regain` | StatsBomb, derived tags ours |
| 2 | Zone | `third`, `channel`, `half`, `in_box`, plus `end_third`, `end_channel`, `end_in_box` for passes, carries and shots | ours |
| 3 | Phase | `phase` | ours, using StatsBomb's `play_pattern` and `counterpress` |
| 4 | Role | `position`, `role_group` (GK, CB, FB, DM, CM, AM, W, ST), `role_side` | StatsBomb, grouped by us |
| 5 | Pressure | `under_pressure`, `counterpress` | StatsBomb |
| 6 | Outcome | `outcome` (success / failure / none), `outcome_detail` | StatsBomb, unified by us |
| 7 | Game state | `goals_for`, `goals_against`, `goal_diff`, `game_state` (winning / drawing / losing) | rebuilt from goals |
| 8 | Time | `period`, `minute`, `t` (seconds into the half), `time_bucket`, `since_regain` | StatsBomb, buckets ours |
| 9 | Team | `team`, `our_team`, `home`, `in_possession` | StatsBomb |

**Zones.** StatsBomb records every event with the acting team attacking towards x = 120 and y = 0 on that team's
left, so a zone always means the same thing for both teams: "attacking third" is near the acting team's target goal.
Thirds split x at 40 and 80. Five channels split y along the sides of the penalty area (18, 62) and the six-yard box
(30, 50): left wing, left half-space, centre, right half-space, right wing. Distances in metres assume a 105 × 68 m
pitch, as in the pitch-control project.

**Roles.** `FB` includes wing backs. Leverkusen played with a back three, so their left-sided defender is recorded
as *Left Wing Back* 6,660 times and as *Left Back* only 551 times; "the left back" should find both.

**Outcomes.** A pass with no StatsBomb outcome was completed. A shot succeeds only if it is a goal (`outcome_detail`
says on target, off target or blocked). An aerial duel is only recorded for the player who lost it, so it is always a
failure. Carries, pressures, clearances and blocks have no outcome.

**Game state** is the score *before* the event, from the acting team's side, counting own goals (*Own Goal For*).

## Derived tags

**Progressive** follows Wyscout's definitions of a progressive pass and a progressive run: an open-play pass or a
carry that ends closer to the centre of the opponent's goal by at least

| Start and end | Closer by |
|---|---|
| both in the own half | 30 m |
| in different halves | 15 m |
| both in the opponent's half | 10 m |

Like Wyscout, the tag counts attempted passes; `outcome` says whether they arrived.

**Turnover and regain.** A possession is lost *in open play* when the team played the ball in it, the next possession
is the opponent's and starts in open play (*Regular Play* or *From Counter*), and it did not end in a shot. The
losing team's last ball action is tagged `turnover`, the winning team's first ball action `regain`, and
`since_regain` counts the seconds from then on. Balls put out of play, fouls and saved shots are not turnovers; a
miscontrol after which the team keeps the ball is not one either. Requiring a ball action leaves out possessions such
as a dropped ball, after which nobody lost the ball. Turnovers and regains therefore always come in pairs, which a
test checks for every match.

**Box entry**: a completed pass or a carry from outside into the penalty area.

## Phases

Each event with a location gets exactly one phase, the first that applies:

| In possession | | Out of possession | |
|---|---|---|---|
| 1. `set_piece` | ≤ 10 s after a corner or a free kick in the attacking third | 1. `counterpress` | StatsBomb's counterpress flag |
| 2. `counter_attack` | StatsBomb's *From Counter* pattern | 2. `high_press` | in the defender's attacking third |
| 3. `transition` | ≤ 10 s after an open-play regain | 3. `mid_block` | in the middle third |
| 4. `build_up` / `progression` / `final_third` | by the third the ball is in | 4. `low_block` | in the defender's own third |

The 10-second windows match the analyst's question "led to a shot within 10 seconds".

## Season numbers

Per match, from all 34 matches:

| | Leverkusen | Opponents |
|---|---|---|
| Progressive passes and carries (attempted) | 97.5 | 78.4 |
| … of which completed | 68.2 | 41.1 |
| Open-play turnovers | 27.7 | 35.3 |
| Box entries | 24.9 | 10.9 |

In possession, 42% of events are in progression, 24% in the final third, 16% in transition, 15% in build-up, 2% at
set pieces and 1% in StatsBomb counters. Out of possession, 46% are in a low block, 34% in a mid block, 11% in a high
press and 9% counterpressing.

## Worked example
Leverkusen's first goal of the season (Leverkusen 3–2 Leipzig, minute 23, possessions 43–44), checked in
[`test_tagging.py`](../../tests/test_tagging.py):

| Event | Tags |
|---|---|
| Werner's pass is blocked by Kossonou | `turnover`, Leipzig's own half, middle third, left wing |
| Xhaka recovers the ball | `regain`, attacking third, `transition`, 0.0 s |
| Xhaka's pass into the box | `progressive` (20.6 m closer, 10 m needed), `box_entry` |
| Orban presses Boniface | `counterpress`: StatsBomb flags it, 5.6 s after Werner's lost pass |
| Boniface's miscontrol | failure, but no turnover: Leverkusen keep the ball |
| Frimpong scores | goal, `transition`, 9.1 s after the regain, game state drawing (0–0) |

Earlier in possession 43, Orban's pass was 27.0 m closer to goal inside his own half, short of the 30 m needed, so it is
not progressive.
