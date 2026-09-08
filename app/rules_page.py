"""Transformation Rules — renders data/transformation_rules.json.

Shows the transition: AI suggestion -> human governance -> deterministic executable rule.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app._common import confidence_badge, load_json, review_status_badge, section_missing


def render(ctx) -> None:
    st.header("Transformation Rules")
    st.caption(
        "The final, approved, deterministic rules that `migration/executor.py` will execute. "
        "Each `logic` string is validated by a `sqlglot` AST check before it runs."
    )
    rules = load_json(ctx["base_dir"], "transformation_rules.json")
    if not rules:
        section_missing("No `transformation_rules.json` yet. Run through the `rule_generator` stage.")
        return

    st.write(f"**{len(rules)}** rules")
    for r in rules:
        with st.container(border=True):
            top = st.columns([3, 3, 2, 3])
            top[0].markdown(f"**Source**\n\n`{r['source_table']}.{r['source_column']}`")
            top[1].markdown(f"**Target**\n\n`{r['target_table']}.{r['target_column']}`")
            top[2].markdown(
                "**Confidence**\n\n" + confidence_badge(r.get("confidence")),
                unsafe_allow_html=True,
            )
            top[3].markdown(
                "**Review**\n\n" + review_status_badge(r.get("review_status")),
                unsafe_allow_html=True,
            )
            st.markdown("**Logic**")
            st.code(r.get("logic", ""), language="sql")
            meta = st.columns(3)
            meta[0].markdown(f"**target_type:** `{r.get('target_type')}`")
            meta[1].markdown(f"**null handling:** {r.get('null_handling', '')}")
            reviewer = (
                f"{r.get('reviewer_id')} / {r.get('reviewer_role')}"
                if r.get("reviewer_id")
                else "—"
            )
            meta[2].markdown(f"**reviewer:** {reviewer}")
            if r.get("override_note"):
                st.markdown(f"**Override note:** {r['override_note']}")
            if r.get("edge_cases"):
                with st.expander("Edge cases"):
                    st.write(pd.DataFrame({"edge case": r["edge_cases"]}))
