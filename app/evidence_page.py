"""Evidence — read-only browser of the committed evidence run + scope disclosure."""
from __future__ import annotations

import json

import streamlit as st

from app._common import REPO_ROOT, SEED_ROW_COUNTS, load_text


def render(ctx) -> None:
    st.header("Evidence & Scope")
    evidence_dir = ctx["base_dir"]

    st.info(
        "Two committed live runs are available (pick one in the sidebar). Neither is a "
        "full 5-table / 10K-row run — see the seed capability below and "
        "`SUBMISSION_NOTES.md` for the full scope disclosure."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Seed dataset capability")
        st.caption("`seed/seed_db.py` — inspectable in the repo")
        total = sum(SEED_ROW_COUNTS.values())
        st.dataframe(
            [{"table": t, "rows": n} for t, n in SEED_ROW_COUNTS.items()],
            hide_index=True,
            width="stretch",
        )
        st.metric("Total seed rows across 8 tables", f"{total:,}")
        st.caption("Primary table `patient_records` = 12,000 rows → meets the 10K+ bar.")
    with c2:
        st.subheader("Committed live run")
        rd = load_text(evidence_dir / "README.md")
        if rd:
            # show just the version note + header for brevity
            st.markdown(rd)

    st.divider()
    st.subheader("Artifact browser")
    files = sorted(p.name for p in evidence_dir.glob("*") if p.is_file())
    if not files:
        st.warning("Evidence directory not found.")
        return
    pick = st.selectbox("File", files)
    path = evidence_dir / pick
    text = load_text(path)
    if pick.endswith(".json"):
        try:
            st.json(json.loads(text))
        except json.JSONDecodeError:
            st.code(text, language="json")
    elif pick.endswith(".md"):
        st.markdown(text)
    else:
        st.code(text or "", language=None)

    st.divider()
    sn = load_text(REPO_ROOT / "SUBMISSION_NOTES.md")
    if sn:
        with st.expander("SUBMISSION_NOTES.md (full scope disclosure)"):
            st.markdown(sn)
