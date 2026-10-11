"""Reusable data quality checks for linked patient / admission / event tables.

Each check is a SQL query and returns a CheckResult: how many rows were
checked, how many failed, and the `_row_id`s of the failing rows so they can be
inspected, quarantined or matched against planted errors. `con` is a DuckDB
connection or an engine.SparkConnection; the same SQL runs on both.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .engine import regex

# MIMIC stores ICD codes without the dot. Formats from the ICD-9-CM / ICD-10-CM specs.
ICD10_DX_PATTERN = r"^[A-Z][0-9][0-9A-Z]{1,5}$"
ICD9_DX_PATTERN = r"^([0-9]{3,5}|V[0-9]{2,4}|E[0-9]{3,4})$"


@dataclass
class CheckResult:
    name: str
    table: str
    rule: str
    n_checked: int
    failed_row_ids: list[int] = field(default_factory=list)

    @property
    def n_failed(self) -> int:
        return len(self.failed_row_ids)

    @property
    def passed(self) -> bool:
        return self.n_failed == 0

    def as_row(self) -> dict:
        return {
            "check": self.name,
            "table": self.table,
            "rule": self.rule,
            "n_checked": self.n_checked,
            "n_failed": self.n_failed,
            "pct_failed": round(100 * self.n_failed / self.n_checked, 2) if self.n_checked else 0.0,
            "status": "PASS" if self.passed else "FAIL",
        }


def _result(con, name, table, rule, failing_sql) -> CheckResult:
    n = con.execute(f"select count(*) from {table}").fetchone()[0]
    ids = [r[0] for r in con.execute(f"select distinct _row_id from ({failing_sql}) q order by 1").fetchall()]
    return CheckResult(name, table, rule, n, ids)


def check_duplicates(con, table: str, key: list[str]) -> CheckResult:
    """Rows whose key already appeared earlier in the table (the first copy is kept)."""
    k = ", ".join(key)
    sql = f"""select _row_id from (
                select _row_id, row_number() over (partition by {k} order by _row_id) as rn
                from {table}) d where rn > 1"""
    return _result(con, f"duplicate_{table}", table, f"unique on ({k})", sql)


def check_orphans(con, child: str, parent: str, key: str, allow_null: bool = False) -> CheckResult:
    """Child rows whose key has no match in the parent table (failed linkage)."""
    null_clause = "" if allow_null else f" or c.{key} is null"
    sql = f"""select c._row_id from {child} c
              where (c.{key} is not null and not exists (select 1 from {parent} p where p.{key} = c.{key})){null_clause}"""
    return _result(con, f"orphan_{child}_{key}", child, f"{key} links to {parent}", sql)


def check_events_after_death(con, table: str, time_col: str, patients: str = "patients",
                             grace_days: int = 0) -> CheckResult:
    """Events dated after the patient's date of death (+ grace days)."""
    sql = f"""select e._row_id from {table} e join {patients} p using (subject_id)
              where p.dod is not null and cast(e.{time_col} as date) > p.dod + interval {grace_days} day"""
    return _result(con, f"after_death_{table}", table, f"{time_col} <= dod + {grace_days}d", sql)


def check_time_order(con, table: str, start_col: str, end_col: str) -> CheckResult:
    sql = f"select _row_id from {table} where {end_col} < {start_col}"
    return _result(con, f"time_order_{table}", table, f"{start_col} <= {end_col}", sql)


def check_age_range(con, table: str = "patients", col: str = "anchor_age",
                    lo: int = 0, hi: int = 120) -> CheckResult:
    sql = f"select _row_id from {table} where {col} is null or {col} < {lo} or {col} > {hi}"
    return _result(con, f"age_range_{table}", table, f"{lo} <= {col} <= {hi}, not null", sql)


def check_icd_format(con, table: str = "diagnoses_icd") -> CheckResult:
    """Codes that do not match the ICD-9-CM / ICD-10-CM diagnosis code shape."""
    sql = f"""select _row_id from {table}
              where icd_code is null
                 or (icd_version = 10 and not {regex(con, "icd_code", ICD10_DX_PATTERN)})
                 or (icd_version = 9  and not {regex(con, "icd_code", ICD9_DX_PATTERN)})
                 or icd_version not in (9, 10)"""
    return _result(con, f"icd_format_{table}", table, "matches ICD-9/10 code pattern", sql)


def check_icd_in_dictionary(con, table: str = "diagnoses_icd",
                            dictionary: str = "d_icd_diagnoses") -> CheckResult:
    """Well-formed or not, does the code exist in the coding system's dictionary?"""
    sql = f"""select t._row_id from {table} t
              where not exists (select 1 from {dictionary} d
                                where d.icd_code = t.icd_code and d.icd_version = t.icd_version)"""
    return _result(con, f"icd_known_{table}", table, f"code exists in {dictionary}", sql)


def check_numeric_result(con, itemid: int, table: str = "labevents") -> CheckResult:
    """Lab results with no numeric value: the result is text-only (or absent)."""
    sql = f"select _row_id from {table} where itemid = {itemid} and valuenum is null"
    n_item = con.execute(f"select count(*) from {table} where itemid = {itemid}").fetchone()[0]
    ids = [r[0] for r in con.execute(sql + " order by 1").fetchall()]
    return CheckResult(f"non_numeric_{table}_{itemid}", table, f"itemid {itemid} has valuenum", n_item, ids)


def completeness(con, table: str, by: str | None = None) -> pd.DataFrame:
    """Share of non-null values per column, optionally per group."""
    cols = [r[0] for r in con.execute(f"describe {table}").fetchall() if r[0] != "_row_id" and r[0] != by]
    exprs = ", ".join(f"avg(cast({c} is not null as int)) as {c}" for c in cols)
    if by:
        df = con.execute(f"select {by}, count(*) as n_rows, {exprs} from {table} group by 1 order by 1").df()
    else:
        df = con.execute(f"select count(*) as n_rows, {exprs} from {table}").df()
    return df


def run_standard_checks(con, troponin_itemid: int = 51003) -> list[CheckResult]:
    """The check suite this project runs on every dataset (clean, dirty, cleaned)."""
    return [
        check_duplicates(con, "patients", ["subject_id"]),
        check_duplicates(con, "admissions", ["hadm_id"]),
        check_duplicates(con, "diagnoses_icd", ["hadm_id", "seq_num"]),
        check_orphans(con, "admissions", "patients", "subject_id"),
        check_orphans(con, "diagnoses_icd", "admissions", "hadm_id"),
        check_orphans(con, "labevents", "admissions", "hadm_id", allow_null=True),
        check_events_after_death(con, "admissions", "admittime"),
        check_events_after_death(con, "labevents", "charttime"),
        check_time_order(con, "admissions", "admittime", "dischtime"),
        check_age_range(con),
        check_icd_format(con),
        check_icd_in_dictionary(con),
        check_numeric_result(con, troponin_itemid),
    ]


def results_frame(results: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame([r.as_row() for r in results])
