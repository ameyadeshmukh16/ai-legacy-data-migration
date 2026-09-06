import os,json
from typing import TypedDict
from uuid import uuid4
from pathlib import Path
from langgraph.graph import StateGraph,START,END
from langgraph.types import interrupt,Command
from langgraph.checkpoint.memory import MemorySaver
from config.settings import settings
from config.observability import score_human_review_decision
from audit.audit_logger import AuditLogger
from agents.schema_profiler import profile_database
from agents.ai_mapper import map_schema
from agents.rule_generator import generate_rules
from agents.doc_generator import generate_documentation
from validation.validator import run_validation
from validation.great_expectations.gx_checkpoints import run_source_baseline,run_post_load
from validation.dbt_runner import run_dbt_validation
from migration.executor import execute_migration
from lineage.lineage_generator import generate_lineage

class MigrationState(TypedDict,total=False):
    run_id:str
    schema_profile:dict
    gx_baseline_report:dict
    mappings:list[dict]
    approved_mappings:list[dict]
    rules:list[dict]
    validation:dict
    gx_post_load:dict
    dbt_log:dict
    documentation:str
    status:str

audit=AuditLogger(settings.audit_log_path)

def schema_profiler(s):
    p=profile_database(); Path("data/schema_profile.json").write_text(json.dumps(p,indent=2,default=str),encoding="utf-8")
    audit.append(s["run_id"],"schema_profiler_completed",{"tables":list(p["tables"])})
    baseline_report=run_source_baseline(p)
    audit.append(s["run_id"],"gx_source_baseline_completed",{"passed":baseline_report["passed"]})
    return {"schema_profile":p,"gx_baseline_report":baseline_report}

def ai_mapper(s):
    m=map_schema(s["schema_profile"],s["run_id"]); Path("data/ai_mappings.json").write_text(json.dumps(m,indent=2),encoding="utf-8")
    return {"mappings":m}

def human_review_gate(s):
    m=s["mappings"]; t=settings.confidence_threshold
    flagged=[(i,x) for i,x in enumerate(m) if x["confidence"]<t]
    if not flagged:
        return {"approved_mappings":[dict(x,human_reviewed=True,override_note="Auto-cleared at/above threshold.") for x in m]}
    queue=[{"mapping_index":i,**{k:x[k] for k in ["source_table","source_column","target_table","target_column","confidence","reasoning"]}} for i,x in flagged]
    Path("data/human_review_queue.json").write_text(json.dumps(queue,indent=2),encoding="utf-8")
    decisions=interrupt({"message":"Human review required.","threshold":t,"mappings":queue,
        "format":[{"mapping_index":0,"decision":"approve","override_note":"Domain expert confirmation"}]})
    by={int(x["mapping_index"]):x for x in decisions}
    flagged_indices={i for i,_ in flagged}
    missing=flagged_indices-by.keys()
    if missing: raise PermissionError(f"Missing human decision for flagged mapping index(es): {sorted(missing)}")
    approved=[]
    for i,x in enumerate(m):
        if i not in flagged_indices:
            approved.append(dict(x,human_reviewed=True,override_note="Auto-cleared at/above threshold."))
            continue
        d=by[i]; note=d.get("override_note")
        if d["decision"].lower()=="reject": raise PermissionError(f"Rejected mapping: {x['source_column']}")
        if x["confidence"]<t and not note: raise PermissionError("Low-confidence decision requires override_note")
        approved.append(dict(x,human_reviewed=True,override_note=note))
        audit.append(s["run_id"],"human_mapping_approved",{"mapping_index":i,"source_column":x["source_column"],"decision":d["decision"],"override_note":note})
        score_human_review_decision(s["run_id"],i,x["source_column"],d["decision"],note)
    Path("data/approved_mappings.json").write_text(json.dumps(approved,indent=2),encoding="utf-8")
    return {"approved_mappings":approved}

def rule_generator(s):
    r=generate_rules(s["approved_mappings"],s["run_id"]); Path("data/transformation_rules.json").write_text(json.dumps(r,indent=2),encoding="utf-8")
    generate_lineage(s["approved_mappings"],r,s["schema_profile"])
    return {"rules":r}

def migration_executor(s):
    execute_migration(s["schema_profile"],s["rules"],s["run_id"],s["gx_baseline_report"]); return {"status":"loaded"}

def validator(s):
    post_load_report=run_post_load(s["schema_profile"],s["run_id"],s["gx_baseline_report"],s["rules"])
    if not post_load_report["passed"]: raise RuntimeError("Great Expectations post_load checkpoint failed; migration blocked.")
    audit.append(s["run_id"],"gx_post_load_completed",{"passed":post_load_report["passed"]})
    r=run_validation(s["schema_profile"],s["run_id"],s["rules"])
    if not r["passed"]: raise RuntimeError("Validation failed; migration cannot complete.")
    dbt_log=run_dbt_validation(s["run_id"])
    audit.append(s["run_id"],"dbt_validation_completed",{"steps":list(dbt_log)})
    return {"validation":r,"gx_post_load":post_load_report,"dbt_log":dbt_log}

def doc_generator(s):
    d=generate_documentation(s["schema_profile"],s["approved_mappings"],s["rules"],s["run_id"]); return {"documentation":d,"status":"completed"}

def build_graph():
    g=StateGraph(MigrationState)
    for n,f in [("schema_profiler",schema_profiler),("ai_mapper",ai_mapper),("human_review_gate",human_review_gate),("rule_generator",rule_generator),("migration_executor",migration_executor),("validator",validator),("doc_generator",doc_generator)]: g.add_node(n,f)
    g.add_edge(START,"schema_profiler"); g.add_edge("schema_profiler","ai_mapper"); g.add_edge("ai_mapper","human_review_gate")
    g.add_edge("human_review_gate","rule_generator"); g.add_edge("rule_generator","migration_executor"); g.add_edge("migration_executor","validator")
    g.add_edge("validator","doc_generator"); g.add_edge("doc_generator",END)
    return g.compile(checkpointer=MemorySaver())

if __name__=="__main__":
    rid=os.getenv("RUN_ID",str(uuid4())); app=build_graph()
    cfg={"configurable":{"thread_id":rid}}
    result=app.invoke({"run_id":rid,"status":"started"},config=cfg)
    while "__interrupt__" in result:
        interrupt_payload=result["__interrupt__"][0].value
        print(json.dumps(interrupt_payload,indent=2,default=str))
        print("Enter decisions as a JSON array matching the 'format' shown above, then press Enter:")
        decisions=json.loads(input())
        result=app.invoke(Command(resume=decisions),config=cfg)
    print(json.dumps(result,indent=2,default=str))
