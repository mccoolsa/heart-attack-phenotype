# Source probe report

These facts were verified by direct requests and queries before the pipeline was designed. Where possible, each one is re-asserted on every run (see "Assertions shipped").

## MIMIC-IV Clinical Database Demo v2.2

```
Source:        https://physionet.org/files/mimic-iv-demo/2.2/      Probed: 2026-10-11, ~15 requests
Access:        keyless; HTTP 200 on HEAD and GET with a browser User-Agent; no credentialing (demo only)
Integrity:     all 9 downloaded hosp/*.csv.gz match the published SHA256SUMS.txt
Licence:       Open Data Commons Open Database License v1.0 (LICENSE.txt shipped with the data)
Granularity:   patients 100 rows (1/patient); admissions 275; diagnoses_icd 4,506; labevents 107,727
Retention:     admissions span anchor_year_group 2011-2013 (43 pts) and 2014-2016 (57 pts); dates shifted to 2110-2201
Field checks:  icd_code must be read as text (ICD-9 '0066' loses its leading zeros as an integer)
               icd_version 9 on 152 admissions, 10 on 123 -> coding system switch inside the data
               itemid 51003 = 'Troponin T', ng/mL, ref_range_upper 0.01; lab comment states MI threshold 0.10
               troponin T: 145/278 rows valuenum NULL, result '<0.01' only in `comments`
               labevents.hadm_id NULL on 26.4% of all rows, 81/278 (29%) troponin rows; 65 of the 81
               fall in [admittime - 24h, dischtime] of an admission
               anchor_age capped at 91 (3 patients), no date of birth
               deathtime matches patients.dod on every in-hospital death (0 mismatches, 15 deaths); 31 dod total
               no troponin I rows (itemids 51002, 52642) in the demo
Outcome-conditioned fields: dod / deathtime / hospital_expire_flag are outcomes. They are used only as outcomes, never as phenotype inputs.
Join yield:    diagnoses -> admissions 100% (0 orphans); admissions -> patients 100%;
               troponin -> admissions 71% by hadm_id, 94% with the 24h window
Defaults:      none; static files, no API filters
Gaps:          demo = 100 patients, not representative; full MIMIC-IV needs credentialing (not probed)
Assertions shipped: io._assert_schema (expected columns per table; itemid 51003 is Troponin T);
                    validation.run_standard_checks on every run; tests/test_hapdq.py planted-vs-found
                    on real data; download_data.py checksum assert
```

## HDR UK Phenotype Library API

```
Source:        https://phenotypes.healthdatagateway.org/api/v1/      Probed: 2026-10-11, 6 requests
Access:        keyless JSON
Search:        ?search=myocardial%20infarction -> 3 pages of 20 (60 results, many unrelated co-listed phenotypes)
Chosen:        PH1024 v2257 "Acute Myocardial Infarction (AMI)" - only MI phenotype with BOTH ICD-9 and ICD-10
               export: /phenotypes/PH1024/version/2257/export/codes/?format=json -> 52 rows
               (Read v2 43, ICD-10 4, ICD-9 3, OPCS-4 2); raw export kept in phenotypes/source/
Field checks:  hospital ('Secondary Care - Diagnosis') component = ICD-10 I21 only;
               ICD-9 410/4110/4297 and ICD-10 I21/I22/I23 sit in the 'Death' components
Alternative:   PH215 v430 (CALIBER, Kuan/Denaxas) - ICD-10 I21, I22, I23, I241, I252 (includes old MI; not used)
Gaps:          OPCS-4 (UK procedures) and Read v2 (UK GP) codes do not apply to MIMIC
```
