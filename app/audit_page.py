"""Audit & Lineage — hash-chained audit timeline + hash-chain re-verification."""
from __future__ import annotations

import json

import streamlit as st

from app._common import (
    EVIDENCE_DIR,
    load_audit_events,
    load_json,
    section_missing,
    verify_hash_chain,
)

_ICON = {
    "run_started": "🟢",
    "schema_profiler_completed": "🔍",
    "schema_profile_created": "🔍",
    "gx_source_baseline_completed": "✅",
    "ai_mapping_suggestion": "🤖",
    "human_mapping_approved": "🧑‍⚖️",
    "transformation_rule_generated": "⚙️",
    "table_loaded": "📦",
    "gx_post_load_completed": "✅",
    "validation_completed": "✅",
    "distribution_reconciliation_completed": "📊",
    "dbt_validation_completed": "🧪",
    "documentation_generated": "📄",
    "run_completed": "🏁",
    "run_failed": "❌",
    "run_rolled_back": "↩️",
    "run_rollback_failed": "⚠️",
}


def render(ctx) -> None:
    st.header("Audit Trail")
    st.caption(
        "Append-only, SHA-256 hash-chained. Each event links to the previous by hash, "
        "so any tampering breaks the chain."
    )

    if ctx.get("evidence_mode"):
        events = load_json(EVIDENCE_DIR, "audit_log_snapshot.json") or []
        st.info("Showing the committed evidence snapshot (`audit_log_snapshot.json`).")
    else:
        events = load_audit_events(ctx.get("run_id"))
        if not events:
            events = load_audit_events()  # fall back to the whole log

    if not events:
        section_missing("No audit events yet.")
        return

    run_ids = sorted({e.get("run_id") for e in events})
    st.write(f"**{len(events)}** events · run id(s): " + ", ".join(f"`{r}`" for r in run_ids))

    ok, msg = verify_hash_chain(events)
    if st.button("Verify hash chain"):
        (st.success if ok else st.error)(msg)

    st.divider()
    for e in events:
        icon = _ICON.get(e.get("event_type"), "•")
        with st.container(border=True):
            st.markdown(
                f"{icon} **{e.get('event_type')}**  ·  "
                f"`{e.get('timestamp', '')}`"
            )
            payload = e.get("payload", {})
            if payload:
                with st.expander("payload"):
                    st.json(payload)
            st.caption(f"hash `{e.get('hash', '')[:16]}…`  ◂  prev `{e.get('previous_hash', '')[:16]}…`")
