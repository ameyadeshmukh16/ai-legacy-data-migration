# AI-Assisted Legacy Data Migration Platform

## Project Overview
An auditable AI-assisted migration platform for moving legacy PostgreSQL/MySQL data to Snowflake. It uses SQLAlchemy for profiling, LangChain for semantic mapping/rule/document generation, LangGraph for orchestration and human-in-the-loop gating, LangFuse for LLM observability, Great Expectations for data-quality checkpoints, and dbt for post-migration tests.

**Core principle:** AI proposes. Humans approve high-risk decisions. Only approved rules execute migration.

## Architecture
```text
Legacy PostgreSQL/MySQL
        |
schema_profiler (SQLAlchemy)
        |
Great Expectations: source baseline
        |
ai_mapper (LangChain)
        |
human_review_gate (LangGraph interrupt)
        |
rule_generator (LangChain)
        |
migration_executor -> Snowflake staging
        |
validator -> reconciliation + dbt
        |
doc_generator -> target data dictionary

Cross-cutting: LangFuse + hash-chained audit log
```

## Mandatory Nodes
1. schema_profiler
2. ai_mapper
3. human_review_gate
4. rule_generator
5. migration_executor
6. validator
7. doc_generator

## Setup
```bash
python -m venv .venv
# activate the environment
pip install -r requirements.txt
docker compose up -d
cp .env.example .env
```

Configure LLM, Snowflake and LangFuse credentials in `.env`. Never commit `.env`.

## Environment Variables
See `.env.example`. Required variables include `LLM_API_KEY`, `LLM_MODEL`, `SOURCE_DB_URL`, Snowflake credentials, LangFuse credentials and `CONFIDENCE_THRESHOLD`.

## Run
Profile:
```bash
python -m agents.schema_profiler
```
Pipeline:
```bash
python -m workflow.langgraph_orchestrator
```

If any mapping has confidence below `0.80` (configurable), LangGraph pauses at the human-review node. Resume the same thread after decisions are supplied.

## Human Review
Low-confidence mappings are written to `data/human_review_queue.json`. Decisions are `approve`, `reject`, or `override`. A low-confidence approval/override requires a non-empty `override_note`. Rejection blocks migration.

## Rollback
1. Stop the run.
2. Inspect `data/reconciliation_report.json`.
3. Inspect `audit/migration_audit_log.json`.
4. Do not publish staging data.
5. Drop run-specific Snowflake staging tables.
6. Correct mapping/rule issues and resume/re-run from the appropriate checkpoint.

The source is read-only.

## AI Decision Audit
Audit log: `audit/migration_audit_log.json`. Each event records run ID, event ID, timestamp, event type, prompt ID where applicable, confidence/decision metadata and SHA-256 hash chaining.

LangFuse traces should be filtered by the migration `run_id`.

## Validation
Required checkpoints:
1. Source baseline
2. Post-extraction
3. Post-load

Reconciliation compares row counts, null rates and cardinality/distributions. dbt models cover row counts, null checks, FK integrity and business-rule checks.

## Transformation Rule Contract
```json
{
  "source_column": "pat_st_cd",
  "target_column": "patient_status",
  "logic": "CASE WHEN src = 'A' THEN 'Active' WHEN src = 'D' THEN 'Discharged' ELSE NULL END",
  "null_handling": "Map to NULL; flag in reconciliation report.",
  "edge_cases": ["Unknown codes default to NULL", "Trim whitespace before mapping"],
  "confidence": 0.84,
  "prompt_id": "prompt-uuid-abc123",
  "human_reviewed": false,
  "override_note": null
}
```

## Known Limitations
LLM confidence is a routing signal, not proof. Semantic ambiguity needs domain expertise. Live Snowflake/LLM credentials are required. Great Expectations APIs can differ by version and are isolated behind a validation adapter. Production deployments require organization-specific IAM, encryption, retention, networking and regulatory review.
