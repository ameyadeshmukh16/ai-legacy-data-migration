# DECISIONS.md

## Confidence Threshold
Default `CONFIDENCE_THRESHOLD=0.80`. This is a conservative routing threshold, not a statistical probability.

## Human-in-the-Loop
Every mapping is evaluated. Low-confidence mappings pause the graph. A human must approve, reject or override. Rejection blocks migration. Low-confidence execution requires `human_reviewed=true` and a meaningful `override_note`.

## Audit Immutability
Events are hash chained with SHA-256 using the previous event hash and canonical event JSON. Production should additionally store the log in WORM/append-only storage with restricted IAM.

## Sensitive Data
Legacy data may contain PII, health, financial or other regulated information. Controls include no credential logging, minimized samples, masking/tokenization of sensitive values before LLM submission, encryption in transit/at rest, least privilege and restricted audit access. Applicable regulatory requirements must be determined by the organization.

## LLM Privacy
Use an approved provider, appropriate retention/privacy settings and masked/minimized samples. Do not send unnecessary row-level data.

## Source Safety
The source database is read-only. No UPDATE/DELETE is executed.

## Target Safety
Load to run-specific staging tables. Publish only after validation succeeds.

## Failure Strategy
Transient failures use exponential backoff. Each run has a unique run ID and isolated staging objects. Non-transient validation/transformation errors block completion.

## Validation
Migration is complete only after source baseline, post-extraction, post-load and reconciliation checks pass.

## Reproducibility
Record run ID, schema profile, prompt IDs, AI suggestions, human decisions, approved rules, validation output and generated documentation.

## Trade-off
Human review adds latency but reduces semantic corruption risk.

## Future Extensions
PII detection, visual review UI, Airflow, CDC/incremental migration, lineage graphs and WORM audit storage.
