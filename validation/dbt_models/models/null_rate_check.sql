-- Zero-row diagnostic: returns one row per column whose source-to-target
-- null rate delta exceeds 2%. A healthy migration produces an empty result.
-- Both null rates come from reconciliation_report.json via the null_rates_seed.
-- The singular test tests/assert_null_rates_match.sql fails dbt when this
-- model returns any rows.
SELECT
    table_name,
    column_name,
    source_null_rate,
    target_null_rate,
    ABS(source_null_rate - target_null_rate) AS null_rate_delta
FROM {{ ref('null_rates_seed') }}
WHERE ABS(source_null_rate - target_null_rate) > 0.02
