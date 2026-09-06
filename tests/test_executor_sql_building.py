import pytest
from migration.executor import _build_select_sql, _validate_logic, _validate_identifier, snowflake_type, _check_unique_target_columns

def test_snowflake_type_mappings():
    assert snowflake_type("VARCHAR(80)") == "VARCHAR(80)"
    assert snowflake_type("NUMERIC(12,2)") == "NUMBER(12,2)"
    assert snowflake_type("BIGINT") == "NUMBER(38,0)"
    assert snowflake_type("TIMESTAMP") == "TIMESTAMP_NTZ"
    assert snowflake_type("totally_unknown_type") == "VARCHAR(16777216)"

def test_validate_logic_rejects_semicolon_injection():
    with pytest.raises(ValueError):
        _validate_logic("pat_st_cd = 'A'; DROP TABLE patient_records", "pat_st_cd")

def test_validate_logic_rejects_ddl_keywords():
    with pytest.raises(ValueError):
        _validate_logic("(SELECT 1); DELETE FROM x", "pat_st_cd")

def test_validate_logic_rejects_comment_injection():
    with pytest.raises(ValueError):
        _validate_logic("pat_st_cd = 'A' -- comment", "pat_st_cd")

def test_validate_logic_allows_case_expression():
    logic = "CASE WHEN pat_st_cd = 'A' THEN 'Active' ELSE NULL END"
    assert _validate_logic(logic, "pat_st_cd") == logic

def test_validate_logic_rejects_empty():
    with pytest.raises(ValueError):
        _validate_logic("", "pat_st_cd")

def test_validate_identifier_rejects_quotes_and_spaces():
    with pytest.raises(ValueError):
        _validate_identifier('bad" OR 1=1--', "target_column")

def test_validate_identifier_accepts_normal_name():
    assert _validate_identifier("patient_status", "target_column") == "patient_status"

def test_build_select_sql_produces_expected_shape():
    rules = [
        {"source_column": "pat_id", "target_column": "pat_id", "logic": "pat_id"},
        {"source_column": "pat_st_cd", "target_column": "patient_status",
         "logic": "CASE WHEN pat_st_cd = 'A' THEN 'Active' ELSE NULL END"},
    ]
    sql = _build_select_sql("patient_records", rules)
    assert 'FROM "patient_records"' in sql
    assert 'AS "pat_id"' in sql
    assert 'AS "patient_status"' in sql
    assert "CASE WHEN pat_st_cd = 'A'" in sql

def test_check_unique_target_columns_raises_on_duplicate():
    # Reproduces a real failure seen live: two low-confidence AI mappings both
    # fell back to target_column='UNKNOWN' when no target schema was supplied,
    # which previously reached Snowflake as a duplicate-column CREATE TABLE error.
    rules = [
        {"source_column": "dept_id", "target_column": "UNKNOWN"},
        {"source_column": "dept_cd", "target_column": "UNKNOWN"},
    ]
    with pytest.raises(RuntimeError):
        _check_unique_target_columns("departments", rules)

def test_check_unique_target_columns_passes_when_distinct():
    rules = [
        {"source_column": "dept_id", "target_column": "department_id"},
        {"source_column": "dept_cd", "target_column": "department_code"},
    ]
    _check_unique_target_columns("departments", rules)
