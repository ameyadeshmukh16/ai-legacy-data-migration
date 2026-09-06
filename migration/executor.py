import re
from collections import defaultdict
import sqlglot
from sqlglot import exp
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

# Functions an AI-generated transformation expression is allowed to call. Anything
# else (window funcs, subquery-driven aggregates, system/UDF calls) is rejected.
_ALLOWED_FUNCS={
    "TRIM","BTRIM","LTRIM","RTRIM","UPPER","LOWER","INITCAP","COALESCE","NULLIF",
    "CONCAT","SUBSTRING","SUBSTR","LEFT","RIGHT","REPLACE","LPAD","RPAD","SPLIT_PART",
    "CAST","TRY_CAST","TO_DATE","TO_TIMESTAMP","TO_CHAR","TO_NUMBER","DATE","LENGTH",
    "CHAR_LENGTH","ABS","ROUND","FLOOR","CEIL","CEILING","MOD","GREATEST","LEAST",
    "REGEXP_REPLACE",
}
# AST node types that must never appear inside a column-transformation expression.
_FORBIDDEN_NODES=(
    exp.Select,exp.Subquery,exp.Union,exp.Join,exp.From,exp.With,exp.CTE,exp.Table,
    exp.Star,exp.Insert,exp.Update,exp.Delete,exp.Create,exp.Drop,exp.Command,
    exp.Window,exp.Placeholder,exp.Semicolon,
)

def _validate_identifier(name,kind):
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"Rejected unsafe {kind} identifier: {name!r}")
    return name

def _ast_validate_logic(logic,source_column):
    """Parse-verify an AI-generated transformation expression: it must be a single
    scalar expression over exactly the one source column, with no subqueries,
    table refs, joins, CTEs, DML/DDL, or non-whitelisted function calls."""
    try:
        tree=sqlglot.parse_one(logic,read="postgres")
    except Exception as e:
        raise ValueError(f"Unparseable transformation logic for {source_column}: {logic!r} ({e})")
    if tree is None:
        raise ValueError(f"Empty transformation logic for column {source_column}")
    if isinstance(tree,exp.Expression) and tree.find(exp.Semicolon):
        raise ValueError(f"Multiple statements in transformation logic for {source_column}: {logic!r}")
    for node in tree.walk():
        if isinstance(node,_FORBIDDEN_NODES):
            raise ValueError(f"Disallowed SQL construct {type(node).__name__} in logic for {source_column}: {logic!r}")
        if isinstance(node,exp.Column):
            col=node.name
            if col.lower()!=source_column.lower():
                raise ValueError(f"Logic for {source_column} references foreign column {col!r}: {logic!r}")
            if node.args.get("table"):
                raise ValueError(f"Logic for {source_column} uses a table-qualified reference: {logic!r}")
        if isinstance(node,exp.Anonymous):
            raise ValueError(f"Unknown function {node.name!r} in logic for {source_column}: {logic!r}")
        # CASE/WHEN/IF are control flow, not gated function calls; CAST/COALESCE/NULLIF
        # are structural nodes sqlglot models outside the generic function allow-list.
        _CONTROL=(exp.Case,exp.If,exp.Cast,exp.TryCast,exp.Coalesce,exp.Nullif)
        if isinstance(node,exp.Func) and not isinstance(node,_CONTROL):
            fname=(node.sql_name() or type(node).__name__).upper()
            if fname not in _ALLOWED_FUNCS:
                raise ValueError(f"Function {fname!r} not on the transformation allow-list for {source_column}: {logic!r}")
    return logic

def _validate_logic(logic,source_column):
    if not logic or not logic.strip():
        raise ValueError(f"Empty transformation logic for column {source_column}")
    if _FORBIDDEN_RE.search(logic):
        raise ValueError(f"Rejected unsafe transformation logic for {source_column}: {logic!r}")
    if not _SAFE_LOGIC_RE.match(logic):
        raise ValueError(f"Rejected transformation logic with disallowed characters for {source_column}: {logic!r}")
    _ast_validate_logic(logic,source_column)
    return logic

def _target_column_type(rule,source_columns_meta):
    hint=(rule.get("target_type") or "").upper()
    if hint in _RULE_TYPE_MAP: return _RULE_TYPE_MAP[hint]
    src_meta=source_columns_meta.get(rule["source_column"])
    if src_meta and rule["logic"].strip().strip('"')==rule["source_column"]:
        return snowflake_type(src_meta["data_type"])
    return "VARCHAR(16777216)"

def _build_extract_sql(table,source_columns):
    cols_sql=", ".join(f'"{_validate_identifier(c,"source_column")}"' for c in source_columns)
    return f'SELECT {cols_sql} FROM "{table}"'

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

def _check_unique_target_columns(table,table_rules):
    seen=set(); dupes=set()
    for r in table_rules:
        tc=r["target_column"]
        (dupes if tc in seen else seen).add(tc)
    if dupes:
        raise RuntimeError(f"Multiple rules map to the same target_column {sorted(dupes)} in table '{table}'. Each approved mapping must resolve to a unique target column name (check for placeholder values like 'UNKNOWN' from low-confidence AI mappings).")

def _snowflake_engine():
    url=f"snowflake://{settings.snowflake_user}:{settings.snowflake_password}@{settings.snowflake_account}/{settings.snowflake_database}/{settings.snowflake_schema}?warehouse={settings.snowflake_warehouse}"
    return create_engine(url)

def qualified_target_table(table,run_id):
    return f'"{settings.target_schema}"."{table}_{run_id.replace("-","_")}"'

def rollback_run(run_id):
    """Drop every run-scoped target table created by this run. Used by the
    orchestrator when any stage fails, so a blocked migration leaves no
    orphaned <table>_<run_id> tables in Snowflake. Returns the list dropped."""
    if not settings.snowflake_account:
        return []
    engine=_snowflake_engine(); dropped=[]
    with engine.begin() as conn:
        for table in settings.tables_to_migrate:
            qt=qualified_target_table(table,run_id)
            conn.execute(text(f'DROP TABLE IF EXISTS {qt}'))
            dropped.append(qt)
    return dropped

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

    for table,meta in profile["tables"].items():
        table_rules=rules_by_table.get(table,[])
        _check_full_coverage(table,meta,table_rules)
        _check_unique_target_columns(table,table_rules)
        source_cols_meta={c["name"]:c for c in meta["columns"]}
        source_columns=[c["name"] for c in meta["columns"]]

        # 1. Raw extract - no transformation yet.
        extract_sql=_build_extract_sql(table,source_columns)
        with source.connect() as conn: raw_rows=conn.execute(text(extract_sql)).fetchall()
        raw_extracted={table:[dict(zip(source_columns,row)) for row in raw_rows]}

        # 2. Post-extraction checkpoint guards the extraction boundary: raw rows,
        #    raw column names, before any rule is applied.
        run_post_extraction(raw_extracted,baseline_report,expected_columns={table:source_columns})

        # 3. Apply the approved transformation rules.
        select_sql=_build_select_sql(table,table_rules)
        with source.connect() as conn: rows=conn.execute(text(select_sql)).fetchall()
        target_columns=[r["target_column"] for r in table_rules]

        # 4. Load transformed rows into Snowflake.
        defs=", ".join(f'"{r["target_column"]}" {_target_column_type(r,source_cols_meta)}' for r in table_rules)
        qualified_table=qualified_target_table(table,run_id)
        with target.begin() as conn: conn.execute(text(f'CREATE TABLE IF NOT EXISTS {qualified_table} ({defs})'))
        _load_rows(target,qualified_table,target_columns,rows)
        AuditLogger(settings.audit_log_path).append(run_id,"table_loaded",{"source_table":table,"target_table":qualified_table,"row_count":len(rows),"extract_sql":extract_sql,"select_sql":select_sql})

    return {"status":"loaded"}
