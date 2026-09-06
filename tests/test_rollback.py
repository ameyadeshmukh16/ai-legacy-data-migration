import json
import types
import pytest
import migration.executor as ex
import workflow.langgraph_orchestrator as orch


class _FakeConn:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, stmt, *a, **kw): self.sink.append(str(stmt))


class _FakeEngine:
    def __init__(self, sink): self.sink = sink
    def begin(self): return _FakeConn(self.sink)


def test_rollback_run_drops_every_run_scoped_table(monkeypatch):
    monkeypatch.setattr(ex, "settings", types.SimpleNamespace(
        snowflake_account="acct", target_schema="MIGRATION_STAGE",
        tables_to_migrate=("departments", "patient_records")))
    sink = []
    monkeypatch.setattr(ex, "_snowflake_engine", lambda: _FakeEngine(sink))

    dropped = ex.rollback_run("11112222-3333-4444-5555-666677778888")

    assert len(dropped) == 2
    joined = " ".join(sink)
    assert "DROP TABLE IF EXISTS" in joined
    assert "departments_11112222_3333_4444_5555_666677778888" in joined
    assert "patient_records_11112222_3333_4444_5555_666677778888" in joined


def test_rollback_noop_without_snowflake(monkeypatch):
    monkeypatch.setattr(ex, "settings", types.SimpleNamespace(
        snowflake_account="", target_schema="MIGRATION_STAGE", tables_to_migrate=()))
    assert ex.rollback_run("any-run-id") == []


def test_run_migration_emits_run_failed_and_rolls_back(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    audit_dir = tmp_path / "audit"; audit_dir.mkdir()
    (audit_dir / "migration_audit_log.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(orch, "audit", orch.AuditLogger(str(audit_dir / "migration_audit_log.json")))
    monkeypatch.setattr(orch, "settings", types.SimpleNamespace(tables_to_migrate=("departments",)))

    class _Boom:
        def invoke(self, *a, **kw): raise RuntimeError("validator blew up")
    monkeypatch.setattr(orch, "build_graph", lambda: _Boom())

    rolled = {"called": False}
    def _fake_rollback(rid):
        rolled["called"] = True
        return [f"departments_{rid.replace('-', '_')}"]
    monkeypatch.setattr(orch, "rollback_run", _fake_rollback)

    with pytest.raises(RuntimeError, match="validator blew up"):
        orch.run_migration("aaaa-bbbb")

    assert rolled["called"]
    events = json.loads((audit_dir / "migration_audit_log.json").read_text(encoding="utf-8"))
    evtypes = [e["event_type"] for e in events]
    assert "run_started" in evtypes
    assert "run_failed" in evtypes
    assert "run_rolled_back" in evtypes
    assert "run_completed" not in evtypes
