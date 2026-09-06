-- Verifies FK relationships are intact in the Snowflake target for the
-- given migration run: every appointments.pat_id must exist in
-- patient_records.pat_id. run_id is passed via --vars (same run_id
-- used by migration/executor.py to name the target tables).
-- Skips gracefully (returns no rows) when TABLES_TO_MIGRATE for this run
-- doesn't include both appointments and patient_records, rather than
-- failing dbt over a table that was never supposed to exist.
{% set run_id = var('run_id', 'unset') | replace('-', '_') %}
{% set appointments_rel = adapter.get_relation(database=source('migration_target', 'appointments_' ~ run_id).database, schema=source('migration_target', 'appointments_' ~ run_id).schema, identifier=source('migration_target', 'appointments_' ~ run_id).identifier) %}
{% set patients_rel = adapter.get_relation(database=source('migration_target', 'patient_records_' ~ run_id).database, schema=source('migration_target', 'patient_records_' ~ run_id).schema, identifier=source('migration_target', 'patient_records_' ~ run_id).identifier) %}

{% if appointments_rel is none or patients_rel is none %}

SELECT NULL AS appt_id, NULL AS orphaned_pat_id WHERE FALSE

{% else %}

SELECT
    a."appt_id",
    a."pat_id" AS orphaned_pat_id
FROM {{ appointments_rel }} a
LEFT JOIN {{ patients_rel }} p ON a."pat_id" = p."pat_id"
WHERE a."pat_id" IS NOT NULL AND p."pat_id" IS NULL

{% endif %}
