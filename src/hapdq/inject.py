"""Plant known errors in a copy of the data so the checks can be scored.

Real MIMIC data passes most structural checks (it has been curated), so a check
that reports zero failures proves nothing on its own. Planting a fixed,
documented number of errors and scoring "planted vs found" shows each check
actually fires. Every planted row is recorded in a manifest by `_row_id`.
"""
from __future__ import annotations

import random

import duckdb
import pandas as pd

from .io import copy_tables

# error_type -> (count, check expected to catch it)
PLAN = {
    "duplicate_patient": (5, "duplicate_patients"),
    "admission_after_death": (4, "after_death_admissions"),
    "discharge_before_admission": (3, "time_order_admissions"),
    "impossible_age": (3, "age_range_patients"),
    "malformed_icd_code": (6, "icd_format_diagnoses_icd"),
    "unknown_icd_code": (3, "icd_known_diagnoses_icd"),
    "unlinked_diagnosis": (5, "orphan_diagnoses_icd_hadm_id"),
}
# How many of the code corruptions deliberately hit MI codes, so the effect of
# coding errors on the phenotype count can be measured (random hits are unlikely:
# MI codes are ~12 of ~4,500 diagnosis rows).
MI_CODE_CORRUPTIONS = 3
MI_CODE_SQL = ("((icd_version = 10 and left(icd_code, 3) in ('I21','I22','I23')) or "
               "(icd_version = 9 and (left(icd_code, 3) = '410' or left(icd_code, 4) in ('4110','4297'))))")


def _malform(code: str, style: int) -> str:
    # dotted (as written on paper), lower case, trailing whitespace.
    # Lower-casing a purely numeric ICD-9 code changes nothing, so dot those instead.
    style = style % 3
    if style == 1 and code.lower() == code:
        style = 0
    return [code[:3] + "." + code[3:], code.lower(), code + " "][style]


def _unknown(code: str) -> str:
    # letter O typed for zero / letter I for one: right shape, not a real code
    if "0" in code[1:]:
        i = code.index("0", 1)
        return code[:i] + "O" + code[i + 1:]
    if "1" in code[1:]:
        i = code.index("1", 1)
        return code[:i] + "I" + code[i + 1:]
    return code[:-1] + "Z" if len(code) > 3 else code + "ZZ"


def inject(clean: duckdb.DuckDBPyConnection, seed: int = 42) -> tuple[duckdb.DuckDBPyConnection, pd.DataFrame]:
    rng = random.Random(seed)
    con = copy_tables(clean)
    manifest: list[dict] = []

    def log(error_type, table, row_id, detail):
        manifest.append({"error_type": error_type, "table": table, "_row_id": int(row_id),
                         "expected_check": PLAN[error_type][1], "detail": detail})

    # 1. duplicate patient records (new rows, new _row_ids)
    pts = [r[0] for r in con.execute("select _row_id from patients order by 1").fetchall()]
    next_id = con.execute("select max(_row_id) from patients").fetchone()[0] + 1
    for rid in rng.sample(pts, PLAN["duplicate_patient"][0]):
        con.execute("insert into patients select ? as _row_id, * exclude (_row_id) from patients where _row_id = ?",
                    [next_id, rid])
        log("duplicate_patient", "patients", next_id, f"copy of patients row {rid}")
        next_id += 1

    # 2. admissions moved to after the patient's death (excluding the admission they died in)
    adm_dead = [r[0] for r in con.execute(
        """select a._row_id from admissions a join patients p using (subject_id)
           where p.dod is not null and a.hospital_expire_flag = 0 order by 1""").fetchall()]
    used_adm = set(rng.sample(adm_dead, PLAN["admission_after_death"][0]))
    for rid in sorted(used_adm):
        con.execute(
            """update admissions set
                 admittime = cast((select p.dod from patients p where p.subject_id = admissions.subject_id limit 1)
                                  as timestamp) + interval 30 day,
                 dischtime = cast((select p.dod from patients p where p.subject_id = admissions.subject_id limit 1)
                                  as timestamp) + interval 33 day
               where _row_id = ?""", [rid])
        log("admission_after_death", "admissions", rid, "admittime set to dod + 30 days")

    # 3. discharge before admission (swap the two timestamps)
    adm_all = [r[0] for r in con.execute("select _row_id from admissions order by 1").fetchall()]
    for rid in rng.sample([a for a in adm_all if a not in used_adm], PLAN["discharge_before_admission"][0]):
        con.execute("update admissions set admittime = dischtime, dischtime = admittime where _row_id = ?", [rid])
        log("discharge_before_admission", "admissions", rid, "admittime and dischtime swapped")

    # 4. impossible / missing ages (only on original rows, not the planted duplicates)
    for rid, val in zip(rng.sample(pts, PLAN["impossible_age"][0]), [-4, 150, None]):
        con.execute("update patients set anchor_age = ? where _row_id = ?", [val, rid])
        log("impossible_age", "patients", rid, f"anchor_age set to {val}")

    # 5/6. diagnosis code corruption, some deliberately on MI codes
    mi_rows = [r[0] for r in con.execute(f"select _row_id from diagnoses_icd where {MI_CODE_SQL} order by 1").fetchall()]
    other_rows = [r[0] for r in con.execute(f"select _row_id from diagnoses_icd where not {MI_CODE_SQL} order by 1").fetchall()]
    n_mal, n_unk = PLAN["malformed_icd_code"][0], PLAN["unknown_icd_code"][0]
    mi_pick = rng.sample(mi_rows, MI_CODE_CORRUPTIONS)
    other_pick = rng.sample(other_rows, n_mal + n_unk - MI_CODE_CORRUPTIONS)
    targets = mi_pick + other_pick  # MI rows first, so they land in the malformed group
    for i, rid in enumerate(targets):
        code = con.execute("select icd_code from diagnoses_icd where _row_id = ?", [rid]).fetchone()[0]
        kind = "malformed_icd_code" if i < n_mal else "unknown_icd_code"
        new = _malform(code, i) if kind == "malformed_icd_code" else _unknown(code)
        assert new != code, f"planted error on row {rid} is a no-op ({code!r})"
        con.execute("update diagnoses_icd set icd_code = ? where _row_id = ?", [new, rid])
        log(kind, "diagnoses_icd", rid, f"{code!r} -> {new!r}" + (" (MI code)" if rid in mi_pick else ""))

    # 7. diagnoses that no longer link to an admission
    used_dx = set(targets)
    for j, rid in enumerate(rng.sample([r for r in other_rows if r not in used_dx], PLAN["unlinked_diagnosis"][0])):
        con.execute("update diagnoses_icd set hadm_id = ? where _row_id = ?", [99_000_000 + j, rid])
        log("unlinked_diagnosis", "diagnoses_icd", rid, f"hadm_id set to {99_000_000 + j}")

    return con, pd.DataFrame(manifest)


def score(manifest: pd.DataFrame, dirty_results, baseline_results) -> pd.DataFrame:
    """Planted vs found per error type.

    found   = planted rows the expected check flagged
    missed  = planted rows it did not flag
    extra   = rows it flagged that were not planted for ANY error type and not already
              flagged on the clean data (i.e. genuine false alarms)
    cross   = planted rows of a different error type it also flagged (e.g. a dotted
              code fails the dictionary check as well as the format check)
    """
    all_planted = set(zip(manifest.table, manifest._row_id))
    dirty = {r.name: set(r.failed_row_ids) for r in dirty_results}
    base = {r.name: set(r.failed_row_ids) for r in baseline_results}
    rows = []
    for error_type, (n, check) in PLAN.items():
        table = manifest.loc[manifest.error_type == error_type, "table"].iloc[0]
        planted = set(manifest.loc[manifest.error_type == error_type, "_row_id"])
        planted_other = {rid for t, rid in all_planted if t == table} - planted
        flagged = dirty.get(check, set())
        rows.append({
            "error_type": error_type,
            "expected_check": check,
            "planted": len(planted),
            "found": len(planted & flagged),
            "missed": len(planted - flagged),
            "pre_existing": len(base.get(check, set())),
            "cross": len(flagged & planted_other),
            "extra": len(flagged - planted - planted_other - base.get(check, set())),
        })
    return pd.DataFrame(rows)
