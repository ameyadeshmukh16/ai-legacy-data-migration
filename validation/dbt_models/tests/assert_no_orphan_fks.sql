-- Singular test: fails when the target contains an appointments row whose
-- pat_id has no matching patient_records.pat_id. dbt marks a singular test as
-- failed if the query returns >= 1 row. When the run scope excludes either
-- table, fk_integrity_check returns no rows and this test passes.
SELECT *
FROM {{ ref('fk_integrity_check') }}
