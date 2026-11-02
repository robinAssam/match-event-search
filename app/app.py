"""Match event search: ask a question about Leverkusen's 2023/24 season and see the moments on the pitch.

Run from the repository root:
    streamlit run app/app.py
"""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from match_event_search.graph import season_graph
from match_event_search.plotting import plot_moment, plot_overview
from match_event_search.query import QueryError, search
from match_event_search.rule_parser import ParseError, Vocabulary, parse_verbose

EXAMPLES = [
    "Progressive passes by the left back after the 60th minute",
    "Turnovers in our own half that led to a shot within 10 seconds",
    "Regains in the final third that led to a goal",
    "Wirtz's dribbles in the box",
    "Crosses from the right followed by a headed shot",
    "Shots conceded from corners",
]
MAX_ROWS = 1000

st.set_page_config(page_title="Match event search", page_icon=":soccer:", layout="wide")


@st.cache_resource(show_spinner="Tagging the season and building the graph…")
def load():
    g = season_graph()
    return g, Vocabulary.from_tags(g.graph["tags"])


def run_question(question, vocab, g):
    parsed = parse_verbose(question, vocab)
    return parsed.query, parsed.unparsed, search(parsed.query, g)


def use_example():
    """Copy the clicked example into the question box (runs before the box is drawn)."""
    if st.session_state.example:
        st.session_state.question = st.session_state.example
        st.session_state.example = None  # so the same example can be picked again later


def time_label(row) -> str:
    return f"{int(row.minute)}:{int(row.second):02d}"


g, vocab = load()
tags = g.graph["tags"]

st.title("Match event search")
st.caption("Bayer Leverkusen, Bundesliga 2023/24 · 34 matches · data: StatsBomb open data. "
           "Questions are read by the rule-based parser (v1).")

if "question" not in st.session_state:
    st.session_state.question = EXAMPLES[0]

ask, write = st.tabs(["Ask a question", "Write a query (JSON)"])
with ask:
    st.text_input("Question", key="question", label_visibility="collapsed",
                  placeholder="e.g. turnovers in our own half that led to a shot within 10 seconds")
    st.pills("Examples", EXAMPLES, label_visibility="collapsed", key="example", on_change=use_example)
with write:
    raw = st.text_area("JSON query", height=160, key="raw_query",
                       placeholder='{"event": {"action": "shot", "header": true, "our_team": true}}')
    use_json = st.toggle("Search with this JSON query instead of the question", value=False)

query, unparsed, results, error = None, [], None, None
try:
    if use_json:
        query = json.loads(raw)
        results = search(query, g)
    elif st.session_state.question.strip():
        query, unparsed, results = run_question(st.session_state.question, vocab, g)
except json.JSONDecodeError as e:
    error = f"That is not valid JSON: {e}"
except (ParseError, QueryError) as e:
    error = str(e)

if error:
    st.error(error)
    st.stop()
if results is None:
    st.stop()

with st.expander("Query", expanded=False):
    st.code(json.dumps(query, indent=2), language="json")
if unparsed:
    st.warning("Words the parser did not use: " + ", ".join(unparsed))

st.subheader(f"{len(results):,} moments")
if results.empty:
    st.info("Nothing matches this question. Open the query above to see how it was read.")
    st.stop()

shown = results.head(MAX_ROWS)
if len(results) > MAX_ROWS:
    st.caption(f"Showing the first {MAX_ROWS:,} in date order.")
table = pd.DataFrame({
    "Match": shown.match,
    "Half": shown.period,
    "Time": [time_label(r) for r in shown.itertuples()],
    "Players": shown.players,
    "Outcome": shown.outcome,
    "Duration (s)": shown.duration_s,
})
selection = st.dataframe(table, hide_index=True, use_container_width=True, height=320,
                         on_select="rerun", selection_mode="single-row", key="results")
rows = selection.selection.rows
chosen = shown.iloc[rows[0] if rows else 0]

left, right = st.columns(2)
with left:
    first_steps = tags.loc[[s[0] for s in results.steps]]
    fig = plot_overview(first_steps, title=f"Where the {len(results):,} moments started (our attack →)")
    st.pyplot(fig)
    plt.close(fig)
with right:
    span = tags.loc[chosen.span]
    title = f"{chosen.match}, {time_label(chosen)} (our attack →)"
    fig = plot_moment(span, list(chosen.steps), title=title)
    st.pyplot(fig)
    plt.close(fig)
    events = span[~span.action.eq("ball_receipt")]
    st.dataframe(pd.DataFrame({
        "Step": ["●" if e in chosen.steps else "" for e in events.index],
        "Time": [time_label(r) for r in events.itertuples()],
        "Team": events.team,
        "Player": events.player,
        "Action": events.action,
        "Outcome": events.outcome_detail.fillna(events.outcome).fillna(""),
    }), hide_index=True, use_container_width=True, height=240)
