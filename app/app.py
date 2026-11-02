"""Match event search: ask a question about Leverkusen's 2023/24 season and see the moments on the pitch.

Run from the repository root:
    streamlit run app/app.py
"""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from match_event_search.graph import season_graph
from match_event_search.llm_parser import LLMParser
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
    "Goalkeeper passes to a defender intercepted that led to conceding a goal",
]
MAX_ROWS = 1000
PARSERS = ["Rule-based (v1)", "LLM (v2)"]

GUIDE = """
**Build the question in this order:** *[who] [action] [where / when]* → **that led to** → *[next action]*
*[within N seconds]*. Steps are split at "led to", "followed by", "resulting in" and "then".

| You want | Write |
|---|---|
| Players | surname or full name: Wirtz, Grimaldo, Hincapié |
| Roles | goalkeeper, defenders, centre backs, left / right back (wing backs included), full backs, defensive midfielders, midfielders, wingers, striker |
| Receiver | passes **to** a defender, **to** the left back, **to** Boniface |
| Actions | passes, carries, dribbles, shots, goals, crosses, through balls, switches, cutbacks, key passes, assists, headers, tackles, interceptions, clearances, blocks, aerials, fouls, pressing |
| Derived | progressive, turnovers / lost the ball / intercepted (a pass), regains / won the ball, box entries / into the box |
| Outcome | successful, completed, failed, incomplete; shots on target / off target / blocked |
| Where | own half, opponent half, final / middle / defensive third, in the box, our own box, their box, left wing, left half-space, from the left |
| When | after the 60th minute, before the 30th minute, between the 30th and 45th minute, last 15 minutes, first / second half |
| Situation | under pressure, not under pressure, counter attacks, transitions, build-up, set pieces, high press, low block, counterpressing, when winning / drawing / losing |
| Set pieces | corners, free kicks, throw-ins, goal kicks, penalties; **from corners** = anything after a corner |
| Opponent | goals conceded, shots conceded, their shots, against Bayern, at home, away |

**Good to know**
- No team mentioned means Leverkusen; say *their*, *opponent* or *conceded* for the other team.
- A turnover is placed where the losing action started (a pass played from our box is a turnover in our box);
  for where the opponent won the ball, ask for *opponent regains in our box*.
- Give sequences a time limit ("within 20 seconds"). Without one, the next step must be in the same possession,
  or within 15 s when the ball changes team (30 s when it is a goal).
- Small typos in football words are corrected (shown above the results); names must be spelt right.
- Not supported yet: "or" between different things, negation (apart from "not under pressure"), score lines.
- Check **Query** to see how the question was read. If it cannot be phrased, write the query in the JSON tab.
"""

st.set_page_config(page_title="Match event search", page_icon=":soccer:", layout="wide")


@st.cache_resource(show_spinner="Tagging the season and building the graph…")
def load():
    g = season_graph()
    return g, Vocabulary.from_tags(g.graph["tags"]), LLMParser(g)


@st.cache_resource
def llm_answers() -> dict:
    """Questions the LLM parser has answered, so asking again costs nothing.

    Only the model's own answers are kept: a fallback (e.g. no API key yet)
    is asked again next time.
    """
    return {}


def read_question(question: str, parser: str):
    """The query for a question, plus what to tell the user about how it was read."""
    if parser == PARSERS[0]:
        parsed = parse_verbose(question, vocab)
        return parsed.query, parsed.unparsed, parsed.corrected, None
    answers = llm_answers()
    if question not in answers:
        with st.spinner("Asking the model…"):
            result = llm.parse(question)
        if result.parser == "llm":
            answers[question] = result
    else:
        result = answers[question]
    if result.query is None:
        raise ParseError(result.note)
    return result.query, result.unparsed, result.corrected, result


def use_example():
    """Copy the clicked example into the question box (runs before the box is drawn)."""
    if st.session_state.example:
        st.session_state.question = st.session_state.example
        st.session_state.example = None  # so the same example can be picked again later


def time_label(row) -> str:
    return f"{int(row.minute)}:{int(row.second):02d}"


g, vocab, llm = load()
tags = g.graph["tags"]

st.title("Match event search")
st.caption("Bayer Leverkusen, Bundesliga 2023/24 · 34 matches · data: StatsBomb open data.")

if "question" not in st.session_state:
    st.session_state.question = EXAMPLES[0]

ask, write = st.tabs(["Ask a question", "Write a query (JSON)"])
with ask:
    st.text_input("Question", key="question", label_visibility="collapsed",
                  placeholder="e.g. turnovers in our own half that led to a shot within 10 seconds")
    st.pills("Examples", EXAMPLES, label_visibility="collapsed", key="example", on_change=use_example)
    parser = st.radio("Parser", PARSERS, horizontal=True, key="parser",
                      help="The rule-based parser reads fixed phrases. The LLM parser sends the question to an "
                           "Anthropic model (needs ANTHROPIC_API_KEY and LLM_MODEL) and falls back to the "
                           "rule-based parser if it fails.")
    with st.expander("How to ask"):
        st.markdown(GUIDE)
with write:
    raw = st.text_area("JSON query", height=160, key="raw_query",
                       placeholder='{"event": {"action": "shot", "header": true, "our_team": true}}')
    use_json = st.toggle("Search with this JSON query instead of the question", value=False)

query, unparsed, corrected, llm_result, results, error = None, [], {}, None, None, None
try:
    if use_json:
        query = json.loads(raw)
        results = search(query, g)
    elif st.session_state.question.strip():
        query, unparsed, corrected, llm_result = read_question(st.session_state.question, parser)
        results = search(query, g)
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
if llm_result is not None:
    if llm_result.parser == "llm":
        tries = "first attempt" if llm_result.attempts == 1 else f"{llm_result.attempts} attempts"
        st.caption(f"Read by the LLM parser ({tries}).")
    else:
        st.warning(f"The LLM parser was not used: {llm_result.note}. The rule-based parser answered.")
if corrected:
    st.info("Read " + ", ".join(f"“{a}” as “{b}”" for a, b in corrected.items()))
if unparsed:
    st.warning("Words the parser did not use: " + ", ".join(unparsed))

st.subheader(f"{len(results):,} moment{'' if len(results) == 1 else 's'}")
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
selection = st.dataframe(table, hide_index=True, width="stretch", height=320,
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
    }), hide_index=True, width="stretch", height=240)
