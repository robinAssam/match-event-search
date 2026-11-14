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

## Evaluation
31 questions with expected queries, written and approved before either parser saw them. A parser is correct when its
query finds exactly the same moments as the expected one. → [notes](docs/methodology/07_evaluation.md)

| Parser | Correct | Exact query |
|---|---|---|
| Rule-based (v1, baseline) | 19 / 31 (61%) | 17 / 31 (55%) |
| LLM (v2: Anthropic's Opus 5.5, medium effort) | **30 / 31 (97%)** | 27 / 31 (87%) |
| LLM with fallback to v1 | 30 / 31 (97%) | 27 / 31 (87%) |

The LLM parser handled the paraphrases, the negation, the point of view ("shots we conceded while we were winning") and
the misspelt name that the rules miss. Its one miss is the question the format cannot express: instead of saying so, it
approximated "passes that broke the midfield line" as successful progressive passes from the middle into the final
third. Two runs gave the same verdict on every question; a run of all 31 questions costs about $0.13. Every wrong v1 answer came with a "words not used" warning
(12 of 12), against 1 of the 19 correct ones. To re-run the LLM parser, use `python scripts/evaluate.py --llm` with
your own API key.

## Similar situations
Pick a moment and find the possessions across the season that looked most like it, compared by the ball's route,
tempo and how the possession started, and see how they ended. For Leverkusen's opening goal of the season (Leipzig,
22:55) the ten most similar possessions are all quick attacks after a regain: 9 reached the box, 5 ended in a shot,
none in a goal. → [notes](docs/methodology/09_similarity.md)

![The opening goal and its five most similar possessions](outputs/similarity/similar_3895052_44.png)

## Data
All 34 Bundesliga matches of Bayer Leverkusen's 2023/24 season (unbeaten: 28 wins, 6 draws), with event data and
360 freeze-frames. → [notes](docs/methodology/01_data.md)

Data provided by [StatsBomb](https://statsbomb.com/) through its [open-data repository](https://github.com/statsbomb/open-data).
