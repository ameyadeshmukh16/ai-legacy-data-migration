# Architecture
SQLAlchemy profiles the source healthcare schema; LangChain (via Groq by default, provider-swappable through `config/llm_factory.py`) maps semantics and generates rules/docs; LangGraph orchestrates seven stages and pauses for low-confidence human review; a Mermaid lineage diagram is generated alongside the transformation rules; the transformation `logic` each rule carries is `sqlglot`-AST-validated before execution; Snowflake receives run-specific staging data with mapped column types; Great Expectations, row-count/null-rate reconciliation, value-distribution reconciliation, and dbt checks block completion on failure, and a failed run rolls back its run-scoped target tables; LangFuse and a hash-chained audit log (with run-lifecycle events) provide observability and governance.

A thin Streamlit application layer (`app.py`, `app/`, `services/workflow_service.py`) sits
on top as an optional presentation/control surface — it drives the same compiled LangGraph
graph via `build_graph`/`invoke`/`Command(resume=...)` and adds no pipeline logic of its
own; see `README.md` § Application.

See `docs/lineage.md` for the auto-generated data lineage diagrams and `docs/architecture.png` for the visual diagram (predates the application layer above — the diagram covers the LangGraph pipeline only).
