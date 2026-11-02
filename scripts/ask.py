"""Ask a question in plain English: parse it with the rule-based parser and search the season.

Usage:
    python scripts/ask.py "turnovers in our own half that led to a shot within 10 seconds"
"""
import json
import sys

import pandas as pd

from match_event_search.graph import season_graph
from match_event_search.query import QueryError, search
from match_event_search.rule_parser import ParseError, Vocabulary, parse_verbose


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    g = season_graph()
    try:
        parsed = parse_verbose(sys.argv[1], Vocabulary.from_tags(g.graph["tags"]))
        results = search(parsed.query, g)
    except (ParseError, QueryError) as error:
        sys.exit(f"Could not answer: {error}")
    print("Query:", json.dumps(parsed.query))
    if parsed.unparsed:
        print("Words not used:", " ".join(parsed.unparsed))
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 50)
    print(f"{len(results)} results")
    print(results.drop(columns=["match_id", "steps", "span"]).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
