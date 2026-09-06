from sqlalchemy import create_engine,text
from tenacity import retry,stop_after_attempt,wait_exponential
from config.settings import settings
from audit.audit_logger import AuditLogger

def _snowflake_engine():
    url=f"snowflake://{settings.snowflake_user}:{settings.snowflake_password}@{settings.snowflake_account}/{settings.snowflake_database}/{settings.snowflake_schema}?warehouse={settings.snowflake_warehouse}"
    return create_engine(url)

@retry(stop=stop_after_attempt(3),wait=wait_exponential(multiplier=1,min=2,max=20))
def _load_rows(engine,table,columns,rows):
    cols=", ".join(f'"{c}"' for c in columns); ph=", ".join(f":p{i}" for i in range(len(columns)))
    stmt=text(f'INSERT INTO "{table}" ({cols}) VALUES ({ph})')
    with engine.begin() as conn:
        for row in rows: conn.execute(stmt,{f"p{i}":row[i] for i in range(len(columns))})

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
        target_table=f'{settings.target_schema}_{table}_{run_id.replace("-","_")}'
        defs=", ".join(f'"{c}" VARCHAR' for c in columns)
        with target.begin() as conn: conn.execute(text(f'CREATE TABLE IF NOT EXISTS "{target_table}" ({defs})'))
        _load_rows(target,target_table,columns,rows)
        AuditLogger(settings.audit_log_path).append(run_id,"table_loaded",{"source_table":table,"target_table":target_table,"row_count":len(rows)})
    return {"status":"loaded"}
