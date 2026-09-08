"""Migration Configuration — pick scope + threshold, check connections, launch a run."""
from __future__ import annotations

import os

import streamlit as st

from app._common import ALL_TABLES, SEED_ROW_COUNTS, section_missing


def _probe_postgres(url: str) -> tuple[bool, str]:
    if not url:
        return False, "SOURCE_DB_URL not set"
    try:
        from sqlalchemy import create_engine, text

        eng = create_engine(url)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _probe_snowflake() -> tuple[bool, str]:
    from config.settings import settings

    if not settings.snowflake_account:
        return False, "SNOWFLAKE_ACCOUNT not set"
    try:
        from migration.executor import _snowflake_engine
        from sqlalchemy import text

        with _snowflake_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def render(ctx) -> None:
    from config.settings import settings

    st.header("Migration Configuration")

    if ctx.get("evidence_mode"):
        st.info(
            "Evidence Viewer mode is active — launching a live run is disabled. "
            "Switch to **Live Run** mode in the sidebar to configure and start a migration."
        )

    st.subheader("Connections")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Source — PostgreSQL**")
        if st.button("Test PostgreSQL", disabled=ctx.get("evidence_mode", False)):
            ok, msg = _probe_postgres(settings.source_db_url)
            (st.success if ok else st.error)(msg)
        st.caption(f"`{settings.source_db_url or '(not set)'}`")
    with c2:
        st.markdown("**Target — Snowflake**")
        if st.button("Test Snowflake", disabled=ctx.get("evidence_mode", False)):
            ok, msg = _probe_snowflake()
            (st.success if ok else st.error)(msg)
        acct = settings.snowflake_account or "(not set)"
        st.caption(f"account `{acct}` · schema `{settings.target_schema}`")

    st.markdown(
        f"**LLM provider:** `{settings.llm_provider}` · **model:** `{settings.llm_model or '(not set)'}` · "
        f"key {'set' if settings.llm_api_key else 'MISSING'}"
    )

    st.divider()
    st.subheader("Run scope")
    st.caption(
        "Scope and threshold are applied by writing environment variables and rebuilding "
        "`config.settings` before the pipeline is imported."
    )
    current = list(settings.tables_to_migrate) or ["departments"]
    tables = st.multiselect(
        "Tables to migrate",
        ALL_TABLES,
        default=[t for t in current if t in ALL_TABLES] or ["departments"],
        disabled=ctx.get("evidence_mode", False),
    )
    threshold = st.slider(
        "Confidence threshold (below this → human review)",
        min_value=0.50,
        max_value=0.99,
        value=float(settings.confidence_threshold),
        step=0.01,
        disabled=ctx.get("evidence_mode", False),
    )
    seed_total = sum(SEED_ROW_COUNTS.get(t, 0) for t in tables)
    st.caption(
        f"Seed dataset capability for this scope: **{seed_total:,} rows** "
        f"(primary table `patient_records` = {SEED_ROW_COUNTS['patient_records']:,} if selected). "
        "Actual rows migrated depend on what the source database currently holds."
    )

    st.divider()
    svc = ctx.get("service")
    busy = bool(svc and svc.is_busy())
    already = bool(svc and svc.status().phase not in ("idle",))
    disabled = ctx.get("evidence_mode", False) or busy or not tables

    if st.button("🚀 Analyze & Start Migration", type="primary", disabled=disabled):
        if not tables:
            st.error("Select at least one table.")
            return
        os.environ["TABLES_TO_MIGRATE"] = ",".join(tables)
        os.environ["CONFIDENCE_THRESHOLD"] = str(threshold)
        ctx["reload_settings"]()
        ctx["create_service"]()
        st.session_state["_nav_to"] = "Run Status"
        st.rerun()

    if already and not busy:
        st.info(
            f"A run is in progress or finished (`{svc.status().phase}`). "
            "See **Run Status**. Use *New run* in the sidebar to start another."
        )
    elif busy:
        st.info("A run segment is currently executing — see **Run Status**.")
