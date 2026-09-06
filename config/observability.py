from dotenv import load_dotenv
load_dotenv()
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.types import TraceContext

_client = None

def get_langfuse_client():
    global _client
    if _client is None:
        _client = Langfuse()
    return _client

def trace_id_for(run_id, node_name):
    return get_langfuse_client().create_trace_id(seed=f"{run_id}:{node_name}")

def get_langfuse_callback(run_id, node_name):
    tid = trace_id_for(run_id, node_name)
    return CallbackHandler(trace_context=TraceContext(trace_id=tid))

def score_human_review_decision(run_id, mapping_index, source_column, decision, override_note, reviewer_id=None, reviewer_role=None):
    tid = trace_id_for(run_id, "ai_mapper")
    get_langfuse_client().create_score(
        trace_id=tid,
        name="human_review_decision",
        value=1.0 if decision.lower() == "approve" else 0.0,
        data_type="BOOLEAN",
        comment=f"mapping_index={mapping_index} column={source_column} note={override_note} reviewer={reviewer_id}/{reviewer_role}",
    )
