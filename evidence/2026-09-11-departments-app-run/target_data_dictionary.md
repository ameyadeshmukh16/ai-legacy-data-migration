## Target Data Dictionary – `departments` Table  

| Target Column | Target Type | Definition (inferred meaning) | Source Lineage | Transformation Logic | Confidence | Human Override |
|--------------|------------|--------------------------------|----------------|----------------------|------------|----------------|
| **dept_id** | NUMBER (BIGINT) | Unique identifier for each department (primary key) | `departments.dept_id` | Direct copy – no change | 0.98 | No (auto‑approved) |
| **dept_cd** | STRING (VARCHAR) | Department code identifier | `departments.dept_cd` | Direct copy – no change | 0.93 | No (auto‑approved) |
| **dept_name** | STRING (VARCHAR) | Free‑text label of the department (e.g., “Cardiology”, “Smith, Rowland and Clayton”) | `departments.dept_name` | `TRIM(dept_name)` – remove leading/trailing whitespace only | 0.40 | **Yes** – reviewed by *reviewer‑001* (data SME) and approved |
| **dept_typ_cd** | STRING (VARCHAR) | Department type code (e.g., IPD, ICU, SRG, ER) | `departments.dept_typ_cd` | Direct copy – no change | 0.85 | No (auto‑approved) |

### Notes & Edge Cases
| Target Column | Edge Cases |
|--------------|------------|
| **dept_id** | None identified (no nulls, primary‑key‑like values). |
| **dept_cd** | Future codes not represented in the current sample may appear. |
| **dept_name** | • Values that are only whitespace become empty strings after `TRIM`. <br>• Some entries look like company names rather than department names, but the SME confirmed they are valid free‑text labels. |
| **dept_typ_cd** | New or unexpected department type codes could be introduced later. |

*All mappings are based on the approved mappings and rule set provided; no additional business assumptions were introduced.*