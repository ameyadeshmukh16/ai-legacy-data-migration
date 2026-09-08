# FDE Capstone Plan - AI-Assisted Legacy Data Migration

## Stack Decisions

- Source: PostgreSQL (Docker) - free, easy local setup
- Target: Snowflake (30-day trial, $400 credits)
- Domain: Healthcare (Clinical Operations)
- Base: Existing zip project - expand, don't rebuild
- Standout Feature: Auto-generated data lineage visualization (Mermaid diagrams)
- LLM: Google Gemini (via LangChain + langchain-google-genai), selected for free credits during development. Provider is abstracted behind `config/llm_factory.py` (`LLM_PROVIDER` env var) so Anthropic Claude can be added later as a second/alternate option without touching agent code.
- Primary dev tool: Claude Code CLI

## Time Budget (4.5-5 hours)

Since the base project already has the LangGraph orchestrator, all 7 nodes, audit logger, settings, and agent scaffolding in place, the work is additive - not from scratch.

| Phase | Time | What gets done | Base status |
|-------|------|----------------|-------------|
| Phase 1 - Schema expansion + seed data | 40 min | Expand 5-table schema to 8 tables, write seed script (10k+ rows) | init_db.sql exists but minimal, no seed script |
| Phase 2 - LLM swap + LangFuse | 25 min | LLM swap (OpenAI to Gemini via provider factory) and LangFuse callback/scoring wiring both done | Complete |
| Phase 3 - Great Expectations | 35 min | GX suites for all 3 checkpoints implemented (GX 1.x API); also fixed a pre-existing Snowflake schema-qualification bug and slow row-by-row insert in executor.py | Complete |
| Phase 4 - dbt models | 20 min | Real row count, null rate, and FK integrity models built and verified against live Snowflake; added missing dbt-core/dbt-snowflake deps | Complete |
| Phase 5 - Lineage visualization | 30 min | lineage_generator.py built, wired into rule_generator, Mermaid diagrams verified rendering correctly | Complete |
| Phase 6 - executor type mapping | 15 min | Real type mapping implemented and verified via DESCRIBE TABLE against live Snowflake | Complete |
| Phase 7 - Documentation update | 25 min | README + DECISIONS.md rewritten for healthcare domain, LLM provider/lineage/validation sections added, docs/architecture.md refreshed | Complete |

Total: ~3 hrs 10 min (leaves buffer for testing + unexpected issues)

---

## What the Base Project Already Has (Do Not Rebuild)

These are solid and should be used as-is:

- `workflow/langgraph_orchestrator.py` - All 7 nodes wired, real LangGraph `interrupt()` for human review gate, state schema, edge routing
- `audit/audit_logger.py` - SHA-256 hash-chained append-only logger, thread-safe
- `agents/schema_profiler.py` - Full SQLAlchemy reflection, null rates, cardinality, value distribution, FK graph
- `agents/rule_generator.py` - TransformationRule Pydantic model, pre-execution confidence validation
- `agents/doc_generator.py` - LangChain doc generation, writes target data dictionary
- `config/settings.py` - Clean dataclass-based settings from .env
- `migration/executor.py` - Snowflake load with tenacity retry + exponential backoff
- `validation/validator.py` - Source baseline + reconciliation report structure
- `docker-compose.yml` - PostgreSQL container setup
- `audit/migration_audit_log.json` - Initialized and ready
- `tests/test_confidence_gate.py` - Basic gate logic tests
- `data/example_*.json` - Example rule and mapping shapes

---

## Phase 1 - Schema Expansion + Seed Data (40 min)

### 1.1 Expand init_db.sql

Keep the existing 5 tables. Add 3 more to reach 8 total, increasing clinical complexity and giving the AI mapper more varied ambiguity to work with.

**Existing tables (keep, add columns):**

| Table | Additions |
|-------|-----------|
| `departments` | Add `dept_typ_cd` (VARCHAR(3): 'IPD', 'OPD', 'ICU', 'ER', 'SRG') - undocumented |
| `patient_records` | Add `dob` as VARCHAR (legacy stored as string 'DD-MM-YYYY'), `blood_grp_cd` (VARCHAR(3): 'AP', 'AN', 'BP', 'BN', 'OP', 'ON', 'ABP', 'ABN'), `gndr_cd` (VARCHAR(1): 'M', 'F', 'U'), `ins_prvdr_cd` (VARCHAR(5): insurer codes, no lookup) |
| `doctors` | Add `spec_cd` (VARCHAR(5): specialization codes 'CARD', 'ORTH', 'NEUR', 'PEDS', 'ONCO'), `qlf_cd` (VARCHAR(10): qualification codes 'MBBS', 'MD', 'MS', 'DM', 'MCH') |
| `appointments` | Add `appt_typ_cd` (VARCHAR(3): 'NEW', 'FLW', 'EMR', 'REV'), `cncl_rsn` (VARCHAR free text, often NULL), `pri_lvl` (INT: 1-5, undocumented priority) |
| `billing` | Add `pay_mthd_cd` (VARCHAR(3): 'CSH', 'INS', 'CRD', 'UPI'), `ins_clm_st` (VARCHAR(2): 'PN', 'AP', 'RJ', 'PP'), `disc_pct` (NUMERIC: discount %, nullable) |

**New tables (add 3):**

| Table | Purpose | Legacy quirks |
|-------|---------|---------------|
| `med_records` | Medication prescriptions | `med_cd` (drug codes, no lookup), `dosage_txt` (free text: '1x2', 'BD', 'TDS', 'SOS'), `rte_cd` (route: 'OR', 'IV', 'IM', 'SC'), `dur_days` as VARCHAR |
| `lab_orders` | Lab test orders | `tst_cd` (test codes: 'CBC', 'LFT', 'KFT', 'TSH', 'XRAY'), `tst_st_cd` (VARCHAR(2): 'OR', 'PR', 'CM', 'CN'), `rslt_txt` (free text results, often NULL), `urgcy_cd` (VARCHAR: 'ROU', 'URG', 'STT') |
| `ward_alloc` | Ward/bed allocation | `ward_cd` (VARCHAR: 'G1', 'G2', 'ICU', 'PVTW', 'SRG'), `bed_no` (VARCHAR: '101A', '202B' - alphanumeric), `alloc_st` (VARCHAR(1): 'A', 'V', 'M', 'B'), `alloc_dt` as VARCHAR |

**Total: 8 tables, 30+ columns, most with undocumented codes.**

Key ambiguities the AI mapper will hit (drives human review gate):
- `blood_grp_cd`: 'AP' could be A-Positive or something else entirely - confidence will be low
- `appt_st` (INT in existing schema, no meaning documented): 1/2/3/4/5 - no context
- `ins_clm_st`: 'PP' could be Partially Paid or Pre-Processing - requires domain review
- `dosage_txt` free text ('BD', 'TDS', 'SOS'): pharmaceutical abbreviations, AI will flag these
- `alloc_st`: single char codes with no table comment
- `pri_lvl` INT: is 1 highest priority or lowest? - genuinely ambiguous

### 1.2 Seed Script

New file: `seed/seed_db.py`

Row targets:
- `patient_records`: 12,000 rows
- `appointments`: 15,000 rows (multiple per patient)
- `billing`: 13,000 rows
- `med_records`: 20,000 rows
- `lab_orders`: 18,000 rows
- `departments`: 12 rows (reference data)
- `doctors`: 150 rows
- `ward_alloc`: 8,000 rows

Use `Faker` for names, dates. Use `random.choice` for all code columns. Inject deliberate data quality issues:
- 3-5% NULL rate on nullable FKs
- ~2% NULL on `pat_st_cd`, `appt_st`
- `dob` stored inconsistently: mix of 'DD-MM-YYYY' and 'YYYY-MM-DD' in same column (simulates organic legacy growth)
- `dur_days` in `med_records`: mix of '7', '7 days', 'one week' (genuinely messy)

---

## Phase 2 - LLM Swap + LangFuse (25 min)

### 2.1 Swap OpenAI to Gemini (done ahead of schedule, during prerequisite setup)

Rather than hardcoding a single provider in each agent, `config/llm_factory.py` was introduced as a thin provider switch, read via `LLM_PROVIDER` (`google_genai` default, `anthropic` and `openai` also supported). All three agent files (`agents/ai_mapper.py`, `agents/rule_generator.py`, `agents/doc_generator.py`) now call `get_chat_llm()` instead of instantiating `ChatOpenAI` directly:

```python
# config/llm_factory.py
def get_chat_llm(temperature=0):
    if settings.llm_provider == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(google_api_key=settings.llm_api_key, model=settings.llm_model, temperature=temperature)
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(api_key=settings.llm_api_key, model=settings.llm_model, temperature=temperature)
    ...

# agents/ai_mapper.py (and rule_generator.py, doc_generator.py)
from config.llm_factory import get_chat_llm
llm = get_chat_llm().with_structured_output(MappingSuggestion)
```

`requirements.txt`: removed `langchain-openai`, added `langchain-google-genai>=2.0`. Adding Claude later is just `pip install langchain-anthropic`, setting `LLM_PROVIDER=anthropic`, and updating `LLM_API_KEY`/`LLM_MODEL` in `.env` — no agent code changes.

`.env` / `.env.example`:
```
LLM_PROVIDER=google_genai
LLM_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-flash-latest
```

Note: Gemini's free tier gives **zero** request quota to `-pro` models (confirmed via a live 429 during setup) — `gemini-flash-latest` is the model that actually has free-tier quota and is what's configured. If richer reasoning is needed later, either request pro-tier quota/billing or switch `LLM_PROVIDER` to `anthropic`.

### 2.2 Wire LangFuse (done)

The installed `langfuse` SDK is v4.x, which redesigned the integration from the original v2-era plan: the callback now lives at `langfuse.langchain.CallbackHandler` (not `langfuse.callback`), auth/host come from the `Langfuse()` client singleton reading `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` env vars directly (no constructor kwargs for these), and scoring is `Langfuse.create_score(...)`/`score_current_trace(...)` rather than `langfuse_handler.langfuse.score(...)`. `requirements.txt` was bumped to `langfuse>=3.0` to reflect this.

`config/observability.py` wraps this as a small helper:
```python
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.types import TraceContext

def get_langfuse_client():
    ...  # cached Langfuse() singleton, reads env vars automatically

def trace_id_for(run_id, node_name):
    return get_langfuse_client().create_trace_id(seed=f"{run_id}:{node_name}")

def get_langfuse_callback(run_id, node_name):
    return CallbackHandler(trace_context=TraceContext(trace_id=trace_id_for(run_id, node_name)))

def score_human_review_decision(run_id, mapping_index, source_column, decision, override_note):
    get_langfuse_client().create_score(
        trace_id=trace_id_for(run_id, "ai_mapper"),
        name="human_review_decision",
        value=1.0 if decision.lower() == "approve" else 0.0,
        data_type="BOOLEAN",
        comment=f"mapping_index={mapping_index} column={source_column} note={override_note}",
    )
```

Each agent wires the callback at LLM initialization: `llm = get_chat_llm().with_config({"callbacks": [get_langfuse_callback(run_id, "ai_mapper")], "tags": ["migration", "healthcare"]})`. Trace IDs are deterministic (seeded from `run_id` + node name), so `human_review_gate` in the orchestrator can call `score_human_review_decision(...)` after each override decision and have it land on the same `ai_mapper` trace that produced the original low-confidence suggestion — verified end-to-end via the LangFuse public API (trace + attached score both confirmed present).

---

## Phase 3 - Great Expectations (35 min, done)

Replaced the `validation/great_expectations/README.md` placeholder with `validation/great_expectations/gx_checkpoints.py`.

The installed `great-expectations` is 1.22.0, a major redesign from the 0.18.x line the plan originally targeted — `great_expectations.core.batch.RuntimeBatchRequest` no longer exists. GX 1.x's lightweight path is `gx.get_context(mode="ephemeral")` + `data_sources.add_pandas(...).add_dataframe_asset(...).add_batch_definition_whole_dataframe(...).get_batch(...)`, then `batch.validate(single_expectation)` per check — still no YAML/project config needed, just a different object path to get there:

```python
def run_source_baseline(profile: dict) -> dict: ...       # validates Postgres source tables directly
def run_post_extraction(extracted_data: dict, baseline_report: dict) -> dict: ...  # row counts + no dropped columns vs baseline
def run_post_load(profile: dict, run_id: str, baseline_report: dict) -> dict: ...  # validates Snowflake target vs baseline
```

**Checkpoint 1 - Source baseline expectations per table:**
- `expect_table_row_count_to_be_between` (min: seeded count * 0.95)
- `expect_column_values_to_not_be_null` for PK columns
- `expect_column_values_to_be_in_set` for known code columns (pat_st_cd: ['A','D','I','S'], appt_typ_cd: ['NEW','FLW','EMR','REV'])
- `expect_column_values_to_be_unique` for PK columns

**Checkpoint 2 - Post-extraction:**
- Row counts from extraction match source baseline counts
- No columns dropped during extraction

**Checkpoint 3 - Post-load (Snowflake):**
- Target row counts match source
- Null rates within 2% tolerance of source baseline
- Mapped status code columns contain only valid target values (e.g., patient_status in ['Active', 'Discharged', 'Inactive', 'Suspended'])

All three checkpoints write results to `data/gx_results_{checkpoint}.json`. A failure at any checkpoint raises an exception that blocks the pipeline. Known status-code domains live in `KNOWN_VALUE_SETS` in `gx_checkpoints.py`, sourced from `scripts/init_db.sql`/`seed/seed_db.py` (e.g. `pat_st_cd`: `['A','D','I','S']`, `blood_grp_cd`: the 8 seeded blood-group codes); columns not in that dict are free text / undocumented and are not domain-checked, matching the deliberate ambiguity built into the schema.

While testing `run_post_load` against real Snowflake data, found and fixed two pre-existing bugs blocking it:
- `migration/executor.py` created the `MIGRATION_STAGE` schema but never actually wrote into it — `CREATE SCHEMA IF NOT EXISTS` doesn't switch the connection's current schema the way `USE SCHEMA` would, so every table silently landed in `PUBLIC` instead. Fixed by fully qualifying every target table reference via a new `qualified_target_table(table, run_id)` helper, used consistently by the executor, `validation/validator.py`, and `gx_checkpoints.py`.
- `_load_rows` inserted one row at a time inside a single long transaction — 27k rows took over 16 minutes without completing. Rewritten to batch in chunks of 500 (matching the pattern already used in `seed/seed_db.py`), bringing the same load down to ~70 seconds.

Verified end-to-end: all three checkpoints run for real against the live Postgres source and a real Snowflake load (`patient_records`, `appointments`), all passing.

---

## Phase 4 - dbt Models (20 min, done)

Replaced the stub `migration_reconciliation.sql`/`schema.yml` with a real dbt project. `dbt-core` and `dbt-snowflake` (1.8+) were not in `requirements.txt` despite `validation/dbt_models/` existing — added both.

Structure built:
```
validation/dbt_models/
├── dbt_project.yml
├── profiles.yml               # Snowflake target via env_var(), schema = TARGET_SCHEMA
├── generate_seeds.py           # converts data/reconciliation_report.json -> seed CSVs
├── seeds/
│   ├── migration_counts_seed.csv    (generated, gitignored)
│   └── null_rates_seed.csv          (generated, gitignored)
└── models/
    ├── sources.yml              # declares the run's target tables as a dbt source
    ├── schema.yml                # not_null / unique / accepted_values tests
    ├── row_count_reconciliation.sql
    ├── null_rate_check.sql
    └── fk_integrity_check.sql
```

**row_count_reconciliation.sql** and **null_rate_check.sql** both read from seed CSVs generated by `generate_seeds.py` out of `data/reconciliation_report.json` (the same report `validation/validator.py` already produces) — not queried live, since the report is already the audit-trail source of truth for those numbers:
```sql
SELECT table_name, source_row_count, target_row_count,
    source_row_count - target_row_count AS row_delta,
    CASE WHEN source_row_count = target_row_count THEN 'PASS' ELSE 'FAIL' END AS status
FROM {{ ref('migration_counts_seed') }}
```

**fk_integrity_check.sql** queries Snowflake live via a `source()` pointing at that run's actual target tables (`patient_records_{run_id}`, `appointments_{run_id}`) and returns any `appointments` row whose `pat_id` has no matching `patient_records.pat_id` (empty result = pass).

Two Snowflake-specific issues surfaced during testing and were fixed:
- **Identifier case sensitivity**: `migration/executor.py` creates tables with quoted (case-preserved, lowercase) names, but dbt's `source()` and column references are unquoted by default and get uppercased by Snowflake, causing "object does not exist" / "invalid identifier" errors. Fixed via `quoting: {identifier: true}` on the source in `sources.yml` plus explicit double-quoted column references in `fk_integrity_check.sql`.
- **`var('run_id')` with no default fails at parse time**: dbt parses all models before running any of them, so a bare `var('run_id')` (no default) breaks even commands that don't touch that model. Fixed by defaulting to `'unset'` in both `sources.yml` and `fk_integrity_check.sql`; the real run always passes `--vars '{"run_id": "..."}'`.
- Also hit a deprecation in this dbt version: `accepted_values` test args must be nested under an `arguments:` key now, not top-level.

`run_id` threads through the same way it does everywhere else in the pipeline: `generate_seeds.py` reads it from the report JSON, and `dbt run --vars '{"run_id": "..."}'` is how the orchestrator would invoke dbt for a given run.

Verified end-to-end: `dbt debug` (connects), `dbt seed`, `dbt run` (all 3 models build), `dbt test` (10/10 pass) — all against a real Snowflake load, with `fk_integrity_check` confirmed returning 0 orphaned rows and `row_count_reconciliation`/`null_rate_check` both showing PASS for real migrated data.

---

## Phase 5 - Lineage Visualization (30 min, done) - STANDOUT

New file: `lineage/lineage_generator.py`, called from inside `rule_generator` in `workflow/langgraph_orchestrator.py` right after `transformation_rules.json` is written — README's "Mandatory Nodes" list is exactly 7 nodes, so this is wired as a side effect of the existing `rule_generator` node rather than an 8th graph node. Reads `approved_mappings` + `rules` + `schema_profile` already in orchestrator state (matching data/approved_mappings.json + data/transformation_rules.json's shapes). No dependency on live DB or LLM — verified by generating diagrams from realistic synthetic fixtures alone.

Since `transformation_rules.json` (from `rule_generator`) only carries `source_column`/`target_column`, not table names, the generator joins it against `approved_mappings.json` (which has both table names) on `(source_column, target_column)` to know which source table each rule belongs to, and pulls the original source data type from `schema_profile.json`.

**What it builds:**

A Mermaid `graph LR` diagram grouped by source table, with three columns:
- Left subgraph: source table + column (with original data type)
- Middle node: transformation logic summary (CASE / CAST / direct map)
- Right subgraph: target table + column (with mapped type)

**Color coding by confidence:**
- `fill:#00d4aa` (green): confidence >= 0.90, auto-approved
- `fill:#f59e0b` (amber): confidence 0.80-0.89, passed threshold
- `fill:#ef4444` (red): confidence < 0.80, required human review - shows `(reviewed)` marker

**Healthcare-specific example output (partial):**
```mermaid
graph LR
    subgraph src_patient_records["Source: patient_records"]
        S1["pat_st_cd VARCHAR(2)"]
        S2["dob VARCHAR"]
        S3["blood_grp_cd VARCHAR(3)"]
        S4["gndr_cd VARCHAR(1)"]
    end

    subgraph transforms["Transformations"]
        T1["CASE: A→Active, D→Discharged..."]
        T2["CAST + reformat to DATE"]
        T3["CASE: AP→A+, AN→A-..."]
        T4["CASE: M→Male, F→Female, U→Unknown"]
    end

    subgraph tgt_patient_records["Target: patient_records"]
        TG1["patient_status VARCHAR"]
        TG2["date_of_birth DATE"]
        TG3["blood_group VARCHAR"]
        TG4["gender VARCHAR"]
    end

    S1 -->|"conf: 0.82 ✓ reviewed"| T1 --> TG1
    S2 -->|"conf: 0.91"| T2 --> TG2
    S3 -->|"conf: 0.68 ✓ reviewed"| T3 --> TG3
    S4 -->|"conf: 0.88"| T4 --> TG4

    style T1 fill:#f59e0b
    style T2 fill:#00d4aa
    style T3 fill:#ef4444
    style T4 fill:#f59e0b
```

Output written to `docs/lineage.md`. One diagram per source table, all in the same file with H2 headers per table. The reviewed marker only appears when a mapping actually passed through `human_review_gate` (checked via `override_note` not starting with `"Auto-cleared"`) — auto-cleared high-confidence mappings above the threshold don't get a false "reviewed" label just because `human_reviewed=True` is set on every approved mapping.

The transformation summary extracts `WHEN x = 'A' THEN 'B'` pairs out of generated CASE-statement logic into the compact `A→B, C→D` form shown above (real LLM-generated SQL is often much longer than the plan's example), falling back to the raw logic (length-capped) for CAST/other transformations, and to `"direct map"` when no rule matches.

`docs/lineage.md` is committed to the repo as a worked example (using realistic fixtures covering the plan's own healthcare ambiguity examples — blood group codes, appointment priority, etc.) — visible without running the pipeline, and regenerated for real on every actual migration run.

**Why this matters for healthcare:** Blood group codes, clinical status codes, medication routes - these are exactly the columns where a reader looking at the diagram can immediately see which transformations were human-validated versus auto-approved. That's the story the evaluator needs to see.

---

## Phase 6 - Executor Type Mapping (15 min, done)

`migration/executor.py` previously created every Snowflake column as `VARCHAR`. Added `TYPE_MAP` (exactly as planned) plus a `snowflake_type(source_type)` function that parses SQLAlchemy's rendered type strings (e.g. `"VARCHAR(80)"`, `"NUMERIC(12, 2)"`, `"BIGINT"`) and maps them:

```python
TYPE_MAP = {
    "BIGINT": "NUMBER(38,0)", "INTEGER": "NUMBER(10,0)", "NUMERIC": "NUMBER(18,4)",
    "TIMESTAMP": "TIMESTAMP_NTZ", "DATE": "DATE", "BOOLEAN": "BOOLEAN",
    "TEXT": "VARCHAR(16777216)", "VARCHAR": "VARCHAR({length})",
}
```

One deviation from the plan's fixed `NUMBER(18,4)` for every `NUMERIC` column: `snowflake_type` preserves the source's actual precision/scale when present (e.g. `billing.bill_amt NUMERIC(12, 2)` → `NUMBER(12,2)`, not a hardcoded `NUMBER(18,4)`) — the fixed default is used only as a fallback for a bare `NUMERIC` with no precision specified. Unknown/unmapped types fall back to `VARCHAR(16777216)` rather than erroring, since Postgres has types (UUID, JSONB, etc.) this project's schema doesn't use but that shouldn't hard-fail a migration.

Verified end-to-end against a real Snowflake load: `DESCRIBE TABLE` on the migrated `patient_records`/`appointments` confirmed `NUMBER(38,0)` for BIGINT PKs, `NUMBER(10,0)` for INTEGER columns, `TIMESTAMP_NTZ(9)` for TIMESTAMP, and correctly-sized VARCHARs — not blanket VARCHAR. Re-ran the Phase 3 GX checkpoints and Phase 4 dbt models against this typed data; both still pass, confirming the type fix doesn't regress the earlier validation work.

---

## Phase 7 - Documentation Update (25 min, done)

### README.md - done:

- Project Overview rewritten for the healthcare clinical-operations domain, naming the actual undocumented codes and messy fields in this schema.
- Added an "LLM Provider" section documenting the `config/llm_factory.py` abstraction and the Gemini free-tier quota finding from Phase 2.
- Architecture diagram updated to show `lineage_generator` after `rule_generator`, typed Snowflake columns, and GX/dbt in the validator step.
- Run section documents that lineage generation is automatic (a `rule_generator` side effect, not a separate pipeline step — see Phase 5), with the standalone command for regenerating it from existing JSON, plus the dbt seed/run/test commands for a given run_id.
- Added "Lineage Diagram" section: what the color coding means, where `docs/lineage.md` lives, that GitHub/VS Code render Mermaid natively.
- Validation section rewritten to describe the real GX 1.x checkpoints and dbt models built in Phases 3-4, not the original generic placeholder description.
- Known Limitations: added the three healthcare-specific notes (clinical code ambiguity, medication/dosage free text needing clinical SME review specifically, `pri_lvl` ordinal direction being structurally unknowable from data alone).
- `docs/architecture.md` also lightly refreshed (Gemini, GX/dbt, lineage) since it had gone stale relative to what was actually built — not originally called out as a Phase 7 target but worth keeping in sync.

### DECISIONS.md - done:

- **Sensitive data section**: added field-level classification (patient PII: `first_name`/`last_name`/`dob`; clinical: `pat_st_cd`/`blood_grp_cd`/`med_cd`/`dosage_txt`/`tst_cd`/`rslt_txt`; insurance/financial: `ins_prvdr_cd`/`ins_clm_st`/`bill_amt`/`pay_mthd_cd`) plus a description of the actual masking/minimization approach `agents/ai_mapper.py` already uses (column-level metadata + capped samples, never joined rows) and what a production deployment would still need to add.
- **Confidence threshold justification**: `blood_grp_cd` example added under Confidence Threshold — why pattern-matchable codes without a lookup table still warrant sub-0.80 confidence given the patient-safety-adjacent stakes.
- **Dosage text handling**: new "Medication and Free-Text Clinical Fields" section — flags `dosage_txt`/`dur_days` for clinical SME review specifically, not generic human review, and notes the platform doesn't yet distinguish reviewer qualification (added to Future Extensions).
- **Why Mermaid for lineage**: new section under Trade-off, explaining the portability rationale and when a dedicated lineage backend would be worth the switch.
- **Human override examples**: three realistic examples added under Human-in-the-Loop (`blood_grp_cd`, `pri_lvl`, `ins_clm_st`), each with a plausible override note.

---

## Post-Phase-7 Remediation - Integration Gaps Found by External Review (done)

After all 7 phases above were built, an external review (ChatGPT) audited the completed codebase and found that several pieces verified in isolation during Phases 3/4/6 above were never actually wired into the *executable* `workflow/langgraph_orchestrator.py` graph — the phase-level "verified end-to-end" claims were true for standalone scripts, not for a real pipeline run. Independently verified each claim against the code (not taken on the review's word) and found:

1. **`migration/executor.py` never applied AI-generated transformation rules** — it copied raw source values under source column names, using `rules` only for the confidence gate. The core "AI-assisted transformation" claim wasn't actually happening.
2. **`human_review_gate` had a real merge bug** — it required a decision for every mapping (including auto-cleared ones that never entered the review queue), breaking on the common case of a mixed batch.
3. **No LangGraph checkpointer was configured** (found independently, not by the review) — `Command(resume=...)` raised unconditionally, meaning the human-review pause/resume flow the README already claimed worked could not function at all.
4. **Great Expectations and dbt were fully built but never invoked from the graph** — `validator` only called the weaker row-count-only `validation/validator.py`, and dbt was a manual-CLI-only step.
5. **`TABLES_TO_MIGRATE` defaulted to 2 of 8 seeded tables**, below the rubric's 5-table minimum, and `sources.yml` hard-coded those same 2 tables.
6. **Test coverage was 2 tests against inline dict literals**, not real functions.

Fixed all of these (`migration/executor.py` rewritten for rule-driven transformation with a SQL-injection allow-list validator and LLM-supplied target-type hints; `human_review_gate` merge logic corrected; `MemorySaver` checkpointer added with a real run/resume loop; GX checkpoints wired into `schema_profiler`/`migration_executor`/`validator`; a new `validation/dbt_runner.py` invokes dbt via subprocess from `validator`; `TABLES_TO_MIGRATE` expanded to 5 tables with `sources.yml` updated; test suite grown to 28 tests exercising real functions).

**Live verification against real Postgres + Snowflake** (not just unit tests) then surfaced 4 further real bugs, each fixed and covered by a new regression test:
- `agents/ai_mapper.py` returning an empty string or the literal `'UNKNOWN'` for `target_column` when given no target schema, causing a "duplicate column name" crash in Snowflake when two columns collided — fixed with a stronger prompt instruction plus a `_fallback_target()` backstop that doesn't rely on prompt compliance alone.
- `migration/executor.py` needed `_check_unique_target_columns` to fail fast and clearly on any remaining collision rather than reaching Snowflake as a cryptic SQL error.
- A numpy-bool JSON-serialization crash in `gx_checkpoints.py` (`pandas.isna().mean()` comparisons aren't natively JSON-serializable, and `audit_logger.py` has no `default=str` fallback by design, to keep the audit format canonical) — fixed with explicit `bool()`/`float()` casts.
- `validation/validator.py` was still querying Snowflake target stats by source column names after the rename, breaking `reconciliation_report.json`'s shape that `generate_seeds.py` depends on — fixed by querying by `target_column` and re-keying the result back to source names.
- `validation/dbt_models/models/fk_integrity_check.sql` was hardcoded to always check `appointments`/`patient_records`, failing dbt for any smaller-scope run that doesn't include both — fixed to use `adapter.get_relation()` and skip gracefully (empty passing result) when either table doesn't exist for the current run.

**Provider note**: also discovered mid-remediation that Gemini's free tier (20 requests/day) and NVIDIA NIM's `gpt-oss-20b` (unreliable/hanging under `with_structured_output` for this project's real prompts, confirmed via direct timing tests) were both unworkable for a multi-table live run. Switched the default to Groq's `openai/gpt-oss-120b` (fast, correct, but rate-limited to ~8000 tokens/minute on the free tier — a full 5-table run takes 20-30+ minutes). At that point `config/llm_factory.py` carried `groq`/`google_genai`/`nvidia`/`anthropic`/`openai` branches. (Update, commit `c4f0b3d`: the unused/untested `anthropic` branch was removed and `langchain-openai` added to `requirements.txt`; the factory now handles `groq`/`google_genai`/`nvidia`/`openai`. This build log below reflects earlier phases and is not rewritten to match — see `README.md`, `DECISIONS.md`, and `SUBMISSION_NOTES.md` for current state and test count, now 53.)

**Verification performed** (against real Postgres/Snowflake, not mocks):
- A full pipeline run (`departments` table, to fit free-tier rate limits) completed successfully end-to-end for the first time — `python -m workflow.langgraph_orchestrator` genuinely paused at `human_review_gate`, resumed via `Command(resume=...)` in the same process, ran the rule-driven executor (`DESCRIBE TABLE`/`SELECT *` confirmed renamed columns and `TRIM()`-transformed values in the real Snowflake table), all 3 GX checkpoints, dbt seed/run/test (10/10 tests passing), and `doc_generator` — the resulting `audit/migration_audit_log.json` (16 real hash-chained events, chain integrity independently re-verified) and `data/target_data_dictionary.md` are committed as evidence.
- Deliberately broke `run_post_extraction`'s row-count check (fed a false extraction count against a real GX `source_baseline` result) and confirmed it raises `RuntimeError` and would halt the pipeline.
- Deliberately fed a transformed value outside `TARGET_VALUE_SETS`'s allowed domain into the real GX `_validate` machinery and confirmed it's correctly flagged as a failed expectation.
- A run at the full 5-table default scope (`departments,patient_records,doctors,appointments,billing`) has not yet been executed live — every live run so far used a 1-2 table subset to fit within free-tier LLM rate limits during same-day testing. The `sources.yml`/`fk_integrity_check.sql` changes needed for 5-table scope were verified by direct code inspection and the graceful-skip path was tested live, but not the full-scope happy path. This is the one item still pending, deferred to whenever LLM quota/rate-limit headroom allows a ~20-30 minute uninterrupted run.

---

## Execution Order with Claude Code

Build in this sequence to minimize blocked time:

1. `scripts/init_db.sql` - schema expansion (run and verify in Docker first)
2. `seed/seed_db.py` - seed data (run, confirm row counts)
3. `agents/ai_mapper.py` + `agents/rule_generator.py` + `agents/doc_generator.py` - LLM swap to Gemini + LangFuse callbacks (both done)
4. `validation/great_expectations/gx_checkpoints.py` - GX suites
5. `validation/dbt_models/` - real SQL models
6. `lineage/lineage_generator.py` - Mermaid generator
7. `migration/executor.py` - type mapping fix
8. README.md + DECISIONS.md - documentation pass

Key Claude Code prompts:
- "Expand this PostgreSQL healthcare schema SQL to add these 3 tables and column additions, preserving existing CREATE TABLE statements"
- "Write a Python seed script using Faker to populate this schema with realistic healthcare data, injecting these specific data quality issues"
- "Add LangFuse callback handler to these 3 agent files, wired through the existing get_chat_llm() factory"
- "Implement Great Expectations suites for these 3 checkpoints using the in-memory/pandas approach, no YAML"
- "Build a Mermaid lineage diagram generator that reads approved_mappings.json and transformation_rules.json"

---

## Gap Summary vs Capstone Rubric

| Requirement | Base project | After this plan |
|-------------|-------------|-----------------|
| 7 LangGraph nodes | Done | Done |
| Human-in-the-loop gate | Done (real interrupt) | Done |
| LangFuse instrumentation | Missing | Added Phase 2 |
| Great Expectations (3 checkpoints) | README stub | Added Phase 3 |
| dbt post-migration models | Single stub SQL | Added Phase 4 |
| 10,000+ rows seed data | 1 demo row | Added Phase 1 |
| Healthcare schema with complexity | 5 minimal tables | Expanded Phase 1 |
| Gemini as LLM (Anthropic Claude as later add-on via provider factory) | Hardcoded OpenAI | Fixed ahead of Phase 2 |
| Lineage visualization | Missing | Added Phase 5 |
| Correct Snowflake type mapping | All VARCHAR | Fixed Phase 6 |
| README all 8 sections | Mostly there | Updated Phase 7 |
| DECISIONS.md with PII/domain notes | Generic | Updated Phase 7 |
| .env.example | Exists | Minor update |
| audit_log.json | Exists + hash-chained | No change |
| architecture.png | Exists | No change |
| Rule-driven transformation actually executed | Rules generated but never applied (raw copy) | Fixed in post-Phase-7 remediation |
| Human-review pause/resume actually functions | No checkpointer; `Command(resume=...)` always raised | Fixed in post-Phase-7 remediation |
| GX/dbt wired into the executable graph | Verified only as standalone scripts | Fixed in post-Phase-7 remediation |
| 5+ tables in default migration scope | 2 of 8 tables | Fixed in post-Phase-7 remediation |
| Test coverage of real functions | 2 tests on inline dict literals | 28 tests on real functions |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Snowflake trial setup takes longer than expected | BigQuery free tier as fallback - executor.py already has the Snowflake engine isolated in one function |
| LangFuse callback not firing correctly | Test with a single ai_mapper call before running full pipeline |
| GX version API differences | Pin to `great-expectations==0.18.x`, use in-memory approach to avoid context/config overhead |
| Seed script slow for 80k+ rows | Use bulk inserts with `executemany`, batch size 500 |
| `blood_grp_cd` and similar codes all get high confidence | Prompt engineering in ai_mapper system prompt - explicitly instruct low confidence for single/dual char codes without accompanying lookup tables |
| Time overrun | Phase 6 (type mapping) is the lowest priority - skip if needed, everything else passes without it |
