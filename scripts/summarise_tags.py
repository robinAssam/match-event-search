"""Tag the whole season and summarise the tags (numbers in docs/methodology/02_tagging.md).

Usage:
    python scripts/summarise_tags.py

Writes outputs/tagging/derived_tags.csv and outputs/tagging/phases.csv.
"""
from pathlib import Path

import pandas as pd

from match_event_search.tagging import tag_season

OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "tagging"


def main():
    tags = tag_season()
    n_matches = tags.match_id.nunique()
    side = tags.our_team.map({True: "our team", False: "opponents"}).rename("team")

    derived = (tags.groupby(side)[["progressive", "turnover", "regain", "box_entry"]].sum() / n_matches).round(1)
    progressive = tags[tags.progressive]
    completed = progressive.action.eq("carry") | progressive.outcome.eq("success")
    derived["progressive_completed"] = (progressive[completed].groupby(side[tags.progressive]).size()
                                        / n_matches).round(1)

    located = tags[tags.x.notna()]
    possession = located.in_possession.map({True: "in possession", False: "out of possession"})
    phases = (located.groupby(possession).phase.value_counts(normalize=True) * 100).round(1).rename("percent")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    derived.to_csv(OUT_DIR / "derived_tags.csv")
    phases.to_csv(OUT_DIR / "phases.csv")
    print(f"{len(tags)} events in {n_matches} matches\n")
    print("Per match:\n", derived.to_string(), "\n")
    print("Phases (% of located events):\n", phases.to_string())


if __name__ == "__main__":
    main()
