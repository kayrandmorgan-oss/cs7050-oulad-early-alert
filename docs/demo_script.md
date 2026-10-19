# Demo video: narration script

`Morgan_Demo.mp4` (about 5½ minutes, 1920×1080) replays **real recorded runs** of the pipeline on the build machine, with on-screen captions. Long steps are sped up, and a badge on screen gives the speed factor. Read the narration below over the video, or re-record your own screen following the same steps. Timestamps are approximate; `Morgan_Demo.chapters.json` has the exact start time of each scene.

| # | Scene (command shown) | Say |
|---|---|---|
| 0 | Title card | “This is my CS 7050 term project, *From Clickstream to Early Alert*. Everything you’ll see is a real run of the pipeline. The long steps are sped up, and the speed is shown on screen.” |
| 1 | `ls -lh data/raw/*.csv && wc -l …` | “The input is the Open University Learning Analytics Dataset: seven CSV files, including ten point six million clickstream rows. `data/get_data.sh` downloads them.” |
| 2 | Constellation diagram | “The target is a fact constellation. Weekly VLE clicks and assessment submissions share conformed dimensions for enrollment, student, presentation and course week. Two aggregate tables roll the clicks up.” |
| 3 | `python3 etl/build_warehouse.py` | “One command rebuilds the warehouse from scratch. It loads the staging tables, runs seventeen timed SQL transform steps, then runs the reconciliation suite. About nine minutes of real time is compressed here. At the end, all twenty-eight checks pass. Every row and all thirty-nine point six million clicks reach the fact table and both aggregates.” |
| 4 | `mysql … <row counts; one student's weeks 1-4>` | “Inside the warehouse: the row counts, and one student’s first four weeks. Each row is one week and one activity type. A week with no clicks is stored as a *no activity* row, so inactivity can be counted.” |
| 5 | `python3 olap/run_olap.py` | “The OLAP pack has eleven queries: roll-up, drill-down, slice, dice, pivot, cross-tab, cross-term and drill-across. Each is timed five times. Where an aggregate can answer the question, the harness checks that it returns identical rows. The roll-ups drop from about seven seconds to eleven milliseconds.” |
| 5b | `column -s, -t out/olap_results/Q06.csv` | “Here is the cross-tab of outcome against week-one-to-four click decile. In the bottom decile, ninety-seven percent fail or withdraw. In the top decile, twenty-five percent do.” |
| 5c | Engagement heatmap | “Weekly clicks per student for all twenty-two presentations: early peaks, then a taper. Module intensity differs about three-fold, which is why the model uses clicks *relative* to classmates.” |
| 6 | `python3 mining/check_leakage.py` | “Before any modeling, this script proves the week-four cutoff holds. It recomputes every feature from the raw CSV using only days zero to twenty-seven and gets zero mismatches. Without the cutoff it gets twenty-five thousand mismatches, so the test can detect leakage.” |
| 7 | `python3 mining/model.py` | “Three classifiers, evaluated two ways: five-fold cross-validation, then training on February presentations and testing on October. Logistic regression wins, with held-out AUC point seven one nine, eight points above the baseline. With the threshold tuned for recall, it catches eighty percent of at-risk students.” |
| 7b | ROC / PR / lift | “On the held-out test, the top risk decile is eighty percent at risk, a lift of about two.” |
| 8 | `python3 mining/cluster.py 4` + profiles | “K-means picks out four engagement archetypes, confirmed by Ward clustering. The minimal-presence fifth of the class has a sixty-five percent fail-or-withdraw rate. The assessment-spike group has the most withdrawals.” |
| 9 | `python3 mining/audit.py` | “Protected attributes are joined only after prediction. The model passes the four-fifths screen for gender, deprivation and disability, but fails it for age band. I report that as found.” |
| 10 | `show_example.py T04` | “Finally, text-to-SQL. Qwen2.5-Coder 7B wrote SQL from a schema context generated from the live warehouse. Here it is correct, and it used the aggregate table.” |
| 10b | `show_example.py T18` | “A typical miss: it wrote *week_key equals two*, treating a surrogate key as a week number. That error comes directly from the dimensional design.” |
| 10c | `score.py …` | “Scored on forty held-out questions, it gets nineteen exactly right, and it routes ninety-one percent of eligible questions to the aggregates. With no schema it gets none.” |
| 11 | Closing card | “The code is on GitHub, and the report has the full results. Thank you.” |
