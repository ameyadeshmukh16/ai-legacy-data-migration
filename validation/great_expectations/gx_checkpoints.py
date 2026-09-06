import json
from pathlib import Path
import pandas as pd
import great_expectations as gx
from great_expectations import expectations as gxe
from sqlalchemy import create_engine, text
from config.settings import settings

# Known code-column domains, taken from scripts/init_db.sql and seed/seed_db.py.
# Columns not listed here are not domain-checked (free text / undocumented codes).
KNOWN_VALUE_SETS = {
    "pat_st_cd": ["A", "D", "I", "S"],
    "appt_typ_cd": ["NEW", "FLW", "EMR", "REV"],
    "bill_st": ["PD", "UP", "PP", "WO"],
    "pay_mthd_cd": ["CSH", "INS", "CRD", "UPI"],
    "ins_clm_st": ["PN", "AP", "RJ", "PP"],
    "gndr_cd": ["M", "F", "U"],
    "blood_grp_cd": ["AP", "AN", "BP", "BN", "OP", "ON", "ABP", "ABN"],
    "dept_typ_cd": ["IPD", "OPD", "ICU", "ER", "SRG"],
    "status_cd": ["A", "I"],
    "rte_cd": ["OR", "IV", "IM", "SC"],
    "tst_st_cd": ["OR", "PR", "CM", "CN"],
    "urgcy_cd": ["ROU", "URG", "STT"],
    "alloc_st": ["A", "V", "M", "B"],
}

# Target-side value sets for known post-transformation columns. Populated as rules
# are authored/observed producing these target column names; a rule-driven target
# column not listed here simply skips the domain check rather than failing it.
TARGET_VALUE_SETS = {
    "patient_status": ["Active", "Discharged", "Inactive", "Suspended"],
    "gender": ["Male", "Female", "Unknown"],
    "blood_group": ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
    "appointment_type": ["New", "Follow-up", "Emergency", "Review"],
}

_PK_COLUMN = {
    "departments": "dept_id", "patient_records": "pat_id", "doctors": "doctor_id",
    "appointments": "appt_id", "billing": "bill_id", "med_records": "med_record_id",
    "lab_orders": "lab_order_id", "ward_alloc": "ward_alloc_id",
}

_gx_context = None

def _context():
    global _gx_context
    if _gx_context is None:
        _gx_context = gx.get_context(mode="ephemeral")
    return _gx_context


def _batch(df, name):
    ctx = _context()
    ds_name = f"ds_{name}"
    ds = ctx.data_sources.get(ds_name) if ds_name in ctx.data_sources.all() else ctx.data_sources.add_pandas(ds_name)
    asset = ds.add_dataframe_asset(name=f"asset_{name}")
    batch_def = asset.add_batch_definition_whole_dataframe(f"batchdef_{name}")
    return batch_def.get_batch(batch_parameters={"dataframe": df})


def _validate(df, table, expectations):
    batch = _batch(df, f"{table}_{id(df)}")
    results = []
    passed = True
    for exp in expectations:
        r = batch.validate(exp)
        ok = bool(r.success)
        passed = passed and ok
        results.append({
            "expectation": type(exp).__name__,
            "kwargs": {k: v for k, v in exp.configuration.kwargs.items() if k != "batch_id"},
            "success": ok,
            "result": {k: v for k, v in r.result.items() if k != "partial_unexpected_index_list"},
        })
    return passed, results


def _load_df(engine, table, columns):
    cols = ", ".join(f'"{c}"' for c in columns)
    with engine.connect() as conn:
        return pd.read_sql(text(f'SELECT {cols} FROM "{table}"'), conn)


def run_source_baseline(profile):
    engine = create_engine(settings.source_db_url)
    report = {"checkpoint": "source_baseline", "tables": {}, "passed": True}
    for table, meta in profile["tables"].items():
        columns = [c["name"] for c in meta["columns"]]
        df = _load_df(engine, table, columns)
        seeded_count = len(df)
        expectations = [gxe.ExpectTableRowCountToBeBetween(min_value=int(seeded_count * 0.95))]
        pk = _PK_COLUMN.get(table)
        if pk and pk in df.columns:
            expectations.append(gxe.ExpectColumnValuesToNotBeNull(column=pk))
            expectations.append(gxe.ExpectColumnValuesToBeUnique(column=pk))
        for col, allowed in KNOWN_VALUE_SETS.items():
            if col in df.columns:
                expectations.append(gxe.ExpectColumnValuesToBeInSet(column=col, value_set=allowed, mostly=0.98))
        passed, results = _validate(df, table, expectations)
        report["tables"][table] = {"row_count": seeded_count, "passed": passed, "expectations": results}
        report["passed"] = report["passed"] and passed
    _write(report, "source_baseline")
    if not report["passed"]:
        raise RuntimeError("Great Expectations source_baseline checkpoint failed")
    return report


def run_post_extraction(extracted_data, baseline_report, expected_columns=None):
    """Guards the extraction boundary: raw extracted rows, raw column names,
    before any transformation rule is applied. expected_columns maps table ->
    the list of source columns the profile says should have been extracted."""
    expected_columns = expected_columns or {}
    report = {"checkpoint": "post_extraction", "tables": {}, "passed": True}
    for table, rows in extracted_data.items():
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        baseline = baseline_report["tables"].get(table, {})
        baseline_count = baseline.get("row_count")
        row_count_match = baseline_count is None or len(df) == baseline_count
        expected = set(expected_columns.get(table, []))
        actual = set(df.columns)
        dropped = sorted(expected - actual)
        added = sorted(actual - expected)
        no_columns_dropped = not dropped and not added
        report["tables"][table] = {
            "row_count": len(df),
            "baseline_row_count": baseline_count,
            "row_count_match": row_count_match,
            "no_columns_dropped": no_columns_dropped,
            "dropped_columns": dropped,
            "unexpected_columns": added,
            "passed": row_count_match and no_columns_dropped,
        }
        report["passed"] = report["passed"] and row_count_match and no_columns_dropped
    _write(report, "post_extraction")
    if not report["passed"]:
        raise RuntimeError("Great Expectations post_extraction checkpoint failed")
    return report


def run_post_load(profile, run_id, baseline_report, rules):
    from migration.executor import _snowflake_engine, qualified_target_table
    target = _snowflake_engine()
    report = {"checkpoint": "post_load", "tables": {}, "passed": True}
    rules_by_table = {}
    for r in rules:
        rules_by_table.setdefault(r["source_table"], []).append(r)

    for table, meta in profile["tables"].items():
        table_rules = rules_by_table.get(table, [])
        target_columns = [r["target_column"] for r in table_rules]
        qualified_table = qualified_target_table(table, run_id)
        try:
            cols = ", ".join(f'"{c}"' for c in target_columns)
            with target.connect() as conn:
                df = pd.read_sql(text(f'SELECT {cols} FROM {qualified_table}'), conn)
        except Exception as e:
            report["tables"][table] = {"error": str(e), "passed": False}
            report["passed"] = False
            continue
        baseline = baseline_report["tables"].get(table, {})
        baseline_count = baseline.get("row_count")
        expectations = [gxe.ExpectTableRowCountToEqual(value=baseline_count)] if baseline_count is not None else []
        for col, allowed in TARGET_VALUE_SETS.items():
            if col in df.columns:
                expectations.append(gxe.ExpectColumnValuesToBeInSet(column=col, value_set=allowed, mostly=0.98))
        passed, results = _validate(df, table, expectations) if expectations else (True, [])
        null_rate_ok = True
        null_rate_details = {}
        for r in table_rules:
            target_col = r["target_column"]
            if target_col not in df.columns:
                continue
            target_null_rate = float(df[target_col].isna().mean())
            source_col_meta = next((c for c in meta["columns"] if c["name"] == r["source_column"]), None)
            source_null_rate = source_col_meta["null_rate"] if source_col_meta else None
            if source_null_rate is not None:
                within_tolerance = bool(abs(target_null_rate - source_null_rate) <= 0.02)
                null_rate_ok = null_rate_ok and within_tolerance
                null_rate_details[target_col] = {"source": source_null_rate, "target": target_null_rate, "within_tolerance": within_tolerance}
        table_passed = bool(passed and null_rate_ok)
        report["tables"][table] = {
            "row_count": len(df), "baseline_row_count": baseline_count,
            "passed": table_passed, "expectations": results, "null_rate_check": null_rate_details,
        }
        report["passed"] = bool(report["passed"] and table_passed)
    _write(report, "post_load")
    if not report["passed"]:
        raise RuntimeError("Great Expectations post_load checkpoint failed")
    return report


def _write(report, checkpoint):
    Path("data").mkdir(exist_ok=True)
    Path(f"data/gx_results_{checkpoint}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
