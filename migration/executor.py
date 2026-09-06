from sqlalchemy import create_engine,text
from tenacity import retry,stop_after_attempt,wait_exponential
from config.settings import settings
from audit.audit_logger import AuditLogger

def _snowflake_engine():
    url=f"snowflake://{settings.snowflake_user}:{settings.snowflake_password}@{settings.snowflake_account}/{settings.snowflake_database}/{settings.snowflake_schema}?warehouse={settings.snowflake_warehouse}"
    return create_engine(url)

def qualified_target_table(table,run_id):
    return f'"{settings.target_schema}"."{table}_{run_id.replace("-","_")}"'

BATCH_SIZE=500

@retry(stop=stop_after_attempt(3),wait=wait_exponential(multiplier=1,min=2,max=20))
def _load_batch(engine,stmt,batch):
    with engine.begin() as conn: conn.execute(stmt,batch)

def _load_rows(engine,qualified_table,columns,rows):
    cols=", ".join(f'"{c}"' for c in columns); ph=", ".join(f":p{i}" for i in range(len(columns)))
    stmt=text(f'INSERT INTO {qualified_table} ({cols}) VALUES ({ph})')
    for start in range(0,len(rows),BATCH_SIZE):
        chunk=rows[start:start+BATCH_SIZE]
        batch=[{f"p{j}":row[j] for j in range(len(columns))} for row in chunk]
        _load_batch(engine,stmt,batch)

def execute_migration(profile,rules,run_id):
    for r in rules:
        if r["confidence"]<settings.confidence_threshold and (not r["human_reviewed"] or not r["override_note"]):
            raise PermissionError("Migration blocked by confidence policy")
    source=create_engine(settings.source_db_url); target=_snowflake_engine()
    with target.begin() as conn: conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.target_schema}"'))
    for table,meta in profile["tables"].items():
        columns=[c["name"] for c in meta["columns"]]
        select_cols=", ".join(f'"{c}"' for c in columns)
        with source.connect() as conn: rows=conn.execute(text(f'SELECT {select_cols} FROM "{table}"')).fetchall()
        qualified_table=qualified_target_table(table,run_id)
        defs=", ".join(f'"{c}" VARCHAR' for c in columns)
        with target.begin() as conn: conn.execute(text(f'CREATE TABLE IF NOT EXISTS {qualified_table} ({defs})'))
        _load_rows(target,qualified_table,columns,rows)
        AuditLogger(settings.audit_log_path).append(run_id,"table_loaded",{"source_table":table,"target_table":qualified_table,"row_count":len(rows)})
    return {"status":"loaded"}
