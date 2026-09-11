# Data Lineage

Auto-generated from `data/approved_mappings.json` and `data/transformation_rules.json`. Green = auto-approved (confidence >= 0.90), amber = passed threshold (0.80-0.89), red = required human review (confidence < 0.80).

## departments

```mermaid
graph LR
    subgraph src_departments["Source: departments"]
        S1["dept_id BIGINT"]
        S2["dept_cd VARCHAR(20)"]
        S3["dept_name VARCHAR(120)"]
        S4["dept_typ_cd VARCHAR(3)"]
    end

    subgraph transforms["Transformations"]
        T1["dept_id"]
        T2["dept_cd"]
        T3["TRIM(dept_name)"]
        T4["dept_typ_cd"]
    end

    subgraph tgt_departments["Target: departments"]
        TG1["dept_id"]
        TG2["dept_cd"]
        TG3["dept_name"]
        TG4["dept_typ_cd"]
    end

    S1 -->|"conf: 0.98"| T1 --> TG1
    S2 -->|"conf: 0.93"| T2 --> TG2
    S3 -->|"conf: 0.40 ✓ reviewed"| T3 --> TG3
    S4 -->|"conf: 0.85"| T4 --> TG4

    style T1 fill:#00d4aa
    style T2 fill:#00d4aa
    style T3 fill:#ef4444
    style T4 fill:#f59e0b
```
