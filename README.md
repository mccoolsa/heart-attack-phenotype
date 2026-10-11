# Heart attack phenotype and data quality pipeline (MIMIC-IV)

A reusable acute myocardial infarction (MI) phenotype and data quality pipeline, run on **real, de-identified hospital records** from the [MIMIC-IV Clinical Database Demo v2.2](https://physionet.org/content/mimic-iv-demo/2.2/). It follows a published definition from the [HDR UK Phenotype Library](https://phenotypes.healthdatagateway.org/phenotypes/PH1024/version/2257/detail/).

## Question

Using linked admissions, diagnoses, lab results and deaths, how many patients have had a heart attack, and how much does that answer depend on which source you trust and how clean the data is?

## Answer

Depending on the rule, **between 6 and 17 of the same 100 patients** have had an MI:
- principal-diagnosis code: 6
- code in any position: 11
- positive troponin: 13
- either source: 17

Codes and troponin agree on only 7 patients. The biggest data quality risks are in how results are stored and linked, not in the record structure:
- **52% of troponin T results have no numeric value**: the `<0.01` result is only in a free-text comment.
- **29% of troponin rows are not linked to an admission**: these are pre-admission ED draws.

Full write-up: [`report/dq_report.md`](report/dq_report.md).

## What's in the repo

| Path | What it is |
|---|---|
| `src/hapdq/validation.py` | Reusable SQL check functions: duplicates, orphans/linkage, events after death, time order, age range, ICD format, ICD dictionary lookup, non-numeric results, completeness. Each returns pass/fail counts and the failing row ids. |
| `src/hapdq/phenotype.py` | MI phenotype: codes (any / principal position) vs troponin, per admission and per patient, with first date per source and which source found it. |
| `src/hapdq/inject.py` | Plants 29 known errors in a copy of the data and scores planted vs found. |
| `src/hapdq/clean.py` | Repairs what is unambiguous and quarantines the rest, with reasons. Quarantine cascades to child rows. |
| `src/hapdq/pseudonymise.py` | Salted SHA-256 patient ids for every published output (`HAPDQ_SALT`). |
| `src/hapdq/pipeline.py` | End-to-end run, which writes everything in `outputs/`. |
| `src/hapdq/engine.py` | Lets the same SQL run on DuckDB or Spark (Databricks). |
| `notebooks/databricks_pipeline.py` | Databricks notebook: loads Delta tables and runs the checks and phenotype, then asserts parity with the local run. Setup in `notebooks/README.md`. |
| `phenotypes/mi_codelist.csv` | ICD-9/ICD-10 code list built from PH1024 (`scripts/build_codelist.py`, raw export in `phenotypes/source/`). |
| `docs/data_dictionary.md` | Every table and field: type, completeness, distinct values, meaning, known issues. It is generated from the data, so it cannot drift. |
| `docs/source_probe.md` | What was verified about the data source before building on it. |
| `report/dq_report.md` / `.pdf` | Data quality findings, MI counts by source, planted vs found, limitations. |
| `tests/` | 13 pytest tests, including a test that every planted error is found on the real data. |

## Run it

```bash
pip install -r requirements.txt
python scripts/download_data.py        # ~5 MB from PhysioNet, SHA-256 verified
python scripts/build_codelist.py
cd src && python -m hapdq.pipeline     # writes outputs/ and report/figures/
python ../scripts/build_pdf.py        # report/dq_report.pdf (uses Chrome or Edge, headless)
cd .. && python -m pytest
```

The pipeline takes `--data <path>/hosp`, so it can also be pointed at the full MIMIC-IV, which needs [PhysioNet credentialing](https://physionet.org/settings/credentialing/).

## Design choices

- **Published phenotype, not an invented one.** PH1024's hospital component is ICD-10 `I21`. Its ICD-9 and `I22`/`I23` codes come from the death component and are used here for MIMIC's ICD-9 era. This adaptation is documented in the code list.
- **Troponin is a comparator, not a gold standard.** It rises in sepsis, pulmonary embolism and respiratory failure too, and the troponin-only cases in the report show exactly that.
- **Repair or quarantine, never guess.** A code like `E78Z` is quarantined, not "corrected" to `E785`.
- **One codebase, two engines.** The checks and phenotype run on DuckDB locally and on Spark SQL on Databricks (the platform behind the NHS England Secure Data Environment). `hapdq/engine.py` keeps the SQL engine-neutral. `notebooks/databricks_pipeline.py` reruns the checks and phenotype on Delta tables and asserts that all 17 headline metrics match the local run. That check passed on Databricks Free Edition.

## The Irish angle: HIPE

The Hospital In-Patient Enquiry (HIPE), run by the Healthcare Pricing Office, is Ireland's equivalent of HES. It holds one record per discharge from acute public hospitals, with a principal diagnosis and (since 2011) up to 29 additional diagnoses. It is coded in ICD-10-AM/ACHI/ACS, using the 12th edition from 2024. The MI codes `I21` and `I22` exist in ICD-10-AM, so the diagnosis part of this phenotype carries across.

Linkage is the harder part. HIPE identifies patients by hospital-specific medical record numbers, which track episodes of care rather than people. The Individual Health Identifier (IHI) was introduced in 2014. By July 2024 it was populated in GP practice systems and 41 hospitals, and HIPE was named as an early system to integrate it. I found no confirmation that HIPE integration is complete. So the Irish version of this project would look much like the MIMIC one: hospital episodes with limited linkage to GP or death records.

Sources: [HSE PQ 52130/25 (coding edition)](https://www.hse.ie/eng/about/personalpq/pq/2025-pq-responses/september-2025/pq-52130-25-emer-currie.pdf), [HIPE Report 2024](https://www.drugsandalcohol.ie/44501/1/HIPE_Report_2024.pdf), [HSE PQ 32249/24 (IHI rollout)](https://hse.ie/eng/about/personalpq/pq/2024-pq-responses/july-2024/pq-32249-24-jim-o-callaghan.pdf), [TEHDAS Ireland country factsheet (2022)](https://tehdas.eu/app/uploads/2023/03/ireland-country-visit-factsheets-10-2022.pdf).

## Data licence and citation

Code: MIT (see `LICENSE`). Data: MIMIC-IV demo, Open Data Commons ODbL 1.0. Raw data is not committed; `scripts/download_data.py` fetches it. Files in `outputs/` are derived from the MIMIC-IV demo and are shared under the same ODbL 1.0 licence.

> Johnson, A., Bulgarelli, L., Pollard, T., Horng, S., Celi, L. A., & Mark, R. (2023). MIMIC-IV Clinical Database Demo (version 2.2). PhysioNet. https://doi.org/10.13026/dp1f-ex47

Phenotype: HDR UK Phenotype Library PH1024 v2257, Acute Myocardial Infarction (George J, Herrett E, Smeeth L et al.).
