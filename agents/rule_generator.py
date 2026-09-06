from uuid import uuid4
from pydantic import BaseModel,Field
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from config.llm_factory import get_chat_llm
from config.observability import get_langfuse_callback
from audit.audit_logger import AuditLogger

class TransformationRule(BaseModel):
    source_table:str
    target_table:str
    source_column:str
    target_column:str
    logic:str
    target_type:str|None=None
    null_handling:str
    edge_cases:list[str]=Field(default_factory=list)
    confidence:float=Field(ge=0,le=1)
    prompt_id:str
    human_reviewed:bool=False
    override_note:str|None=None

def validate_rules_before_execution(rules):
    for r in rules:
        if r["confidence"]<settings.confidence_threshold and (not r["human_reviewed"] or not r["override_note"]):
            raise PermissionError(f"Unapproved low-confidence rule: {r['source_column']} -> {r['target_column']}")

def generate_rules(mappings,run_id):
    llm=get_chat_llm().with_structured_output(TransformationRule)
    llm=llm.with_config({"callbacks":[get_langfuse_callback(run_id,"rule_generator")],"tags":["migration","healthcare"]})
    audit=AuditLogger(settings.audit_log_path); rules=[]
    for m in mappings:
        pid=str(uuid4())
        msgs=ChatPromptTemplate.from_messages([
            ("system","""Generate a deterministic SQL transformation rule only from the approved mapping. Preserve NULL semantics.
The logic field must be a bare SQL expression (no AS clause, no column alias) that references the source column by its exact literal name '{source_column}' as it would appear unquoted in a PostgreSQL SELECT list, e.g. "CASE WHEN {source_column} = 'A' THEN 'Active' ELSE NULL END".
The target_type field must be exactly one of: STRING, NUMBER, DATE, TIMESTAMP, BOOLEAN - chosen based on what the logic expression actually produces, not the source column's original type."""),
            ("human","""Source: {source_table}.{source_column}
Target: {target_table}.{target_column}
Meaning: {meaning}
Suggested transformation: {suggestion}
Confidence: {confidence}
Human reviewed: {reviewed}
Override note: {note}""")
        ]).format_messages(source_table=m["source_table"],source_column=m["source_column"],
            target_table=m["target_table"],target_column=m["target_column"],meaning=m["inferred_meaning"],
            suggestion=m["transformation_rule"],confidence=m["confidence"],
            reviewed=m.get("human_reviewed",False),note=m.get("override_note"))
        r=llm.invoke(msgs); r.prompt_id=pid; r.source_table=m["source_table"]; r.target_table=m["target_table"]
        r.source_column=m["source_column"]; r.target_column=m["target_column"]
        r.confidence=m["confidence"]; r.human_reviewed=m.get("human_reviewed",False); r.override_note=m.get("override_note")
        rules.append(r.model_dump())
        audit.append(run_id,"transformation_rule_generated",{"prompt_id":pid,"source_column":r.source_column,
            "target_column":r.target_column,"confidence":r.confidence,"human_reviewed":r.human_reviewed})
    validate_rules_before_execution(rules); return rules
