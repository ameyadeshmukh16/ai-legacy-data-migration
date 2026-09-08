"""Schema Profiling viewer — renders data/schema_profile.json (or the evidence copy)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app._common import load_json, section_missing


def render(ctx) -> None:
    st.header("Schema Profiling")
    st.caption(
        "Real profiling of the legacy source: per-column type, null rate, cardinality, "
        "sample values and value distributions — produced by `agents/schema_profiler.py`."
    )
    profile = load_json(ctx["base_dir"], "schema_profile.json")
    if not profile:
        section_missing(
            "No `schema_profile.json` yet. Start a run from **Configuration**, "
            "or switch to Evidence Viewer mode."
        )
        return

    st.write(f"**Source kind:** `{profile.get('database_kind', 'unknown')}`")
    tables = profile.get("tables", {})
    fk_graph = profile.get("fk_graph", [])

    for tname, tmeta in tables.items():
        st.subheader(f"Table: `{tname}`")
        cols = tmeta.get("columns", [])
        if cols:
            df = pd.DataFrame(
                [
                    {
                        "column": c["name"],
                        "type": c["data_type"],
                        "nullable": c.get("nullable"),
                        "rows": c.get("row_count"),
                        "null %": round(100 * c.get("null_rate", 0), 2),
                        "cardinality": c.get("cardinality"),
                    }
                    for c in cols
                ]
            )
            st.dataframe(df, hide_index=True, width="stretch")

            with st.expander("Sample values & value distributions"):
                for c in cols:
                    st.markdown(f"**`{c['name']}`**")
                    sv = c.get("sample_values") or []
                    if sv:
                        st.code(", ".join(str(v) for v in sv[:20]), language=None)
                    dist = c.get("value_distribution") or []
                    if dist:
                        dd = pd.DataFrame(dist).set_index("value")
                        st.bar_chart(dd, height=180)

        tfks = [f for f in fk_graph if f.get("table") == tname]
        if tfks:
            st.markdown("**Foreign keys**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "columns": ", ".join(f.get("columns", [])),
                            "→ referred table": f.get("referred_table"),
                            "→ referred columns": ", ".join(f.get("referred_columns", [])),
                        }
                        for f in tfks
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        st.divider()
