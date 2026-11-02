"""Ask a question in plain English and search the season.

Usage:
    python scripts/ask.py "turnovers in our own half that led to a shot within 10 seconds"
    python scripts/ask.py --llm "goalkeeper passes to a defender that were lost and led to a goal against us"

Without --llm the rule-based parser reads the question; with --llm an Anthropic model does (set
ANTHROPIC_API_KEY and LLM_MODEL), falling back to the rule-based parser if it fails.
"""
import argparse
import json
import sys

import pandas as pd

from match_event_search.graph import season_graph
from match_event_search.llm_parser import LLMParser
from match_event_search.query import QueryError, search
from match_event_search.rule_parser import ParseError, Vocabulary, parse_verbose


def main():
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("question")
    args.add_argument("--llm", action="store_true", help="read the question with the LLM parser")
    args = args.parse_args()

    g = season_graph()
    try:
        if args.llm:
            parsed = LLMParser(g).parse(args.question)
            if parsed.parser == "llm":
                print(f"Read by the LLM parser in {parsed.attempts} attempt(s); tokens: {parsed.usage}")
            else:
                print(f"LLM parser not used ({parsed.note}); rule-based parser instead")
            if parsed.query is None:
                sys.exit("Could not answer.")
        else:
            parsed = parse_verbose(args.question, Vocabulary.from_tags(g.graph["tags"]))
        results = search(parsed.query, g)
    except (ParseError, QueryError) as error:
        sys.exit(f"Could not answer: {error}")
    print("Query:", json.dumps(parsed.query))
    if parsed.corrected:
        print("Read as:", ", ".join(f"{a} -> {b}" for a, b in parsed.corrected.items()))
    if parsed.unparsed:
        print("Words not used:", " ".join(parsed.unparsed))
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 50)
    print(f"{len(results)} results")
    print(results.drop(columns=["match_id", "steps", "span"]).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
