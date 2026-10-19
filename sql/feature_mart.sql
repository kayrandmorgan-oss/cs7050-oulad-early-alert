-- =====================================================================
-- feature_mart.sql  —  week-4 early-alert feature view
--
-- Population: every enrollment still registered at the alert point, i.e.
--   date_unregistration IS NULL OR date_unregistration >= 28      [D13]
-- Cutoff: ONLY fact rows whose course week satisfies
--   dim_course_week.is_early_window = 1   (last_day <= 27)
-- are visible to the feature joins below.  mining/check_leakage.py asserts
-- this independently against the raw CSV.
-- Excluded by construction: final_result (label only), date_unregistration,
-- all fact_assessment_submission data, and every protected attribute
-- (gender, age_band, imd_band, disability) — those appear only in
-- v_audit_attributes, which is never joined into the model matrix.
-- =====================================================================
DROP VIEW IF EXISTS v_features_week4;
CREATE VIEW v_features_week4 AS
WITH pop AS (
  SELECT e.enrollment_key, e.presentation_key, e.code_module, e.code_presentation,
         e.num_of_prev_attempts, e.studied_credits, e.date_registration, e.is_at_risk
  FROM dim_enrollment e
  WHERE e.date_unregistration IS NULL OR e.date_unregistration >= 28),
wk AS (      -- enrollment-week totals, early window only
  SELECT g.enrollment_key, w.week_num, g.total_clicks, g.active_days, g.distinct_sites
  FROM agg_enrollment_week g JOIN dim_course_week w ON w.week_key = g.week_key
  WHERE w.is_early_window = 1),
grp AS (     -- activity-group clicks, weeks 1-4, early window only
  SELECT f.enrollment_key,
         SUM(IF(a.activity_group='content',       f.sum_click,0)) AS clicks_content,
         SUM(IF(a.activity_group='navigation',    f.sum_click,0)) AS clicks_navigation,
         SUM(IF(a.activity_group='communication', f.sum_click,0)) AS clicks_communication,
         SUM(IF(a.activity_group='assessment',    f.sum_click,0)) AS clicks_assessment,
         COUNT(DISTINCT IF(f.activity_key>0, f.activity_key, NULL))  AS n_activity_types
  FROM fact_vle_weekly f
  JOIN dim_course_week w ON w.week_key = f.week_key
  JOIN dim_activity a    ON a.activity_key = f.activity_key
  WHERE w.is_early_window = 1 AND w.week_num >= 1
  GROUP BY f.enrollment_key),
agg AS (
  SELECT enrollment_key,
    SUM(IF(week_num <= 0, total_clicks, 0)) AS clicks_prestart,
    SUM(IF(week_num <= 0, active_days, 0))  AS active_days_prestart,
    SUM(IF(week_num = 1, total_clicks, 0))  AS clicks_w1,
    SUM(IF(week_num = 2, total_clicks, 0))  AS clicks_w2,
    SUM(IF(week_num = 3, total_clicks, 0))  AS clicks_w3,
    SUM(IF(week_num = 4, total_clicks, 0))  AS clicks_w4,
    SUM(IF(week_num BETWEEN 1 AND 4, active_days, 0)) AS active_days_w1_4,
    SUM(IF(week_num BETWEEN 1 AND 4 AND total_clicks > 0, 1, 0)) AS active_weeks_w1_4,
    MAX(IF(week_num BETWEEN 1 AND 4 AND total_clicks > 0, week_num, 0)) AS last_active_week,
    MAX(IF(week_num = 4, distinct_sites, 0)) AS sites_w4
  FROM wk GROUP BY enrollment_key)
SELECT p.enrollment_key, p.presentation_key, p.code_module, p.code_presentation,
       p.num_of_prev_attempts, p.studied_credits,
       COALESCE(p.date_registration, -53) AS date_registration,       -- -53 = median of the modelling population, see D5
       IF(p.date_registration IS NULL, 1, 0) AS reg_date_missing,
       COALESCE(a.clicks_prestart,0) AS clicks_prestart, COALESCE(a.active_days_prestart,0) AS active_days_prestart,
       COALESCE(a.clicks_w1,0) AS clicks_w1, COALESCE(a.clicks_w2,0) AS clicks_w2,
       COALESCE(a.clicks_w3,0) AS clicks_w3, COALESCE(a.clicks_w4,0) AS clicks_w4,
       COALESCE(a.clicks_w1,0)+COALESCE(a.clicks_w2,0)+COALESCE(a.clicks_w3,0)+COALESCE(a.clicks_w4,0) AS clicks_w1_4,
       COALESCE(a.active_days_w1_4,0) AS active_days_w1_4,
       COALESCE(a.active_weeks_w1_4,0) AS active_weeks_w1_4,
       COALESCE(a.last_active_week,0) AS last_active_week,
       COALESCE(a.sites_w4,0) AS sites_w4,
       COALESCE(g.clicks_content,0) AS clicks_content, COALESCE(g.clicks_navigation,0) AS clicks_navigation,
       COALESCE(g.clicks_communication,0) AS clicks_communication, COALESCE(g.clicks_assessment,0) AS clicks_assessment,
       COALESCE(g.n_activity_types,0) AS n_activity_types,
       p.is_at_risk
FROM pop p
LEFT JOIN agg a ON a.enrollment_key = p.enrollment_key
LEFT JOIN grp g ON g.enrollment_key = p.enrollment_key;

-- Protected attributes, for the post-hoc audit only (never a model input).
DROP VIEW IF EXISTS v_audit_attributes;
CREATE VIEW v_audit_attributes AS
SELECT e.enrollment_key, s.gender, e.age_band, s.imd_band, s.disability
FROM dim_enrollment e JOIN dim_student s USING (student_key);
