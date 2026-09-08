# Submission Notes

## Operational

1. Enter your actual FDE participant ID in the portal.
2. `.env` is git-ignored and not included. Configure evaluator LLM / Snowflake / LangFuse
   credentials in a local `.env` (copy `.env.example`).
3. To run the pipeline: `docker compose up -d` (source Postgres) → `python -m seed.seed_db`
   → `python -m workflow.langgraph_orchestrator`. See `README.md` § Run.

## Evidence & scope — read this before evaluating the `evidence/` folder

### Seed capability (in the repo, inspectable)

`seed/seed_db.py` seeds **8 tables, ~106K rows total**, with `patient_records` at
**12,000 rows** and `appointments` at 15,000 — i.e. the "5+ tables / 10,000+ rows on a
primary table" requirement is met by the seed configuration. `scripts/init_db.sql` defines
the deliberately messy healthcare schema (undocumented status codes, mixed date formats,
free-text clinical fields).

### What HAS been executed live

One genuine end-to-end run is committed: `evidence/2026-09-06-departments-full-run/`
(`run_id=1f0fef8a-...`, 2026-09-06). Real Postgres source, real Snowflake target, real Groq
LLM calls, real dbt. It exercised: schema profiling → GX source baseline → AI mapping →
confidence gate → HITL pause/resume via `Command(resume=...)` → deterministic rule
generation → rule-driven execution into Snowflake (`TRIM(dept_name)`, `dept_typ_cd` →
`department_type_code` rename, verified in the real target table) → all 3 GX checkpoints →
reconciliation → dbt seed/run/test → data-dictionary generation → 16-event hash-chained
audit log (chain independently re-verifiable with the snippet in that folder's README).

**Scale of that run: 1 table (`departments`), 12 rows.** It was scoped down to fit the
free-tier LLM rate limit available that day.

**Code version of that run: commit `40e93dc`** — *before* the final hardening round
(`c4f0b3d`).

### What has NOT been executed live

- A run at 5+ table / 10,000+ row scale.
- Any run on the final hardened code (`c4f0b3d`), which added: value-distribution
  reconciliation, GX post-extraction on raw pre-transform data with a real column-drop
  check, `sqlglot` AST validation of transformation logic, `reviewer_id`/`reviewer_role` on
  human decisions, explicit `review_status`, and `run_started`/`run_completed`/`run_failed`/
  `run_rolled_back` lifecycle events with automatic rollback of run-scoped Snowflake tables.

**Reason:** a multi-table run needs ~20–30 minutes of uninterrupted free-tier LLM quota,
which was not available, and no paid LLM credits were on hand to substitute.

### How the un-re-run changes are verified instead

- **`pytest` — 53 tests, all passing** (`evidence/pytest-final.txt`, captured in the
  project venv). New/changed coverage: `tests/test_sql_ast_validation.py` (16),
  `tests/test_rollback.py` (3), `tests/test_semantic_e2e.py` (4 — including a
  **live-Postgres** test that executes `A -> Active` / `I -> Inactive` through the real
  `_build_select_sql` path and asserts the transformed values), plus updates to
  `tests/test_human_review_gate.py`, `tests/test_confidence_gate.py`,
  `tests/test_rule_generator_validation.py` for reviewer identity and `review_status`.
- **Clean-venv install check** — a fresh `python -m venv` + `pip install -r requirements.txt`
  imports `config.llm_factory` and `sqlglot` with no `ModuleNotFoundError`.
- **dbt project re-parses** and the 3 new singular tests
  (`assert_row_counts_match`, `assert_null_rates_match`, `assert_no_orphan_fks`) register;
  the vacuous `accepted_values` tests are gone.
- Distribution-reconciler diff logic is unit-tested for both the passing and the
  count-drift-FAIL path (`tests/test_semantic_e2e.py`), with the Snowflake-side query
  stubbed.

### Explicit non-claim

**No full-scale production migration was executed. Do not read the `evidence/` folder as a
5-table / 10K-row run, and do not read it as output of the final code.** It is a genuine
small-scale end-to-end execution of an earlier revision; the delta to the final code is
covered by the automated tests listed above.
