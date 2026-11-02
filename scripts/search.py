"""Search the season with a JSON query (format: docs/methodology/04_query.md).

Usage:
    python scripts/search.py '{"event": {"action": "shot", "header": true, "our_team": true}}'
    python scripts/search.py query.json
"""
import json
import sys
from pathlib import Path

import pandas as pd

from match_event_search.graph import season_graph
from match_event_search.query import QueryError, search


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    arg = sys.argv[1]
    query = json.loads(Path(arg).read_text(encoding="utf-8") if arg.endswith(".json") else arg)
    g = season_graph()
    try:
        results = search(query, g)
    except QueryError as error:
        sys.exit(f"Invalid query: {error}")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 50)
    print(f"{len(results)} results")
    print(results.drop(columns=["match_id", "steps", "span"]).to_string(index=False))


if __name__ == "__main__":
    main()
