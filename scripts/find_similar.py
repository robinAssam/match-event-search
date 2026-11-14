"""Find the possessions most similar to one possession and draw their routes.

Usage:
    python scripts/find_similar.py                      # Leverkusen's opening goal of the season (v Leipzig, 22:55)
    python scripts/find_similar.py MATCH_ID POSSESSION

Writes outputs/similarity/similar_<match>_<possession>.png and prints the neighbours.
"""
import sys
from pathlib import Path

from match_event_search.graph import season_graph
from match_event_search.plotting import plot_routes
from match_event_search.similarity import summary

OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "similarity"


def main():
    match_id, possession = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (3895052, 44)
    g = season_graph()
    index = g.graph["similarity"]
    labels = {d["match_id"]: f"{d['home_team']} {d['home_score']}-{d['away_score']} {d['away_team']}"
              for _, d in g.nodes(data=True) if d["kind"] == "match"}
    neighbours = index.similar(match_id, possession, k=10)
    me = index.table.loc[(match_id, possession)]
    print(f"{labels[match_id]}, {me.team} from {me.minute}:{me.second:02d}: {summary(neighbours)}")
    for (m, _), r in neighbours.iterrows():
        ended = "goal" if r.goal else "shot" if r.shot else "lost ball" if r.lost_ball else "-"
        print(f"  {r.distance:.3f}  {labels[m]:48s} {r.minute:>2}:{r.second:02d}  {r.team:20s} {ended}")

    keys = [(match_id, possession)] + list(neighbours.index[:5])
    titles = [f"{labels[match_id]} {me.minute}' (chosen)"] + [f"{labels[m]} {index.table.loc[(m, p)].minute}'"
                                                             for m, p in neighbours.index[:5]]
    fig = plot_routes([index.paths[k] for k in keys], titles, [bool(index.table.loc[k].shot) for k in keys])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"similar_{match_id}_{possession}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
