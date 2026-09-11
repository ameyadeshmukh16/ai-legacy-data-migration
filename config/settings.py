import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class Settings:
    source_db_url: str = os.getenv("SOURCE_DB_URL","")
    source_db_kind: str = os.getenv("SOURCE_DB_KIND","postgresql")
    llm_provider: str = os.getenv("LLM_PROVIDER","groq")
    llm_api_key: str = os.getenv("LLM_API_KEY","")
    llm_model: str = os.getenv("LLM_MODEL","")
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD","0.80"))
    tables_to_migrate: tuple[str,...] = tuple(x.strip() for x in os.getenv("TABLES_TO_MIGRATE","").split(",") if x.strip())
    target_schema: str = os.getenv("TARGET_SCHEMA","MIGRATION_STAGE")
    audit_log_path: str = os.getenv("AUDIT_LOG_PATH","audit/migration_audit_log.json")
    snowflake_account: str = os.getenv("SNOWFLAKE_ACCOUNT","")
    snowflake_user: str = os.getenv("SNOWFLAKE_USER","")
    snowflake_password: str = os.getenv("SNOWFLAKE_PASSWORD","")
    snowflake_warehouse: str = os.getenv("SNOWFLAKE_WAREHOUSE","")
    snowflake_database: str = os.getenv("SNOWFLAKE_DATABASE","")
    snowflake_schema: str = os.getenv("SNOWFLAKE_SCHEMA","PUBLIC")
settings=Settings()
