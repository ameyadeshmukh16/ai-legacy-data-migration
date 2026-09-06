import pytest
from migration.executor import _validate_logic, _ast_validate_logic


@pytest.mark.parametrize("logic,col", [
    ("dept_id", "dept_id"),
    ("TRIM(dept_name)", "dept_name"),
    ("COALESCE(TRIM(dob), '')", "dob"),
    ("CAST(appt_st AS VARCHAR)", "appt_st"),
    ("NULLIF(TRIM(bill_st), '')", "bill_st"),
    ("CASE WHEN pat_st_cd = 'A' THEN 'Active' WHEN pat_st_cd = 'D' THEN 'Discharged' ELSE NULL END", "pat_st_cd"),
    ("CASE WHEN blood_grp_cd = 'AP' THEN 'A+' ELSE UPPER(blood_grp_cd) END", "blood_grp_cd"),
])
def test_valid_transformation_logic_accepted(logic, col):
    assert _validate_logic(logic, col) == logic


@pytest.mark.parametrize("logic,col", [
    ("(SELECT max(x) FROM other)", "dept_id"),                       # subquery
    ("dept_name || (SELECT code FROM secrets)", "dept_name"),        # embedded subquery
    ("other_col", "dept_id"),                                        # foreign column ref
    ("t.dept_id", "dept_id"),                                        # table-qualified ref
    ("pg_sleep(10)", "dept_id"),                                     # non-allowlisted / unknown func
    ("version()", "dept_id"),                                        # non-allowlisted func
    ("dept_id; DROP TABLE x", "dept_id"),                            # statement break
    ("CASE WHEN (SELECT 1) THEN 'x' END", "dept_id"),                # subquery inside CASE
])
def test_unsafe_transformation_logic_rejected(logic, col):
    with pytest.raises(ValueError):
        _validate_logic(logic, col)


def test_ast_validator_reports_the_offending_construct():
    with pytest.raises(ValueError, match="Subquery"):
        _ast_validate_logic("(SELECT 1)", "dept_id")
    with pytest.raises(ValueError, match="foreign column"):
        _ast_validate_logic("some_other_col", "dept_id")
