"""Migration Configuration — pick scope + threshold, check connections, launch a run."""
from __future__ import annotations

import os

import streamlit as st

from app._common import ALL_TABLES, SEED_ROW_COUNTS


def _missing_credentials(settings) -> list[str]:
    """Return the names of required config that isn't set. The pipeline needs all
    of these before a run: the LLM (ai_mapper/rule_generator/doc_generator),
    Postgres (schema_profiler/executor), Snowflake (executor/validator), and
    Langfuse (ai_mapper attaches a callback on the worker thread)."""
    missing = []
    if not settings.llm_api_key:
        missing.append("LLM_API_KEY")
    if not settings.llm_model:
        missing.append("LLM_MODEL")
    if not settings.source_db_url:
        missing.append("SOURCE_DB_URL")
    if not settings.snowflake_account:
        missing.append("SNOWFLAKE_ACCOUNT")
    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        missing.append("LANGFUSE_SECRET_KEY")
    return missing


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
        "Scope & threshold are read from `.env` and applied once when the app launches / a "
        "run starts. To change them for another run, edit `.env` and restart "
        "`streamlit run app.py`."
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
    phase = svc.status().phase if svc else None
    run_active = phase in ("running", "awaiting_review", "completed", "failed")
    missing_env = _missing_credentials(settings)

    if missing_env:
        st.error(
            "Cannot start a run — these `.env` variables are unset: "
            + ", ".join(f"`{k}`" for k in missing_env)
            + ". Set them and restart the app."
        )

    disabled = (
        ctx.get("evidence_mode", False)
        or not tables
        or bool(missing_env)
        or run_active
    )

    if st.button("🚀 Analyze & Start Migration", type="primary", disabled=disabled):
        os.environ["TABLES_TO_MIGRATE"] = ",".join(tables)
        os.environ["CONFIDENCE_THRESHOLD"] = str(threshold)
        ctx["reload_settings"]()
        new_svc = ctx["create_service"]()
        new_svc.start()
        st.session_state["page"] = "Run Status"
        st.rerun()

    if run_active:
        st.info(
            f"A run is in progress or finished (`{phase}`). See **Run Status**. "
            "Use *New run* in the sidebar to start another."
        )
