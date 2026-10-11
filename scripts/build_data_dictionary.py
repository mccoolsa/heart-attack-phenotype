"""Generate docs/data_dictionary.md: profiled from the data, meanings written by hand.

Type, completeness and distinct counts are measured on every run, so the
dictionary cannot drift from the data it describes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hapdq import io  # noqa: E402

DATA = ROOT / "data" / "raw" / "mimic-iv-demo-2.2" / "hosp"

# (meaning, known issues) - from the MIMIC-IV docs (mimic.mit.edu) and this project's probing
META = {
    "patients": {
        "_doc": "One row per patient.",
        "subject_id": ("Patient identifier, links every table.", "Pseudonymised (salted SHA-256) in all published outputs."),
        "gender": ("Administrative gender (F/M).", ""),
        "anchor_age": ("Age in `anchor_year`.", "Ages over 89 are set to 91 (HIPAA); no date of birth is released."),
        "anchor_year": ("Shifted year in which the patient was `anchor_age`.", "Dates are shifted per patient into 2100-2200; only intervals within a patient are meaningful."),
        "anchor_year_group": ("Real 3-year window that `anchor_year` maps to.", "The only link to real calendar time; use for era effects (e.g. ICD-9 to ICD-10 switch in Oct 2015)."),
        "dod": ("Date of death, in-hospital or from state records.", "Out-of-hospital deaths captured only up to 1 year after last discharge; no cause of death."),
    },
    "admissions": {
        "_doc": "One row per hospital admission (hadm_id).",
        "subject_id": ("Patient identifier.", ""),
        "hadm_id": ("Admission identifier.", "Dropped from published outputs."),
        "admittime": ("Admission timestamp (shifted).", ""),
        "dischtime": ("Discharge timestamp (shifted).", ""),
        "deathtime": ("In-hospital death timestamp.", "Null unless the patient died in this admission; matched `patients.dod` on every row in the 2026-10-11 probe."),
        "admission_type": ("Urgency of admission.", ""),
        "admit_provider_id": ("Admitting provider (anonymised).", ""),
        "admission_location": ("Where the patient came from.", ""),
        "discharge_location": ("Where the patient went.", "Null for some admissions."),
        "insurance": ("Insurance category.", ""),
        "language": ("Preferred language.", ""),
        "marital_status": ("Marital status.", "Incomplete."),
        "race": ("Recorded race/ethnicity.", "Includes UNKNOWN / UNABLE TO OBTAIN / OTHER."),
        "edregtime": ("Emergency department registration time.", "Null when not admitted via ED."),
        "edouttime": ("Emergency department exit time.", "Null when not admitted via ED."),
        "hospital_expire_flag": ("1 if the patient died in this admission.", ""),
    },
    "diagnoses_icd": {
        "_doc": "One row per billed diagnosis per admission.",
        "subject_id": ("Patient identifier.", ""),
        "hadm_id": ("Admission the diagnosis was billed on.", ""),
        "seq_num": ("Diagnosis position; 1 = principal.", "Billing priority, not strictly clinical importance."),
        "icd_code": ("ICD-9-CM or ICD-10-CM code, no dot.", "Coding system changes mid-dataset (US switch, Oct 2015)."),
        "icd_version": ("9 or 10.", "Must be used with `icd_code`: the same string can be valid in both systems."),
    },
    "labevents": {
        "_doc": "One row per lab result (all lab tests; this project uses troponin T, itemid 51003).",
        "labevent_id": ("Lab result identifier.", ""),
        "subject_id": ("Patient identifier.", ""),
        "hadm_id": ("Admission the result belongs to.", "Null on ~26% of all rows and 29% of troponin rows: outpatient and pre-admission ED draws."),
        "specimen_id": ("Specimen identifier; groups results from one sample.", ""),
        "itemid": ("Lab test, see `d_labitems`.", "51003 = Troponin T (asserted at load)."),
        "order_provider_id": ("Ordering provider (anonymised).", ""),
        "charttime": ("Time the specimen was taken (shifted).", ""),
        "storetime": ("Time the result was stored.", ""),
        "value": ("Result as text.", "De-identified to `___` on many rows."),
        "valuenum": ("Result as a number.", "Null on 52% of troponin T rows: the result ('<0.01') is only in `comments`."),
        "valueuom": ("Unit.", "Troponin T in ng/mL."),
        "ref_range_lower": ("Lower reference limit.", ""),
        "ref_range_upper": ("Upper reference limit.", "Troponin T upper limit 0.01 ng/mL; the lab comments put the MI threshold at 0.10."),
        "flag": ("'abnormal' when outside the reference range.", "Null for normal results."),
        "priority": ("ROUTINE / STAT.", ""),
        "comments": ("Free-text result comment.", "Carries the actual result for '<0.01' troponins."),
    },
}


def main() -> None:
    con = io.load(DATA)
    out = ["# Data dictionary", "",
           "MIMIC-IV Clinical Database Demo v2.2 (`hosp` module), as used by this project.",
           "Type, completeness and distinct counts are measured by `scripts/build_data_dictionary.py`;",
           "meanings follow the [MIMIC-IV documentation](https://mimic.mit.edu/docs/iv/modules/hosp/).", ""]
    for table, meta in META.items():
        n = con.execute(f"select count(*) from {table}").fetchone()[0]
        out += [f"## `{table}`", "", f"{meta['_doc']} **{n:,} rows.**", "",
                "| Field | Type | Non-null | Distinct | Meaning | Known issues |", "|---|---|---|---|---|---|"]
        for col, typ, *_ in con.execute(f"describe {table}").fetchall():
            if col == "_row_id":
                continue
            nn, nd = con.execute(f'select avg(("{col}" is not null)::int), count(distinct "{col}") from {table}').fetchone()
            meaning, issue = meta.get(col, ("", ""))
            out.append(f"| `{col}` | {typ} | {nn:.0%} | {nd:,} | {meaning} | {issue} |")
        out.append("")
    out += ["## Derived outputs (`outputs/`)", "",
            "| File | Grain | Notes |", "|---|---|---|",
            "| `admission_mi_evidence.csv` | admission | MI code flags (any / principal position), troponin tested / peak / positive. Pseudonymised. |",
            "| `mi_patients.csv` | patient with any MI evidence | First date per source, `found_by`, days from first coded MI to death. Pseudonymised. |",
            "| `dq_checks_real.csv` / `dq_checks_cleaned.csv` | check | Pass/fail counts per validation rule. |",
            "| `injected_errors_manifest.csv` | planted error | Every planted error by table and `_row_id`. |",
            "| `planted_vs_found.csv` | error type | Planted, found, missed, cross-caught, false alarms. |",
            "| `quarantine_log.csv` | cleaning rule | Rows quarantined by the cleaning step and why. |",
            "| `linkage_sensitivity.csv` | linkage rule | Troponin linkage strict vs 24h window. |",
            "| `cleaning_effect.csv` | dataset | MI patient count: real, with planted errors, after cleaning. |", ""]
    (ROOT / "docs" / "data_dictionary.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote docs/data_dictionary.md")


if __name__ == "__main__":
    main()
