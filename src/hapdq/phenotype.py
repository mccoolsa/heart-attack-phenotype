"""Acute myocardial infarction (MI) phenotype on MIMIC-IV hospital data.

Two independent evidence streams per admission:
  * codes     - ICD-9/ICD-10 diagnosis codes from HDR UK Phenotype Library PH1024
                (prefix match, as the published list gives 3/4-character codes)
  * troponin  - peak cardiac troponin T >= 0.10 ng/mL, the threshold the MIMIC lab
                itself prints on each result ("cTropnT > 0.10 ng/mL suggests Acute MI")

The phenotype is the code definition. Troponin is a comparator, not a gold
standard: it also rises in type 2 MI, sepsis, renal failure and heart failure.

`con` is a DuckDB connection or an engine.SparkConnection; the SQL runs on both.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .engine import concat_distinct, create_table_from_pandas, epoch_seconds, regex

TROPONIN_T_ITEMID = 51003
TROPONIN_THRESHOLD = 0.10  # ng/mL, from the lab's own interpretive comment
LINK_WINDOW_HOURS = 24     # unlinked draws up to 24h before admission belong to it (ED work-up)

# prefix match without engine-specific functions (DuckDB starts_with / Spark startswith)
PREFIX_MATCH = "d.icd_version = c.icd_version and left(d.icd_code, length(c.code)) = c.code"
BELOW_DETECTION = r"^\s*<\s*0?\.01"  # '<0.01' at the start of the comment


def load_codelist(con, path: str | Path) -> None:
    create_table_from_pandas(con, "mi_codelist", pd.read_csv(path, dtype={"code": str}))


def troponin_results(con, link_window_hours: int | None = LINK_WINDOW_HOURS) -> None:
    """Troponin T with text-only results recovered and unlinked draws linked by time.

    * ~half of MIMIC troponin T rows have valuenum NULL: the result is in `comments`
      ("<0.01. cTropnT > 0.10 ng/mL suggests Acute MI."). Treating those as missing
      would make every negative test disappear and inflate the positive rate.
    * ~3 in 10 rows have no hadm_id, typically the ED draw taken before the patient
      is formally admitted. With `link_window_hours` set, such a row is attached to the
      admission whose [admittime - window, dischtime] contains it (nearest admittime
      wins). None = strict hadm_id linkage only.
    """
    if link_window_hours is None:
        window_join, hadm = "", "l.hadm_id"
    else:
        distance = f"abs({epoch_seconds(con, 'a.admittime')} - {epoch_seconds(con, 't.charttime')})"
        window_join = f"""
        left join (
            select t._row_id, a.hadm_id,
                   row_number() over (partition by t._row_id order by {distance}) as rn
            from labevents t join admissions a
              on a.subject_id = t.subject_id
             and t.charttime between a.admittime - interval {int(link_window_hours)} hour and a.dischtime
            where t.itemid = {TROPONIN_T_ITEMID} and t.hadm_id is null) w
          on w._row_id = l._row_id and w.rn = 1"""
        hadm = "coalesce(l.hadm_id, w.hadm_id)"
    below = regex(con, "coalesce(l.comments, l.value, '')", BELOW_DETECTION)
    con.execute(f"""
        create or replace table troponin as
        select l._row_id, l.subject_id, l.hadm_id as hadm_id_source, {hadm} as hadm_id, l.charttime,
               coalesce(l.valuenum, case when {below} then 0.0 end) as tnt,
               l.valuenum is null as recovered_from_text
        from labevents l{window_join}
        where l.itemid = {TROPONIN_T_ITEMID}""")


def admission_evidence(con, link_window_hours: int | None = LINK_WINDOW_HOURS) -> pd.DataFrame:
    """One row per admission: MI code (any / primary position) and peak troponin."""
    troponin_results(con, link_window_hours)
    con.execute(f"""
        create or replace table mi_dx as
        select d.subject_id, d.hadm_id, d.seq_num, d.icd_version, d.icd_code, c.description
        from diagnoses_icd d
        join mi_codelist c on {PREFIX_MATCH}""")
    con.execute(f"""
        create or replace table admission_mi as
        select a.subject_id, a.hadm_id, a.admittime, a.dischtime, a.hospital_expire_flag,
               dx.n_mi_codes is not null                    as code_any,
               coalesce(dx.primary_mi, false)               as code_primary,
               dx.mi_codes,
               t.n_tests is not null                        as troponin_tested,
               t.peak_tnt,
               coalesce(t.peak_tnt >= {TROPONIN_THRESHOLD}, false) as troponin_positive,
               t.first_positive_time
        from admissions a
        left join (select hadm_id, count(*) as n_mi_codes, bool_or(seq_num = 1) as primary_mi,
                          {concat_distinct(con, "icd_code")} as mi_codes
                   from mi_dx group by hadm_id) dx on dx.hadm_id = a.hadm_id
        left join (select hadm_id, count(*) as n_tests, max(tnt) as peak_tnt,
                          min(case when tnt >= {TROPONIN_THRESHOLD} then charttime end) as first_positive_time
                   from troponin where hadm_id is not null group by hadm_id) t on t.hadm_id = a.hadm_id""")
    return con.execute("select * from admission_mi order by subject_id, admittime").df()


def patient_phenotype(con) -> pd.DataFrame:
    """One row per patient with any MI evidence: first date per source and outcome."""
    con.execute("""
        create or replace table patient_mi as
        with per_patient as (
            select subject_id,
                   min(case when code_any then admittime end)          as first_code_any,
                   min(case when code_primary then admittime end)      as first_code_primary,
                   min(case when troponin_positive then first_positive_time end) as first_troponin_pos,
                   sum(cast(code_any as int))                           as n_mi_admissions
            from admission_mi group by subject_id)
        select pp.*,
               least(pp.first_code_any, pp.first_troponin_pos)          as first_mi_evidence,
               case when first_code_any is not null and first_troponin_pos is not null then 'codes + troponin'
                    when first_code_any is not null then 'codes only'
                    else 'troponin only' end                            as found_by,
               p.dod
        from per_patient pp
        join (select distinct subject_id, dod from patients) p on p.subject_id = pp.subject_id
        where pp.first_code_any is not null or pp.first_troponin_pos is not null""")
    df = con.execute("select * from patient_mi order by subject_id").df()
    days = (pd.to_datetime(df.dod) - pd.to_datetime(df.first_code_any).dt.normalize()).dt.days
    df["days_code_mi_to_death"] = days.astype("Int64")
    return df


def count_mi_patients(con) -> int:
    """Headline phenotype count: distinct patients with a PH1024 code in any position."""
    return con.execute(f"""
        select count(distinct d.subject_id)
        from diagnoses_icd d
        join admissions a on a.hadm_id = d.hadm_id
        join mi_codelist c on {PREFIX_MATCH}""").fetchone()[0]
