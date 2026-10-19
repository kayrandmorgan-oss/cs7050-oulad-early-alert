-- =====================================================================
-- olap_queries.sql  —  OLAP query pack over the OULAD warehouse (MySQL 8)
-- Each query is tagged '-- query: <id> | <operation> | <question>'.
-- Where a materialized aggregate can answer the question, a second
-- variant tagged '-- variant: agg' follows the '-- variant: base' version;
-- olap/run_olap.py times both and asserts they return identical rows.
-- Recorded runtimes: out/olap_runtimes.csv
-- =====================================================================

-- query: Q01 | roll-up | Total clicks by module, rolled up to presentation and grand total
-- variant: base
SELECT p.code_module, p.code_presentation, SUM(f.sum_click) AS clicks
FROM fact_vle_weekly f JOIN dim_presentation p USING (presentation_key)
GROUP BY p.code_module, p.code_presentation WITH ROLLUP;
-- variant: agg
SELECT p.code_module, p.code_presentation, SUM(a.total_clicks) AS clicks
FROM agg_pres_week_activity a JOIN dim_presentation p USING (presentation_key)
GROUP BY p.code_module, p.code_presentation WITH ROLLUP;

-- query: Q02 | drill-down | Module FFF: clicks per enrolled student by presentation and course phase
-- variant: base
SELECT p.code_presentation, w.phase,
       ROUND(SUM(f.sum_click) / MAX(n.enrolled), 1) AS clicks_per_student
FROM fact_vle_weekly f
JOIN dim_presentation p USING (presentation_key)
JOIN dim_course_week  w USING (week_key)
JOIN (SELECT presentation_key, COUNT(*) enrolled FROM dim_enrollment GROUP BY presentation_key) n USING (presentation_key)
WHERE p.code_module = 'FFF'
GROUP BY p.code_presentation, w.phase
ORDER BY p.code_presentation, MIN(w.week_num);
-- variant: agg
SELECT p.code_presentation, w.phase,
       ROUND(SUM(a.total_clicks) / MAX(n.enrolled), 1) AS clicks_per_student
FROM agg_pres_week_activity a
JOIN dim_presentation p USING (presentation_key)
JOIN dim_course_week  w USING (week_key)
JOIN (SELECT presentation_key, COUNT(*) enrolled FROM dim_enrollment GROUP BY presentation_key) n USING (presentation_key)
WHERE p.code_module = 'FFF'
GROUP BY p.code_presentation, w.phase
ORDER BY p.code_presentation, MIN(w.week_num);

-- query: Q03 | slice | One presentation (BBB-2014J): clicks and active students by activity group
-- variant: base
SELECT a.activity_group, SUM(f.sum_click) AS clicks,
       COUNT(DISTINCT CASE WHEN f.sum_click > 0 THEN f.enrollment_key END) AS students_using
FROM fact_vle_weekly f JOIN dim_activity a USING (activity_key)
JOIN dim_presentation p USING (presentation_key)
WHERE p.module_presentation = 'BBB-2014J' AND a.activity_key > 0
GROUP BY a.activity_group ORDER BY clicks DESC;

-- query: Q04 | dice | October presentations of BBB and FFF, weeks 1-4, communication+assessment activity, by outcome
-- variant: base
SELECT p.code_module, e.outcome_group, a.activity_group,
       ROUND(SUM(f.sum_click) / COUNT(DISTINCT e.enrollment_key), 2) AS clicks_per_student
FROM fact_vle_weekly f
JOIN dim_enrollment e  USING (enrollment_key)
JOIN dim_presentation p ON p.presentation_key = f.presentation_key
JOIN dim_course_week w USING (week_key)
JOIN dim_activity a    USING (activity_key)
WHERE p.code_module IN ('BBB','FFF') AND p.pres_term = 'J'
  AND w.week_num BETWEEN 1 AND 4
  AND a.activity_group IN ('communication','assessment')
GROUP BY p.code_module, e.outcome_group, a.activity_group
ORDER BY p.code_module, a.activity_group, e.outcome_group;

-- query: Q05 | pivot | Activity type x course week (1-10) click matrix for DDD-2014J
-- variant: base
SELECT a.activity_type,
  SUM(IF(w.week_num=1, f.sum_click,0)) AS w01, SUM(IF(w.week_num=2, f.sum_click,0)) AS w02,
  SUM(IF(w.week_num=3, f.sum_click,0)) AS w03, SUM(IF(w.week_num=4, f.sum_click,0)) AS w04,
  SUM(IF(w.week_num=5, f.sum_click,0)) AS w05, SUM(IF(w.week_num=6, f.sum_click,0)) AS w06,
  SUM(IF(w.week_num=7, f.sum_click,0)) AS w07, SUM(IF(w.week_num=8, f.sum_click,0)) AS w08,
  SUM(IF(w.week_num=9, f.sum_click,0)) AS w09, SUM(IF(w.week_num=10,f.sum_click,0)) AS w10
FROM fact_vle_weekly f
JOIN dim_activity a USING (activity_key) JOIN dim_course_week w USING (week_key)
JOIN dim_presentation p USING (presentation_key)
WHERE p.module_presentation='DDD-2014J' AND w.week_num BETWEEN 1 AND 10 AND a.activity_key > 0
GROUP BY a.activity_type ORDER BY SUM(f.sum_click) DESC;
-- variant: agg
SELECT a.activity_type,
  SUM(IF(w.week_num=1, g.total_clicks,0)) AS w01, SUM(IF(w.week_num=2, g.total_clicks,0)) AS w02,
  SUM(IF(w.week_num=3, g.total_clicks,0)) AS w03, SUM(IF(w.week_num=4, g.total_clicks,0)) AS w04,
  SUM(IF(w.week_num=5, g.total_clicks,0)) AS w05, SUM(IF(w.week_num=6, g.total_clicks,0)) AS w06,
  SUM(IF(w.week_num=7, g.total_clicks,0)) AS w07, SUM(IF(w.week_num=8, g.total_clicks,0)) AS w08,
  SUM(IF(w.week_num=9, g.total_clicks,0)) AS w09, SUM(IF(w.week_num=10,g.total_clicks,0)) AS w10
FROM agg_pres_week_activity g
JOIN dim_activity a USING (activity_key) JOIN dim_course_week w USING (week_key)
JOIN dim_presentation p USING (presentation_key)
WHERE p.module_presentation='DDD-2014J' AND w.week_num BETWEEN 1 AND 10 AND a.activity_key > 0
GROUP BY a.activity_type ORDER BY SUM(g.total_clicks) DESC;

-- query: Q06 | cross-tab | Final outcome x week-1-4 engagement decile (all enrollments)
-- variant: base
WITH e4 AS (
  SELECT e.enrollment_key, e.final_result, COALESCE(SUM(f.sum_click),0) AS clicks
  FROM dim_enrollment e
  LEFT JOIN (fact_vle_weekly f JOIN dim_course_week w ON w.week_key=f.week_key AND w.week_num BETWEEN 1 AND 4)
         ON f.enrollment_key = e.enrollment_key
  GROUP BY e.enrollment_key, e.final_result),
d AS (SELECT *, NTILE(10) OVER (ORDER BY clicks, enrollment_key) AS decile FROM e4)
SELECT decile, MIN(clicks) AS min_clicks, MAX(clicks) AS max_clicks, COUNT(*) AS n,
  SUM(final_result='Distinction') AS distinction, SUM(final_result='Pass') AS pass,
  SUM(final_result='Fail') AS fail, SUM(final_result='Withdrawn') AS withdrawn,
  ROUND(100*AVG(final_result IN ('Fail','Withdrawn')),1) AS pct_at_risk
FROM d GROUP BY decile ORDER BY decile;
-- variant: agg
WITH e4 AS (
  SELECT e.enrollment_key, e.final_result, COALESCE(SUM(g.total_clicks),0) AS clicks
  FROM dim_enrollment e
  LEFT JOIN (agg_enrollment_week g JOIN dim_course_week w ON w.week_key=g.week_key AND w.week_num BETWEEN 1 AND 4)
         ON g.enrollment_key = e.enrollment_key
  GROUP BY e.enrollment_key, e.final_result),
d AS (SELECT *, NTILE(10) OVER (ORDER BY clicks, enrollment_key) AS decile FROM e4)
SELECT decile, MIN(clicks) AS min_clicks, MAX(clicks) AS max_clicks, COUNT(*) AS n,
  SUM(final_result='Distinction') AS distinction, SUM(final_result='Pass') AS pass,
  SUM(final_result='Fail') AS fail, SUM(final_result='Withdrawn') AS withdrawn,
  ROUND(100*AVG(final_result IN ('Fail','Withdrawn')),1) AS pct_at_risk
FROM d GROUP BY decile ORDER BY decile;

-- query: Q07 | cross-term comparison | Module CCC: weekly clicks per enrolled student, 2014B vs 2014J, weeks 1-12
-- variant: base
SELECT w.week_num,
  ROUND(SUM(IF(p.code_presentation='2014B', f.sum_click,0)) / (SELECT COUNT(*) FROM dim_enrollment WHERE code_module='CCC' AND code_presentation='2014B'),2) AS ccc_2014B,
  ROUND(SUM(IF(p.code_presentation='2014J', f.sum_click,0)) / (SELECT COUNT(*) FROM dim_enrollment WHERE code_module='CCC' AND code_presentation='2014J'),2) AS ccc_2014J
FROM fact_vle_weekly f JOIN dim_presentation p USING (presentation_key) JOIN dim_course_week w USING (week_key)
WHERE p.code_module='CCC' AND w.week_num BETWEEN 1 AND 12
GROUP BY w.week_num ORDER BY w.week_num;
-- variant: agg
SELECT w.week_num,
  ROUND(SUM(IF(p.code_presentation='2014B', g.total_clicks,0)) / (SELECT COUNT(*) FROM dim_enrollment WHERE code_module='CCC' AND code_presentation='2014B'),2) AS ccc_2014B,
  ROUND(SUM(IF(p.code_presentation='2014J', g.total_clicks,0)) / (SELECT COUNT(*) FROM dim_enrollment WHERE code_module='CCC' AND code_presentation='2014J'),2) AS ccc_2014J
FROM agg_pres_week_activity g JOIN dim_presentation p USING (presentation_key) JOIN dim_course_week w USING (week_key)
WHERE p.code_module='CCC' AND w.week_num BETWEEN 1 AND 12
GROUP BY w.week_num ORDER BY w.week_num;

-- query: Q08 | roll-up (hierarchy) | Clicks by activity group > type with subtotals, split by outcome group
-- variant: base
SELECT a.activity_group, a.activity_type,
  SUM(IF(e.is_at_risk=0, f.sum_click,0)) AS clicks_pass_dist,
  SUM(IF(e.is_at_risk=1, f.sum_click,0)) AS clicks_fail_wd
FROM fact_vle_weekly f JOIN dim_activity a USING (activity_key) JOIN dim_enrollment e USING (enrollment_key)
WHERE a.activity_key > 0
GROUP BY a.activity_group, a.activity_type WITH ROLLUP;

-- query: Q09 | roll-up on fact 2 | Mean score and late-submission rate by module > assessment type
-- variant: base
SELECT p.code_module, d.assessment_type, COUNT(*) AS submissions,
       ROUND(AVG(s.score),1) AS mean_score, ROUND(100*AVG(s.is_late),1) AS pct_late
FROM fact_assessment_submission s
JOIN dim_assessment d USING (assessment_key)
JOIN dim_presentation p ON p.presentation_key = s.presentation_key
WHERE s.is_banked = 0
GROUP BY p.code_module, d.assessment_type WITH ROLLUP;

-- query: Q10 | drill-across | Per presentation: engagement (fact 1) beside assessment performance (fact 2) and outcomes
-- variant: base
SELECT p.module_presentation,
       n.enrolled, ROUND(v.clicks / n.enrolled) AS clicks_per_student,
       s.mean_score, ROUND(100*n.at_risk/n.enrolled,1) AS pct_at_risk
FROM dim_presentation p
JOIN (SELECT presentation_key, COUNT(*) enrolled, SUM(is_at_risk) at_risk FROM dim_enrollment GROUP BY 1) n USING (presentation_key)
JOIN (SELECT presentation_key, SUM(sum_click) clicks FROM fact_vle_weekly GROUP BY 1) v USING (presentation_key)
JOIN (SELECT presentation_key, ROUND(AVG(score),1) mean_score FROM fact_assessment_submission WHERE is_banked=0 GROUP BY 1) s USING (presentation_key)
ORDER BY p.module_presentation;
-- variant: agg
SELECT p.module_presentation,
       n.enrolled, ROUND(v.clicks / n.enrolled) AS clicks_per_student,
       s.mean_score, ROUND(100*n.at_risk/n.enrolled,1) AS pct_at_risk
FROM dim_presentation p
JOIN (SELECT presentation_key, COUNT(*) enrolled, SUM(is_at_risk) at_risk FROM dim_enrollment GROUP BY 1) n USING (presentation_key)
JOIN (SELECT presentation_key, SUM(total_clicks) clicks FROM agg_pres_week_activity GROUP BY 1) v USING (presentation_key)
JOIN (SELECT presentation_key, ROUND(AVG(score),1) mean_score FROM fact_assessment_submission WHERE is_banked=0 GROUP BY 1) s USING (presentation_key)
ORDER BY p.module_presentation;

-- query: Q11 | zero-activity analysis | Share of still-registered students with no clicks, weeks 1-8, by outcome
-- variant: base
SELECT w.week_num,
  ROUND(100*SUM(IF(e.is_at_risk=0 AND f.activity_key=0,1,0)) / COUNT(DISTINCT IF(e.is_at_risk=0, f.enrollment_key, NULL)),1) AS pct_inactive_pass_dist,
  ROUND(100*SUM(IF(e.is_at_risk=1 AND f.activity_key=0,1,0)) / COUNT(DISTINCT IF(e.is_at_risk=1, f.enrollment_key, NULL)),1) AS pct_inactive_fail_wd
FROM fact_vle_weekly f JOIN dim_enrollment e USING (enrollment_key) JOIN dim_course_week w USING (week_key)
WHERE w.week_num BETWEEN 1 AND 8
GROUP BY w.week_num ORDER BY w.week_num;
-- variant: agg
SELECT w.week_num,
  ROUND(100*SUM(IF(e.is_at_risk=0 AND g.total_clicks=0,1,0)) / SUM(e.is_at_risk=0),1) AS pct_inactive_pass_dist,
  ROUND(100*SUM(IF(e.is_at_risk=1 AND g.total_clicks=0,1,0)) / SUM(e.is_at_risk=1),1) AS pct_inactive_fail_wd
FROM agg_enrollment_week g JOIN dim_enrollment e USING (enrollment_key) JOIN dim_course_week w USING (week_key)
WHERE w.week_num BETWEEN 1 AND 8
GROUP BY w.week_num ORDER BY w.week_num;
