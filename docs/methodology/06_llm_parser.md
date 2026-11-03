# 6. LLM parser (v2)

[`llm_parser.py`](../../src/match_event_search/llm_parser.py) asks an Anthropic model to translate the question into
the same JSON query format as the rule-based parser (stage 5). The model writes the query; the search itself is the
same engine as before, so every result can be traced back to a query you can read.

## What the model gets
One set of instructions, the same for every question (so it is cached between questions):

- the query format (filters, sequences, scope) and how `within_s`, `team` and `same_possession` work;
- every field with its allowed values, generated from the query schema itself, so the two cannot drift apart;
- the football conventions of the rule-based parser: no team means Leverkusen, "left back" includes wing backs,
  "defenders" are centre and full backs, an intercepted pass is a `turnover`, "from corners" is a `play_pattern`,
  zones are seen from the acting team, `minute` starts at 0, the default team and time window of a later step;
- the names of every team and player in the season (372 players), so it can map "Wirtz" or a misspelling to the
  full StatsBomb name;
- the two example questions from the project brief, with their queries.

It answers with the JSON query only, or `{"error": ...}` if the question cannot be expressed.

## Checks, retry and fallback

1. The answer is read as JSON and checked like any other query: the JSON Schema, then names against the data.
2. If it fails, the model sees its answer and the error messages (e.g. `event/third: 'atacking' is not one of
   [...]`) and is asked once for a corrected query (`retries` in `LLMConfig`).
3. If it still fails, if the model says it cannot express the question, if the request is declined, or if the API
   cannot be reached (no key, no network), the rule-based parser answers. The result says which parser answered
   and why, in the app and in `scripts/ask.py --llm`.

So the LLM parser is never worse at producing *a* valid query than v1; whether its queries are *right* more often is
what stage 7 measures.

## Setup
The LLM parser uses the API key of whoever runs the code, and requests are billed to that account. No key is part of
the repository, and the app has no field to enter one: to use the LLM parser, run the code on your own machine with
your own Anthropic API key and the model id set as environment variables (never in a file you commit; `.env` files
are ignored by git, and a test fails if a key is ever tracked):

```bash
setx ANTHROPIC_API_KEY "<your key>"
setx LLM_MODEL "<model id>"
```

Settings are in `LLMConfig` ([`config.py`](../../src/match_event_search/config.py)): reasoning effort `medium`,
one retry. Each question costs one request (two if it is retried); the instructions are cached, and the app keeps
the model's answers per question, so asking the same question again costs nothing.

## Tests
[`test_llm_parser.py`](../../tests/test_llm_parser.py) replaces the API with a simulated client, so the tests send
no requests and cost nothing: a valid answer, an answer corrected after seeing the errors, an unknown player name, an
answer still invalid after the retry, a code fence around the JSON, the model declining, API errors, no model
configured, and a question neither parser can read. The app test runs with no model configured, so it never calls
the API either.

Not measured yet: how often the model's queries are correct and what a question costs. Both need the API key and
are part of stage 7.
