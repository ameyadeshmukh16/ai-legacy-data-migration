import json
import re
from pathlib import Path

GREEN = "#00d4aa"
AMBER = "#f59e0b"
RED = "#ef4444"


def _confidence_color(confidence):
    if confidence >= 0.90:
        return GREEN
    if confidence >= 0.80:
        return AMBER
    return RED


def _sanitize_id(text_value):
    return re.sub(r"[^A-Za-z0-9_]", "_", text_value)


def _source_type(schema_profile, source_table, source_column):
    table = schema_profile.get("tables", {}).get(source_table, {})
    for col in table.get("columns", []):
        if col["name"] == source_column:
            return col["data_type"]
    return "UNKNOWN"


_CASE_PAIR = re.compile(r"WHEN\s+\w+\s*=\s*'([^']*)'\s+THEN\s+'([^']*)'", re.IGNORECASE)
MAX_SUMMARY_LEN = 60

def _transformation_summary(logic):
    if not logic:
        return "direct map"
    logic = logic.strip()
    pairs = _CASE_PAIR.findall(logic)
    if pairs:
        mapped = ", ".join(f"{src}→{tgt}" for src, tgt in pairs)
        summary = f"CASE: {mapped}"
    elif logic.upper().startswith("CAST"):
        summary = logic
    else:
        summary = logic
    if len(summary) > MAX_SUMMARY_LEN:
        summary = summary[:MAX_SUMMARY_LEN - 3] + "..."
    return summary


def _escape_label(text_value):
    return text_value.replace('"', "'")


def _build_rule_lookup(rules):
    lookup = {}
    for rule in rules:
        key = (rule.get("source_column"), rule.get("target_column"))
        lookup[key] = rule
    return lookup


def _group_by_source_table(approved_mappings):
    grouped = {}
    for mapping in approved_mappings:
        grouped.setdefault(mapping["source_table"], []).append(mapping)
    return grouped


def build_diagram_for_table(source_table, mappings, rule_lookup, schema_profile):
    lines = [f"## {source_table}", "", "```mermaid", "graph LR"]

    src_id = _sanitize_id(f"src_{source_table}")
    tgt_ids = {}
    lines.append(f'    subgraph {src_id}["Source: {source_table}"]')
    for i, m in enumerate(mappings, start=1):
        dtype = _source_type(schema_profile, source_table, m["source_column"])
        lines.append(f'        S{i}["{_escape_label(m["source_column"])} {_escape_label(dtype)}"]')
    lines.append("    end")
    lines.append("")

    lines.append('    subgraph transforms["Transformations"]')
    for i, m in enumerate(mappings, start=1):
        rule = rule_lookup.get((m["source_column"], m["target_column"]), {})
        summary = _transformation_summary(rule.get("logic"))
        lines.append(f'        T{i}["{_escape_label(summary)}"]')
    lines.append("    end")
    lines.append("")

    target_tables = sorted({m["target_table"] for m in mappings})
    for target_table in target_tables:
        tgt_id = _sanitize_id(f"tgt_{target_table}")
        tgt_ids[target_table] = tgt_id
        lines.append(f'    subgraph {tgt_id}["Target: {target_table}"]')
        for i, m in enumerate(mappings, start=1):
            if m["target_table"] != target_table:
                continue
            lines.append(f'        TG{i}["{_escape_label(m["target_column"])}"]')
        lines.append("    end")
        lines.append("")

    style_lines = []
    for i, m in enumerate(mappings, start=1):
        confidence = m["confidence"]
        was_auto_cleared = (m.get("override_note") or "").startswith("Auto-cleared")
        reviewed_marker = " ✓ reviewed" if m.get("human_reviewed") and not was_auto_cleared else ""
        label = f"conf: {confidence:.2f}{reviewed_marker}"
        lines.append(f'    S{i} -->|"{label}"| T{i} --> TG{i}')
        color = _confidence_color(confidence)
        style_lines.append(f"    style T{i} fill:{color}")

    lines.append("")
    lines.extend(style_lines)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def generate_lineage(approved_mappings, rules, schema_profile, output_path="docs/lineage.md"):
    rule_lookup = _build_rule_lookup(rules)
    grouped = _group_by_source_table(approved_mappings)

    sections = ["# Data Lineage", "", "Auto-generated from `data/approved_mappings.json` and `data/transformation_rules.json`. "
                "Green = auto-approved (confidence >= 0.90), amber = passed threshold (0.80-0.89), "
                "red = required human review (confidence < 0.80).", ""]
    for source_table in sorted(grouped):
        sections.append(build_diagram_for_table(source_table, grouped[source_table], rule_lookup, schema_profile))

    content = "\n".join(sections)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


if __name__ == "__main__":
    approved_mappings = json.loads(Path("data/approved_mappings.json").read_text(encoding="utf-8"))
    rules = json.loads(Path("data/transformation_rules.json").read_text(encoding="utf-8"))
    schema_profile = json.loads(Path("data/schema_profile.json").read_text(encoding="utf-8"))
    out = generate_lineage(approved_mappings, rules, schema_profile)
    print(f"Lineage diagram written to {out}")
