"""The event graph: tagged events as nodes, linked by containment and by sequence.

Node kinds (attribute `kind`):

* `season` → `match` → `half` → `possession` → `event`, linked by `contains`
  edges, like articles in the legal tree. Event nodes are the events with a
  location (136,803 in the season); the rest are administrative (lineups,
  substitutions, half start and end).

Edge kinds (the key of each edge in the MultiDiGraph):

* `contains`     parent → child in the hierarchy.
* `next`         event → the next event in the same half, whoever plays it.
                 Attributes `dt` (seconds) and `same_possession`.
* `same_player`  event → the same player's next event in the same half, with `dt`.
* `similar`      possession → one of its most similar possessions (similarity.py), with
                 `distance`; added by `season_graph`.

Two events in the same possession share a possession node, so "same
possession" needs no edges of its own; `next` edges also say whether they stay
in the possession.

The node id of an event is its StatsBomb id. Event nodes carry only what is
needed to move through the graph (`NODE_ATTRIBUTES`); the full tags are in the
table `g.graph["tags"]`, indexed by event id. Putting every tag on the nodes
doubles the build time and memory (25 s and about 1 GB for the season, against
12 s and 425 MB).
"""
import networkx as nx
import numpy as np
import pandas as pd

from .tagging import OPEN_PLAY_STARTS

SEASON = "season"
NODE_ATTRIBUTES = ["match_id", "period", "t", "possession", "team", "player"]


def match_node(match_id) -> str:
    return f"match:{match_id}"


def half_node(match_id, period) -> str:
    return f"half:{match_id}:{period}"


def possession_node(match_id, possession) -> str:
    return f"possession:{match_id}:{possession}"


def build_graph(tags: pd.DataFrame, matches: pd.DataFrame) -> nx.MultiDiGraph:
    """Build the graph from tagged events (`tagging.tag_season`) and the match list."""
    events = tags[tags.x.notna()].sort_values(["match_id", "index"]).reset_index(drop=True)
    g = nx.MultiDiGraph()
    g.add_node(SEASON, kind="season")

    played = matches[matches.match_id.isin(events.match_id.unique())]
    for m in played.itertuples():
        g.add_node(match_node(m.match_id), kind="match", match_id=m.match_id, date=m.match_date,
                   home_team=m.home_team, away_team=m.away_team,
                   home_score=m.home_score, away_score=m.away_score)
        g.add_edge(SEASON, match_node(m.match_id), key="contains")

    for (match_id, period), _ in events.groupby(["match_id", "period"]):
        g.add_node(half_node(match_id, period), kind="half", match_id=match_id, period=period)
        g.add_edge(match_node(match_id), half_node(match_id, period), key="contains")

    possessions = events.groupby(["match_id", "possession"]).agg(
        period=("period", "first"), team=("possession_team", "first"),
        play_pattern=("play_pattern", "first"), start=("t", "first"), end=("t", "last"),
        n_events=("id", "size"))
    for (match_id, number), p in possessions.iterrows():
        node = possession_node(match_id, number)
        g.add_node(node, kind="possession", match_id=match_id, possession=number, **p.to_dict())
        g.add_edge(half_node(match_id, p.period), node, key="contains")

    records = events[["id"] + NODE_ATTRIBUTES].replace({np.nan: None}).to_dict("records")
    g.add_nodes_from((r.pop("id"), {"kind": "event", **r}) for r in records)
    g.add_edges_from((possession_node(m, p), e, "contains")
                     for e, m, p in zip(events.id, events.match_id, events.possession))
    g.graph["tags"] = events.set_index("id")

    _add_sequence_edges(g, events, by=["match_id", "period"], key="next")
    _add_sequence_edges(g, events[events.player.notna()], by=["match_id", "period", "player"], key="same_player")
    return g


def _add_sequence_edges(g: nx.MultiDiGraph, events: pd.DataFrame, by: list, key: str):
    """Link each event to the following one within each group."""
    nxt = events.groupby(by).shift(-1)
    linked = nxt.id.notna()
    src, dst = events[linked], nxt[linked]
    dt = (dst.t - src.t).to_numpy()
    if key == "next":
        same = (dst.possession == src.possession).to_numpy()
        g.add_edges_from((a, b, key, {"dt": d, "same_possession": bool(s)})
                         for a, b, d, s in zip(src.id, dst.id, dt, same))
    else:
        g.add_edges_from((a, b, key, {"dt": d}) for a, b, d in zip(src.id, dst.id, dt))


# --- Navigation ------------------------------------------------------------------

def children(g: nx.MultiDiGraph, node) -> list:
    return [v for _, v, k in g.out_edges(node, keys=True) if k == "contains"]


def parent(g: nx.MultiDiGraph, node):
    parents = [u for u, _, k in g.in_edges(node, keys=True) if k == "contains"]
    return parents[0] if parents else None


def events_in(g: nx.MultiDiGraph, node) -> list:
    """All event nodes below a season, match, half or possession node, in order."""
    if g.nodes[node]["kind"] == "event":
        return [node]
    return [e for child in children(g, node) for e in events_in(g, child)]


def following(g: nx.MultiDiGraph, event, key: str = "next", within_s: float = None,
              same_possession: bool = False, stop_at_restart: bool = False):
    """The events after `event` along `next` or `same_player` edges.

    Stops after `within_s` seconds, when the possession changes if
    `same_possession` is set, and when the ball has been dead if
    `stop_at_restart` is set: a later possession that starts from a throw-in,
    free kick, corner, goal kick, kick-off or the goalkeeper's hands.
    Yields (event id, seconds after `event`).
    """
    elapsed, node = 0.0, event
    while True:
        out = [(v, d) for _, v, k, d in g.out_edges(node, keys=True, data=True) if k == key]
        if not out:
            return
        previous, (node, data) = node, out[0]
        elapsed += data["dt"]
        if within_s is not None and elapsed > within_s:
            return
        if same_possession and g.nodes[node]["possession"] != g.nodes[event]["possession"]:
            return
        if stop_at_restart and _restart_between(g, previous, node):
            return
        yield node, elapsed


def _restart_between(g: nx.MultiDiGraph, a, b) -> bool:
    """Whether a possession after a's, up to b's, started with the ball dead.

    Checks every possession in between, so it also works along same_player
    edges, which skip other players' events.
    """
    match_id, first, last = g.nodes[a]["match_id"], g.nodes[a]["possession"], g.nodes[b]["possession"]
    for number in range(first + 1, last + 1):
        node = possession_node(match_id, number)
        if node in g and g.nodes[node]["play_pattern"] not in OPEN_PLAY_STARTS:
            return True
    return False


def add_similar_edges(g: nx.MultiDiGraph, index, k: int):
    """Link each possession to its k most similar possessions (`similar` edges, attribute `distance`).

    The index (similarity.SimilarityIndex) is kept as g.graph["similarity"].
    """
    g.graph["similarity"] = index
    g.add_edges_from((possession_node(*a), possession_node(*b), "similar", {"distance": d})
                     for a, b, d in index.all_neighbours(k))


def season_graph(similar: bool = True) -> nx.MultiDiGraph:
    """Tag the configured season and build its graph, with similar-situation edges unless `similar` is False."""
    from .config import SimilarityConfig
    from .loaders import load_matches
    from .similarity import SimilarityIndex
    from .tagging import tag_season
    tags = tag_season()
    g = build_graph(tags, load_matches())
    if similar:
        config = SimilarityConfig()
        add_similar_edges(g, SimilarityIndex(g.graph["tags"], config), config.neighbours)
    return g


def describe(g: nx.MultiDiGraph) -> dict:
    """Number of nodes of each kind and edges of each kind."""
    nodes = pd.Series([d["kind"] for _, d in g.nodes(data=True)]).value_counts()
    edges = pd.Series([k for *_, k in g.edges(keys=True)]).value_counts()
    return {"nodes": nodes.to_dict(), "edges": edges.to_dict()}
