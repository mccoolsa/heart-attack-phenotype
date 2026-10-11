# Databricks notebook source
# MAGIC %md
# MAGIC # Heart attack phenotype on Databricks
# MAGIC
# MAGIC Runs the same validation checks and MI phenotype as the local DuckDB pipeline, on Spark SQL with Delta tables,
# MAGIC and asserts that every headline number matches the local run (`outputs/summary.json`).
# MAGIC
# MAGIC **Setup:** upload the MIMIC-IV demo `hosp/*.csv.gz` files to a Unity Catalog volume and point `raw_path` at it.
# MAGIC See `notebooks/README.md`.

# COMMAND ----------

dbutils.widgets.text("schema", "workspace.heart_attack_phenotype")
dbutils.widgets.text("raw_path", "/Volumes/workspace/heart_attack_phenotype/raw/hosp")
SCHEMA = dbutils.widgets.get("schema")
RAW = dbutils.widgets.get("raw_path")

# COMMAND ----------

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.getcwd(), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from pyspark.sql import Window
from pyspark.sql import functions as F

from hapdq import phenotype, validation
from hapdq.engine import SparkConnection

# COMMAND ----------

# MAGIC %md ## 1. Load the CSVs into Delta tables
# MAGIC Each table gets a `_row_id` in file order, as the local loader does, so failing rows can be traced.

# COMMAND ----------

# Read every column as text, then cast explicitly: inferred types would turn ICD-9 '0066' into 66.
BIG, TS = "bigint", "timestamp"
TABLES = {
    "patients": {"subject_id": BIG, "anchor_age": "int", "anchor_year": "int", "dod": "date"},
    "admissions": {"subject_id": BIG, "hadm_id": BIG, "admittime": TS, "dischtime": TS, "deathtime": TS,
                   "edregtime": TS, "edouttime": TS, "hospital_expire_flag": "int"},
    "diagnoses_icd": {"subject_id": BIG, "hadm_id": BIG, "seq_num": "int", "icd_version": "int"},
    "labevents": {"labevent_id": BIG, "subject_id": BIG, "hadm_id": BIG, "specimen_id": BIG, "itemid": BIG,
                  "charttime": TS, "storetime": TS, "valuenum": "double",
                  "ref_range_lower": "double", "ref_range_upper": "double"},
    "d_icd_diagnoses": {"icd_version": "int"},
    "d_labitems": {"itemid": BIG},
}

spark.sql(f"create schema if not exists {SCHEMA}")
for table, casts in TABLES.items():
    df = (spark.read.option("header", True).option("multiLine", True).option("escape", '"')
          .csv(f"{RAW}/{table}.csv.gz"))
    for c, t in casts.items():
        df = df.withColumn(c, F.col(c).cast(t))
    df = df.withColumn("_row_id", F.row_number().over(Window.orderBy(F.monotonically_increasing_id())))
    (df.select("_row_id", *[c for c in df.columns if c != "_row_id"])
       .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{SCHEMA}.{table}"))
    print(f"{table:16s} {spark.table(f'{SCHEMA}.{table}').count():>8,d} rows")

# COMMAND ----------

# MAGIC %md ## 2. Validation checks (same functions as local)

# COMMAND ----------

con = SparkConnection(spark, SCHEMA)
assert con.execute("select label from d_labitems where itemid = 51003").fetchone()[0] == "Troponin T"
results = validation.run_standard_checks(con)
checks = validation.results_frame(results)
display(checks)

# COMMAND ----------

# MAGIC %md ## 3. Phenotype: codes vs troponin, strict and windowed linkage

# COMMAND ----------

phenotype.load_codelist(con, os.path.join(REPO, "phenotypes", "mi_codelist.csv"))
linkage = {}
for label, window in (("strict", None), ("windowed", phenotype.LINK_WINDOW_HOURS)):
    adm = phenotype.admission_evidence(con, window)
    pts = phenotype.patient_phenotype(con)
    linkage[label] = {"admissions_tested": int(adm.troponin_tested.sum()),
                      "rows_linked": con.execute("select count(hadm_id) from troponin").fetchone()[0]}
display(pts.drop(columns=["subject_id"]))

# COMMAND ----------

# MAGIC %md ## 4. Parity with the local DuckDB run

# COMMAND ----------

local = json.load(open(os.path.join(REPO, "outputs", "summary.json")))
trop = con.execute("""select count(*), sum(cast(recovered_from_text as int)), count(tnt),
                             sum(cast(hadm_id_source is null as int)) from troponin""").fetchone()
spark_summary = {
    "patients": con.execute("select count(*) from patients").fetchone()[0],
    "admissions": con.execute("select count(*) from admissions").fetchone()[0],
    "mi_patients_code_any": int(pts.first_code_any.notna().sum()),
    "mi_patients_code_primary": int(pts.first_code_primary.notna().sum()),
    "mi_patients_troponin_pos": int(pts.first_troponin_pos.notna().sum()),
    "mi_patients_any_evidence": int(len(pts)),
    "overlap": {k: int((pts.found_by == k).sum()) for k in local["overlap"]},
    "coded_admissions": int(adm.code_any.sum()),
    "coded_admissions_tested": int(adm[adm.code_any].troponin_tested.sum()),
    "coded_admissions_trop_pos": int(adm[adm.code_any].troponin_positive.sum()),
    "trop_pos_admissions": int(adm.troponin_positive.sum()),
    "tested_admissions": int(adm.troponin_tested.sum()),
    "troponin_rows": trop[0],
    "troponin_text_only_rows": trop[1],
    "troponin_rows_no_hadm": trop[3],
    "checks_failing_real": [r.name for r in results if not r.passed],
    "coded_mi_died_within_30d": int(((pts.days_code_mi_to_death >= 0) & (pts.days_code_mi_to_death <= 30)).sum()),
}
assert trop[2] == trop[0], "every troponin row should have a value after text recovery"
assert linkage["strict"]["admissions_tested"] == local["linkage_sensitivity"][0]["admissions_tested"]
assert linkage["windowed"]["rows_linked"] == local["linkage_sensitivity"][1]["troponin_rows_linked"]
mismatch = {k: (v, local[k]) for k, v in spark_summary.items() if local[k] != v}
assert not mismatch, f"Spark and DuckDB disagree: {mismatch}"
print("Parity OK: all", len(spark_summary), "headline metrics match the local DuckDB run")
dbutils.notebook.exit(json.dumps({"parity": "ok", **spark_summary}))
