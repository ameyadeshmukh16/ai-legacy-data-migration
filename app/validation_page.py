"""Validation Dashboard — the validation-gated architecture, made visible.

Reads the GX / reconciliation / distribution / dbt artifacts and shows each gate
as pass/fail. Any failure => the migration is BLOCKED (the pipeline raises and
rolls back).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app._common import EVIDENCE_DIR, load_audit_events, load_json, section_missing, status_pill


def _gx_passed(base_dir, fname):
    d = load_json(base_dir, fname)
    if d is None:
        return None, None
    return bool(d.get("passed")), d


def _audit_events(ctx):
    if ctx.get("evidence_mode"):
        return load_json(EVIDENCE_DIR, "audit_log_snapshot.json") or []
    return load_audit_events(ctx.get("run_id"))


def _dbt_passed(ctx):
    """dbt result isn't written to data/; it lives in the run's final state and
    the audit log. Treat a `dbt_validation_completed` audit event as the signal
    (the dbt runner raises on failure, so its presence == pass)."""
    result = (ctx.get("service_status") or {}).get("result") or {}
    if "dbt_log" in result:
        return True, result["dbt_log"]
    events = _audit_events(ctx)
    if any(e.get("event_type") == "dbt_validation_completed" for e in events):
        return True, None
    if any(e.get("event_type") == "run_failed" for e in events):
        return False, None
    return None, None


def render(ctx) -> None:
    st.header("Validation Dashboard")
    st.caption(
        "Every gate must pass. A single failure blocks completion — the pipeline raises "
        "and the run's Snowflake tables are rolled back."
    )
    base = ctx["base_dir"]

    baseline_ok, _ = _gx_passed(base, "gx_results_source_baseline.json")
    postext = load_json(base, "gx_results_post_extraction.json")
    postext_ok = None if postext is None else bool(postext.get("passed"))
    postload = load_json(base, "gx_results_post_load.json")
    postload_ok = None if postload is None else bool(postload.get("passed"))

    recon = load_json(base, "reconciliation_report.json")
    recon_ok = None if recon is None else bool(recon.get("passed"))
    # null-rate lives inside gx post_load's per-table null_rate_check
    null_ok = None
    if postload:
        checks = []
        for t in postload.get("tables", {}).values():
            for c in (t.get("null_rate_check") or {}).values():
                checks.append(bool(c.get("within_tolerance")))
        null_ok = all(checks) if checks else None

    dist = load_json(base, "distribution_reconciliation_report.json")
    dist_ok = None if dist is None else bool(dist.get("passed"))

    # FK integrity: dbt's fk_integrity_check zero-row model. No standalone artifact;
    # surface it from the distribution/recon presence + dbt outcome.
    dbt_ok, dbt_log = _dbt_passed(ctx)
    fk_ok = dbt_ok  # fk_integrity_check runs inside the same dbt test invocation

    gates = [
        ("Source Baseline (GX)", baseline_ok),
        ("Post-Extraction (GX, raw rows)", postext_ok),
        ("Post-Load (GX, Snowflake)", postload_ok),
        ("Row-Count Reconciliation", recon_ok),
        ("Null-Rate (±2%)", null_ok),
        ("Value-Distribution Reconciliation", dist_ok),
        ("Foreign-Key Integrity (dbt)", fk_ok),
        ("dbt Tests", dbt_ok),
    ]

    any_known = any(v is not None for _, v in gates)
    if not any_known:
        section_missing("No validation artifacts yet. Run the pipeline through the `validator` stage.")
        return

    any_fail = any(v is False for _, v in gates)
    known = [v for _, v in gates if v is not None]
    if any_fail:
        st.error("MIGRATION BLOCKED — at least one validation gate failed.")
    elif ctx.get("evidence_mode") and all(v is True for v in known):
        st.success(
            "Every gate captured in this run passed. Gates marked *n/a* "
            "(distribution reconciliation, and the dbt FK-integrity zero-row test) were "
            "added after this evidence run — see **Evidence & Scope**."
        )
    elif all(v is True for _, v in gates):
        st.success("All validation gates passed.")
    else:
        st.warning("Validation in progress / partial results.")

    rows_html = "".join(
        f"<tr><td style='padding:6px 12px'>{name}</td>"
        f"<td style='padding:6px 12px'>{status_pill(v)}</td></tr>"
        for name, v in gates
    )
    st.markdown(
        f"<table style='border-collapse:collapse'>{rows_html}</table>",
        unsafe_allow_html=True,
    )

    if dist and dist.get("columns"):
        st.subheader("Value-distribution detail")
        for key, d in dist["columns"].items():
            with st.expander(f"{key}  —  {d.get('status')}"):
                if d.get("status") == "SKIPPED_IDENTITY":
                    st.caption("Identity pass-through; covered by row-count + null-rate.")
                    continue
                exp = d.get("expected_distribution") or {}
                act = d.get("actual_distribution") or {}
                allk = sorted(set(exp) | set(act))
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"value": k, "expected": exp.get(k, 0), "actual": act.get(k, 0)}
                            for k in allk
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
                if d.get("mismatches"):
                    st.error(f"Mismatches: {d['mismatches']}")

    if recon and recon.get("tables"):
        st.subheader("Reconciliation detail")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "table": t,
                        "source rows": v.get("source", {}).get("row_count"),
                        "target rows": v.get("target", {}).get("row_count"),
                        "match": v.get("row_count_match"),
                        "error": v.get("error", ""),
                    }
                    for t, v in recon["tables"].items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )

    if isinstance(dbt_log, dict):
        with st.expander("dbt output"):
            for step, info in dbt_log.items():
                st.markdown(f"**dbt {step}** — exit {info.get('returncode')}")
                if info.get("stdout"):
                    st.code(info["stdout"][-3000:], language=None)
