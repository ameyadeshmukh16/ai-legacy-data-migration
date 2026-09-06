import pytest
from agents.rule_generator import validate_rules_before_execution

def _rule(confidence,human_reviewed=False,override_note=None):
    return {"source_column":"pat_st_cd","target_column":"patient_status",
            "confidence":confidence,"human_reviewed":human_reviewed,"override_note":override_note}

def test_low_confidence_without_review_raises():
    with pytest.raises(PermissionError):
        validate_rules_before_execution([_rule(0.65)])

def test_low_confidence_reviewed_without_note_raises():
    with pytest.raises(PermissionError):
        validate_rules_before_execution([_rule(0.65,human_reviewed=True,override_note=None)])

def test_low_confidence_approved_with_note_passes():
    validate_rules_before_execution([_rule(0.65,human_reviewed=True,override_note="Confirmed.")])

def test_high_confidence_passes_without_review():
    validate_rules_before_execution([_rule(0.95)])
