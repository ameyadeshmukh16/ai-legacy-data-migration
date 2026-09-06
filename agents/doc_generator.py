import json
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from config.settings import settings
from audit.audit_logger import AuditLogger

def generate_documentation(profile,mappings,rules,run_id):
    if not settings.llm_api_key or not settings.llm_model: raise RuntimeError("LLM credentials required")
    llm=ChatOpenAI(api_key=settings.llm_api_key,model=settings.llm_model,temperature=0)
    msgs=ChatPromptTemplate.from_messages([
        ("system","Create a concise target data dictionary in Markdown. Include target columns, definitions, source lineage, transformation logic, confidence and human overrides. Do not invent business facts."),
        ("human","Schema profile:
{profile}

Approved mappings:
{mappings}

Rules:
{rules}")
    ]).format_messages(profile=json.dumps(profile,default=str),mappings=json.dumps(mappings,default=str),rules=json.dumps(rules,default=str))
    out=Path("data/target_data_dictionary.md"); out.write_text(llm.invoke(msgs).content,encoding="utf-8")
    AuditLogger(settings.audit_log_path).append(run_id,"documentation_generated",{"output":str(out)})
    return out.read_text(encoding="utf-8")
