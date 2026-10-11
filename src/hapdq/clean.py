"""Cleaning rules: repair what is safely repairable, quarantine the rest.

Repair only where the intended value is unambiguous (whitespace, case, a dot
in an ICD code). Anything else is moved to a quarantine table with a reason,
never silently dropped or guessed.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from . import validation as v
from .io import copy_tables


def clean(dirty: duckdb.DuckDBPyConnection) -> tuple[duckdb.DuckDBPyConnection, pd.DataFrame]:
    con = copy_tables(dirty)
    con.execute("create table quarantine (tbl varchar, _row_id bigint, reason varchar)")

    def quarantine(result: v.CheckResult, reason: str, delete: bool = True):
        if not result.failed_row_ids:
            return
        ids = ",".join(map(str, result.failed_row_ids))
        con.execute(f"insert into quarantine select '{result.table}', _row_id, '{reason}' from {result.table} "
                    f"where _row_id in ({ids})")
        if delete:
            con.execute(f"delete from {result.table} where _row_id in ({ids})")

    # 1. exact duplicate patients: keep the first copy
    quarantine(v.check_duplicates(con, "patients", ["subject_id"]), "duplicate patient")
    # 2. repair: normalise code formatting (case, whitespace, dots)
    con.execute("update diagnoses_icd set icd_code = upper(replace(trim(icd_code), '.', ''))")
    # 3. codes still unknown after repair are not guessed at
    quarantine(v.check_icd_in_dictionary(con), "unknown ICD code after normalisation")
    # 4. diagnoses that do not link to an admission
    quarantine(v.check_orphans(con, "diagnoses_icd", "admissions", "hadm_id"), "diagnosis without admission")
    # 5. temporal impossibilities: keep the admission out of analysis
    quarantine(v.check_events_after_death(con, "admissions", "admittime"), "admission after death")
    quarantine(v.check_time_order(con, "admissions", "admittime", "dischtime"), "discharge before admission")
    # 5b. cascade: rows belonging to a quarantined admission go with it
    for child in ("diagnoses_icd", "labevents"):
        quarantine(v.check_orphans(con, child, "admissions", "hadm_id", allow_null=True),
                   "parent admission quarantined")
    # 6. impossible age: keep the patient, null the age
    bad_age = v.check_age_range(con)
    quarantine(bad_age, "impossible age (value nulled, row kept)", delete=False)
    if bad_age.failed_row_ids:
        con.execute(f"update patients set anchor_age = null where _row_id in ({','.join(map(str, bad_age.failed_row_ids))})")

    log = con.execute("select tbl as table_name, reason, count(*) as n_rows from quarantine group by all order by 1, 2").df()
    return con, log
