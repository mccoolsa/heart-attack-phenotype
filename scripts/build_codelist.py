"""Build phenotypes/mi_codelist.csv from the HDR UK Phenotype Library export.

Source: PH1024 v2257 "Acute Myocardial Infarction (AMI)" (George, Herrett, Smeeth),
https://phenotypes.healthdatagateway.org/phenotypes/PH1024/version/2257/detail/
fetched from /api/v1/phenotypes/PH1024/version/2257/export/codes/?format=json.

Only ICD-9 and ICD-10 codes are kept: MIMIC-IV has no Read (UK GP) codes and codes
procedures in ICD-9-PCS / ICD-10-PCS rather than OPCS-4.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "phenotypes" / "source" / "PH1024.json"
OUT = ROOT / "phenotypes" / "mi_codelist.csv"

rows = json.loads(SRC.read_text(encoding="utf-8"))
keep = {"ICD10 codes": 10, "ICD9 codes": 9}
df = pd.DataFrame(
    {
        "icd_version": keep[r["coding_system"]["name"]],
        "code": r["code"].replace(".", ""),
        "description": r["description"],
        "ph1024_component": r["concept_name"].replace("File - Acute Myocardial Infarction - ", ""),
    }
    for r in rows
    if r["coding_system"]["name"] in keep
)
df = (df.groupby(["icd_version", "code", "description"], as_index=False)
        .agg(ph1024_component=("ph1024_component", lambda s: "; ".join(sorted(set(s))))))
df["match"] = "prefix"
df["source"] = "HDR UK Phenotype Library PH1024 v2257"
OUT.parent.mkdir(exist_ok=True)
df.sort_values(["icd_version", "code"], ascending=[False, True]).to_csv(OUT, index=False)
print(df.to_string(index=False))
