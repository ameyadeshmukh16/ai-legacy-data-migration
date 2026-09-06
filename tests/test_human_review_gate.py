import pytest
import workflow.langgraph_orchestrator as orch

_AUTO = orch._AUTO_NOTE

def _setup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path); (tmp_path / "data").mkdir()
    audit_dir = tmp_path / "audit"; audit_dir.mkdir()
    (audit_dir / "migration_audit_log.json").write_text("[]", encoding="utf-8")

def test_all_auto_cleared_no_interrupt_needed(monkeypatch, tmp_path):
    mappings = [{"source_table":"t","source_column":"a","target_table":"t","target_column":"a",
                 "confidence":0.95,"reasoning":"clear"}]
    def _boom(*a, **kw): raise AssertionError("interrupt() should not be called")
    monkeypatch.setattr(orch, "interrupt", _boom)
    _setup(monkeypatch, tmp_path)
    result = orch.human_review_gate({"run_id":"test","mappings":mappings})
    m = result["approved_mappings"][0]
    assert m["override_note"] == _AUTO
    assert m["review_status"] == "AUTO_APPROVED"
    assert m["human_reviewed"] is False

def test_mixed_flagged_and_clear_only_requires_flagged_decision(monkeypatch, tmp_path):
    mappings = [
        {"source_table":"t","source_column":"clear_col","target_table":"t","target_column":"clear_col",
         "confidence":0.95,"reasoning":"clear"},
        {"source_table":"t","source_column":"flagged_col","target_table":"t","target_column":"flagged_col",
         "confidence":0.5,"reasoning":"unclear"},
    ]
    # Only the flagged mapping (index 1) gets a decision supplied to interrupt()'s resume -
    # this is the exact scenario that triggers the original bug (index 0 missing from `by`).
    monkeypatch.setattr(orch, "interrupt", lambda payload: [
        {"mapping_index": 1, "decision": "approve", "override_note": "Confirmed by reviewer.",
         "reviewer_id": "reviewer-001", "reviewer_role": "data_sme"}
    ])
    monkeypatch.setattr(orch, "score_human_review_decision", lambda *a, **kw: None)
    _setup(monkeypatch, tmp_path)
    result = orch.human_review_gate({"run_id":"test","mappings":mappings})
    approved = result["approved_mappings"]
    assert approved[0]["override_note"] == _AUTO
    assert approved[0]["review_status"] == "AUTO_APPROVED"
    assert approved[1]["override_note"] == "Confirmed by reviewer."
    assert approved[1]["review_status"] == "HUMAN_APPROVED"
    assert approved[1]["human_reviewed"] is True
    assert approved[1]["reviewer_id"] == "reviewer-001"
    assert approved[1]["reviewer_role"] == "data_sme"

def test_rejected_flagged_mapping_raises(monkeypatch, tmp_path):
    mappings = [{"source_table":"t","source_column":"c","target_table":"t","target_column":"c",
                 "confidence":0.4,"reasoning":"unclear"}]
    monkeypatch.setattr(orch, "interrupt", lambda payload: [
        {"mapping_index": 0, "decision": "reject", "override_note": None,
         "reviewer_id": "reviewer-001", "reviewer_role": "data_sme"}
    ])
    _setup(monkeypatch, tmp_path)
    with pytest.raises(PermissionError):
        orch.human_review_gate({"run_id":"test","mappings":mappings})

def test_missing_decision_for_flagged_mapping_raises(monkeypatch, tmp_path):
    mappings = [{"source_table":"t","source_column":"c","target_table":"t","target_column":"c",
                 "confidence":0.4,"reasoning":"unclear"}]
    monkeypatch.setattr(orch, "interrupt", lambda payload: [])  # no decisions at all
    _setup(monkeypatch, tmp_path)
    with pytest.raises(PermissionError):
        orch.human_review_gate({"run_id":"test","mappings":mappings})

def test_missing_reviewer_identity_raises(monkeypatch, tmp_path):
    mappings = [{"source_table":"t","source_column":"c","target_table":"t","target_column":"c",
                 "confidence":0.4,"reasoning":"unclear"}]
    monkeypatch.setattr(orch, "interrupt", lambda payload: [
        {"mapping_index": 0, "decision": "approve", "override_note": "Confirmed."}
    ])
    _setup(monkeypatch, tmp_path)
    with pytest.raises(PermissionError):
        orch.human_review_gate({"run_id":"test","mappings":mappings})
