"""Shared helpers for the Streamlit application layer.

Pure presentation utilities: file loaders, confidence colour coding, pass/fail
pills, and a mermaid renderer. Nothing here touches the pipeline.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
AUDIT_LOG = REPO_ROOT / "audit" / "migration_audit_log.json"
EVIDENCE_DIR = REPO_ROOT / "evidence" / "2026-09-06-departments-full-run"

ALL_TABLES = [
    "departments",
    "patient_records",
    "doctors",
    "appointments",
    "billing",
    "med_records",
    "lab_orders",
    "ward_alloc",
]

# seed/seed_db.py default row counts, for the "seed capability" display.
SEED_ROW_COUNTS = {
    "departments": 12,
    "doctors": 150,
    "patient_records": 12000,
    "appointments": 15000,
    "billing": 13000,
    "med_records": 20000,
    "lab_orders": 18000,
    "ward_alloc": 8000,
}

GREEN = "#00a878"
AMBER = "#e08e00"
RED = "#e5484d"


# --------------------------------------------------------------------- loaders
def load_json(base_dir: Path, name: str):
    """Return parsed JSON from ``base_dir/name`` or ``None`` if absent/invalid."""
    p = Path(base_dir) / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_text(path: Path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def load_audit_events(run_id: str | None = None):
    events = load_json(AUDIT_LOG.parent, AUDIT_LOG.name) or []
    if run_id:
        events = [e for e in events if e.get("run_id") == run_id]
    return events


# ----------------------------------------------------------------- formatting
def confidence_color(conf: float) -> str:
    if conf is None:
        return "#888"
    if conf >= 0.90:
        return GREEN
    if conf >= 0.80:
        return AMBER
    return RED


def confidence_badge(conf: float) -> str:
    color = confidence_color(conf)
    txt = "n/a" if conf is None else f"{conf:.2f}"
    return (
        f'<span style="background:{color};color:#fff;border-radius:6px;'
        f'padding:2px 8px;font-weight:600;font-size:0.85em">{txt}</span>'
    )


def status_pill(passed: bool | None, true_label: str = "PASS", false_label: str = "FAIL") -> str:
    if passed is None:
        return (
            '<span style="background:#888;color:#fff;border-radius:6px;'
            'padding:2px 10px;font-weight:600">— n/a</span>'
        )
    color = GREEN if passed else RED
    label = true_label if passed else false_label
    mark = "✓" if passed else "✗"
    return (
        f'<span style="background:{color};color:#fff;border-radius:6px;'
        f'padding:2px 10px;font-weight:600">{mark} {label}</span>'
    )


def review_status_badge(status: str | None) -> str:
    palette = {
        "AUTO_APPROVED": "#5b6b7a",
        "HUMAN_APPROVED": GREEN,
        "HUMAN_REJECTED": RED,
    }
    s = status or "—"
    color = palette.get(s, "#888")
    return (
        f'<span style="background:{color};color:#fff;border-radius:6px;'
        f'padding:2px 8px;font-weight:600;font-size:0.85em">{s}</span>'
    )


# -------------------------------------------------------------------- mermaid
def render_mermaid(diagram: str, height: int = 420) -> None:
    """Render a single mermaid diagram body via the mermaid.js CDN.

    Streamlit's ``st.markdown`` does not render ```mermaid fences, so we embed a
    minimal HTML component. CDN-only; no local asset.
    """
    safe = html.escape(diagram)
    st.components.v1.html(
        f"""
        <div class="mermaid">{safe}</div>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>
          mermaid.initialize({{ startOnLoad: true, theme: "neutral", securityLevel: "loose" }});
        </script>
        """,
        height=height,
        scrolling=True,
    )


def render_lineage_markdown(md_text: str) -> None:
    """Split a lineage markdown doc into ``## <table>`` sections and render each
    mermaid block as a component, keeping the surrounding prose as markdown."""
    if not md_text:
        st.info("No lineage document found.")
        return
    parts = md_text.split("```mermaid")
    st.markdown(parts[0])
    for chunk in parts[1:]:
        diagram, _, rest = chunk.partition("```")
        render_mermaid(diagram.strip())
        if rest.strip():
            st.markdown(rest)


# ------------------------------------------------------------- hash-chain check
def verify_hash_chain(events: list[dict]) -> tuple[bool, str]:
    """Re-verify the SHA-256 audit hash chain (same logic as the evidence README)."""
    prev = "GENESIS"
    for i, e in enumerate(events):
        if e.get("previous_hash") != prev:
            return False, f"Event {i} ({e.get('event_type')}): previous_hash mismatch."
        canonical = json.dumps(
            {k: v for k, v in e.items() if k != "hash"},
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = hashlib.sha256((prev + canonical).encode()).hexdigest()
        if e.get("hash") != expected:
            return False, f"Event {i} ({e.get('event_type')}): hash mismatch."
        prev = e["hash"]
    return True, f"Hash chain verified intact across all {len(events)} events."


def section_missing(msg: str) -> None:
    st.info(msg)
