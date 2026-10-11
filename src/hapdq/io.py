"""Load MIMIC-IV hosp tables into an in-memory DuckDB connection.

Every table gets a stable `_row_id` (file order) so validation checks and the
error-injection manifest can point at exact rows.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

TABLES = [
    "patients",
    "admissions",
    "diagnoses_icd",
    "procedures_icd",
    "labevents",
    "d_icd_diagnoses",
    "d_labitems",
]

# Facts verified against MIMIC-IV demo v2.2 on 2026-10-11 (see docs/source_probe.md).
# Asserted on every load so a different release fails loudly instead of quietly.
TROPONIN_T_ITEMID = 51003
EXPECTED_COLUMNS = {
    "patients": {"subject_id", "gender", "anchor_age", "anchor_year", "anchor_year_group", "dod"},
    "admissions": {"subject_id", "hadm_id", "admittime", "dischtime", "deathtime", "hospital_expire_flag"},
    "diagnoses_icd": {"subject_id", "hadm_id", "seq_num", "icd_code", "icd_version"},
    "labevents": {"subject_id", "hadm_id", "itemid", "charttime", "value", "valuenum", "valueuom", "comments"},
}


def load(data_dir: str | Path, con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
    data_dir = Path(data_dir)
    con = con or duckdb.connect()
    for t in TABLES:
        f = data_dir / f"{t}.csv.gz"
        if not f.exists():
            raise FileNotFoundError(f"{f} missing - run scripts/download_data.py")
        # all_varchar=False but force code columns to text: ICD-9 codes like '0066' lose
        # their leading zeros if sniffed as integers.
        types = ", types={'icd_code': 'VARCHAR'}" if t in ("diagnoses_icd", "procedures_icd", "d_icd_diagnoses") else ""
        con.execute(
            f"""create or replace table {t} as
                select row_number() over () as _row_id, *
                from read_csv('{f.as_posix()}', auto_detect=true{types})"""
        )
    _assert_schema(con)
    return con


def _assert_schema(con: duckdb.DuckDBPyConnection) -> None:
    for t, cols in EXPECTED_COLUMNS.items():
        have = {r[0] for r in con.execute(f"describe {t}").fetchall()}
        missing = cols - have
        assert not missing, f"{t} is missing expected columns {missing}"
    label = con.execute(
        "select label from d_labitems where itemid = ?", [TROPONIN_T_ITEMID]
    ).fetchone()
    assert label and label[0] == "Troponin T", f"itemid {TROPONIN_T_ITEMID} is {label}, expected Troponin T"


def copy_tables(src: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Independent copy of every table (used before injecting errors)."""
    dst = duckdb.connect()
    for t in TABLES:
        dst.register("_tmp", src.table(t).arrow())
        dst.execute(f"create table {t} as select * from _tmp")
        dst.unregister("_tmp")
    return dst
