"""Score the parsers on the approved questions (evaluation/questions.json).

Usage:
    python scripts/evaluate.py          # the rule-based parser (v1), free
    python scripts/evaluate.py --llm    # also the LLM parser (v2), with your own API key

--llm sends each question to the model, billed to the API key of whoever runs it (ANTHROPIC_API_KEY, with the
model id in LLM_MODEL). Results go to outputs/evaluation/: one file of per-question results per parser, and
summary.csv over all parsers whose results are there.
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

from match_event_search.evaluation import evaluate, summarise
from match_event_search.graph import season_graph
from match_event_search.llm_parser import LLMParser

OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "evaluation"
FILES = {"v1": "results_v1.csv", "v2": "results_v2.csv", "v2 + fallback": "results_v2_fallback.csv"}


def main():
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--llm", action="store_true", help="also evaluate the LLM parser (uses your API key)")
    args = args.parse_args()
    if args.llm and not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("LLM_MODEL")):
        sys.exit("--llm needs your own ANTHROPIC_API_KEY and LLM_MODEL in the environment.")

    g = season_graph()
    results = evaluate(g, llm=LLMParser(g) if args.llm else None)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for parser, part in results.groupby("parser", sort=False):
        part.to_csv(OUT_DIR / FILES[parser], index=False)
    every = pd.concat([pd.read_csv(OUT_DIR / f) for f in FILES.values() if (OUT_DIR / f).exists()])
    summary = summarise(every)
    summary.to_csv(OUT_DIR / "summary.csv")

    pd.set_option("display.width", 200)
    print(summary.to_string(), "\n")
    for parser, part in results.groupby("parser", sort=False):
        wrong = part[~part.correct]
        print(f"{parser}: {int(part.correct.sum())}/{len(part)} correct. Wrong:")
        for r in wrong.itertuples():
            print(f"  #{r.id} {r.question}\n      found {r.n_found} of {r.n_expected}; {r.query or '(no query)'}"
                  + (f"\n      {r.note}" if r.note else ""))


if __name__ == "__main__":
    main()
