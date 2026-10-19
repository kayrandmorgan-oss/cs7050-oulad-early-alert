# AI-use log

The proposal promised an itemized log of AI assistance. This project was AI-assisted throughout. The assistant was **Claude** (Anthropic; model configured as `claude-opus-5-5`), used through the Claude app in an agentic session that could run code in a Linux container and read and write my course folder.

| # | Task | What the AI did | What I did / must verify |
|---|---|---|---|
| 1 | Data acquisition | Found that the official OULAD link no longer served the archive. Located a public GitHub mirror, reassembled `studentVle` from 8 parts, checked row counts against the dataset paper, and rejected a second mirror that capped `sum_click` (D1). | Approve the data source; cite OULAD [1]. |
| 2 | Profiling + cleaning decisions | Wrote `etl/profile_raw.py`; proposed decisions D1–D14 in `etl/DECISIONS.md`. | Review each decision, especially D9 (zero rows only inside the registered span) and D13 (population). |
| 3 | Schema design | Wrote `sql/schema.sql`. Refined the proposal's Fact 1 grain to enrollment × week × activity type, with an `(no activity)` member. | Confirm the grain refinement is acceptable. |
| 4 | ETL + reconciliation | Wrote `etl/build_warehouse.py`, `sql/transform_load.sql` and `sql/reconciliation.sql`. Ran the full build (723.8 s, 28/28 checks). | Re-run the build on my own MySQL to confirm. |
| 5 | OLAP pack | Wrote the 11 queries and the timing harness; ran them; produced the heatmap and decile chart. Found the CMA lateness quirk (D14) from Q09's output. | Check that the queries answer the intended questions. |
| 6 | Feature mart + leakage test | Wrote `sql/feature_mart.sql` and `mining/check_leakage.py` (independent recompute + negative control). | — |
| 7 | Classification | Wrote and ran `mining/model.py`. The first run used raw total clicks; the AI removed that feature because of LR collinearity (disclosed in the report). The precision floor was first coded at 0.70, then set to 0.60 on cost-asymmetry grounds after seeing the 0.70 operating point. Both are shown in the sensitivity table, so no operating point is hidden. | Decide whether 0.60 is the floor I want to defend. |
| 8 | Weka cross-check | Installed Weka 3.6 and ran Logistic / J48 / NaiveBayes on the same ARFF split. | Optional: reproduce in my Weka GUI. |
| 9 | Clustering | Wrote and ran `mining/cluster.py`. Chose k = 4 (elbow, Ward ARI 0.64) over the silhouette maximum k = 2, with the rationale stated. Named the archetypes. | Agree with the k = 4 choice and the names. |
| 10 | Disparate-impact audit | Wrote and ran `mining/audit.py`. Reported the failing age-band screen as found. | — |
| 11 | Text-to-SQL | Wrote the 40 test questions + gold SQL, 200 template training pairs, the schema-context builder, the evaluator, and the scorer. Ran Qwen2.5-Coder (7B and 1.5B, Q4_K_M) on CPU via llama.cpp. Wrote the NRP LoRA kit (`text2sql/nrp/`). | **Run the LoRA condition on NRP myself** (see `text2sql/nrp/README_NRP.md`) to obtain GPU receipts, then fill in the pending rows. |
| 12 | Report | Drafted `report/Morgan_Project_Report.tex` from the logged outputs. Every number traces to a file in `out/`. | Read, edit into my own voice, and update the date before submission. |

No AI system was used as a *component* of the predictive models. The only model-in-the-loop component is the text-to-SQL evaluation, which is the subject of section 7 of the report.
