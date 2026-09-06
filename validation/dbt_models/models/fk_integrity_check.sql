-- Verifies FK relationships are intact in the Snowflake target for the
-- given migration run: every appointments.pat_id must exist in
-- patient_records.pat_id. run_id is passed via --vars (same run_id
-- used by migration/executor.py to name the target tables).
{% set run_id = var('run_id', 'unset') | replace('-', '_') %}
{% set appointments_table = source('migration_target', 'appointments_' ~ run_id) %}
{% set patients_table = source('migration_target', 'patient_records_' ~ run_id) %}

SELECT
    a."appt_id",
    a."pat_id" AS orphaned_pat_id
FROM {{ appointments_table }} a
LEFT JOIN {{ patients_table }} p ON a."pat_id" = p."pat_id"
WHERE a."pat_id" IS NOT NULL AND p."pat_id" IS NULL
