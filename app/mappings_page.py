"""AI Mapping Review — renders data/ai_mappings.json with confidence colour coding."""
from __future__ import annotations

import streamlit as st

from app._common import confidence_badge, load_json, section_missing


def render(ctx) -> None:
    st.header("AI Mapping Review")
    st.caption(
        "One structured LLM call per source column (`agents/ai_mapper.py`). "
        "The AI *proposes*; nothing here has been approved yet."
    )
    mappings = load_json(ctx["base_dir"], "ai_mappings.json")
    if not mappings:
        section_missing(
            "No `ai_mappings.json` yet. Run the pipeline through the `ai_mapper` stage."
        )
        return

    threshold = ctx.get("threshold", 0.80)
    st.write(
        f"**{len(mappings)}** mappings · confidence threshold **{threshold:.2f}** · "
        f"green ≥ 0.90 · amber ≥ 0.80 · red < 0.80"
    )

    auto = [m for m in mappings if m.get("confidence", 0) >= threshold]
    flagged = [m for m in mappings if m.get("confidence", 0) < threshold]
    c1, c2 = st.columns(2)
    c1.metric("Auto-approve (≥ threshold)", len(auto))
    c2.metric("Require human review (< threshold)", len(flagged))

    for m in mappings:
        conf = m.get("confidence", 0)
        status = "AUTO-APPROVED" if conf >= threshold else "REQUIRES HUMAN REVIEW"
        with st.container(border=True):
            head = st.columns([3, 3, 2, 3])
            head[0].markdown(f"**Source**\n\n`{m['source_table']}.{m['source_column']}`")
            head[1].markdown(f"**Target**\n\n`{m['target_table']}.{m['target_column']}`")
            head[2].markdown("**Confidence**\n\n" + confidence_badge(conf), unsafe_allow_html=True)
            head[3].markdown(f"**Status**\n\n{status}")
            st.markdown(f"**Inferred meaning:** {m.get('inferred_meaning', '')}")
            st.markdown(f"**Suggested transformation:** {m.get('transformation_rule', '')}")
            st.markdown(f"**Null handling:** {m.get('null_handling', '')}")
            if m.get("edge_cases"):
                st.markdown("**Edge cases:** " + "; ".join(m["edge_cases"]))
            with st.expander("AI reasoning"):
                st.write(m.get("reasoning", ""))
                st.caption(f"prompt_id: `{m.get('prompt_id', '')}`")
