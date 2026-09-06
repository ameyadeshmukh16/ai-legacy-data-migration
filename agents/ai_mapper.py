import json
from uuid import uuid4
from pydantic import BaseModel,Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from config.settings import settings
from audit.audit_logger import AuditLogger

class MappingSuggestion(BaseModel):
    source_table:str
    source_column:str
    target_table:str
    target_column:str
    inferred_meaning:str
    transformation_rule:str
    null_handling:str
    edge_cases:list[str]=Field(default_factory=list)
    confidence:float=Field(ge=0,le=1)
    reasoning:str
    prompt_id:str

SYSTEM_PROMPT="""You are a senior data migration assistant. Infer semantic meaning only from supplied evidence. Never invent undocumented business meanings. If evidence is weak, lower confidence and explain why human review is required."""

def map_schema(profile,run_id):
    if not settings.llm_api_key or not settings.llm_model: raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")
    llm=ChatOpenAI(api_key=settings.llm_api_key,model=settings.llm_model,temperature=0).with_structured_output(MappingSuggestion)
    audit=AuditLogger(settings.audit_log_path); results=[]
    for table,meta in profile["tables"].items():
        for col in meta["columns"]:
            pid=str(uuid4())
            msgs=ChatPromptTemplate.from_messages([
                ("system",SYSTEM_PROMPT),
                ("human","""Table: {table}
Column: {column}
Type: {dtype}
Sample values: {samples}
Null rate: {null_rate}
Cardinality: {cardinality}
Related foreign keys: {fks}

Return target mapping, transformation suggestion, confidence 0.0-1.0 and reasoning. Do not guess when evidence is unclear.""")
            ]).format_messages(table=table,column=col["name"],dtype=col["data_type"],
                samples=json.dumps(col["sample_values"],default=str),null_rate=col["null_rate"],
                cardinality=col["cardinality"],fks=json.dumps(meta["foreign_keys"],default=str))
            r=llm.invoke(msgs); r.prompt_id=pid; r.source_table=table; r.source_column=col["name"]
            item=r.model_dump(); results.append(item)
            audit.append(run_id,"ai_mapping_suggestion",{"prompt_id":pid,"source_table":table,
                "source_column":col["name"],"target_table":r.target_table,"target_column":r.target_column,
                "confidence":r.confidence,"reasoning":r.reasoning})
    return results
