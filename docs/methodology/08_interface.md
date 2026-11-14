# 8. Interface

[`app/app.py`](../../app/app.py) is a Streamlit page over everything built so far. Run it with
`python -m streamlit run app/app.py`; the first load tags the season, builds the graph and the similarity index (30-60 s, then cached).
On Windows with Smart App Control, `streamlit run` can be blocked because pip's `streamlit.exe` launcher is
unsigned; starting it through Python as above avoids that.

- **Question box** with example questions, a "How to ask" guide, and a choice of parser: rule-based (stage 5) or
  LLM (stage 6). The page shows which parser answered (and why the rule-based parser stepped in, if it did), typos it
  corrected, words it did not use, and the query it produced.
- **JSON tab**: type a query in the stage 4 format directly, for questions the parser cannot read yet.
- **Results table**: match, half, time, players, outcome and duration of each moment, in date order (the first
  1,000 for very broad questions).
- **Two pitch plots** ([`plotting.py`](../../src/match_event_search/plotting.py), mplsoccer): where all the
  moments started, and the selected moment with every event from its first to its last step, the steps numbered.
- **Step through a moment**: Start / Back / Next / End and a slider redraw the selected moment up to one event,
  with earlier events faded and the current one circled. A card under the pitch describes that event in plain
  words ([`describe.py`](../../src/match_event_search/describe.py)): zone, phase, outcome, who a pass was meant for,
  pressure, game state, seconds since the regain, and each derived tag with the reason it applies (e.g.
  "progressive: 20.6 m closer to goal; 10 m needed"). It also says which step of the question the event is. A new
  moment opens on the whole move; the full event list is one click away.

Every event is stored from the acting team's side (stage 1), so the plots turn the opponent's events round,
(x, y) → (120 − x, 80 − y), and show the pitch from Leverkusen's side, attacking to the right.

The LLM parser's answers are kept per question while the app runs, so asking again costs nothing.
