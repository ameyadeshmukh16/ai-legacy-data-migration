# Evidence: first genuine full pipeline run (2026-09-06)

This is the artifact set from `run_id=1f0fef8a-a433-48d7-ae50-9e6ee3b181ba`, the first
`python -m workflow.langgraph_orchestrator` execution to complete successfully end-to-end
after the post-Phase-7 P0 remediation (see `capstone_plan.md`'s "Post-Phase-7 Remediation"
section). Scoped to a single table (`TABLES_TO_MIGRATE=departments`, 12 rows) to fit within
the free-tier LLM rate limits available that day.

Real Postgres (docker-compose) source, real Snowflake target, real LLM calls (Groq
`openai/gpt-oss-120b`), real dbt execution. Nothing here is synthetic or hand-edited.

## Version note — READ THIS BEFORE INTERPRETING THESE ARTIFACTS

This evidence was captured on commit **`40e93dc`** (2026-09-06), *before* the final
hardening round (**`c4f0b3d`**, "Harden validation layer"). It is a genuine end-to-end
execution of the pipeline **as it stood then** — it is **not** output of the final code,
and is not presented as such.

The final code additionally performs, none of which is reflected in the JSON files here:

- **Value-distribution reconciliation** (`validation/distribution_reconciler.py`) — replays
  each non-identity rule's `logic` as a `GROUP BY` against the source and matches every
  value bucket against the loaded Snowflake target; blocks on mismatch.
- **GX post-extraction on raw pre-transform data** with a real column-drop check
  (`dropped_columns` / `unexpected_columns` set comparison) instead of a hardcoded
  `no_columns_dropped: true`.
- **`sqlglot` AST validation** of every transformation `logic` (rejects subqueries, table
  refs, joins, CTEs, DML/DDL, foreign column refs, non-allowlisted functions).
- **Reviewer identity** — `reviewer_id` / `reviewer_role` required on every human decision
  and persisted into the approved mapping, the `human_mapping_approved` audit event, and
  the LangFuse score; explicit `review_status` (`AUTO_APPROVED` / `HUMAN_APPROVED` /
  `HUMAN_REJECTED`) with `human_reviewed=false` on the auto path.
- **Run lifecycle + rollback** — `run_started` / `run_completed` / `run_failed` /
  `run_rolled_back` audit events; on any failure the run's `<table>_<run_id>` Snowflake
  tables are dropped automatically.
- **dbt zero-row / singular tests** — the old `accepted_values: ['PASS','FAIL']` schema
  tests (which passed whether the row said PASS *or* FAIL) are gone; a reconciliation
  mismatch now actually fails `dbt test`.

These additions are covered by automated tests — `tests/test_sql_ast_validation.py`,
`tests/test_rollback.py`, `tests/test_semantic_e2e.py` (incl. a live-Postgres test
executing `A -> Active` / `I -> Inactive` through the real rule pipeline), and updates to
the HITL / rule-generator tests (53 tests total; see `evidence/pytest-final.txt`). They
were **not** re-executed as a committed live run because the free-tier LLM quota needed for
a multi-table run was unavailable. See `SUBMISSION_NOTES.md` for the full scope disclosure.

## Files

- `schema_profile.json` — `agents/schema_profiler.py`'s output for the `departments` table.
- `ai_mappings.json` — all 4 raw AI mapping suggestions from `agents/ai_mapper.py`.
- `human_review_queue.json` — the 1 mapping (`dept_name`, confidence 0.3) that required human review.
- `approved_mappings.json` — all 4 mappings after `human_review_gate` (3 auto-cleared, 1 human-approved).
- `transformation_rules.json` — the 4 `TransformationRule`s from `agents/rule_generator.py`, including
  the `TRIM(dept_name)` transformation and the `dept_typ_cd` -> `department_type_code` rename.
- `gx_results_source_baseline.json` — Great Expectations source-baseline checkpoint (passed).
- `gx_results_post_extraction.json` — Great Expectations post-extraction checkpoint (passed).
- `gx_results_post_load.json` — Great Expectations post-load checkpoint against the real
  Snowflake target (passed).
- `reconciliation_report.json` — `validation/validator.py`'s source-vs-target row count/null-rate
  comparison (passed, `row_count_match: true`).
- `target_data_dictionary.md` — `agents/doc_generator.py`'s generated data dictionary.
- `audit_log_snapshot.json` — a point-in-time copy of `audit/migration_audit_log.json` as it stood
  right after this run (16 events). The live file at `audit/migration_audit_log.json` keeps
  accumulating events from later runs on top of this same hash chain; this snapshot preserves
  exactly what this specific run produced for reference.

## Independently re-verifying the hash chain

```python
import json, hashlib
events = json.load(open("evidence/2026-09-06-departments-full-run/audit_log_snapshot.json"))
prev = "GENESIS"
for e in events:
    assert e["previous_hash"] == prev
    canonical = json.dumps({k: v for k, v in e.items() if k != "hash"}, sort_keys=True, separators=(",", ":"))
    assert e["hash"] == hashlib.sha256((prev + canonical).encode()).hexdigest()
    prev = e["hash"]
print(f"Hash chain verified intact across all {len(events)} events.")
```

## What this run proves (as of commit `40e93dc`)

- `migration_executor` genuinely applies each rule's `logic` (see `transformation_rules.json`'s
  `TRIM(dept_name)` rule and `audit_log_snapshot.json`'s `table_loaded` event, whose `select_sql`
  field shows the actual SELECT executed against Snowflake) and renames columns
  (`dept_typ_cd` -> `department_type_code`) — not a raw copy under source names.
- `human_review_gate`'s merge-bug fix works on a real mixed batch (3 auto-cleared + 1 flagged).
- The `MemorySaver` checkpointer genuinely supports pause/resume: this run paused once for human
  review and resumed in the same process via `Command(resume=...)`.
- All three Great Expectations checkpoints ran from inside the executable graph (not standalone
  scripts) and passed against real data.
- dbt `seed`/`run`/`test` executed from `validator` via subprocess and completed; the dbt test
  set has since been rewritten (see the Version note above), so the specific count here is
  historical.

For what the *current* code does beyond this, and how it is verified, see the Version note
above and `SUBMISSION_NOTES.md`.
