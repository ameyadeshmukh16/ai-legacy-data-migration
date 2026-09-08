"""Human Review — the HITL form. Submits decisions to the live LangGraph interrupt.

This does NOT implement a review engine; it collects decisions and hands them to
``WorkflowService.submit_decisions`` which resumes the graph via ``Command(resume=…)``.
"""
from __future__ import annotations

import streamlit as st

from app._common import confidence_badge, section_missing


def render(ctx) -> None:
    st.header("Human Review")

    if ctx.get("evidence_mode"):
        section_missing(
            "Evidence Viewer mode — human review is a live-run interaction. "
            "The committed evidence run's decision is visible under **Audit Trail** "
            "(`human_mapping_approved`) and **Rules**."
        )
        return

    svc = ctx.get("service")
    if not svc:
        section_missing("No active run. Start one from **Configuration**.")
        return

    status = svc.status()
    if status.phase == "completed":
        st.success("This run completed with no mappings requiring human review, "
                   "or the review was already submitted.")
        return
    if status.phase == "failed":
        st.error(f"Run failed: {status.error}")
        return
    if status.phase != "awaiting_review" or not status.interrupt_payload:
        st.info(
            "No pending review. The run either hasn't reached `human_review_gate` yet, "
            "or all mappings are above the confidence threshold. Check **Run Status**."
        )
        return

    payload = status.interrupt_payload
    queue = payload.get("mappings", [])
    threshold = payload.get("threshold", 0.80)
    st.warning(
        f"**{len(queue)}** mapping(s) scored below the {threshold:.2f} confidence "
        "threshold and require an explicit human decision before the migration can proceed."
    )

    # reviewer identity (session-remembered)
    ident = st.session_state.setdefault("_reviewer", {"id": "", "role": ""})
    ci1, ci2 = st.columns(2)
    ident["id"] = ci1.text_input("Reviewer ID", value=ident["id"], placeholder="e.g. reviewer-001")
    ident["role"] = ci2.text_input("Reviewer role", value=ident["role"], placeholder="e.g. data_sme / clinical_sme")

    st.divider()
    with st.form("review_form"):
        decisions = []
        for m in queue:
            idx = m["mapping_index"]
            with st.container(border=True):
                st.markdown(
                    f"**`{m['source_table']}.{m['source_column']}`** → "
                    f"**`{m['target_table']}.{m['target_column']}`**  ·  "
                    + confidence_badge(m.get("confidence")),
                    unsafe_allow_html=True,
                )
                st.caption(m.get("reasoning", ""))
                col_a, col_b = st.columns([1, 3])
                decision = col_a.radio(
                    "Decision",
                    ["approve", "reject"],
                    key=f"dec_{idx}",
                    horizontal=True,
                )
                note = col_b.text_input(
                    "Override / justification note (required)",
                    key=f"note_{idx}",
                    placeholder="e.g. Confirmed against hospital lab reference sheet.",
                )
                decisions.append({"mapping_index": idx, "decision": decision, "override_note": note})

        submitted = st.form_submit_button("Submit decisions & resume migration", type="primary")

    if submitted:
        if not ident["id"] or not ident["role"]:
            st.error("Reviewer ID and role are required on every decision.")
            return
        for d in decisions:
            if d["decision"] == "approve" and not d["override_note"].strip():
                st.error(
                    f"Mapping {d['mapping_index']}: a below-threshold approval needs a non-empty note."
                )
                return
            d["reviewer_id"] = ident["id"]
            d["reviewer_role"] = ident["role"]
        rejects = [d["mapping_index"] for d in decisions if d["decision"] == "reject"]
        if rejects:
            st.warning(
                f"You rejected mapping(s) {rejects}. Per the pipeline contract a rejection "
                "blocks the migration — the run will fail and roll back."
            )
        try:
            svc.submit_decisions(decisions)
            st.session_state["_nav_to"] = "Run Status"
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))
