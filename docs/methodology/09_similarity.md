# 9. Similar situations

"Find situations like this one": pick a moment, and see the possessions across the season that looked most like it,
and how they ended. It is the football version of the law project's semantic-similarity channel.
[`similarity.py`](../../src/match_event_search/similarity.py); settings in `SimilarityConfig`
([`config.py`](../../src/match_event_search/config.py)).

## A possession as a vector
Every possession with at least 3 actions by the team on the ball (4,785 of 5,453) becomes a vector of 36 numbers in
three parts. Each part is scaled so it contributes its weight to the distance between two possessions:

| Part | Weight | What it holds |
|---|---|---|
| Route | 60% | the ball's path (each action's start, and the end of passes and carries) resampled to 10 points, seen from the team on the ball, which always attacks to the right |
| Tempo | 25% | duration, number of passes, carries and dribbles, ground gained, and ground gained per second |
| Start | 15% | how the possession started (StatsBomb's play pattern: open play, counter, corner, throw-in, …) and whether it began with a regain |

Similar possessions are the ones at the smallest (Euclidean) distance. Left and right are not mirrored: a move down
the right only matches moves down the right.

**The outcome is left out on purpose.** Box entry, shot, goal, xG and losing the ball are stored next to the vectors
and shown with the results, so the neighbours answer how often this kind of move ends in a shot or a goal. For
Leverkusen's opening goal of the season (Leipzig, 22:55: Xhaka's regain, Frimpong's goal 9 s later) the ten most
similar possessions are all quick attacks after a regain; 9 reached the box, 5 ended in a shot (0.74 xG), none in a
goal. Figure: [`outputs/similarity/similar_3895052_44.png`](../../outputs/similarity/similar_3895052_44.png), made by
[`scripts/find_similar.py`](../../scripts/find_similar.py).

## Checks
- **Neighbours start the same way**: 96.8% of the ten nearest neighbours share the possession's start (play pattern
  and regain), against 24.7% for possessions picked at random.
- **The shape carries information about the outcome**, although the outcome is not in the vector: the neighbours of
  possessions that ended in a shot ended in a shot 37.9% of the time, against 10.7% for the neighbours of the others
  (15.3% of all possessions end in a shot).
- The weights are our choice, checked by eye on pitch plots and by the first check. An early version that included
  the outcome matched goals with goals regardless of how they were built up (a free kick next to a counter), which is
  why the outcome was taken out.

## In the graph and the app
`season_graph()` adds the fourth edge type, `similar`: each possession to its 5 nearest (23,925 edges, attribute
`distance`), and keeps the index as `g.graph["similarity"]`. In the app, "Find similar situations" under the selected
moment lists the ten nearest possessions with how they ended, and draws the routes of the five nearest next to it.
