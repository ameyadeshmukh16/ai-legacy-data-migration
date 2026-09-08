"""Data Lineage — renders docs/lineage.md mermaid diagrams."""
from __future__ import annotations

import streamlit as st

from app._common import DOCS_DIR, GREEN, AMBER, RED, load_text, render_lineage_markdown, section_missing


def render(ctx) -> None:
    st.header("Data Lineage")
    st.caption(
        "Auto-generated alongside the transformation rules (`lineage/lineage_generator.py`). "
        "One diagram per source table: source column → transformation → target column."
    )
    st.markdown(
        f"<span style='color:{GREEN};font-weight:600'>■ green</span> auto-approved (conf ≥ 0.90) &nbsp;·&nbsp; "
        f"<span style='color:{AMBER};font-weight:600'>■ amber</span> passed threshold (0.80–0.89) &nbsp;·&nbsp; "
        f"<span style='color:{RED};font-weight:600'>■ red</span> required human review (< 0.80)",
        unsafe_allow_html=True,
    )
    st.divider()

    # lineage is always written to docs/lineage.md (both live and evidence share it)
    md = load_text(DOCS_DIR / "lineage.md")
    if not md:
        section_missing("No `docs/lineage.md` found. Run through the `rule_generator` stage.")
        return
    render_lineage_markdown(md)
