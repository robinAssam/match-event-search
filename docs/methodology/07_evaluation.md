# 7. Evaluation

How well does each parser turn a question into the right query? [`evaluation/questions.json`](../../evaluation/questions.json)
holds 31 questions with their expected queries, drafted before either parser saw them and approved by hand: players,
roles, zones, time, game state, set pieces, receivers, opponents, venue, eight sequences, a negation, two misspellings
(a football word and a player's name) and one question the format cannot express. The expected queries are fixed;
the parsers are not tuned on these questions.

Run with [`scripts/evaluate.py`](../../scripts/evaluate.py) (code: [`evaluation.py`](../../src/match_event_search/evaluation.py));
results per question are in [`outputs/evaluation/`](../../outputs/evaluation).

## Scoring

- **Correct**: the parser's query finds exactly the same moments as the expected query. Two differently written
  queries can mean the same thing, so this is the main score. For the question that cannot be expressed, correct
  means the parser said so.
- **Exact**: the query itself is the expected one, up to key order, list order and one-item lists.
- The LLM parser is scored on its own (**v2**: when it hands over to the rules, it has not answered) and as the
  system a user gets (**v2 + fallback**), with the tokens it used.

## Results

| Parser | Correct | Exact |
|---|---|---|
| Rule-based (v1, baseline) | 19 / 31 (61%) | 17 / 31 (55%) |
| LLM (v2: Anthropic's Opus 5.5, medium effort) | 30 / 31 (97%) | 27 / 31 (87%) |
| LLM with fallback (v2 + fallback) | 30 / 31 (97%) | 27 / 31 (87%) |

The LLM parser needs an API key, billed to whoever runs it: `python scripts/evaluate.py --llm` with your own
`ANTHROPIC_API_KEY` and `LLM_MODEL`.

## The LLM parser
- **It fixes what the rules miss.** All eleven questions the rule-based parser got wrong and the format can express
  were read correctly: the paraphrases ("found a teammate", "balls won high up the pitch", "after corners"), the
  negation ("weren't progressive"), the point of view (#10, #11), the sequences without a connector (#27, #28) and the
  misspelt name ("Schik").
- **Its one miss is #31**, the question the format cannot express. It did not say so, but approximated "passes that
  broke the opposition's midfield line" as successful progressive passes from the middle third into the final third:
  a reasonable proxy, but a guess presented as an answer, which the scoring counts as wrong.
- **Exact**: 27 of 31. Three correct answers (#24, #26, #27) were written differently from the expected query but find
  exactly the same moments, which is why the main score compares moments.
- **Consistent**: two separate runs gave the same verdict on every question; only #27 was written differently, with
  the same moments. Every answer was valid on the first attempt, so the retry and the fallback were never needed.
- **Tokens and cost**: per question about 22 new input tokens, 6,465 read from the cache (the instructions, the same
  for every question) and about 80 output tokens. At Opus 5.5's list prices (October 2026: $4 per million input tokens,
  $20 per million output, $0.20 per million cache reads, $5 per million cache writes) the whole run of 31 questions
  costs about $0.13, or $0.004 per question. The one cache write of the instructions was not recorded in these runs and
  is estimated at the size of a cache read; the evaluation now records it.

## What the rule-based parser gets wrong

| Kind | Questions | What happened |
|---|---|---|
| Paraphrases it does not know | #1 "from outside the box", #3 "found a teammate", #16 "didn't reach a teammate", #18 "after corners", #23 "balls won high up the pitch" | the phrase is skipped, or read as something else: "won" as a successful action, "corners" as the corner kicks rather than what followed them |
| Negation | #19 "weren't progressive" | the negation is ignored, so the query means the opposite |
| Whose point of view | #10 "shots we conceded while we were winning", #11 "Leipzig's shots on target against us" | read as Leverkusen's shots (#11 even finds the same number, 12, but other moments) |
| A sequence without a connector | #27 "dribbling straight after receiving the ball", #28 "goals we conceded within 20 seconds of losing the ball" | read as one event, because steps are only split at "led to", "followed by" and similar |
| A misspelt name | #30 "Schik" | names are never corrected, by design |
| Cannot say no | #31 "passes that broke the opposition's midfield line" | it returns a partial query instead of saying the question cannot be expressed |

**The warning is a reliable signal.** All 12 wrong answers came with words the parser did not use, and only 1 of the 19
correct ones did (#14, where the unused word was "actions"). So when the rule-based parser reports no unused words, its
answer was right every time here; when it does, the answer should be checked.
