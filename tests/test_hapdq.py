from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hapdq import phenotype, validation as v
from hapdq.pseudonymise import pseudo_id, pseudonymise

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "raw" / "mimic-iv-demo-2.2" / "hosp"
CODELIST = ROOT / "phenotypes" / "mi_codelist.csv"


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""create table patients as select * from (values
        (1, 1, 'F', 70, date '2150-01-10'),
        (2, 2, 'M', 55, null),
        (3, 2, 'M', 55, null),          -- duplicate of subject 2
        (4, 3, 'F', -1, null)) t(_row_id, subject_id, gender, anchor_age, dod)""")
    c.execute("""create table admissions as select * from (values
        (1, 1, 100, timestamp '2150-01-01 10:00', timestamp '2150-01-05 10:00', 0),
        (2, 1, 101, timestamp '2150-02-01 10:00', timestamp '2150-02-03 10:00', 0),  -- after death
        (3, 2, 200, timestamp '2140-05-05 10:00', timestamp '2140-05-01 10:00', 0))  -- ends before it starts
        t(_row_id, subject_id, hadm_id, admittime, dischtime, hospital_expire_flag)""")
    c.execute("""create table diagnoses_icd as select * from (values
        (1, 1, 100, 1, 'I214', 10),
        (2, 1, 100, 2, 'I21.4', 10),   -- malformed
        (3, 2, 200, 1, '41071', 9),
        (4, 2, 999, 1, 'E785', 10),    -- orphan
        (5, 2, 200, 2, 'E78Z', 10))    -- right shape, not a real code
        t(_row_id, subject_id, hadm_id, seq_num, icd_code, icd_version)""")
    c.execute("""create table d_icd_diagnoses as select * from (values
        ('I214', 10), ('41071', 9), ('E785', 10)) t(icd_code, icd_version)""")
    c.execute("""create table labevents as select * from (values
        (1, 1, 100, 51003, timestamp '2150-01-01 12:00', null, null, '<0.01.  cTropnT > 0.10 ng/mL suggests Acute MI.'),
        (2, 1, 100, 51003, timestamp '2150-01-02 12:00', '___', 0.45, null),
        (3, 2, null, 51003, timestamp '2140-05-02 12:00', '___', 0.02, null))
        t(_row_id, subject_id, hadm_id, itemid, charttime, value, valuenum, comments)""")
    return c


def test_duplicates_keep_first_copy(con):
    assert v.check_duplicates(con, "patients", ["subject_id"]).failed_row_ids == [3]


def test_orphans(con):
    assert v.check_orphans(con, "diagnoses_icd", "admissions", "hadm_id").failed_row_ids == [4]
    # labs without an admission are allowed (outpatient / ED draws)
    assert v.check_orphans(con, "labevents", "admissions", "hadm_id", allow_null=True).passed


def test_events_after_death(con):
    assert v.check_events_after_death(con, "admissions", "admittime").failed_row_ids == [2]


def test_time_order(con):
    assert v.check_time_order(con, "admissions", "admittime", "dischtime").failed_row_ids == [3]


def test_age_range(con):
    assert v.check_age_range(con).failed_row_ids == [4]


def test_icd_format_and_dictionary(con):
    assert v.check_icd_format(con).failed_row_ids == [2]
    # 'E78Z' passes the format check but is not a real code; the dictionary check catches it
    assert v.check_icd_in_dictionary(con).failed_row_ids == [2, 5]


def test_non_numeric_troponin(con):
    r = v.check_numeric_result(con, 51003)
    assert (r.n_checked, r.failed_row_ids) == (3, [1])


def test_troponin_text_result_recovered_as_zero(con):
    phenotype.troponin_results(con)
    df = con.execute("select tnt, recovered_from_text from troponin order by subject_id, charttime").df()
    assert df.tnt.tolist() == [0.0, 0.45, 0.02]
    assert df.recovered_from_text.tolist() == [True, False, False]


def test_codelist_prefix_match(con):
    phenotype.load_codelist(con, CODELIST)
    adm = phenotype.admission_evidence(con).set_index("hadm_id")
    assert adm.loc[100, "code_any"] and adm.loc[100, "code_primary"] and adm.loc[100, "troponin_positive"]
    assert adm.loc[200, "code_any"]                 # ICD-9 41071 matches prefix 410


def test_unlinked_troponin_linked_by_time_window(con):
    phenotype.load_codelist(con, CODELIST)
    # the subject-2 draw has no hadm_id; it falls inside admission 200's window
    # (that admission's times are swapped in the fixture, so use admittime-24h..admittime)
    con.execute("update admissions set dischtime = timestamp '2140-05-06 10:00' where hadm_id = 200")
    con.execute("update admissions set admittime = timestamp '2140-05-02 20:00' where hadm_id = 200")
    strict = phenotype.admission_evidence(con, None).set_index("hadm_id")
    assert not strict.loc[200, "troponin_tested"]
    windowed = phenotype.admission_evidence(con, 24).set_index("hadm_id")
    assert windowed.loc[200, "troponin_tested"] and windowed.loc[200, "peak_tnt"] == 0.02


def test_codelist_excludes_old_mi():
    codes = pd.read_csv(CODELIST, dtype={"code": str})
    assert not any(c.startswith(("I252", "412")) for c in codes.code)


def test_pseudonymise_is_stable_and_drops_ids():
    df = pd.DataFrame({"subject_id": [1, 1, 2], "hadm_id": [10, 11, 20]})
    out = pseudonymise(df, "salt")
    assert "subject_id" not in out and "hadm_id" not in out
    assert out.pseudo_id.nunique() == 2 and out.pseudo_id[0] == pseudo_id(1, "salt")
    assert pseudo_id(1, "salt") != pseudo_id(1, "other")


@pytest.mark.skipif(not DATA.exists(), reason="MIMIC-IV demo not downloaded")
def test_every_planted_error_is_found_on_real_data():
    from hapdq import inject, io
    real = io.load(DATA)
    base = v.run_standard_checks(real)
    dirty, manifest = inject.inject(real)
    scored = inject.score(manifest, v.run_standard_checks(dirty), base)
    assert scored.missed.sum() == 0 and scored.extra.sum() == 0
