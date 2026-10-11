# Running on Databricks

`databricks_pipeline.py` runs the validation checks and the MI phenotype on Spark SQL with Delta tables. It uses the same `hapdq` functions as the local DuckDB pipeline; `hapdq.engine.SparkConnection` gives a SparkSession the interface the SQL expects. The last cell asserts that every headline number matches `outputs/summary.json` from the local run.

It was verified on Databricks Free Edition (serverless): all 17 headline metrics matched the local run.

## Setup (Databricks CLI)

```bash
# 1. schema and a volume for the raw files
databricks schemas create heart_attack_phenotype workspace
databricks volumes create workspace heart_attack_phenotype raw MANAGED

# 2. raw MIMIC-IV demo files (after python scripts/download_data.py)
for t in patients admissions diagnoses_icd labevents d_icd_diagnoses d_labitems; do
  databricks fs cp data/raw/mimic-iv-demo-2.2/hosp/$t.csv.gz \
    dbfs:/Volumes/workspace/heart_attack_phenotype/raw/hosp/$t.csv.gz
done

# 3. the repo (or clone it as a Databricks Git folder instead)
databricks workspace import-dir . /Workspace/Users/<you>/heart-attack-phenotype
```

Then open `notebooks/databricks_pipeline` and run all. The `schema` and `raw_path` widgets default to the paths above.

On Git Bash for Windows, set `MSYS_NO_PATHCONV=1` first, or the workspace path gets rewritten to a Windows path.
