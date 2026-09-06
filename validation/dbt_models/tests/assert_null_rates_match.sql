-- Singular test: fails when any migrated column's source-to-target null rate
-- delta exceeds 2%. dbt marks a singular test as failed if the query returns
-- >= 1 row.
SELECT *
FROM {{ ref('null_rate_check') }}
