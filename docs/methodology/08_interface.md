# 8. Interface (first version)

[`app/app.py`](../../app/app.py) is a Streamlit page over everything built so far. Run it with
`streamlit run app/app.py`; the first load tags the season and builds the graph (about 15 s, then cached).

- **Question box** with example questions, read by the rule-based parser (stage 5). Words the parser did not use
  are shown, and the query it produced can be opened.
- **JSON tab**: type a query in the stage 4 format directly, for questions the parser cannot read yet.
- **Results table**: match, half, time, players, outcome and duration of each moment, in date order (the first
  1,000 for very broad questions).
- **Two pitch plots** ([`plotting.py`](../../src/match_event_search/plotting.py), mplsoccer): where all the
  moments started, and the selected moment with every event from its first to its last step, the steps numbered.
  Below it, the list of those events.

Every event is stored from the acting team's side (stage 1), so the plots turn the opponent's events round,
(x, y) → (120 − x, 80 − y), and show the pitch from Leverkusen's side, attacking to the right.

This version comes before the LLM parser (stage 6); it will get a choice of parser once that exists.
