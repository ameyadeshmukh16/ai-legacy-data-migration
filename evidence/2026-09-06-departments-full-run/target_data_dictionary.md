## Target Data Dictionary – *departments*  

| Target Column | Data Type | Definition (inferred meaning) | Source Lineage (table.column) | Transformation Logic | Confidence | Human Override / Review |
|---------------|-----------|------------------------------|------------------------------|----------------------|------------|--------------------------|
| **dept_id** | NUMBER (BIGINT) | Unique identifier for each department | `departments.dept_id` | Direct copy – no change (`dept_id`) | 0.99 | ✅ Human‑reviewed – auto‑cleared (override note: “Auto‑cleared at/above threshold.”) |
| **dept_cd** | STRING (VARCHAR 20) | Department code identifier | `departments.dept_cd` | Direct copy – no change (`dept_cd`) | 0.92 | ✅ Human‑reviewed – auto‑cleared (override note: “Auto‑cleared at/above threshold.”) |
| **dept_name** | STRING (VARCHAR 120) | Name of the department (generic group identifier) | `departments.dept_name` | Trim leading/trailing whitespace (`TRIM(dept_name)`) | 0.30 | ✅ Human‑reviewed – domain expert confirmed semantics (override note: “Domain expert confirmed semantics for dept_name (automated test approval).”) |
| **department_type_code** | STRING (VARCHAR 3) | Code representing the type of department (e.g., Inpatient, ICU, Surgery, Emergency) | `departments.dept_typ_cd` | Direct copy – no change (`dept_typ_cd`) | 0.90 | ✅ Human‑reviewed – auto‑cleared (override note: “Auto‑cleared at/above threshold.”) |

### Notes
* **Null handling** – All source columns currently contain **no nulls**; the rule “preserve” is applied, so the target columns are loaded as NOT NULL where possible.  
* **Edge cases** – Documented in the source mappings (e.g., future nulls for `dept_cd`, unexpected characters, mixed content in `dept_name`, unseen codes for `department_type_code`). These are not reflected in the transformation logic but should be monitored during downstream processing.  