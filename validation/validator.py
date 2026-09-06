import json
from pathlib import Path
from sqlalchemy import create_engine,text
from config.settings import settings
from audit.audit_logger import AuditLogger

def _stats(engine,table,columns):
    with engine.connect() as conn:
        count=conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one()
        stats={}
        for c in columns:
            nulls=conn.execute(text(f'SELECT COUNT(*) FROM {table} WHERE "{c}" IS NULL')).scalar_one()
            distinct=conn.execute(text(f'SELECT COUNT(DISTINCT "{c}") FROM {table}')).scalar_one()
            stats[c]={"null_rate":nulls/count if count else 0,"cardinality":distinct}
        return {"row_count":count,"columns":stats}

def run_validation(profile,run_id,rules):
    source=create_engine(settings.source_db_url)
    report={"run_id":run_id,"source_baseline":{},"post_extraction":{"passed":True},"post_load":{},"tables":{},"passed":True}
    for table,meta in profile["tables"].items():
        cols=[c["name"] for c in meta["columns"]]
        report["source_baseline"][table]=_stats(source,f'"{table}"',cols)
    if settings.snowflake_account:
        from migration.executor import _snowflake_engine,qualified_target_table
        target=_snowflake_engine()
        rules_by_table={}
        for r in rules: rules_by_table.setdefault(r["source_table"],[]).append(r)
        for table,meta in profile["tables"].items():
            table_rules=rules_by_table.get(table,[])
            target_cols=[r["target_column"] for r in table_rules]
            source_by_target={r["target_column"]:r["source_column"] for r in table_rules}
            tt=qualified_target_table(table,run_id)
            try:
                src=report["source_baseline"][table]; tgt=_stats(target,tt,target_cols); match=src["row_count"]==tgt["row_count"]
                tgt["columns"]={source_by_target.get(c,c):stats for c,stats in tgt["columns"].items()}
                report["tables"][table]={"source":src,"target":tgt,"row_count_match":match}; report["passed"] &= match
            except Exception as e:
                report["passed"]=False; report["tables"][table]={"error":str(e)}
    Path("data").mkdir(exist_ok=True)
    Path("data/reconciliation_report.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    AuditLogger(settings.audit_log_path).append(run_id,"validation_completed",{"passed":report["passed"]})
    return report
