"""Build the season graph and print its size (numbers in docs/methodology/03_graph.md).

Usage:
    python scripts/build_graph.py
"""
import time

from match_event_search.graph import describe, season_graph


def main():
    start = time.perf_counter()
    g = season_graph()
    sizes = describe(g)
    print(f"Built in {time.perf_counter() - start:.0f} s (tagging included)")
    print("Nodes:", ", ".join(f"{k} {v:,}" for k, v in sizes["nodes"].items()))
    print("Edges:", ", ".join(f"{k} {v:,}" for k, v in sizes["edges"].items()))


if __name__ == "__main__":
    main()
