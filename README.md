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
python scripts/download_data.py     # ~400 MB of StatsBomb open data into data/raw/ (--limit 3 for a quick start)
pytest
```

## Search interface
```bash
streamlit run app/app.py
```
Type a question or pick an example; the page shows how the question was read, the moments found, where they
started, and the selected moment on the pitch. → [notes](docs/methodology/08_interface.md)

## Questions in plain English
Two parsers turn a question into a query: fixed rules (v1, no setup) and an Anthropic model (v2), which falls back to
the rules when it fails. v2 uses the API key of whoever runs the code, so set your own key and the model id:
```bash
setx ANTHROPIC_API_KEY "<your key>"
setx LLM_MODEL "<model id>"
python scripts/ask.py --llm "goalkeeper passes to a defender that were lost and led to a goal against us"
```
→ [rule-based parser](docs/methodology/05_rule_parser.md), [LLM parser](docs/methodology/06_llm_parser.md)

## Data
All 34 Bundesliga matches of Bayer Leverkusen's 2023/24 season (unbeaten: 28 wins, 6 draws), with event data and
360 freeze-frames. → [notes](docs/methodology/01_data.md)

Data provided by [StatsBomb](https://statsbomb.com/) through its [open-data repository](https://github.com/statsbomb/open-data).
