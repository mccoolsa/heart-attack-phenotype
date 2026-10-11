"""End-to-end run: load -> validate -> inject -> clean -> phenotype -> outputs.

    python -m hapdq.pipeline --data data/raw/mimic-iv-demo-2.2/hosp

Runs unchanged on the full credentialed MIMIC-IV (point --data at its hosp/ folder).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import clean as clean_mod
from . import inject as inject_mod
from . import io, phenotype, validation
from .pseudonymise import get_salt, pseudonymise

ROOT = Path(__file__).resolve().parents[2]


def run(data_dir: Path, out_dir: Path, codelist: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    salt = get_salt()

    # 1. load the real data and run the check suite on it as-is
    real = io.load(data_dir)
    real_results = validation.run_standard_checks(real)
    validation.results_frame(real_results).to_csv(out_dir / "dq_checks_real.csv", index=False)
    validation.completeness(real, "admissions").T.to_csv(out_dir / "completeness_admissions.csv", header=["share_non_null"])
    validation.completeness(real, "labevents").T.to_csv(out_dir / "completeness_labevents.csv", header=["share_non_null"])

    # 2. phenotype on the real data
    phenotype.load_codelist(real, codelist)
    # sensitivity: strict hadm_id linkage of troponin, then the default windowed linkage
    linkage = []
    for label, window in (("strict hadm_id", None), (f"hadm_id + {phenotype.LINK_WINDOW_HOURS}h window", phenotype.LINK_WINDOW_HOURS)):
        a = phenotype.admission_evidence(real, window)
        p = phenotype.patient_phenotype(real)
        c = a[a.code_any]
        linkage.append({"troponin_linkage": label,
                        "troponin_rows_linked": int(real.execute("select count(hadm_id) from troponin").fetchone()[0]),
                        "admissions_tested": int(a.troponin_tested.sum()),
                        "coded_mi_admissions_tested": int(c.troponin_tested.sum()),
                        "coded_mi_admissions_trop_pos": int(c.troponin_positive.sum()),
                        "patients_codes_and_troponin": int((p.found_by == "codes + troponin").sum()),
                        "patients_codes_only": int((p.found_by == "codes only").sum()),
                        "patients_troponin_only": int((p.found_by == "troponin only").sum())})
    pd.DataFrame(linkage).to_csv(out_dir / "linkage_sensitivity.csv", index=False)
    adm = a
    pts = p
    pseudonymise(adm, salt).to_csv(out_dir / "admission_mi_evidence.csv", index=False)
    pseudonymise(pts, salt).to_csv(out_dir / "mi_patients.csv", index=False)

    n_patients = real.execute("select count(*) from patients").fetchone()[0]
    n_adm = real.execute("select count(*) from admissions").fetchone()[0]
    overlap = pts.found_by.value_counts().reindex(["codes + troponin", "codes only", "troponin only"], fill_value=0)
    coded = adm[adm.code_any]
    trop_pos = adm[adm.troponin_positive]
    tested = adm[adm.troponin_tested]

    # 3. plant errors, score the checks, clean, and measure the effect on the count
    dirty, manifest = inject_mod.inject(real)
    dirty_results = validation.run_standard_checks(dirty)
    manifest.to_csv(out_dir / "injected_errors_manifest.csv", index=False)
    pvf = inject_mod.score(manifest, dirty_results, real_results)
    pvf.to_csv(out_dir / "planted_vs_found.csv", index=False)

    cleaned, quarantine_log = clean_mod.clean(dirty)
    quarantine_log.to_csv(out_dir / "quarantine_log.csv", index=False)
    cleaned_results = validation.run_standard_checks(cleaned)
    validation.results_frame(cleaned_results).to_csv(out_dir / "dq_checks_cleaned.csv", index=False)

    for con in (dirty, cleaned):
        phenotype.load_codelist(con, codelist)
    effect = pd.DataFrame([
        {"dataset": "real (as published)", "mi_patients": phenotype.count_mi_patients(real),
         "patient_rows": n_patients},
        {"dataset": "with planted errors", "mi_patients": phenotype.count_mi_patients(dirty),
         "patient_rows": dirty.execute("select count(*) from patients").fetchone()[0]},
        {"dataset": "after cleaning", "mi_patients": phenotype.count_mi_patients(cleaned),
         "patient_rows": cleaned.execute("select count(*) from patients").fetchone()[0]},
    ])
    effect.to_csv(out_dir / "cleaning_effect.csv", index=False)

    trop = real.execute("""select count(*) n, sum(recovered_from_text::int) text_only,
                                  count(distinct subject_id) patients from troponin""").fetchone()
    labs_no_hadm = real.execute("select avg((hadm_id is null)::int) from labevents").fetchone()[0]
    summary = {
        "data_dir": data_dir.resolve().relative_to(ROOT).as_posix() if data_dir.resolve().is_relative_to(ROOT) else data_dir.name,
        "patients": n_patients,
        "admissions": n_adm,
        "icd9_admissions": int(real.execute("select count(distinct hadm_id) from diagnoses_icd where icd_version=9").fetchone()[0]),
        "icd10_admissions": int(real.execute("select count(distinct hadm_id) from diagnoses_icd where icd_version=10").fetchone()[0]),
        "mi_patients_code_any": int(pts.first_code_any.notna().sum()),
        "mi_patients_code_primary": int(pts.first_code_primary.notna().sum()),
        "mi_patients_troponin_pos": int(pts.first_troponin_pos.notna().sum()),
        "mi_patients_any_evidence": int(len(pts)),
        "overlap": {k: int(v) for k, v in overlap.items()},
        "coded_admissions": int(len(coded)),
        "coded_admissions_tested": int(coded.troponin_tested.sum()),
        "coded_admissions_trop_pos": int(coded.troponin_positive.sum()),
        "trop_pos_admissions": int(len(trop_pos)),
        "trop_pos_admissions_coded": int(trop_pos.code_any.sum()),
        "tested_admissions": int(len(tested)),
        "troponin_rows": int(trop[0]),
        "troponin_text_only_rows": int(trop[1]),
        "troponin_patients": int(trop[2]),
        "troponin_rows_no_hadm": int(real.execute("select count(*) from troponin where hadm_id_source is null").fetchone()[0]),
        "linkage_sensitivity": linkage,
        "labevents_no_hadm_share": round(float(labs_no_hadm), 4),
        "coded_mi_died_within_30d": int(((pts.days_code_mi_to_death >= 0) & (pts.days_code_mi_to_death <= 30)).sum()),
        "coded_mi_died_within_1y": int(((pts.days_code_mi_to_death >= 0) & (pts.days_code_mi_to_death <= 365)).sum()),
        "checks_failing_real": [r.name for r in real_results if not r.passed],
        "planted_total": int(pvf.planted.sum()),
        "planted_found": int(pvf.found.sum()),
        "cleaning_effect": effect.set_index("dataset").mi_patients.to_dict(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "raw" / "mimic-iv-demo-2.2" / "hosp"))
    ap.add_argument("--out", default=str(ROOT / "outputs"))
    ap.add_argument("--codelist", default=str(ROOT / "phenotypes" / "mi_codelist.csv"))
    a = ap.parse_args()
    print(json.dumps(run(Path(a.data), Path(a.out), Path(a.codelist)), indent=2, default=str))
    from . import figures
    figures.build_all(Path(a.out), ROOT / "report" / "figures", phenotype.TROPONIN_THRESHOLD)


if __name__ == "__main__":
    main()
