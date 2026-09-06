import json
from collections import Counter
from sqlalchemy import create_engine,inspect,text
from config.settings import settings
from audit.audit_logger import AuditLogger

def _distribution(values):
    c=Counter(str(v) for v in values if v is not None)
    return [{"value":k,"count":v} for k,v in c.most_common(20)]

def profile_database():
    if not settings.source_db_url: raise RuntimeError("SOURCE_DB_URL is required")
    engine=create_engine(settings.source_db_url); insp=inspect(engine)
    tables=settings.tables_to_migrate or tuple(insp.get_table_names())
    profile={"database_kind":settings.source_db_kind,"tables":{},"fk_graph":[]}
    with engine.connect() as conn:
        for table in tables:
            fks=insp.get_foreign_keys(table); profile["tables"][table]={"columns":[],"foreign_keys":fks}
            for col in insp.get_columns(table):
                n=col["name"]
                total=conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
                nulls=conn.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE "{n}" IS NULL')).scalar_one()
                distinct=conn.execute(text(f'SELECT COUNT(DISTINCT "{n}") FROM "{table}"')).scalar_one()
                vals=[r[0] for r in conn.execute(text(f'SELECT "{n}" FROM "{table}" LIMIT 100')).fetchall()]
                profile["tables"][table]["columns"].append({
                    "name":n,"data_type":str(col["type"]),"nullable":bool(col.get("nullable",True)),
                    "row_count":total,"null_count":nulls,"null_rate":nulls/total if total else 0,
                    "cardinality":distinct,"sample_values":vals[:20],
                    "value_distribution":_distribution(vals)})
            for fk in fks:
                profile["fk_graph"].append({"table":table,"columns":fk.get("constrained_columns",[]),
                    "referred_table":fk.get("referred_table"),"referred_columns":fk.get("referred_columns",[])})
    return profile

if __name__=="__main__":
    p=profile_database()
    open("data/schema_profile.json","w",encoding="utf-8").write(json.dumps(p,indent=2,default=str))
    AuditLogger(settings.audit_log_path).append("profiling-only","schema_profile_created",{"tables":list(p["tables"])})
    print("Schema profile written to data/schema_profile.json")
