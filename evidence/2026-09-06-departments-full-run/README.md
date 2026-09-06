# Evidence: first genuine full pipeline run (2026-09-06)

This is the artifact set from `run_id=1f0fef8a-a433-48d7-ae50-9e6ee3b181ba`, the first
`python -m workflow.langgraph_orchestrator` execution to complete successfully end-to-end
after the post-Phase-7 P0 remediation (see `capstone_plan.md`'s "Post-Phase-7 Remediation"
section). Scoped to a single table (`TABLES_TO_MIGRATE=departments`) to fit within the
free-tier LLM rate limits available that day — the full 5-table default scope has not yet
been run live (see the plan's Verification section for what's still pending).

Real Postgres (docker-compose) source, real Snowflake target, real LLM calls (Groq
`openai/gpt-oss-120b`), real dbt execution. Nothing here is synthetic or hand-edited.

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

## What this proves

- `migration_executor` genuinely applies each rule's `logic` (see `transformation_rules.json`'s
  `TRIM(dept_name)` rule and `audit_log_snapshot.json`'s `table_loaded` event, whose `select_sql`
  field shows the actual SELECT executed against Snowflake) and renames columns
  (`dept_typ_cd` -> `department_type_code`) — not a raw copy under source names.
- `human_review_gate`'s merge-bug fix works on a real mixed batch (3 auto-cleared + 1 flagged).
- The `MemorySaver` checkpointer genuinely supports pause/resume: this run paused once for human
  review and resumed in the same process via `Command(resume=...)`.
- All three Great Expectations checkpoints ran from inside the executable graph (not standalone
  scripts) and passed against real data.
- dbt `seed`/`run`/`test` executed from `validator` via subprocess and all 10 dbt tests passed.
