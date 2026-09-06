# AI-Assisted Legacy Data Migration Platform

## Project Overview
An auditable AI-assisted migration platform for moving a legacy healthcare clinical-operations database (patients, appointments, billing, medication records, lab orders, ward allocation) from PostgreSQL to Snowflake. The source schema is deliberately messy in the way real hospital systems tend to be: undocumented status codes (`blood_grp_cd`, `ins_clm_st`, `alloc_st`), inconsistent date formats (`dob` stored as a mix of `DD-MM-YYYY` and `YYYY-MM-DD`), and free-text clinical fields (`dosage_txt`, `rslt_txt`) with no lookup tables to disambiguate them.

The platform uses SQLAlchemy for profiling, LangChain for semantic mapping/rule/document generation (provider is swappable — see [LLM Provider](#llm-provider) below), LangGraph for orchestration and human-in-the-loop gating, LangFuse for LLM observability, Great Expectations for data-quality checkpoints, and dbt for post-migration tests.

**Core principle:** AI proposes. Humans approve high-risk decisions. Only approved rules execute migration — `migration_executor` applies each approved rule's transformation `logic` for real (e.g. `pat_st_cd` values of `'A'`/`'D'` land in Snowflake as `'Active'`/`'Discharged'`, under a renamed `patient_status` column), not a raw copy of source values under source column names.

## Architecture
```text
Legacy PostgreSQL (healthcare schema)
        |
schema_profiler (SQLAlchemy) -> Great Expectations: source baseline
        |
ai_mapper (LangChain) -- one LLM call per column, proposes target name/type/transformation + confidence
        |
human_review_gate (LangGraph interrupt, checkpointed) -- pauses only for mappings below CONFIDENCE_THRESHOLD;
        |                auto-approved mappings are marked review_status=AUTO_APPROVED (human_reviewed=false);
        |                human decisions carry reviewer_id/reviewer_role
        |
rule_generator (LangChain) -> lineage_generator (Mermaid diagrams)
        |
migration_executor -- per table: raw extract -> Great Expectations: post-extraction (raw rows, raw
        |                column names, real no-columns-dropped check) -> apply approved rule logic ->
        |                load to staging (Snowflake types from each rule's target_type hint)
        |
validator -- Great Expectations: post-load -> reconciliation -> value-distribution reconciliation
        |                -> dbt seed/run/test
        |
doc_generator -> target data dictionary

Cross-cutting: LangFuse traces/scores + hash-chained audit log (run_started/run_completed/run_failed;
failed runs roll back their run-scoped Snowflake tables)
```

## LLM Provider
The LLM backend is abstracted behind `config/llm_factory.py`, selected via `LLM_PROVIDER` in `.env`. Supported providers: `groq` (default), `google_genai`, `nvidia`, `openai`. `groq`/`nvidia`/`openai` all run through `langchain-openai` (declared in `requirements.txt`); `google_genai` uses `langchain-google-genai`. Switching is a config change (`LLM_PROVIDER`/`LLM_API_KEY`/`LLM_MODEL` in `.env`), never an agent code change.

Groq (`openai/gpt-oss-120b`) is the current default: it was the most reliable option tested for this project's structured-output workload (one JSON-schema-constrained LLM call per source column). Notes from evaluating alternatives during development:
- **Google Gemini** (`gemini-flash-latest`): works, but the free tier is capped at 20 requests/day on some models — easily exhausted by a single multi-table run (~35+ LLM calls).
- **NVIDIA NIM** (`openai/gpt-oss-20b`): connects fine for simple prompts, but reliably timed out under `with_structured_output` once given this project's real prompts (column metadata, sample values, FK context) — confirmed via direct timing tests, not just occasional flakiness.
- **Groq** (`openai/gpt-oss-120b`): fast (~1-2s/call) and correct, but the free tier's 8000-tokens/minute cap throttles a multi-table run to roughly one call per minute — a full 5-table run takes 20-30+ minutes on the free tier. Budget for this when running the full pipeline, or supply a paid-tier key for faster runs.

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

If any mapping has confidence below `0.80` (configurable), LangGraph pauses at the human-review node (checkpointed via `MemorySaver` — resume must happen in the same process). `python -m workflow.langgraph_orchestrator`'s `__main__` block handles this automatically: it prints the review queue, reads a JSON array of decisions from stdin, and resumes via `Command(resume=decisions)` until the run completes.

`docs/lineage.md` is generated automatically as part of the `rule_generator` step, and the three Great Expectations checkpoints plus the dbt `seed`/`run`/`test` cycle all run automatically as part of `schema_profiler`/`migration_executor`/`validator` — none of these require a separate manual command during a normal pipeline run. To regenerate the lineage diagram standalone from existing `data/approved_mappings.json` + `data/transformation_rules.json` + `data/schema_profile.json` (e.g. after manually editing a mapping), run:
```bash
python -m lineage.lineage_generator
```

To re-run the dbt validation models standalone for a given run (e.g. to inspect results without re-running the whole pipeline):
```bash
python -m validation.dbt_models.generate_seeds
dbt run --project-dir validation/dbt_models --profiles-dir validation/dbt_models --vars '{"run_id": "<run_id>"}'
dbt test --project-dir validation/dbt_models --profiles-dir validation/dbt_models --vars '{"run_id": "<run_id>"}'
```

## Human Review
Low-confidence mappings are written to `data/human_review_queue.json`. Each decision is a JSON object with `mapping_index`, `decision` (`approve`/`reject`/`override`), `override_note`, `reviewer_id`, and `reviewer_role` — `reviewer_id`/`reviewer_role` are required on every decision, and a low-confidence approval/override also requires a non-empty `override_note`. Rejection blocks migration.

Approved mappings carry an explicit `review_status`:
- `AUTO_APPROVED` — confidence ≥ threshold, no human looked at it (`human_reviewed=false`).
- `HUMAN_APPROVED` — a reviewer approved it (`human_reviewed=true`, with `reviewer_id`/`reviewer_role`).

Only `HUMAN_APPROVED` satisfies the low-confidence execution gate in `agents/rule_generator.validate_rules_before_execution`.

## Rollback
On any pipeline failure (a GX checkpoint, reconciliation, distribution reconciliation, or dbt test), `workflow/langgraph_orchestrator.run_migration` writes a `run_failed` audit event and calls `migration.executor.rollback_run`, which drops every `<table>_<run_id>` staging table this run created in Snowflake, then writes `run_rolled_back`. The source is read-only and never touched. To recover: inspect `data/reconciliation_report.json` + `audit/migration_audit_log.json`, correct the mapping/rule issue, and re-run.

## AI Decision Audit
Audit log: `audit/migration_audit_log.json`. Each event records run ID, event ID, timestamp, event type, prompt ID where applicable, confidence/decision metadata and SHA-256 hash chaining. Human-review events additionally record `reviewer_id`/`reviewer_role`. Run lifecycle is bracketed by `run_started` … `run_completed` (or `run_failed` + `run_rolled_back`).

LangFuse traces should be filtered by the migration `run_id`.

## Lineage Diagram
`docs/lineage.md` holds one Mermaid `graph LR` diagram per source table, showing source column (with original type) → transformation logic → target column, color-coded by AI mapping confidence:
- green (`#00d4aa`): confidence ≥ 0.90, auto-approved
- amber (`#f59e0b`): confidence 0.80–0.89, passed threshold
- red (`#ef4444`): confidence < 0.80, required human review (marked `✓ reviewed`)

GitHub and VS Code (with a Markdown preview extension, or natively in recent versions) both render Mermaid fenced code blocks directly — no extra tooling needed to view it. This is the fastest way to see, at a glance, which clinical fields (blood group codes, appointment priority, claim status) were AI-inferred versus human-confirmed for a given run.

## Validation
Required checkpoints (implemented in `validation/great_expectations/gx_checkpoints.py`, using the Great Expectations 1.x ephemeral-context API), all wired directly into `workflow/langgraph_orchestrator.py` — not standalone scripts:
1. **Source baseline** (`schema_profiler` node) — row count vs. seeded target, PK not-null/uniqueness, known status-code domains (`pat_st_cd`, `blood_grp_cd`, etc. — see `KNOWN_VALUE_SETS`) checked in-set. Runs before any LLM calls, so a broken source fails fast without spending mapping/rule-generation cost.
2. **Post-extraction** (`migration_executor`, per table, *before* transformation and load) — runs on the raw extracted rows under their raw source column names: row count matches the source baseline, and `no_columns_dropped` is a real set comparison of extracted columns vs. the profile's column list (no longer a hardcoded `True`).
3. **Post-load** (`validator`, first thing it does) — Snowflake target row counts match baseline; null rates within 2% tolerance; **transformed** status-code domains valid (`TARGET_VALUE_SETS`, e.g. `patient_status` must be one of `Active`/`Discharged`/`Inactive`/`Suspended` — checked against the actual post-transformation values, not the raw source codes).

Each checkpoint writes `data/gx_results_{checkpoint}.json` and raises `RuntimeError` on failure, halting the pipeline.

`validation/validator.py` builds `data/reconciliation_report.json` (source/target row counts, null rates, cardinality per column, keyed by source column name even though target stats are queried by the renamed `target_column`). `validator` then runs **value-distribution reconciliation** (`validation/distribution_reconciler.py`): for every non-identity rule it computes the expected target distribution by running the rule's own `logic` as a `GROUP BY` against the immutable source table, computes the actual target distribution from Snowflake, and asserts every value bucket (NULL included) matches exactly. This is what proves a semantic transformation preserved meaning — that source `A` (5 000 rows) actually became target `Active` (5 000 rows), not just that row counts line up. A mismatch writes `data/distribution_reconciliation_report.json` with the offending buckets and blocks completion.

Finally the dbt project (`validation/dbt_models/`) runs against Snowflake, invoked from `validator` via `validation/dbt_runner.py`. The three diagnostic models are **zero-row tests**: `row_count_reconciliation` and `null_rate_check` select only the rows where source and target diverge, `fk_integrity_check` selects orphaned `appointments.pat_id` values, and singular tests in `validation/dbt_models/tests/` fail dbt when any of those return a row. (The earlier `accepted_values: ['PASS','FAIL']` schema tests — which passed whether the status was `PASS` *or* `FAIL* — have been removed.) A failing dbt test blocks completion the same way a failed GX checkpoint does.

## Transformation Rule Contract
```json
{
  "source_table": "patient_records",
  "target_table": "patient_records",
  "source_column": "pat_st_cd",
  "target_column": "patient_status",
  "logic": "CASE WHEN pat_st_cd = 'A' THEN 'Active' WHEN pat_st_cd = 'D' THEN 'Discharged' ELSE NULL END",
  "target_type": "STRING",
  "null_handling": "Map to NULL; flag in reconciliation report.",
  "edge_cases": ["Unknown codes default to NULL", "Trim whitespace before mapping"],
  "confidence": 0.84,
  "prompt_id": "prompt-uuid-abc123",
  "human_reviewed": false,
  "review_status": "AUTO_APPROVED",
  "override_note": null,
  "reviewer_id": null,
  "reviewer_role": null
}
```
`logic` is a bare SQL expression referencing the source column by its real name. It is validated in two layers before being embedded into the SELECT that runs against Snowflake: a fast character allow-list / forbidden-keyword regex, then a `sqlglot` AST check (`_ast_validate_logic` in `migration/executor.py`) that parses the expression and rejects subqueries, table references, joins, CTEs, DML/DDL, any non-allowlisted function, and any column reference other than the declared source column. `target_type` is one of `STRING`/`NUMBER`/`DATE`/`TIMESTAMP`/`BOOLEAN`, used to resolve the Snowflake column type; it takes priority over inferring the type from the source column, so an identity-mapped `BIGINT` column typed `NUMBER` by the LLM lands as `NUMBER(38,4)` rather than preserving `NUMBER(38,0)` precision — a known minor precision tradeoff, not a correctness bug.

## Known Limitations
LLM confidence is a routing signal, not proof. Semantic ambiguity needs domain expertise. Live Snowflake/LLM credentials are required. Great Expectations APIs can differ by version and are isolated behind a validation adapter. Production deployments require organization-specific IAM, encryption, retention, networking and regulatory review.

Healthcare-specific:
- **Clinical code ambiguity**: short undocumented codes (`blood_grp_cd`, `ins_clm_st`, `alloc_st`) can look plausible to an LLM without actually being verifiable from the data alone — the AI mapper is deliberately conservative here and routes them to human review rather than guessing confidently.
- **Medication/dosage free text**: `dosage_txt` (e.g. `'BD'`, `'TDS'`, `'SOS'`) and `dur_days` (mixed `'7'` / `'7 days'` / `'one week'`) are pharmaceutical shorthand that a general-purpose LLM will often mis-normalize; these fields should be reviewed by a clinical SME, not approved on AI confidence alone, regardless of the score returned.
- **Priority/ordinal direction is not inferrable from data**: `pri_lvl` (1–5) has no documented convention for whether 1 is highest or lowest priority — this is a case where confidence should stay low structurally, not just when sample values look unclear.

Implementation:
- **Rule `logic` validation is regex + `sqlglot` AST, not a constrained DSL**: `migration/executor.py` runs the LLM-generated `logic` through a character allow-list / forbidden-keyword regex and then a `sqlglot` parse that rejects subqueries, table refs, joins, CTEs, DML/DDL, non-allowlisted functions, and foreign column references. This is materially stronger than the earlier regex-only allow-list (which let scalar subqueries through). A fully constrained transformation DSL compiled to SQL would be the production-grade endpoint; the AST approach is the pragmatic capstone choice.
- **`ai_mapper` can't always infer a target name from column evidence alone** (no target schema is given to the LLM by design, to avoid inventing undocumented business meaning): when a proposed `target_column` is empty, a known placeholder (`UNKNOWN`, `TBD`, etc.), or not a valid identifier, `agents/ai_mapper.py` falls back to the source column name rather than passing the bad value through. `migration/executor.py` additionally rejects any table where two rules would still collide on the same `target_column` after that fallback, rather than letting a "duplicate column" error reach Snowflake.
