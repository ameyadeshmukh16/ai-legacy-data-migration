import json
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from config.llm_factory import get_chat_llm
from audit.audit_logger import AuditLogger

def generate_documentation(profile,mappings,rules,run_id):
    llm=get_chat_llm()
    msgs=ChatPromptTemplate.from_messages([
        ("system","Create a concise target data dictionary in Markdown. Include target columns, definitions, source lineage, transformation logic, confidence and human overrides. Do not invent business facts."),
        ("human","Schema profile:\n{profile}\n\nApproved mappings:\n{mappings}\n\nRules:\n{rules}")
    ]).format_messages(profile=json.dumps(profile,default=str),mappings=json.dumps(mappings,default=str),rules=json.dumps(rules,default=str))
    out=Path("data/target_data_dictionary.md"); out.write_text(llm.invoke(msgs).content,encoding="utf-8")
    AuditLogger(settings.audit_log_path).append(run_id,"documentation_generated",{"output":str(out)})
    return out.read_text(encoding="utf-8")
