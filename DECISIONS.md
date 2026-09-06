# DECISIONS.md

## Confidence Threshold
Default `CONFIDENCE_THRESHOLD=0.80`. This is a conservative routing threshold, not a statistical probability.

**Healthcare example — why 0.80 is conservative, not arbitrary, for clinical data:** `patient_records.blood_grp_cd` uses two/three-character codes (`'AP'`, `'AN'`, `'BP'`, `'BN'`, `'OP'`, `'ON'`, `'ABP'`, `'ABN'`) with no accompanying lookup table in the source schema. An LLM can pattern-match these to blood group notation (A+/A-/B+/B-/O+/O-/AB+/AB-) fairly confidently from the code shape alone — but that inference has zero verification against ground truth, and a wrong mapping here is not a cosmetic error, it's a patient-safety-adjacent one. The AI mapper's system prompt explicitly instructs lower confidence for short undocumented codes without a lookup table for exactly this reason; in practice `blood_grp_cd` scores well below 0.80 and is routed to human review rather than auto-approved.

## Human-in-the-Loop
Every mapping is evaluated. Low-confidence mappings pause the graph. A human must approve, reject or override. Rejection blocks migration. Low-confidence execution requires `review_status="HUMAN_APPROVED"` and a meaningful `override_note`.

Auto-approved and human-approved mappings are distinguished explicitly rather than conflated:
- Confidence ≥ threshold → `review_status="AUTO_APPROVED"`, `human_reviewed=false`. An automated confidence gate is not a human review, and the record no longer claims it was one.
- Human decision → `review_status="HUMAN_APPROVED"` (or `HUMAN_REJECTED`), `human_reviewed=true`, plus `reviewer_id` and `reviewer_role`, which are **required** on every decision submitted to the interrupt resume and are persisted into the approved mapping, the `human_mapping_approved` audit event, and the LangFuse score. This gives the audit trail an accountable identity for each high-risk approval — a prerequisite for the reviewer-qualification routing described under Medication and Free-Text Clinical Fields.

**Realistic human override examples from this schema:**
- `blood_grp_cd` (confidence ~0.68): AI proposes `'AP'` → `'A+'` etc. based on code-shape pattern matching. A domain expert override note would read something like *"Confirmed AP/AN/BP/BN/OP/ON/ABP/ABN map to standard blood group notation — verified against hospital lab reference sheet."* Without that confirmation, the mapping cannot execute.
- `appointments.pri_lvl` (confidence ~0.55): a bare integer 1–5 with no documented direction. AI can propose a mapping but cannot know whether 1 means highest or lowest priority. Override note: *"Confirmed with scheduling team: 1 = highest priority (matches legacy triage convention)."*
- `billing.ins_clm_st` (`'PN'`, `'AP'`, `'RJ'`, `'PP'`): `'PP'` is genuinely ambiguous between "Partially Paid" and "Pre-Processing" — both are plausible claim-status readings. Override note: *"Confirmed with billing team: PP = Partially Paid in this system, not Pre-Processing."*

## Medication and Free-Text Clinical Fields
`med_records.dosage_txt` (`'BD'`, `'TDS'`, `'SOS'`, `'1x2'`) and `dur_days` (mixed `'7'`, `'7 days'`, `'one week'`) are pharmaceutical shorthand and genuinely inconsistent free text, respectively. These are flagged for **clinical SME review specifically**, not just AI-confidence-based human review generically — a domain expert with no pharmacy background can confirm a blood-group code from a reference sheet, but dosage abbreviation interpretation error carries direct clinical risk and warrants a pharmacist or clinician, not just "any" reviewer. The platform now captures `reviewer_id`/`reviewer_role` on every human decision, so the audit trail records *who* approved a given field; enforcing that a specific role (e.g. `clinical_sme`) must be the one to approve these particular columns is the remaining step, noted for a production deployment (see Future Extensions).

## Audit Immutability
Events are hash chained with SHA-256 using the previous event hash and canonical event JSON. Production should additionally store the log in WORM/append-only storage with restricted IAM.

## Sensitive Data
Legacy data may contain PII, health, financial or other regulated information. Controls include no credential logging, minimized samples, masking/tokenization of sensitive values before LLM submission, encryption in transit/at rest, least privilege and restricted audit access. Applicable regulatory requirements must be determined by the organization.

**Field-level classification for this schema:**
- **Patient PII**: `patient_records.first_name`, `last_name`, `dob` — direct identifiers, sent to the LLM only as column metadata (name, type, null rate, cardinality, a capped sample of raw values) via `agents/schema_profiler.py`, not as bulk row exports.
- **Clinical data**: `patient_records.pat_st_cd`, `blood_grp_cd`; `med_records.med_cd`, `dosage_txt`; `lab_orders.tst_cd`, `rslt_txt` — health information tied to a patient record via FK, regulated under HIPAA (or equivalent) in a real deployment.
- **Insurance/financial data**: `patient_records.ins_prvdr_cd`; `billing.ins_clm_st`, `bill_amt`, `pay_mthd_cd` — financial/insurance information, typically also regulated.

Masking/minimization approach: the AI mapper (`agents/ai_mapper.py`) sends the LLM column-level metadata and up to 20 sample values per column (`agents/schema_profiler.py`'s `sample_values`), never a full row or a joined patient record — so the model never sees, e.g., a patient's name alongside their blood group in the same prompt. A production deployment should additionally mask or hash the sample values themselves for the PII/clinical columns above before they leave the source environment, which this capstone scope does not implement.

## LLM Privacy
Use an approved provider, appropriate retention/privacy settings and masked/minimized samples. Do not send unnecessary row-level data.

## Source Safety
The source database is read-only. No UPDATE/DELETE is executed.

## Target Safety
Load to run-specific staging tables. Publish only after validation succeeds. On any failure the run's staging tables are dropped automatically (`migration.executor.rollback_run`, driven by `run_migration`), so a blocked run leaves nothing partially loaded in the target.

## Failure Strategy
Transient failures use exponential backoff. Each run has a unique run ID and isolated staging objects. Non-transient validation/transformation errors block completion, emit a `run_failed` audit event, and trigger rollback of the run's target tables (`run_rolled_back`).

## Validation
Migration is complete only after all of these pass: GX source baseline, GX post-extraction (on **raw** extracted rows, before transformation — real no-columns-dropped check), GX post-load, row-count/null-rate reconciliation, **value-distribution reconciliation** (each non-identity rule's `logic` replayed as a GROUP BY against the source and matched bucket-for-bucket against the loaded target), and dbt (zero-row diagnostic models + singular tests — a `FAIL` row now actually fails dbt). Each stage raises and blocks; nothing downstream runs.

### Why the post-extraction checkpoint moved
Previously the executor built one rule-driven `SELECT` that extracted *and* transformed in a single query, so the "post-extraction" checkpoint was really running on already-transformed data and its no-columns-dropped check was a hardcoded `True`. Extraction and transformation are now separate steps: raw extract → GX post-extraction on the raw rows/columns → apply rules → load. The checkpoint again guards the boundary its name implies.

### Why value-distribution reconciliation, not just cardinality
Row counts and cardinality can both match while the semantics are wrong: source `{A:5000, I:4000}` and target `{Active:5000, Inactive:4000}` have identical cardinality, but so would a target that mapped `A→Inactive`. The distribution reconciler replays the rule's own transformation over the source distribution and requires the resulting per-value counts to equal the target's exactly (deterministic expression + same source rows ⇒ no tolerance needed; the AST validator forbids non-deterministic `logic`).

## Reproducibility
Record run ID, schema profile, prompt IDs, AI suggestions, human decisions (with `reviewer_id`/`reviewer_role`), approved rules, validation output and generated documentation. The audit chain is bracketed by `run_started` … `run_completed`, or `run_failed` + `run_rolled_back` on failure.

## AI-Generated SQL Validation
Each rule's LLM-generated `logic` passes a fast regex allow-list/denylist and then a `sqlglot` AST check (`_ast_validate_logic`): the expression must parse as a single scalar expression over exactly the declared source column, with no subqueries, table references, joins, CTEs, DML/DDL, or non-allowlisted function calls. This replaces the earlier regex-only check, which allowed scalar subqueries (`SELECT` was never in the denylist). A fully constrained transformation DSL compiled to SQL is the production endpoint; the AST check is the capstone-appropriate midpoint.

## Trade-off
Human review adds latency but reduces semantic corruption risk.

## Why Mermaid for Lineage
`lineage/lineage_generator.py` outputs Mermaid diagrams (`docs/lineage.md`) rather than a dedicated lineage tool (OpenLineage, Marquez, etc.) because it's portable — a plain fenced code block that renders natively in GitHub and VS Code with zero external services, licenses, or infrastructure to stand up. For an auditable pipeline where the lineage doc needs to sit alongside the rest of the run's evidence (audit log, reconciliation report, data dictionary) and be reviewable by anyone with repo access, that portability outweighs the richer querying a dedicated lineage tool would offer. A production deployment migrating many more tables might outgrow this and want a real lineage backend — noted below.

## Future Extensions
PII detection and masking prior to LLM submission, a visual review UI in place of the JSON `human_review_queue.json` contract, Airflow for scheduling, CDC/incremental migration, a dedicated lineage backend (OpenLineage/Marquez) if the current Mermaid-per-run approach doesn't scale past this project's table count, **enforced** reviewer-role routing so clinical fields require a `clinical_sme` approval specifically (the identity is now captured; the enforcement is not), a durable LangGraph checkpointer (`SqliteSaver`/`PostgresSaver`) so HITL pause/resume survives a process restart, streamed/`COPY INTO` Snowflake loading for large tables, a constrained transformation DSL in place of AST-validated raw SQL, and WORM audit storage.
