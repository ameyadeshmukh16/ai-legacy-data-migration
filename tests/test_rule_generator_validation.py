import pytest
from agents.rule_generator import validate_rules_before_execution

def test_validate_rules_before_execution_mixed_batch_raises_on_bad_rule():
    rules = [
        {"source_column":"a","target_column":"a","confidence":0.95,
         "review_status":"AUTO_APPROVED","override_note":None},
        {"source_column":"b","target_column":"b","confidence":0.4,
         "review_status":"AUTO_APPROVED","override_note":None},
    ]
    with pytest.raises(PermissionError):
        validate_rules_before_execution(rules)

def test_validate_rules_before_execution_all_high_confidence_passes():
    rules = [
        {"source_column":"a","target_column":"a","confidence":0.95,
         "review_status":"AUTO_APPROVED","override_note":None},
        {"source_column":"b","target_column":"b","confidence":0.99,
         "review_status":"AUTO_APPROVED","override_note":None},
    ]
    validate_rules_before_execution(rules)
