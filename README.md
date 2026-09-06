# AI-Assisted Legacy Data Migration Platform

## Project Overview
An auditable AI-assisted migration platform for moving a legacy healthcare clinical-operations database (patients, appointments, billing, medication records, lab orders, ward allocation) from PostgreSQL to Snowflake. The source schema is deliberately messy in the way real hospital systems tend to be: undocumented status codes (`blood_grp_cd`, `ins_clm_st`, `alloc_st`), inconsistent date formats (`dob` stored as a mix of `DD-MM-YYYY` and `YYYY-MM-DD`), and free-text clinical fields (`dosage_txt`, `rslt_txt`) with no lookup tables to disambiguate them.

The platform uses SQLAlchemy for profiling, LangChain + Google Gemini for semantic mapping/rule/document generation (provider is swappable — see [LLM Provider](#llm-provider) below), LangGraph for orchestration and human-in-the-loop gating, LangFuse for LLM observability, Great Expectations for data-quality checkpoints, and dbt for post-migration tests.

**Core principle:** AI proposes. Humans approve high-risk decisions. Only approved rules execute migration.

## Architecture
```text
Legacy PostgreSQL (healthcare schema)
        |
schema_profiler (SQLAlchemy)
        |
Great Expectations: source baseline
        |
ai_mapper (LangChain + Gemini)
        |
human_review_gate (LangGraph interrupt)
        |
rule_generator (LangChain + Gemini) -> lineage_generator (Mermaid diagrams)
        |
migration_executor -> Snowflake staging (typed columns, not blanket VARCHAR)
        |
validator -> reconciliation + Great Expectations post-load + dbt
        |
doc_generator -> target data dictionary

Cross-cutting: LangFuse traces/scores + hash-chained audit log
```

## LLM Provider
The LLM backend is abstracted behind `config/llm_factory.py`, selected via `LLM_PROVIDER` in `.env` (`google_genai` by default). Gemini was chosen for development because of its free tier; Anthropic Claude and OpenAI are both already supported by the factory and can be enabled by installing the matching `langchain-*` package and updating `LLM_PROVIDER`/`LLM_API_KEY`/`LLM_MODEL` — no agent code changes required. Note: Gemini's free tier currently has zero request quota on `-pro` models; `gemini-flash-latest` is the model with actual free-tier quota.

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

`docs/lineage.md` is generated automatically as part of the `rule_generator` step — no separate command needed during a normal pipeline run. To regenerate it standalone from existing `data/approved_mappings.json` + `data/transformation_rules.json` + `data/schema_profile.json` (e.g. after manually editing a mapping), run:
```bash
python -m lineage.lineage_generator
```

To run the dbt validation models for a given run (after `migration_executor` has populated the Snowflake staging tables for that run):
```bash
python -m validation.dbt_models.generate_seeds
dbt run --project-dir validation/dbt_models --profiles-dir validation/dbt_models --vars '{"run_id": "<run_id>"}'
dbt test --project-dir validation/dbt_models --profiles-dir validation/dbt_models --vars '{"run_id": "<run_id>"}'
```

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

## Lineage Diagram
`docs/lineage.md` holds one Mermaid `graph LR` diagram per source table, showing source column (with original type) → transformation logic → target column, color-coded by AI mapping confidence:
- green (`#00d4aa`): confidence ≥ 0.90, auto-approved
- amber (`#f59e0b`): confidence 0.80–0.89, passed threshold
- red (`#ef4444`): confidence < 0.80, required human review (marked `✓ reviewed`)

GitHub and VS Code (with a Markdown preview extension, or natively in recent versions) both render Mermaid fenced code blocks directly — no extra tooling needed to view it. This is the fastest way to see, at a glance, which clinical fields (blood group codes, appointment priority, claim status) were AI-inferred versus human-confirmed for a given run.

## Validation
Required checkpoints (implemented in `validation/great_expectations/gx_checkpoints.py`, using the Great Expectations 1.x ephemeral-context API):
1. **Source baseline** — row count vs. seeded target, PK not-null/uniqueness, known status-code domains (`pat_st_cd`, `blood_grp_cd`, etc. — see `KNOWN_VALUE_SETS`) checked in-set.
2. **Post-extraction** — extracted row counts match the source baseline; no columns dropped.
3. **Post-load** — Snowflake target row counts match baseline; null rates within 2% tolerance; status-code domains still valid post-transformation.

Each checkpoint writes `data/gx_results_{checkpoint}.json`; a failed checkpoint raises and blocks the pipeline.

`validation/validator.py` additionally builds `data/reconciliation_report.json` (source/target row counts, null rates, cardinality per column), which `validation/dbt_models/generate_seeds.py` turns into dbt seeds. The dbt project (`validation/dbt_models/`) then runs three models against Snowflake: `row_count_reconciliation`, `null_rate_check` (both PASS/FAIL views built from the reconciliation report), and `fk_integrity_check` (queries the live Snowflake target for a given run to confirm every `appointments.pat_id` resolves to a real `patient_records.pat_id`). `schema.yml` adds `not_null`/`unique`/`accepted_values` tests on top.

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

Healthcare-specific:
- **Clinical code ambiguity**: short undocumented codes (`blood_grp_cd`, `ins_clm_st`, `alloc_st`) can look plausible to an LLM without actually being verifiable from the data alone — the AI mapper is deliberately conservative here and routes them to human review rather than guessing confidently.
- **Medication/dosage free text**: `dosage_txt` (e.g. `'BD'`, `'TDS'`, `'SOS'`) and `dur_days` (mixed `'7'` / `'7 days'` / `'one week'`) are pharmaceutical shorthand that a general-purpose LLM will often mis-normalize; these fields should be reviewed by a clinical SME, not approved on AI confidence alone, regardless of the score returned.
- **Priority/ordinal direction is not inferrable from data**: `pri_lvl` (1–5) has no documented convention for whether 1 is highest or lowest priority — this is a case where confidence should stay low structurally, not just when sample values look unclear.
