"""Thin driver around the existing LangGraph workflow for the Streamlit UI.

This module is the ONLY place the application layer touches the workflow. It does
not re-implement any pipeline logic; it drives the compiled graph exactly the way
``workflow.langgraph_orchestrator.run_migration`` does, minus the blocking
``input()`` call, and it mirrors that function's run-lifecycle audit events and
rollback so the audit trail is identical whether a run is launched from the CLI or
the UI.

Key constraints (see the plan / investigation notes):
  * The compiled graph uses an in-memory ``MemorySaver``. Resume must happen on the
    SAME compiled object in the SAME process, so a ``WorkflowService`` instance is
    created once per Streamlit session and held in ``st.session_state``.
  * All pipeline modules read ``config.settings.settings`` at call time, so the UI
    must set ``os.environ`` and rebuild ``settings`` BEFORE importing this module.
"""
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command

# These imports pull in the workflow; the caller must have configured the
# environment / rebuilt settings before importing this module.
from workflow.langgraph_orchestrator import build_graph, audit
from config.settings import settings
from migration.executor import rollback_run

NODE_SEQUENCE = [
    "schema_profiler",
    "ai_mapper",
    "human_review_gate",
    "rule_generator",
    "migration_executor",
    "validator",
    "doc_generator",
]


@dataclass
class RunStatus:
    """Snapshot of a run, polled by the UI. All fields are plain values assigned
    under ``_lock`` in the worker thread and copied out by ``snapshot()``."""

    phase: str = "idle"  # idle | running | awaiting_review | completed | failed
    current_node: str | None = None
    completed_nodes: list[str] = field(default_factory=list)
    interrupt_payload: dict | None = None
    result: dict | None = None
    error: str | None = None
    traceback: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def snapshot(self) -> "RunStatus":
        return RunStatus(
            phase=self.phase,
            current_node=self.current_node,
            completed_nodes=list(self.completed_nodes),
            interrupt_payload=self.interrupt_payload,
            result=self.result,
            error=self.error,
            traceback=self.traceback,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


class WorkflowService:
    """Owns one compiled graph + its run lifecycle for a single UI session."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.app = build_graph()
        self.cfg = {"configurable": {"thread_id": run_id}}
        self.tables = list(settings.tables_to_migrate)
        self._status = RunStatus()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ status
    def status(self) -> RunStatus:
        with self._lock:
            return self._status.snapshot()

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _set(self, **kw: Any) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self._status, k, v)

    def _mark_node_done(self, node: str) -> None:
        with self._lock:
            if node not in self._status.completed_nodes:
                self._status.completed_nodes.append(node)
            self._status.current_node = None

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        if self.is_busy():
            raise RuntimeError("A run segment is already in progress.")
        self._set(
            phase="running",
            current_node=NODE_SEQUENCE[0],
            completed_nodes=[],
            interrupt_payload=None,
            result=None,
            error=None,
            traceback=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=None,
        )
        audit.append(self.run_id, "run_started", {"run_id": self.run_id, "tables": self.tables})
        self._spawn({"run_id": self.run_id, "status": "started"})

    # --------------------------------------------------------------- resume
    def submit_decisions(self, decisions: list[dict]) -> None:
        if self.is_busy():
            raise RuntimeError("A run segment is already in progress.")
        self._set(phase="running", interrupt_payload=None, error=None, traceback=None)
        self._spawn(Command(resume=decisions))

    # --------------------------------------------------------------- worker
    def _spawn(self, payload: Any) -> None:
        self._thread = threading.Thread(target=self._run_segment, args=(payload,), daemon=True)
        self._thread.start()

    def _run_segment(self, payload: Any) -> None:
        """Drive one segment of the graph (start->interrupt, or resume->end/interrupt).

        Mirrors ``run_migration``'s try/except: on any failure, emit ``run_failed``,
        attempt ``rollback_run`` + ``run_rolled_back`` (or ``run_rollback_failed``),
        and surface the error. On a clean finish, emit ``run_completed``.
        """
        try:
            interrupted = False
            for chunk in self.app.stream(payload, config=self.cfg, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    payload_value = chunk["__interrupt__"][0].value
                    self._set(phase="awaiting_review", interrupt_payload=payload_value, current_node=None)
                    interrupted = True
                    break
                for node in chunk:  # {node_name: state_update}
                    self._mark_node_done(node)
                    nxt = _next_node(node)
                    if nxt:
                        self._set(current_node=nxt)
            if interrupted:
                return

            final_state = self.app.get_state(self.cfg).values
            self._set(
                phase="completed",
                result=final_state,
                current_node=None,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            audit.append(
                self.run_id,
                "run_completed",
                {
                    "run_id": self.run_id,
                    "status": final_state.get("status"),
                    "validation_passed": (final_state.get("validation") or {}).get("passed"),
                    "distribution_reconciliation_passed": (
                        final_state.get("distribution_reconciliation") or {}
                    ).get("passed"),
                },
            )
        except BaseException as e:  # noqa: BLE001 - parity with run_migration
            tb = traceback.format_exc()
            audit.append(
                self.run_id,
                "run_failed",
                {"run_id": self.run_id, "error": f"{type(e).__name__}: {e}"},
            )
            try:
                dropped = rollback_run(self.run_id)
                audit.append(
                    self.run_id,
                    "run_rolled_back",
                    {"run_id": self.run_id, "dropped_tables": dropped},
                )
            except Exception as re:  # noqa: BLE001
                audit.append(
                    self.run_id,
                    "run_rollback_failed",
                    {"run_id": self.run_id, "error": str(re)},
                )
            self._set(
                phase="failed",
                error=f"{type(e).__name__}: {e}",
                traceback=tb,
                current_node=None,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )


def _next_node(done_node: str) -> str | None:
    try:
        i = NODE_SEQUENCE.index(done_node)
    except ValueError:
        return None
    return NODE_SEQUENCE[i + 1] if i + 1 < len(NODE_SEQUENCE) else None
