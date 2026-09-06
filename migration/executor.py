import re
from collections import defaultdict
from sqlalchemy import create_engine,text
from tenacity import retry,stop_after_attempt,wait_exponential
from config.settings import settings
from audit.audit_logger import AuditLogger

TYPE_MAP={
    "BIGINT":"NUMBER(38,0)",
    "INTEGER":"NUMBER(10,0)",
    "NUMERIC":"NUMBER(18,4)",
    "TIMESTAMP":"TIMESTAMP_NTZ",
    "DATE":"DATE",
    "BOOLEAN":"BOOLEAN",
    "TEXT":"VARCHAR(16777216)",
    "VARCHAR":"VARCHAR({length})",
}

_RULE_TYPE_MAP={
    "STRING":"VARCHAR(16777216)",
    "NUMBER":"NUMBER(38,4)",
    "DATE":"DATE",
    "TIMESTAMP":"TIMESTAMP_NTZ",
    "BOOLEAN":"BOOLEAN",
}

def snowflake_type(source_type):
    m=re.match(r"([A-Z]+)(?:\(([\d,\s]+)\))?",source_type.upper())
    if not m: return "VARCHAR(16777216)"
    base,args=m.group(1),m.group(2)
    if base=="NUMERIC" and args:
        parts=[p.strip() for p in args.split(",")]
        return f"NUMBER({parts[0]},{parts[1] if len(parts)>1 else 0})"
    if base=="VARCHAR" and args:
        return TYPE_MAP["VARCHAR"].format(length=args.strip())
    return TYPE_MAP.get(base,"VARCHAR(16777216)")

_IDENT_RE=re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_SAFE_LOGIC_RE=re.compile(r'^[A-Za-z0-9_\s\.\'"(),=<>!+\-*/%|:]*$')
_FORBIDDEN_RE=re.compile(r';|--|/\*|\*/|\b(DROP|DELETE|INSERT|UPDATE|ALTER|GRANT|EXEC|EXECUTE|CREATE|TRUNCATE)\b',re.IGNORECASE)

def _validate_identifier(name,kind):
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"Rejected unsafe {kind} identifier: {name!r}")
    return name

def _validate_logic(logic,source_column):
    if not logic or not logic.strip():
        raise ValueError(f"Empty transformation logic for column {source_column}")
    if _FORBIDDEN_RE.search(logic):
        raise ValueError(f"Rejected unsafe transformation logic for {source_column}: {logic!r}")
    if not _SAFE_LOGIC_RE.match(logic):
        raise ValueError(f"Rejected transformation logic with disallowed characters for {source_column}: {logic!r}")
    return logic

def _target_column_type(rule,source_columns_meta):
    hint=(rule.get("target_type") or "").upper()
    if hint in _RULE_TYPE_MAP: return _RULE_TYPE_MAP[hint]
    src_meta=source_columns_meta.get(rule["source_column"])
    if src_meta and rule["logic"].strip().strip('"')==rule["source_column"]:
        return snowflake_type(src_meta["data_type"])
    return "VARCHAR(16777216)"

def _build_select_sql(table,table_rules):
    select_list=[]
    for r in table_rules:
        logic=_validate_logic(r["logic"],r["source_column"])
        target_col=_validate_identifier(r["target_column"],"target_column")
        select_list.append(f'({logic}) AS "{target_col}"')
    cols_sql=", ".join(select_list)
    return f'SELECT {cols_sql} FROM "{table}"'

def _check_full_coverage(table,meta,table_rules):
    rule_source_cols={r["source_column"] for r in table_rules}
    all_source_cols={c["name"] for c in meta["columns"]}
    missing=all_source_cols-rule_source_cols
    if missing:
        raise RuntimeError(f"No transformation rule found for column(s) {sorted(missing)} in table '{table}'. Every migrated column must have an approved rule.")

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

def execute_migration(profile,rules,run_id,baseline_report):
    from agents.rule_generator import validate_rules_before_execution
    from validation.great_expectations.gx_checkpoints import run_post_extraction
    validate_rules_before_execution(rules)

    rules_by_table=defaultdict(list)
    for r in rules: rules_by_table[r["source_table"]].append(r)

    source=create_engine(settings.source_db_url); target=_snowflake_engine()
    with target.begin() as conn: conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.target_schema}"'))

    extracted_data={}
    for table,meta in profile["tables"].items():
        table_rules=rules_by_table.get(table,[])
        _check_full_coverage(table,meta,table_rules)
        source_cols_meta={c["name"]:c for c in meta["columns"]}

        select_sql=_build_select_sql(table,table_rules)
        with source.connect() as conn: rows=conn.execute(text(select_sql)).fetchall()

        target_columns=[r["target_column"] for r in table_rules]
        extracted_data[table]=[dict(zip(target_columns,row)) for row in rows]

        defs=", ".join(f'"{r["target_column"]}" {_target_column_type(r,source_cols_meta)}' for r in table_rules)
        qualified_table=qualified_target_table(table,run_id)
        with target.begin() as conn: conn.execute(text(f'CREATE TABLE IF NOT EXISTS {qualified_table} ({defs})'))
        _load_rows(target,qualified_table,target_columns,rows)
        AuditLogger(settings.audit_log_path).append(run_id,"table_loaded",{"source_table":table,"target_table":qualified_table,"row_count":len(rows),"select_sql":select_sql})

    run_post_extraction(extracted_data,baseline_report)
    return {"status":"loaded"}
