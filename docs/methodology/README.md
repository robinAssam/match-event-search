# Methodology

Short explanations of each step of the project. Notes are added as each stage is completed.

1. [Data](01_data.md): choice of season, loading, what the events look like and one known data problem
2. [Tagging](02_tagging.md): the nine tag families, progressive passes, turnovers, phases and a worked example
3. [Graph](03_graph.md): the hierarchy, the edge channels and why tags sit in a table next to the graph
4. [Query format and engine](04_query.md): the JSON format, the decisions behind it, validation and how sequences are found
5. [Rule-based parser](05_rule_parser.md): how a question becomes a query, the rules beyond vocabulary, and known limits
6. [LLM parser](06_llm_parser.md): what the model gets, checks, retry and fallback to the rule-based parser
7. [Evaluation](07_evaluation.md): the question set, scoring, results and what the rule-based parser gets wrong
8. [Interface](08_interface.md): the Streamlit page
9. [Similar situations](09_similarity.md): possessions as vectors, the checks, and the `similar` edges
