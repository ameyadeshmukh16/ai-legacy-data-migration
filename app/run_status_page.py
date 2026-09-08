"""Run Status — per-stage progress, table-load detail, failure/rollback banner."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from app._common import load_audit_events, section_missing
from services.workflow_service import NODE_SEQUENCE

_LABELS = {
    "schema_profiler": "Schema profiling + GX source baseline",
    "ai_mapper": "AI column mapping",
    "human_review_gate": "Confidence gate + human review",
    "rule_generator": "Deterministic rule generation + lineage",
    "migration_executor": "Extract → post-extraction GX → transform → load",
    "validator": "Post-load GX · reconciliation · distribution · dbt",
    "doc_generator": "Target data dictionary",
}


def render(ctx) -> None:
    st.header("Migration Execution")

    if ctx.get("evidence_mode"):
        section_missing(
            "Evidence Viewer mode — no live run. The committed run's stages are visible "
            "in the **Audit Trail**."
        )
        return

    svc = ctx.get("service")
    if not svc:
        section_missing("No active run. Start one from **Configuration**.")
        return

    status = svc.status()
    phase = status.phase

    banner = {
        "idle": lambda: st.info("Run not started."),
        "running": lambda: st.info(f"Running… current stage: **{status.current_node or '—'}**"),
        "awaiting_review": lambda: st.warning("Paused for human review — go to **Human Review**."),
        "completed": lambda: st.success("Run completed. All stages finished."),
        "failed": lambda: st.error(f"Run failed: {status.error}"),
    }.get(phase, lambda: None)
    banner()

    # stage checklist
    done = set(status.completed_nodes)
    cur = status.current_node
    st.subheader("Stages")
    for node in NODE_SEQUENCE:
        if node in done:
            mark = "✅"
        elif node == cur and phase == "running":
            mark = "⏳"
        elif phase == "awaiting_review" and node == "human_review_gate":
            mark = "⏸️"
        elif phase == "failed" and node == cur:
            mark = "❌"
        else:
            mark = "▫️"
        st.markdown(f"{mark} **{node}** — {_LABELS.get(node, '')}")

    if status.traceback:
        with st.expander("Error detail"):
            st.code(status.traceback, language=None)

    # table_loaded detail from the audit log
    events = load_audit_events(svc.run_id)
    loaded = [e for e in events if e.get("event_type") == "table_loaded"]
    if loaded:
        st.subheader("Loaded tables")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "source": e["payload"].get("source_table"),
                        "target": e["payload"].get("target_table"),
                        "rows": e["payload"].get("row_count"),
                    }
                    for e in loaded
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        for e in loaded:
            with st.expander(f"SQL — {e['payload'].get('source_table')}"):
                st.code(e["payload"].get("extract_sql", ""), language="sql")
                st.code(e["payload"].get("select_sql", ""), language="sql")

    for et in ("run_failed", "run_rolled_back", "run_rollback_failed"):
        ev = next((e for e in events if e.get("event_type") == et), None)
        if ev:
            st.error(f"**{et}** · {ev.get('payload')}")

    # auto-refresh while a segment is executing
    if phase == "running":
        time.sleep(2)
        st.rerun()
