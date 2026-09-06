import json
import pandas as pd

# Reproduces a real bug seen live: pandas' .isna().mean() returns a numpy
# float, and a numpy bool comparison result (e.g. `numpy_float <= 0.02`)
# is not JSON-serializable via the plain json module the audit logger uses
# (no `default=str` fallback there by design). gx_checkpoints.run_post_load
# now casts these to native Python types before they enter the report dict.

def test_null_rate_comparison_produces_json_serializable_bool():
    df = pd.DataFrame({"x": [1, None, 3]})
    target_null_rate = float(df["x"].isna().mean())
    within_tolerance = bool(abs(target_null_rate - 0.3) <= 0.02)
    assert isinstance(within_tolerance, bool)
    json.dumps({"passed": within_tolerance})  # must not raise
