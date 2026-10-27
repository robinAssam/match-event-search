# Match Event Search

Plain-language search over football match events, built on StatsBomb open data. An analyst types a question like
*"turnovers in our own half that led to a shot within 10 seconds"* and gets back the matching moments with match
time, the players involved and a pitch plot.

Work in progress.

## Quick start
Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
pytest
```

## Data
Uses [StatsBomb open data](https://github.com/statsbomb/open-data).
