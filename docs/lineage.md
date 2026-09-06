# Data Lineage

Auto-generated from `data/approved_mappings.json` and `data/transformation_rules.json`. Green = auto-approved (confidence >= 0.90), amber = passed threshold (0.80-0.89), red = required human review (confidence < 0.80).

## appointments

```mermaid
graph LR
    subgraph src_appointments["Source: appointments"]
        S1["appt_typ_cd VARCHAR(3)"]
        S2["pri_lvl INTEGER"]
    end

    subgraph transforms["Transformations"]
        T1["CASE: NEW→New, FLW→Follow-up, EMR→Emergency, REV→Review"]
        T2["CAST(src AS INTEGER)"]
    end

    subgraph tgt_appointments["Target: appointments"]
        TG1["appointment_type"]
        TG2["priority_level"]
    end

    S1 -->|"conf: 0.95"| T1 --> TG1
    S2 -->|"conf: 0.55 ✓ reviewed"| T2 --> TG2

    style T1 fill:#00d4aa
    style T2 fill:#ef4444
```

## patient_records

```mermaid
graph LR
    subgraph src_patient_records["Source: patient_records"]
        S1["pat_st_cd VARCHAR(2)"]
        S2["dob VARCHAR(10)"]
        S3["blood_grp_cd VARCHAR(3)"]
        S4["gndr_cd VARCHAR(1)"]
    end

    subgraph transforms["Transformations"]
        T1["CASE: A→Active, D→Discharged"]
        T2["CAST(REGEXP_REPLACE(src, format-normalize) AS DATE)"]
        T3["CASE: AP→A+, AN→A-, BP→B+, BN→B-, OP→O+, ON→O-, ABP→AB+, ..."]
        T4["CASE: M→Male, F→Female, U→Unknown"]
    end

    subgraph tgt_patient_records["Target: patient_records"]
        TG1["patient_status"]
        TG2["date_of_birth"]
        TG3["blood_group"]
        TG4["gender"]
    end

    S1 -->|"conf: 0.82 ✓ reviewed"| T1 --> TG1
    S2 -->|"conf: 0.91"| T2 --> TG2
    S3 -->|"conf: 0.68 ✓ reviewed"| T3 --> TG3
    S4 -->|"conf: 0.88 ✓ reviewed"| T4 --> TG4

    style T1 fill:#f59e0b
    style T2 fill:#00d4aa
    style T3 fill:#ef4444
    style T4 fill:#f59e0b
```
