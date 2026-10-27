# 1. Data

## Choice of season
StatsBomb's open data holds 80 competition-seasons, 12 of them with 360 freeze-frames (the positions of the
players visible on the broadcast at the moment of each event). Eleven have 360 data for every match.

The project uses **Bundesliga 2023/24**: all 34 league matches of Bayer Leverkusen's unbeaten season (28 wins,
6 draws). It is one club over a full season, which is how a club analyst works, so "our left back" in a question
always refers to the same team. Euro 2024 (51 matches, six of them involving the Netherlands) was the runner-up and can
be added later to test whether the system generalises.

## Loading
`statsbombpy` reads the open-data files from GitHub on every call. [`loaders.py`](../../src/match_event_search/loaders.py)
keeps a permanent copy of every file in `data/raw/statsbomb/`, byte for byte and in the same folder layout as the
repository, and lets `statsbombpy` parse it as usual. The full season is 408 MB; once downloaded, a match loads in
about a second without network access.

## What the data looks like
Numbers are for all 34 matches, checked by the tests in [`test_loaders.py`](../../tests/test_loaders.py).

| | |
|---|---|
| Events | 137,765 (3,315–4,893 per match) |
| Possessions | 133–189 per match (161 on average) |
| Events with a 360 frame | 86.1% (in 31 matches, see below), about 16–17 players visible per frame |

Findings that matter for the next stages:

- **Coordinates are per team.** The pitch is 120 × 80 and every event is recorded with the acting team attacking
  left to right, so x = 100 is always near the *acting team's* target goal. Only 2 of 916 shots were taken from
  the shooter's own half. A pitch zone therefore needs no flipping, but comparing the positions of two teams'
  events does.
- **`team` is who acted, `possession_team` is who had the ball.** 16% of events are by the team without the ball:
  mostly pressures, blocks and duels, but also short spells of the other team's play that StatsBomb counts as part
  of the same possession.
- **Possessions are numbered 1, 2, 3, … in order** within a match, so "same possession" is simply equal numbers.
- **Time:** `timestamp` restarts at 00:00 in each half; `minute` and `second` run on (the second half starts at
  minute 45). The league has no extra time.
- **Game state is not given and must be rebuilt from goals:** shots with outcome *Goal* plus *Own Goal For* events
  (3 own goals this season). Rebuilt this way, the final score matches the official result in all 34 matches.
- **A pass with no outcome was completed.** StatsBomb only fills `pass_outcome` for failures (*Incomplete*, *Out*,
  *Pass Offside*, …).
- **Useful fields StatsBomb already provides:** `under_pressure`, `counterpress`, `play_pattern` (e.g. *From Counter*,
  *From Corner*) and detailed positions (e.g. *Left Back* vs *Left Wing Back*).

## Known data problem
In three matches (Leverkusen–Dortmund home and away, Leverkusen–Wolfsburg at home; match ids 3895158, 3895309, 3895266)
the 360 file shares no event ids with the event file, so no frame can be linked to its event. StatsBomb updated these 360
files in May 2026 but not the event files, which date from May 2024. Frames carry no timestamp, so there is no
reliable way to match them otherwise; these matches are treated as having no 360 data. A test checks this, and will
fail if StatsBomb repairs the files.
