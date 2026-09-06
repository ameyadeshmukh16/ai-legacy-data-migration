import csv
import json
from pathlib import Path

REPORT_PATH = Path("data/reconciliation_report.json")
SEEDS_DIR = Path(__file__).parent / "seeds"


def generate_counts_seed():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    SEEDS_DIR.mkdir(exist_ok=True)
    out = SEEDS_DIR / "migration_counts_seed.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["table_name", "source_row_count", "target_row_count", "run_id"])
        for table, t in report["tables"].items():
            source_count = t.get("source", {}).get("row_count")
            target_count = t.get("target", {}).get("row_count")
            writer.writerow([table, source_count, target_count, report["run_id"]])
    return out


def generate_null_rates_seed():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    SEEDS_DIR.mkdir(exist_ok=True)
    out = SEEDS_DIR / "null_rates_seed.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["table_name", "column_name", "source_null_rate", "target_null_rate", "run_id"])
        for table, t in report["tables"].items():
            source_cols = t.get("source", {}).get("columns", {})
            target_cols = t.get("target", {}).get("columns", {})
            for col, source_stats in source_cols.items():
                target_stats = target_cols.get(col, {})
                writer.writerow([
                    table, col,
                    source_stats.get("null_rate"),
                    target_stats.get("null_rate"),
                    report["run_id"],
                ])
    return out


if __name__ == "__main__":
    counts = generate_counts_seed()
    rates = generate_null_rates_seed()
    print(f"Wrote {counts}")
    print(f"Wrote {rates}")
