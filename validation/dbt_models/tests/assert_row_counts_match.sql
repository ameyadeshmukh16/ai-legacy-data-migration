-- Singular test: fails when any migrated table has a source/target row-count
-- mismatch. dbt marks a singular test as failed if the query returns >= 1 row.
SELECT *
FROM {{ ref('row_count_reconciliation') }}
