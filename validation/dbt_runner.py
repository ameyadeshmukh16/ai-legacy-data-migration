import os,shutil,sys,subprocess
from pathlib import Path
from config.settings import settings

DBT_PROJECT_DIR=Path(__file__).parent/"dbt_models"

def _dbt_executable():
    local=Path(sys.executable).parent/("dbt.exe" if os.name=="nt" else "dbt")
    if local.exists(): return str(local)
    found=shutil.which("dbt")
    if found: return found
    raise RuntimeError("Could not locate the dbt executable (checked venv Scripts/bin dir and PATH).")

def _dbt_env():
    env=os.environ.copy()
    env["SNOWFLAKE_ACCOUNT"]=settings.snowflake_account
    env["SNOWFLAKE_USER"]=settings.snowflake_user
    env["SNOWFLAKE_PASSWORD"]=settings.snowflake_password
    env["SNOWFLAKE_WAREHOUSE"]=settings.snowflake_warehouse
    env["SNOWFLAKE_DATABASE"]=settings.snowflake_database
    env["TARGET_SCHEMA"]=settings.target_schema
    return env

def _run_dbt(args,run_id):
    cmd=[_dbt_executable(),*args,"--vars",f'{{"run_id": "{run_id}"}}',
         "--project-dir",str(DBT_PROJECT_DIR),"--profiles-dir",str(DBT_PROJECT_DIR)]
    return subprocess.run(cmd,cwd=DBT_PROJECT_DIR,env=_dbt_env(),capture_output=True,text=True,timeout=300)

def run_dbt_validation(run_id):
    from validation.dbt_models.generate_seeds import generate_counts_seed,generate_null_rates_seed
    generate_counts_seed(); generate_null_rates_seed()

    log={}
    for name,args in [("seed",["seed"]),("run",["run"]),("test",["test"])]:
        result=_run_dbt(args,run_id)
        log[name]={"returncode":result.returncode,"stdout":result.stdout[-4000:],"stderr":result.stderr[-4000:]}
        if result.returncode!=0:
            raise RuntimeError(f"dbt {name} failed (exit {result.returncode}) for run {run_id}:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return log
