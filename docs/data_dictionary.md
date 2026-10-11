# Data dictionary

MIMIC-IV Clinical Database Demo v2.2 (`hosp` module), as used by this project.
Type, completeness and distinct counts are measured by `scripts/build_data_dictionary.py`;
meanings follow the [MIMIC-IV documentation](https://mimic.mit.edu/docs/iv/modules/hosp/).

## `patients`

One row per patient. **100 rows.**

| Field | Type | Non-null | Distinct | Meaning | Known issues |
|---|---|---|---|---|---|
| `subject_id` | BIGINT | 100% | 100 | Patient identifier, links every table. | Pseudonymised (salted SHA-256) in all published outputs. |
| `gender` | VARCHAR | 100% | 2 | Administrative gender (F/M). |  |
| `anchor_age` | BIGINT | 100% | 50 | Age in `anchor_year`. | Ages over 89 are set to 91 (HIPAA); no date of birth is released. |
| `anchor_year` | BIGINT | 100% | 62 | Shifted year in which the patient was `anchor_age`. | Dates are shifted per patient into 2100-2200; only intervals within a patient are meaningful. |
| `anchor_year_group` | VARCHAR | 100% | 2 | Real 3-year window that `anchor_year` maps to. | The only link to real calendar time; use for era effects (e.g. ICD-9 to ICD-10 switch in Oct 2015). |
| `dod` | DATE | 31% | 31 | Date of death, in-hospital or from state records. | Out-of-hospital deaths captured only up to 1 year after last discharge; no cause of death. |

## `admissions`

One row per hospital admission (hadm_id). **275 rows.**

| Field | Type | Non-null | Distinct | Meaning | Known issues |
|---|---|---|---|---|---|
| `subject_id` | BIGINT | 100% | 100 | Patient identifier. |  |
| `hadm_id` | BIGINT | 100% | 275 | Admission identifier. | Dropped from published outputs. |
| `admittime` | TIMESTAMP | 100% | 275 | Admission timestamp (shifted). |  |
| `dischtime` | TIMESTAMP | 100% | 275 | Discharge timestamp (shifted). |  |
| `deathtime` | TIMESTAMP | 5% | 15 | In-hospital death timestamp. | Null unless the patient died in this admission; matched `patients.dod` on every row in the 2026-10-11 probe. |
| `admission_type` | VARCHAR | 100% | 9 | Urgency of admission. |  |
| `admit_provider_id` | VARCHAR | 100% | 170 | Admitting provider (anonymised). |  |
| `admission_location` | VARCHAR | 100% | 10 | Where the patient came from. |  |
| `discharge_location` | VARCHAR | 85% | 10 | Where the patient went. | Null for some admissions. |
| `insurance` | VARCHAR | 100% | 3 | Insurance category. |  |
| `language` | VARCHAR | 100% | 2 | Preferred language. |  |
| `marital_status` | VARCHAR | 96% | 4 | Marital status. | Incomplete. |
| `race` | VARCHAR | 100% | 14 | Recorded race/ethnicity. | Includes UNKNOWN / UNABLE TO OBTAIN / OTHER. |
| `edregtime` | TIMESTAMP | 66% | 181 | Emergency department registration time. | Null when not admitted via ED. |
| `edouttime` | TIMESTAMP | 66% | 181 | Emergency department exit time. | Null when not admitted via ED. |
| `hospital_expire_flag` | BIGINT | 100% | 2 | 1 if the patient died in this admission. |  |

## `diagnoses_icd`

One row per billed diagnosis per admission. **4,506 rows.**

| Field | Type | Non-null | Distinct | Meaning | Known issues |
|---|---|---|---|---|---|
| `subject_id` | BIGINT | 100% | 100 | Patient identifier. |  |
| `hadm_id` | BIGINT | 100% | 275 | Admission the diagnosis was billed on. |  |
| `seq_num` | BIGINT | 100% | 39 | Diagnosis position; 1 = principal. | Billing priority, not strictly clinical importance. |
| `icd_code` | VARCHAR | 100% | 1,472 | ICD-9-CM or ICD-10-CM code, no dot. | Coding system changes mid-dataset (US switch, Oct 2015). |
| `icd_version` | BIGINT | 100% | 2 | 9 or 10. | Must be used with `icd_code`: the same string can be valid in both systems. |

## `labevents`

One row per lab result (all lab tests; this project uses troponin T, itemid 51003). **107,727 rows.**

| Field | Type | Non-null | Distinct | Meaning | Known issues |
|---|---|---|---|---|---|
| `labevent_id` | BIGINT | 100% | 107,727 | Lab result identifier. |  |
| `subject_id` | BIGINT | 100% | 100 | Patient identifier. |  |
| `hadm_id` | BIGINT | 74% | 252 | Admission the result belongs to. | Null on ~26% of all rows and 29% of troponin rows: outpatient and pre-admission ED draws. |
| `specimen_id` | BIGINT | 100% | 11,122 | Specimen identifier; groups results from one sample. |  |
| `itemid` | BIGINT | 100% | 498 | Lab test, see `d_labitems`. | 51003 = Troponin T (asserted at load). |
| `order_provider_id` | VARCHAR | 16% | 151 | Ordering provider (anonymised). |  |
| `charttime` | TIMESTAMP | 100% | 5,864 | Time the specimen was taken (shifted). |  |
| `storetime` | TIMESTAMP | 99% | 14,573 | Time the result was stored. |  |
| `value` | VARCHAR | 91% | 3,107 | Result as text. | De-identified to `___` on many rows. |
| `valuenum` | DOUBLE | 88% | 3,032 | Result as a number. | Null on 52% of troponin T rows: the result ('<0.01') is only in `comments`. |
| `valueuom` | VARCHAR | 87% | 50 | Unit. | Troponin T in ng/mL. |
| `ref_range_lower` | DOUBLE | 83% | 95 | Lower reference limit. |  |
| `ref_range_upper` | DOUBLE | 83% | 134 | Upper reference limit. | Troponin T upper limit 0.01 ng/mL; the lab comments put the MI threshold at 0.10. |
| `flag` | VARCHAR | 37% | 1 | 'abnormal' when outside the reference range. | Null for normal results. |
| `priority` | VARCHAR | 91% | 2 | ROUTINE / STAT. |  |
| `comments` | VARCHAR | 17% | 736 | Free-text result comment. | Carries the actual result for '<0.01' troponins. |

## Derived outputs (`outputs/`)

| File | Grain | Notes |
|---|---|---|
| `admission_mi_evidence.csv` | admission | MI code flags (any / principal position), troponin tested / peak / positive. Pseudonymised. |
| `mi_patients.csv` | patient with any MI evidence | First date per source, `found_by`, days from first coded MI to death. Pseudonymised. |
| `dq_checks_real.csv` / `dq_checks_cleaned.csv` | check | Pass/fail counts per validation rule. |
| `injected_errors_manifest.csv` | planted error | Every planted error by table and `_row_id`. |
| `planted_vs_found.csv` | error type | Planted, found, missed, cross-caught, false alarms. |
| `quarantine_log.csv` | cleaning rule | Rows quarantined by the cleaning step and why. |
| `linkage_sensitivity.csv` | linkage rule | Troponin linkage strict vs 24h window. |
| `cleaning_effect.csv` | dataset | MI patient count: real, with planted errors, after cleaning. |
