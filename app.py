"""AI Legacy Migration Assistant — a thin Streamlit control plane + evidence viewer.

Run from the repo root:  streamlit run app.py

This is a PRESENTATION + ORCHESTRATION layer. It renders the pipeline's own
artifacts and drives the existing LangGraph workflow through its public interface
(`build_graph` / `invoke` / `Command(resume=…)`). It does not re-implement any
mapping, validation, execution, audit, or HITL logic, and it does not modify the
pipeline packages.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from uuid import uuid4

import streamlit as st

# Ensure repo root is importable and is the working directory (pipeline nodes
# write to relative "data/..." paths).
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)
(REPO_ROOT / "data").mkdir(exist_ok=True)

st.set_page_config(
    page_title="AI Legacy Migration Assistant",
    page_icon="🩺",
    layout="wide",
)


# --------------------------------------------------------------- settings glue
def reload_settings():
    """Rebuild config.settings from the current os.environ. Called after the
    config page writes TABLES_TO_MIGRATE / CONFIDENCE_THRESHOLD."""
    import config.settings as cs

    importlib.reload(cs)
    return cs.settings


def create_service():
    """Create a fresh WorkflowService bound to this session (new compiled graph,
    new MemorySaver, new run_id). Imported lazily so settings are already set."""
    from services.workflow_service import WorkflowService

    rid = str(uuid4())
    st.session_state["run_id"] = rid
    st.session_state["service"] = WorkflowService(rid)
    return st.session_state["service"]


# ------------------------------------------------------------------- sidebar
st.sidebar.title("🩺 Migration Assistant")
mode = st.sidebar.radio(
    "Mode",
    ["Live Run", "Evidence Viewer"],
    key="mode",
    help="Evidence Viewer renders the committed run with no credentials. "
    "Live Run configures and drives a real migration.",
)
evidence_mode = mode == "Evidence Viewer"

from config.settings import settings as _settings  # noqa: E402  (after chdir/syspath)

if evidence_mode:
    from app._common import EVIDENCE_DIR

    base_dir = EVIDENCE_DIR
else:
    base_dir = REPO_ROOT / "data"

svc = st.session_state.get("service")
run_id = st.session_state.get("run_id")

if not evidence_mode:
    st.sidebar.caption(
        f"scope: `{', '.join(_settings.tables_to_migrate) or '(none set)'}`  \n"
        f"threshold: `{_settings.confidence_threshold:.2f}`"
    )
    if svc:
        busy = svc.is_busy()
        st.sidebar.caption(f"run: `{run_id}` · {svc.status().phase}")
        if st.sidebar.button("New run", disabled=busy):
            svc.request_stop()  # ask the worker to stop after its current node + roll back
            st.session_state.pop("service", None)
            st.session_state.pop("run_id", None)
            st.rerun()
        if busy:
            st.sidebar.caption("Finish or let the current run fail before starting another.")

PAGES = [
    "Configuration",
    "Schema Profile",
    "AI Mappings",
    "Human Review",
    "Rules",
    "Run Status",
    "Validation",
    "Audit Trail",
    "Lineage",
    "Evidence & Scope",
]
if "page" not in st.session_state:
    st.session_state["page"] = "Configuration"
# A page may set st.session_state["page"] before its st.rerun() to jump here.
page = st.sidebar.radio("Page", PAGES, key="page")

st.sidebar.divider()
st.sidebar.caption(
    "Presentation layer only — the LangGraph pipeline, validation, audit and HITL "
    "logic are unchanged. `python -m workflow.langgraph_orchestrator` still works."
)

# --------------------------------------------------------------------- context
ctx = {
    "base_dir": base_dir,
    "evidence_mode": evidence_mode,
    "service": None if evidence_mode else svc,
    "service_status": (svc.status().__dict__ if (svc and not evidence_mode) else None),
    "run_id": None if evidence_mode else run_id,
    "threshold": float(_settings.confidence_threshold),
    "reload_settings": reload_settings,
    "create_service": create_service,
}

# ----------------------------------------------------------------------- route
from app import (  # noqa: E402
    audit_page,
    config_page,
    evidence_page,
    lineage_page,
    mappings_page,
    profile_page,
    review_page,
    rules_page,
    run_status_page,
    validation_page,
)

ROUTES = {
    "Configuration": config_page,
    "Schema Profile": profile_page,
    "AI Mappings": mappings_page,
    "Human Review": review_page,
    "Rules": rules_page,
    "Run Status": run_status_page,
    "Validation": validation_page,
    "Audit Trail": audit_page,
    "Lineage": lineage_page,
    "Evidence & Scope": evidence_page,
}
ROUTES[page].render(ctx)
