"""Audit & Lineage — hash-chained audit timeline + hash-chain re-verification."""
from __future__ import annotations

import json

import streamlit as st

from app._common import (
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
        full = load_json(ctx["base_dir"], "audit_log_snapshot.json") or []
        st.info("Showing the committed evidence snapshot (`audit_log_snapshot.json`).")
        events = full
        # A snapshot from a run that landed after other runs already existed in the
        # live log chains onto those prior events, so its first previous_hash is not
        # "GENESIS" — verify it as an internally-consistent slice in that case.
        anchored_at_genesis = bool(full) and full[0].get("previous_hash") == "GENESIS"
    else:
        full = load_audit_events()  # the entire hash chain (from GENESIS)
        run_id = ctx.get("run_id")
        events = [e for e in full if e.get("run_id") == run_id] if run_id else full
        anchored_at_genesis = True

    if not full:
        section_missing("No audit events yet.")
        return

    run_ids = sorted({e.get("run_id") for e in events})
    st.write(
        f"Showing **{len(events)}** event(s)"
        + (f" for run(s) {', '.join(f'`{r}`' for r in run_ids)}" if run_ids else "")
        + (f" · full log: {len(full)} events" if not ctx.get("evidence_mode") else "")
    )

    # The hash chain is only meaningful over the WHOLE log (each event links to
    # the previous one, back to GENESIS) — always verify `full`, not a slice, unless
    # this snapshot itself doesn't start at GENESIS (see above).
    verify_label = "Verify hash chain" if ctx.get("evidence_mode") else "Verify hash chain (full log)"
    ok, msg = verify_hash_chain(full, require_genesis=anchored_at_genesis)
    if st.button(verify_label):
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
