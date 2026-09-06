# Architecture
SQLAlchemy profiles the source healthcare schema; LangChain (via Google Gemini, provider-swappable) maps semantics and generates rules/docs; LangGraph orchestrates seven stages and pauses for low-confidence human review; a Mermaid lineage diagram is generated alongside the transformation rules; Snowflake receives run-specific staging data with mapped column types; Great Expectations, dbt, and reconciliation checks block completion on failure; LangFuse and a hash-chained audit log provide observability and governance.

See `docs/lineage.md` for the auto-generated data lineage diagrams and `docs/architecture.png` for the visual diagram.
