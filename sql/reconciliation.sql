-- =====================================================================
-- reconciliation.sql  —  integrity suite. Every query returns
-- (check_name, expected, actual); build_warehouse.py fails the build if
-- any row has expected <> actual.  Raw-file counts are checked separately
-- in Python against the CSVs themselves.
-- =====================================================================

-- check: R01 total clicks preserved (fact = staging)
SELECT 'R01 total clicks fact = studentVle', (SELECT SUM(sum_click) FROM stg_student_vle), (SELECT SUM(sum_click) FROM fact_vle_weekly);
-- check: R02 every clickstream row accounted for
SELECT 'R02 interaction rows fact = studentVle rows', (SELECT COUNT(*) FROM stg_student_vle), (SELECT SUM(interaction_rows) FROM fact_vle_weekly);
-- check: R03 distinct students
SELECT 'R03 dim_student = distinct studentInfo students', (SELECT COUNT(DISTINCT id_student) FROM stg_student_info), (SELECT COUNT(*) FROM dim_student);
-- check: R04 enrollments
SELECT 'R04 dim_enrollment = studentInfo rows', (SELECT COUNT(*) FROM stg_student_info), (SELECT COUNT(*) FROM dim_enrollment);
-- check: R05 submissions
SELECT 'R05 fact_assessment rows = studentAssessment rows', (SELECT COUNT(*) FROM stg_student_assessment), (SELECT COUNT(*) FROM fact_assessment_submission);
-- check: R06 score total preserved
SELECT 'R06 SUM(score) fact = staging', (SELECT SUM(score) FROM stg_student_assessment), (SELECT SUM(score) FROM fact_assessment_submission);
-- check: R07 aggregate A1 consistent with base fact
SELECT 'R07 agg_pres_week_activity clicks = fact', (SELECT SUM(sum_click) FROM fact_vle_weekly), (SELECT SUM(total_clicks) FROM agg_pres_week_activity);
-- check: R08 aggregate A2 consistent with base fact
SELECT 'R08 agg_enrollment_week clicks = fact', (SELECT SUM(sum_click) FROM fact_vle_weekly), (SELECT SUM(total_clicks) FROM agg_enrollment_week);
-- check: R09 per-presentation clicks all match (count of mismatching presentations)
SELECT 'R09 presentations with click mismatch', 0, COUNT(*) FROM (
  SELECT p.presentation_key, s.c AS stg, f.c AS fct
  FROM dim_presentation p
  LEFT JOIN (SELECT code_module, code_presentation, SUM(sum_click) c FROM stg_student_vle GROUP BY 1,2) s
         ON s.code_module=p.code_module AND s.code_presentation=p.code_presentation
  LEFT JOIN (SELECT presentation_key, SUM(sum_click) c FROM fact_vle_weekly GROUP BY 1) f
         ON f.presentation_key=p.presentation_key
  WHERE NOT (COALESCE(s.c,0) <=> COALESCE(f.c,0))) x;
-- check: R10 every clicking enrollment flagged
SELECT 'R10 enrollments with VLE activity', (SELECT COUNT(*) FROM (SELECT DISTINCT code_module, code_presentation, id_student FROM stg_student_vle) t), (SELECT SUM(has_vle_activity) FROM dim_enrollment);
-- check: R11 orphan keys in fact 1
SELECT 'R11 fact_vle_weekly orphan enrollment keys', 0, COUNT(*) FROM fact_vle_weekly f LEFT JOIN dim_enrollment e USING (enrollment_key) WHERE e.enrollment_key IS NULL;
-- check: R12 orphan keys in fact 2
SELECT 'R12 fact_assessment orphan assessment keys', 0, COUNT(*) FROM fact_assessment_submission f LEFT JOIN dim_assessment d USING (assessment_key) WHERE d.assessment_key IS NULL;
-- check: R13 zero-activity rows never coexist with clicked rows
SELECT 'R13 enrollment-weeks with both zero row and clicks', 0, COUNT(*) FROM (
  SELECT enrollment_key, week_key FROM fact_vle_weekly GROUP BY 1,2
  HAVING SUM(activity_key=0) > 0 AND SUM(activity_key>0) > 0) x;
-- check: R14 clicked rows have positive clicks; zero rows have none
SELECT 'R14 rows violating click/activity rule', 0, COUNT(*) FROM fact_vle_weekly
 WHERE (activity_key>0 AND sum_click=0) OR (activity_key=0 AND sum_click<>0);
-- check: R15 active_days bounded
SELECT 'R15 rows with active_days > 7', 0, COUNT(*) FROM fact_vle_weekly WHERE active_days > 7;
-- check: R16 at-risk label agrees with final_result
SELECT 'R16 at-risk count = Fail+Withdrawn', (SELECT COUNT(*) FROM stg_student_info WHERE final_result IN ('Fail','Withdrawn')), (SELECT SUM(is_at_risk) FROM dim_enrollment);
-- check: R17 A2 row count = distinct enrollment-weeks in fact
SELECT 'R17 agg_enrollment_week rows = fact enrollment-weeks', (SELECT COUNT(*) FROM (SELECT DISTINCT enrollment_key, week_key FROM fact_vle_weekly) t), (SELECT COUNT(*) FROM agg_enrollment_week);
-- check: R18 assessments
SELECT 'R18 dim_assessment = assessments rows', (SELECT COUNT(*) FROM stg_assessments), (SELECT COUNT(*) FROM dim_assessment);
-- check: R19 presentations
SELECT 'R19 dim_presentation = courses rows', (SELECT COUNT(*) FROM stg_courses), (SELECT COUNT(*) FROM dim_presentation);
-- check: R20 activity types (20 + the no-activity member)
SELECT 'R20 dim_activity = distinct vle activity types + 1', (SELECT COUNT(DISTINCT activity_type)+1 FROM stg_vle), (SELECT COUNT(*) FROM dim_activity);
