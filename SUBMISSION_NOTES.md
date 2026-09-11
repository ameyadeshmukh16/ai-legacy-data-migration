# Submission Notes

## Operational

1. Enter your actual FDE participant ID in the portal.
2. `.env` is git-ignored and not included. Configure evaluator LLM / Snowflake / LangFuse
   credentials in a local `.env` (copy `.env.example`).
3. To run the pipeline: `docker compose up -d` (source Postgres) → `python -m seed.seed_db`
   → `python -m workflow.langgraph_orchestrator`. See `README.md` § Run.
4. The recommended way to review or drive the pipeline is the Streamlit app:
   `streamlit run app.py` (from the repo root). Its **Evidence Viewer** mode needs no
   credentials and renders the committed run + scope disclosure; **Live Run** mode drives a
   real migration. The app is a presentation layer and changes no pipeline logic — see
   `README.md` § Application.

## Evidence & scope — read this before evaluating the `evidence/` folder

### Seed capability (in the repo, inspectable)

`seed/seed_db.py` seeds **8 tables, ~106K rows total**, with `patient_records` at
**12,000 rows** and `appointments` at 15,000 — i.e. the "5+ tables / 10,000+ rows on a
primary table" requirement is met by the seed configuration. `scripts/init_db.sql` defines
the deliberately messy healthcare schema (undocumented status codes, mixed date formats,
free-text clinical fields).

### What HAS been executed live

**Two** genuine end-to-end runs are committed.

**`evidence/2026-09-11-departments-app-run/`** (`run_id=a620702f-...`, 2026-09-11) — the
**fully hardened pipeline**, driven **live through the Streamlit application** (Configuration
→ Start → pause at `human_review_gate` → Human Review form → resume → completion). Real
Postgres source, real Snowflake target, real Groq LLM calls, real dbt. It exercised
everything the earlier run did, *plus* every post-`c4f0b3d` addition: value-distribution
reconciliation (passed), GX post-extraction on the raw pre-transform extract, `sqlglot`
AST-validated transformation logic, `reviewer_id`/`reviewer_role` captured on the human
decision, explicit `review_status`, and the `run_started`/`run_completed` lifecycle events.
19-event hash-chained audit trail (independently re-verifiable per that folder's README, or
via the app's Audit Trail page). **Code version: commit `8db88b9`** (the app-layer
control-flow fixes, on top of `c4f0b3d`).

**`evidence/2026-09-06-departments-full-run/`** (`run_id=1f0fef8a-...`, 2026-09-06) — an
earlier run via the CLI (`python -m workflow.langgraph_orchestrator`), on commit `40e93dc`,
*before* the hardening round. Kept for provenance; superseded by the run above for anything
concerning the final code.

**Scale of both runs: 1 table (`departments`), 12 rows.** Scoped down to fit the free-tier
LLM rate limit available that day.

### What has NOT been executed live

- A run at 5+ table / 10,000+ row scale. This is the one remaining gap — everything else
  the final code does has now been exercised live (see above), just not yet at that scale.

**Reason:** a multi-table run needs ~20–30 minutes of uninterrupted free-tier LLM quota,
which was not available, and no paid LLM credits were on hand to substitute.

### How everything else is verified

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
  stubbed — **and** now also confirmed passing against a real Snowflake target in the
  2026-09-11 live run.

### Explicit non-claim

**No full-scale (5+ table / 10,000+ row) production migration was executed.** Both
committed `evidence/` runs are single-table (`departments`, 12 rows). The 2026-09-11 run
does, however, genuinely exercise the final hardened code end to end, live, through the
Streamlit application — it is not a small-scale stand-in for untested functionality, only
for untested *scale*.
