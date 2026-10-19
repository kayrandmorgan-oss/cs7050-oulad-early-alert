# From Clickstream to Early Alert

CS 7050 term project (Kay Rand Morgan, Section W01). This repository holds a MySQL star-schema warehouse and a mining pipeline over the Open University Learning Analytics Dataset (OULAD). The final report is `report/Morgan_Project_Report.pdf`. The demo narration script is in `docs/demo_script.md`, and the tools that recorded and rendered the demo video are in `docs/video_tools/`.

## Layout

```
data/get_data.sh          downloads the seven OULAD CSVs into data/raw/ (not committed; see "Data")
sql/schema.sql            DDL: staging, 6 dimensions, 2 facts, 2 aggregate tables, grain comments
sql/transform_load.sql    staging -> dimensions -> facts -> aggregates (timed step by step)
sql/reconciliation.sql    the integrity suite (R01-R20)
sql/feature_mart.sql      v_features_week4 (early-alert features) + v_audit_attributes
etl/profile_raw.py        profiling pass -> out/profile_report.json
etl/DECISIONS.md          one documented decision per anomaly (D1-D13)
etl/build_warehouse.py    ONE-COMMAND REBUILD: schema, staging, transform, views, reconciliation
olap/olap_queries.sql     11-query OLAP pack (base and aggregate variants)
olap/run_olap.py          times every variant and asserts base and aggregate results are identical
olap/make_olap_figures.py engagement heatmap, outcome-by-decile chart
mining/features.py        feature list, forbidden-column list, ARFF writer
mining/check_leakage.py   automated no-leakage assertion (independent recompute from raw CSV)
mining/model.py           LR / CART / NB: 5-fold CV, Feb->Oct held-out test, threshold tuning, lift
mining/weka_crosscheck.sh the same held-out test in Weka (cross-package validation)
mining/cluster.py         k-means (k = 2..10, elbow + silhouette), Ward cross-check, profiles
mining/audit.py           post-hoc disparate-impact audit (aggregate only)
text2sql/                 schema-context builder, 40 test questions, 200 LoRA pairs, evaluator, scorer
text2sql/nrp/             LoRA training script + instructions for the NRP GPU hub
out/                      every number in the report (JSON/CSV logs, query results, predictions)
figures/                  every figure in the report (PDF + PNG)
report/                   LaTeX source and PDF of the final report
AI_USE_LOG.md             itemized AI-use log
```

## Reproduce

Requirements: MySQL 8 (with `local_infile` enabled if you use `--load-data`), Python 3.10+, and the following packages: `pandas sqlalchemy pymysql scikit-learn matplotlib scipy`. Weka is optional (cross-check). `llama-cpp-python` is optional (CPU text-to-SQL).

```bash
# 0. database user (once)
mysql -uroot -e "CREATE USER 'oulad'@'localhost' IDENTIFIED BY 'oulad'; GRANT ALL ON *.* TO 'oulad'@'localhost';"
#    (or set OULAD_DB_HOST / OULAD_DB_PORT / OULAD_DB_USER / OULAD_DB_PASS / OULAD_DB_NAME)

# 1. get the data, profile the raw files, then rebuild the warehouse from the CSVs (about 12 min on 2 cores)
bash data/get_data.sh
python etl/profile_raw.py
python etl/build_warehouse.py            # exits non-zero if any reconciliation check fails
#    python etl/build_warehouse.py --load-data   # LOAD DATA LOCAL INFILE fallback for the clickstream

# 2. OLAP pack, runtimes, figures
python olap/run_olap.py && python olap/make_olap_figures.py

# 3. mining
python mining/check_leakage.py          # must print LEAKAGE CHECK PASS
python mining/model.py
bash   mining/weka_crosscheck.sh        # optional
python mining/cluster.py 4
python mining/audit.py

# 4. text-to-SQL (CPU fallback; see text2sql/nrp/README_NRP.md for the GPU/LoRA condition)
python text2sql/make_train_pairs.py
bash   text2sql/run_cpu_evals.sh          # uses the frozen text2sql/schema_context.txt
```

On Windows, run the same commands from a terminal in the project folder. Use `py` in place of `python3` if that is how Python is installed. `run_cpu_evals.sh` stops and starts the Linux MySQL service, so on Windows run its `evaluate.py --generate-only` and `score.py` lines by hand.

## Data

OULAD: J. Kuzilek, M. Hlosta, Z. Zdrahal, *Scientific Data* 4:170171 (2017), CC BY 4.0. In October 2026 the official download link (`analyse.open.ac.uk`) redirected to a page without the archive. The CSVs were therefore taken from a public mirror, `github.com/LuongAnh1/oulad-data-warehouse` (`raw_data/`), and `studentVle` was reassembled from its eight parts. Every table's row count matches the dataset paper, and the reconciliation suite checks the files end to end (see `etl/DECISIONS.md`, D1).

## Build record (this run)

The warehouse was built in a Linux container: MySQL 8.0.46, 2 vCPU, 8 GB RAM. The first full build took 723.8 s and passed 28/28 reconciliation checks (`out/build_log_initial_run.json`; these are the numbers in the report). All timings in the report come from that machine. A second clean rebuild from an empty database, run as the M5 end-to-end test, is logged in `out/build_log.json`.

`text2sql/schema_context.txt` is the exact context used for the reported text-to-SQL runs. It was generated before the table comments' semicolons were changed to periods, a change needed because the build script splits SQL on `;`. Keep using this file for the NRP runs so that every condition sees the same prompt.
