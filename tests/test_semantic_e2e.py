import json
import types
import pytest
from sqlalchemy import text
import validation.distribution_reconciler as dr
from migration.executor import _build_select_sql


_RULE = {
    "source_table": "pat_tmp", "source_column": "pat_st_cd",
    "target_table": "pat_tmp", "target_column": "patient_status",
    "logic": "CASE WHEN pat_st_cd = 'A' THEN 'Active' WHEN pat_st_cd = 'I' THEN 'Inactive' ELSE NULL END",
}


# ---------------------------------------------------------------------------
# Distribution reconciliation diff logic (no live Snowflake needed)
# ---------------------------------------------------------------------------

def _patch_common(monkeypatch, tmp_path, expected, actual):
    monkeypatch.chdir(tmp_path)
    audit_dir = tmp_path / "audit"; audit_dir.mkdir()
    (audit_dir / "migration_audit_log.json").write_text("[]", encoding="utf-8")
    fake_settings = types.SimpleNamespace(
        audit_log_path=str(audit_dir / "migration_audit_log.json"),
        snowflake_account="acct",
        source_db_url="postgresql://unused",
    )
    monkeypatch.setattr(dr, "settings", fake_settings)
    monkeypatch.setattr(dr, "create_engine", lambda *a, **kw: object())
    import migration.executor as ex
    monkeypatch.setattr(ex, "_snowflake_engine", lambda: object())
    monkeypatch.setattr(dr, "_source_expected_distribution", lambda eng, rule: dict(expected))
    monkeypatch.setattr(dr, "_target_actual_distribution", lambda eng, rule, rid: dict(actual))


def test_distribution_reconciliation_passes_when_buckets_align(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path,
                  expected={"Active": 100, "Inactive": 50, None: 5},
                  actual={"Active": 100, "Inactive": 50, None: 5})
    report = dr.reconcile_distributions({"tables": {}}, "run-1", [_RULE])
    assert report["passed"] is True
    assert report["checked"] == 1
    assert report["columns"][list(report["columns"])[0]]["status"] == "PASS"


def test_distribution_reconciliation_fails_on_count_drift(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path,
                  expected={"Active": 100, "Inactive": 50},
                  actual={"Active": 99, "Inactive": 50})
    report = dr.reconcile_distributions({"tables": {}}, "run-2", [_RULE])
    assert report["passed"] is False
    col = report["columns"][list(report["columns"])[0]]
    assert col["status"] == "FAIL"
    assert {"value": "Active", "expected": 100, "actual": 99} in col["mismatches"]
    saved = json.loads((tmp_path / "data" / "distribution_reconciliation_report.json").read_text())
    assert saved["passed"] is False


def test_identity_rules_are_skipped(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, expected={}, actual={})
    identity = {**_RULE, "source_column": "pat_id", "target_column": "pat_id", "logic": "pat_id"}
    report = dr.reconcile_distributions({"tables": {}}, "run-3", [identity])
    assert report["skipped"] == 1
    assert report["checked"] == 0


# ---------------------------------------------------------------------------
# Semantic execution against a real Postgres (skipped if unavailable)
# ---------------------------------------------------------------------------

def test_rule_logic_actually_transforms_values(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS pat_tmp"))
        conn.execute(text("CREATE TABLE pat_tmp (pat_st_cd VARCHAR(2))"))
        conn.execute(text(
            "INSERT INTO pat_tmp (pat_st_cd) "
            "SELECT 'A' FROM generate_series(1,100) "
            "UNION ALL SELECT 'I' FROM generate_series(1,50)"))
    try:
        select_sql = _build_select_sql("pat_tmp", [_RULE])
        with pg_engine.connect() as conn:
            rows = conn.execute(text(select_sql)).fetchall()
        vals = sorted(r[0] for r in rows)
        assert vals.count("Active") == 100
        assert vals.count("Inactive") == 50
        assert "A" not in vals and "I" not in vals

        # And the source-side expected distribution the reconciler computes:
        dist = dr._source_expected_distribution(pg_engine, _RULE)
        assert dist == {"Active": 100, "Inactive": 50}
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS pat_tmp"))
