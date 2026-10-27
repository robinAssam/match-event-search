"""Download the configured season's matches (events + 360 frames) into data/raw/.

Usage:
    python scripts/download_data.py            # all matches
    python scripts/download_data.py --limit 3  # the first 3 matches by date
"""
import argparse

from match_event_search.loaders import CACHE_DIR, load_events, load_frames, load_matches


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="only the first N matches by date")
    args = parser.parse_args()

    matches = load_matches()
    if args.limit:
        matches = matches.head(args.limit)
    for i, m in enumerate(matches.itertuples(), 1):
        events = load_events(m.match_id)
        frames = load_frames(m.match_id)
        print(f"[{i}/{len(matches)}] {m.match_date} {m.home_team} {m.home_score}-{m.away_score} "
              f"{m.away_team}: {len(events)} events, {frames.id.nunique()} with 360 frames")

    size = sum(f.stat().st_size for f in CACHE_DIR.rglob("*.json")) / 1e6
    print(f"Data in {CACHE_DIR} ({size:.0f} MB)")


if __name__ == "__main__":
    main()
