-- Compares null rates per column between source profile and target,
-- both sourced from reconciliation_report.json via the null_rates_seed.
-- Flags any column where the null rate delta exceeds 2%.
SELECT
    table_name,
    column_name,
    source_null_rate,
    target_null_rate,
    ABS(source_null_rate - target_null_rate) AS null_rate_delta,
    CASE WHEN ABS(source_null_rate - target_null_rate) <= 0.02 THEN 'PASS' ELSE 'FAIL' END AS status
FROM {{ ref('null_rates_seed') }}
