"""Evaluate the parsers on the approved questions (docs/methodology/07_evaluation.md).

Each question in `evaluation/questions.json` has an expected query, written
and approved before either parser saw it (or `null` when the question cannot
be expressed). A parser's answer is scored two ways:

* correct: its query finds exactly the same moments as the expected query
  (two differently written queries can mean the same thing). For a question
  that cannot be expressed, correct means the parser said so.
* exact: its query is the expected query, up to key order, list order and
  one-item lists.

The LLM parser is scored on its own ("v2": a fallback to the rules counts as
no answer) and as the system the user gets ("v2 + fallback").
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import pandas as pd

from .query import QueryError, find
from .rule_parser import ParseError, Vocabulary, parse_verbose

QUESTIONS = Path(__file__).resolve().parents[2] / "evaluation" / "questions.json"
DECLINED_BY_MODEL = "the model could not express it"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class Answer:
    query: dict | None
    declined: bool = False  # the parser said the question cannot be expressed
    note: str = ""
    attempts: int = 0
    usage: dict = field(default_factory=dict)


def answer_v1(question: str, vocab: Vocabulary) -> Answer:
    try:
        parsed = parse_verbose(question, vocab)
    except (ParseError, QueryError) as error:
        return Answer(query=None, declined=True, note=str(error))
    note = f"words not used: {' '.join(parsed.unparsed)}" if parsed.unparsed else ""
    return Answer(query=parsed.query, note=note)


def answer_v2(question: str, llm) -> tuple[Answer, Answer]:
    """The LLM parser's answer on its own, and with the fallback to the rules."""
    result = llm.parse(question)
    alone = Answer(query=result.query if result.parser == "llm" else None,
                   declined=result.note.startswith(DECLINED_BY_MODEL),
                   note=result.note, attempts=result.attempts, usage=result.usage)
    with_fallback = Answer(query=result.query, declined=result.query is None,
                           note=f"answered by the {result.parser} parser" + (f": {result.note}" if result.note else ""),
                           attempts=result.attempts, usage=result.usage)
    return alone, with_fallback


def moments(query: dict, g: nx.MultiDiGraph) -> frozenset:
    """The moments a query finds, each as the tuple of its step events."""
    return frozenset(tuple(m.steps) for m in find(query, g))


def normalise(value):
    """A canonical form for comparing queries: sorted keys and scalar lists, one-item lists as their item,
    whole numbers as floats. Lists of objects (sequence steps) keep their order."""
    if isinstance(value, dict):
        return {k: normalise(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        items = [normalise(v) for v in value]
        if all(not isinstance(v, (dict, list)) for v in items):
            items = sorted(items, key=repr)
            return items[0] if len(items) == 1 else items
        return items
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return value


def same_query(a: dict, b: dict) -> bool:
    """Equal after normalising; compared as JSON text, where true and 1 differ (in Python True == 1)."""
    return json.dumps(normalise(a), sort_keys=True) == json.dumps(normalise(b), sort_keys=True)


def grade(answer: Answer, expected: dict | None, g: nx.MultiDiGraph, expected_moments=None) -> dict:
    if expected is None:
        right = answer.query is None and answer.declined
        return {"correct": right, "exact": right, "n_expected": None, "n_found": None}
    if answer.query is None:
        return {"correct": False, "exact": False, "n_expected": len(expected_moments), "n_found": None}
    try:
        found = moments(answer.query, g)
    except QueryError as error:  # e.g. an unknown name
        answer.note = f"{answer.note}; query error: {error}".strip("; ")
        return {"correct": False, "exact": False, "n_expected": len(expected_moments), "n_found": None}
    return {"correct": found == expected_moments,
            "exact": same_query(answer.query, expected),
            "n_expected": len(expected_moments), "n_found": len(found)}


def evaluate(g: nx.MultiDiGraph, questions: list[dict] = None, llm=None) -> pd.DataFrame:
    """One row per question and parser: v1, and v2 alone and with fallback if an LLM parser is given."""
    questions = questions if questions is not None else load_questions()
    vocab = Vocabulary.from_tags(g.graph["tags"])
    rows = []
    for q in questions:
        expected = q["query"]
        expected_moments = moments(expected, g) if expected is not None else None
        answers = {"v1": answer_v1(q["question"], vocab)}
        if llm is not None:
            answers["v2"], answers["v2 + fallback"] = answer_v2(q["question"], llm)
        for parser, answer in answers.items():
            score = grade(answer, expected, g, expected_moments)
            rows.append({"id": q["id"], "category": q["category"], "question": q["question"], "parser": parser,
                         **score, "declined": answer.declined,
                         "query": json.dumps(answer.query, ensure_ascii=False) if answer.query else "",
                         "note": answer.note, "attempts": answer.attempts,
                         "input_tokens": answer.usage.get("input_tokens", 0),
                         "output_tokens": answer.usage.get("output_tokens", 0),
                         "cache_read_tokens": answer.usage.get("cache_read_input_tokens", 0)})
    results = pd.DataFrame(rows)
    # Counts are missing for unanswered questions; keep them whole numbers.
    return results.astype({"n_expected": "Int64", "n_found": "Int64"})


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Per parser: how many questions were read correctly and exactly, and the tokens used."""
    g = results.groupby("parser", sort=False)
    summary = pd.DataFrame({
        "questions": g.size(),
        "correct": g.correct.sum(),
        "exact": g.exact.sum(),
        "declined": g.declined.sum(),
        "input_tokens": g.input_tokens.sum(),
        "output_tokens": g.output_tokens.sum(),
        "cache_read_tokens": g.cache_read_tokens.sum(),
    })
    summary["correct_pct"] = (100 * summary.correct / summary.questions).round(1)
    summary["exact_pct"] = (100 * summary.exact / summary.questions).round(1)
    return summary
