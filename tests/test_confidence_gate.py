import pytest
from agents.rule_generator import validate_rules_before_execution

def _rule(confidence,review_status="AUTO_APPROVED",override_note=None):
    return {"source_column":"pat_st_cd","target_column":"patient_status",
            "confidence":confidence,"review_status":review_status,"override_note":override_note}

def test_low_confidence_without_review_raises():
    with pytest.raises(PermissionError):
        validate_rules_before_execution([_rule(0.65)])

def test_low_confidence_reviewed_without_note_raises():
    with pytest.raises(PermissionError):
        validate_rules_before_execution([_rule(0.65,review_status="HUMAN_APPROVED",override_note=None)])

def test_low_confidence_approved_with_note_passes():
    validate_rules_before_execution([_rule(0.65,review_status="HUMAN_APPROVED",override_note="Confirmed.")])

def test_auto_approved_flag_does_not_satisfy_low_confidence_gate():
    # review_status must be HUMAN_APPROVED - an AUTO_APPROVED low-conf rule with a
    # note is still rejected (guards against the old human_reviewed=True auto-clear).
    with pytest.raises(PermissionError):
        validate_rules_before_execution([_rule(0.65,review_status="AUTO_APPROVED",override_note="Auto note")])

def test_high_confidence_passes_without_review():
    validate_rules_before_execution([_rule(0.95)])
