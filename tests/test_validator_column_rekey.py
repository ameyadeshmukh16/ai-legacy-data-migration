from unittest.mock import patch, MagicMock

# validation/validator.py's run_validation queries the Snowflake target using
# target_column names (since the rule-driven executor renames columns), but
# reconciliation_report.json and dbt's generate_seeds.py both expect the
# target "columns" dict to be keyed by the same names as the source "columns"
# dict (source column names) so they can be paired up by column. This
# reproduces the real live failure: dept_typ_cd was renamed to
# department_type_code, and the seed generator's `target_cols.get(col)`
# lookup by source name silently missed the renamed column's target stats.

def test_target_columns_rekeyed_to_source_names():
    from validation.validator import run_validation

    profile = {"tables": {"departments": {"columns": [
        {"name": "dept_typ_cd"},
    ]}}}
    rules = [{"source_table": "departments", "source_column": "dept_typ_cd",
              "target_column": "department_type_code"}]

    fake_source_stats = {"row_count": 12, "columns": {"dept_typ_cd": {"null_rate": 0.0, "cardinality": 4}}}
    fake_target_stats = {"row_count": 12, "columns": {"department_type_code": {"null_rate": 0.0, "cardinality": 4}}}

    with patch("validation.validator.create_engine"), \
         patch("validation.validator.settings") as mock_settings, \
         patch("validation.validator._stats", side_effect=[fake_source_stats, fake_target_stats]), \
         patch("migration.executor._snowflake_engine"), \
         patch("migration.executor.qualified_target_table", return_value='"stage"."departments_x"'), \
         patch("audit.audit_logger.AuditLogger.append"), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.write_text"):
        mock_settings.snowflake_account = "acct"
        report = run_validation(profile, "run-1", rules)

    target_cols = report["tables"]["departments"]["target"]["columns"]
    assert "dept_typ_cd" in target_cols
    assert "department_type_code" not in target_cols
