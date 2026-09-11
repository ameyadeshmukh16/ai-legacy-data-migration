# LangFuse Trace Evidence — 2026-09-11 departments run

- **Run ID:** `a620702f-1714-4ce8-88c9-6a24757b7733`
- **Workflow:** `legacy_data_migration` (`departments`, single-table scope, driven through the
  Streamlit app — see `../README.md`)
- **Langfuse project:** `cmtpwsmah0smyad0clajuy3wn` ("My Project")
- **Provider / model:** Groq, `openai/gpt-oss-120b`

## Traces captured

| Node | Trace ID | Dashboard URL (requires Langfuse login for this project) | Observations | Real LLM generations | Notes |
|---|---|---|---:|---:|---|
| `ai_mapper` | `5c6f09e8c6cf4f5d74b6669c196ac6c5` | https://cloud.langfuse.com/project/cmtpwsmah0smyad0clajuy3wn/traces/5c6f09e8c6cf4f5d74b6669c196ac6c5 | 12 | 4 | Carries the `human_review_decision` score (see below) |
| `rule_generator` | `c9a71814b4fad43ec96fbddb8fc62da3` | https://cloud.langfuse.com/project/cmtpwsmah0smyad0clajuy3wn/traces/c9a71814b4fad43ec96fbddb8fc62da3 | 12 | 4 | |
| `doc_generator` | `4abbe022986edb68fa466cb29893158a` | https://cloud.langfuse.com/project/cmtpwsmah0smyad0clajuy3wn/traces/4abbe022986edb68fa466cb29893158a | 1 | 1 | |

Each node has one real `GENERATION` span per source column mapped/rule generated (4 columns
in `departments`), plus LangChain's own chain/runnable wrapper spans (`CHAIN` type) around
each call. `ai_mapper`'s total real-LLM latency across its 4 generations was **6.53s**;
`rule_generator`'s was 6.38s; `doc_generator`'s single call was 1.81s.

## `human_review_decision` score (on the `ai_mapper` trace)

```json
{
  "name": "human_review_decision",
  "value": 1.0,
  "data_type": "BOOLEAN",
  "comment": "mapping_index=2 column=dept_name note=Confirmed: dept_name is the free-text department label; TRIM only, no domain constraint. reviewer=reviewer-001/data_sme"
}
```

This is the score `config/observability.score_human_review_decision` attached when the
reviewer approved `dept_name` (confidence 0.30) through the Streamlit **Human Review** page —
the same decision recorded in `../audit_log_snapshot.json`'s `human_mapping_approved` event
and `../approved_mappings.json`.

## How these trace IDs were obtained (reproducible, no re-run needed)

`config/observability.py`'s `trace_id_for(run_id, node_name)` is deterministic
(`Langfuse.create_trace_id(seed=f"{run_id}:{node_name}")` — the Langfuse SDK guarantees the
same seed always produces the same trace ID). Anyone with this repo and the run_id above can
recompute the exact same trace IDs, and — with valid Langfuse credentials for this project —
pull the same live trace data back:

```python
from config.observability import trace_id_for
trace_id_for("a620702f-1714-4ce8-88c9-6a24757b7733", "ai_mapper")
# -> 5c6f09e8c6cf4f5d74b6669c196ac6c5
```

The three files below were captured with exactly this approach: compute the trace ID, then
`client.api.trace.get(trace_id)` against the live Langfuse API — no new LLM calls were made
to produce this evidence; it is a re-export of what the 2026-09-11 run already produced.

## What's committed in this folder

- `trace_ai_mapper.json` / `trace_rule_generator.json` / `trace_doc_generator.json` —
  exported via the Langfuse API (`client.api.trace.get`), containing the real system/human
  prompts, structured LLM outputs, model (`openai/gpt-oss-120b`), per-call timestamps and
  latency, and (for `ai_mapper`) the `human_review_decision` score above.
- `ai_mapper_trace_screenshot.png` — a dashboard screenshot of the `ai_mapper` trace tree
  (4 generations + the human-review score), captured manually from the Langfuse UI at the
  URL above.

## Why the dashboard links aren't sufficient on their own

Langfuse traces are private by default for this project — the URLs above only render for
someone logged into this Langfuse account. The exported JSON files are the self-contained,
independently-inspectable evidence: no live access is needed to see the real prompts,
completions, model, and timing that produced this run's AI mappings and transformation
rules.
