"""Rule-aware value-distribution reconciliation.

Row-count and null-rate checks prove "we loaded the same number of rows". They
do NOT prove a semantic transformation preserved meaning: source 'A' (5000 rows)
mapping to target 'Active' (5000 rows) needs the value-level counts to line up.

For each non-identity transformation rule this module:
  1. computes the EXPECTED target distribution by running the rule's own logic as
     a GROUP BY against the immutable source table, and
  2. computes the ACTUAL target distribution from the loaded Snowflake table,
then asserts every value bucket (NULL included) matches exactly. Because both
sides derive from the same source rows through the same deterministic expression
(AST-validated to forbid non-determinism), exact-count equality is the correct
assertion - no tolerance.
"""
import json
from pathlib import Path
from sqlalchemy import create_engine, text
from config.settings import settings
from audit.audit_logger import AuditLogger
from migration.executor import _validate_logic, _validate_identifier, qualified_target_table


def _is_identity(rule):
    return rule["logic"].strip().strip('"').lower() == rule["source_column"].lower()


def _source_expected_distribution(engine, rule):
    logic = _validate_logic(rule["logic"], rule["source_column"])
    table = _validate_identifier(rule["source_table"], "source_table")
    sql = f'SELECT ({logic}) AS tgt_val, COUNT(*) AS n FROM "{table}" GROUP BY 1'
    with engine.connect() as conn:
        return {(_norm(v)): int(n) for v, n in conn.execute(text(sql)).fetchall()}


def _target_actual_distribution(engine, rule, run_id):
    col = _validate_identifier(rule["target_column"], "target_column")
    tt = qualified_target_table(rule["source_table"], run_id)
    sql = f'SELECT "{col}" AS tgt_val, COUNT(*) AS n FROM {tt} GROUP BY 1'
    with engine.connect() as conn:
        return {(_norm(v)): int(n) for v, n in conn.execute(text(sql)).fetchall()}


def _norm(v):
    # Align NULL/None and numeric/string representations across the two engines.
    if v is None:
        return None
    return str(v)


def reconcile_distributions(profile, run_id, rules):
    source = create_engine(settings.source_db_url)
    report = {"run_id": run_id, "columns": {}, "passed": True, "checked": 0, "skipped": 0}

    if not settings.snowflake_account:
        report["passed"] = False
        report["error"] = "SNOWFLAKE_ACCOUNT not configured; cannot read target distributions."
        _persist(report, run_id, 0, 0)
        return report

    from migration.executor import _snowflake_engine
    target = _snowflake_engine()

    for rule in rules:
        key = f'{rule["source_table"]}.{rule["source_column"]} -> {rule["target_column"]}'
        if _is_identity(rule):
            report["skipped"] += 1
            report["columns"][key] = {"status": "SKIPPED_IDENTITY"}
            continue
        try:
            expected = _source_expected_distribution(source, rule)
            actual = _target_actual_distribution(target, rule, run_id)
        except Exception as e:
            report["passed"] = False
            report["columns"][key] = {"status": "ERROR", "error": str(e)}
            continue

        diffs = []
        for val in sorted(set(expected) | set(actual), key=lambda x: (x is None, x)):
            e, a = expected.get(val, 0), actual.get(val, 0)
            if e != a:
                diffs.append({"value": val, "expected": e, "actual": a})
        passed = not diffs
        report["checked"] += 1
        report["passed"] = report["passed"] and passed
        report["columns"][key] = {
            "status": "PASS" if passed else "FAIL",
            "expected_distribution": {("<NULL>" if k is None else k): v for k, v in expected.items()},
            "actual_distribution": {("<NULL>" if k is None else k): v for k, v in actual.items()},
            "mismatches": [{**d, "value": "<NULL>" if d["value"] is None else d["value"]} for d in diffs],
        }

    _persist(report, run_id, report["checked"], report["skipped"])
    return report


def _persist(report, run_id, checked, skipped):
    Path("data").mkdir(exist_ok=True)
    Path("data/distribution_reconciliation_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    AuditLogger(settings.audit_log_path).append(
        run_id, "distribution_reconciliation_completed",
        {"passed": report["passed"], "columns_checked": checked, "columns_skipped": skipped})
