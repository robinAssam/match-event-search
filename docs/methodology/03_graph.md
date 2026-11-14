# 3. Graph

[`graph.py`](../../src/match_event_search/graph.py) puts the tagged events into one NetworkX `MultiDiGraph`, the
football version of the law project's article graph. Sizes come from
[`scripts/build_graph.py`](../../scripts/build_graph.py); building the whole season, tagging included, takes about
11 seconds.

## Nodes: the hierarchy

| Kind | Count |
|---|---|
| `season` | 1 |
| `match` | 34 |
| `half` | 68 |
| `possession` | 5,453 |
| `event` | 136,803 |

Like the legal hierarchy in the law project, each node has exactly one parent, and events are the atoms at the
bottom.

Event nodes are the events that have a location. The other 962 are administrative (substitutions, half start and
end, lineups, tactical shifts, injury stoppages) and are not actions on the pitch; they remain in the output of `tag_season`.
Possessions never span two halves once these are left out.

## Edges: the channels

| Edge (key) | From → to | Attributes | Count | Law project |
|---|---|---|---|---|
| `contains` | parent → child in the hierarchy | | 142,358 | hierarchical containment |
| `next` | event → next event in the same half, either team | `dt` (s), `same_possession` | 136,735 | (new) |
| `same_player` | event → the same player's next event in the same half | `dt` (s) | 134,985 | (new) |
| `similar` | possession → one of its 5 most similar possessions (stage 9) | `distance` | 23,925 | semantic similarity |

**Same possession** needs no edges: events in one possession share a possession node, and every `next` edge says
whether it stays in the possession. **Similar situation** edges, the counterpart of the law project's semantic
similarity, link possessions ([stage 9](09_similarity.md)). The law project's tag-overlap channel becomes the tag filters of the query engine
(stage 4): events with the same tags are found directly in the tag table.

Edges link each event only to the *next* one, not to every later one, so they grow with the number of events. A
sequence ("followed by a shot within 10 seconds") is found by walking along them with `following()`, which adds up
`dt` and stops at a time limit or when the possession changes. Timestamps never decrease from one event to the
next, so `dt` is never negative.

## Tags: a table next to the graph

Event nodes carry only what is needed to walk the graph: match, half, time, possession, team and player. The
full tags (57 columns) are in a table, `g.graph["tags"]`, indexed by event id. With every tag on the nodes the
season took 25 s and about 1 GB to build; without, 12 s and 425 MB. It also suits the queries: a filter on one event
("progressive passes by the left back") is a fast filter on the table, and only sequences need the graph.

## Example
From Werner's lost pass in Leverkusen 3–2 Leipzig (minute 22), `following()` along `next` edges reaches Kossonou's
block (0.1 s), Xhaka's recovery (1.4 s), Boniface's touches, and Frimpong's goal after 10.5 s. Limited to the same
possession it stops after Kossonou's block: Xhaka's recovery starts Leverkusen's possession. Both are checked in
[`test_graph.py`](../../tests/test_graph.py), along with the structure on every match: the `contains` edges form one
tree over all nodes, each half has one `next` chain, and sequence edges never go back in time or leave a half.
