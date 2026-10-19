-- =====================================================================
-- transform_load.sql  —  staging -> dimensions -> facts -> aggregates
-- Executed step by step (split on lines starting with '-- step:') by
-- etl/build_warehouse.py, which times every step.
-- Cleaning decisions referenced as [D#] are documented in etl/DECISIONS.md.
-- =====================================================================

-- step: dim_presentation
INSERT INTO dim_presentation
SELECT ROW_NUMBER() OVER (ORDER BY code_module, code_presentation),
       code_module, code_presentation, CONCAT(code_module,'-',code_presentation),
       CAST(LEFT(code_presentation,4) AS UNSIGNED), RIGHT(code_presentation,1),
       IF(RIGHT(code_presentation,1)='B','February','October'),
       module_presentation_length, CEIL(module_presentation_length/7)
FROM stg_courses;

-- step: dim_student  [D3 imd_band '10-20' -> '10-20%', NULL -> 'Unknown']
INSERT INTO dim_student
SELECT ROW_NUMBER() OVER (ORDER BY id_student), id_student,
       MAX(gender), MAX(region), MAX(highest_education),
       COALESCE(MAX(CASE WHEN imd_band='10-20' THEN '10-20%' ELSE imd_band END),'Unknown'),
       MAX(disability)
FROM stg_student_info GROUP BY id_student;

-- step: dim_enrollment  [D4 age_band kept per enrollment; D5 registration dates kept NULL when missing]
INSERT INTO dim_enrollment
SELECT ROW_NUMBER() OVER (ORDER BY si.code_module, si.code_presentation, si.id_student),
       s.student_key, p.presentation_key, si.id_student, si.code_module, si.code_presentation,
       si.age_band, si.num_of_prev_attempts, si.studied_credits,
       sr.date_registration, sr.date_unregistration, si.final_result,
       IF(si.final_result IN ('Pass','Distinction'),'Pass/Distinction','Fail/Withdrawn'),
       IF(si.final_result IN ('Pass','Distinction'),0,1),
       0
FROM stg_student_info si
JOIN dim_student s       ON s.id_student = si.id_student
JOIN dim_presentation p  ON p.code_module = si.code_module AND p.code_presentation = si.code_presentation
LEFT JOIN stg_student_registration sr
       ON sr.code_module = si.code_module AND sr.code_presentation = si.code_presentation
      AND sr.id_student = si.id_student;

-- step: dim_course_week  [D6 relative week = FLOOR(day/7)+1; range spans every day seen in either fact source]
INSERT INTO dim_course_week
WITH RECURSIVE bounds AS (
  SELECT LEAST((SELECT MIN(date) FROM stg_student_vle), (SELECT MIN(date_submitted) FROM stg_student_assessment)) AS dmin,
         GREATEST((SELECT MAX(date) FROM stg_student_vle), (SELECT MAX(date_submitted) FROM stg_student_assessment),
                  (SELECT MAX(module_presentation_length) FROM stg_courses)) AS dmax),
wk(w) AS (SELECT FLOOR(dmin/7)+1 FROM bounds
          UNION ALL SELECT w+1 FROM wk, bounds WHERE w+1 <= FLOOR(dmax/7)+1)
SELECT ROW_NUMBER() OVER (ORDER BY w), w,
       IF(w<=0, CONCAT('W-', LPAD(ABS(w),2,'0')), CONCAT('W', LPAD(w,2,'0'))),
       (w-1)*7, (w-1)*7+6,
       CASE WHEN w<=0 THEN 'pre-start' WHEN w<=4 THEN 'early (1-4)'
            WHEN w<=13 THEN 'weeks 5-13' WHEN w<=26 THEN 'weeks 14-26' ELSE 'weeks 27+' END,
       IF((w-1)*7+6 <= 27, 1, 0)
FROM wk;

-- step: dim_activity  [D7 activity_type hierarchy; member 0 represents a zero-activity week]
INSERT INTO dim_activity VALUES (0,'(no activity)','none');
INSERT INTO dim_activity
SELECT ROW_NUMBER() OVER (ORDER BY activity_type), activity_type,
       CASE WHEN activity_type IN ('forumng','oucollaborate','ouelluminate','ouwiki') THEN 'communication'
            WHEN activity_type IN ('quiz','externalquiz','questionnaire','repeatactivity') THEN 'assessment'
            WHEN activity_type = 'homepage' THEN 'navigation'
            ELSE 'content' END
FROM (SELECT DISTINCT activity_type FROM stg_vle) t;

-- step: dim_assessment  [D2 11 exams with no date -> last day of presentation, flagged]
INSERT INTO dim_assessment
SELECT ROW_NUMBER() OVER (ORDER BY a.id_assessment), a.id_assessment, p.presentation_key,
       a.assessment_type, a.weight,
       COALESCE(a.date, p.length_days), IF(a.date IS NULL,1,0),
       FLOOR(COALESCE(a.date, p.length_days)/7)+1
FROM stg_assessments a
JOIN dim_presentation p ON p.code_module=a.code_module AND p.code_presentation=a.code_presentation;

-- step: lookup tables for the clickstream transform
DROP TABLE IF EXISTS tmp_site;
CREATE TABLE tmp_site (id_site INT PRIMARY KEY, activity_key TINYINT UNSIGNED) ENGINE=InnoDB
AS SELECT v.id_site, a.activity_key FROM stg_vle v JOIN dim_activity a ON a.activity_type=v.activity_type;

-- step: fact_vle_weekly (clicked rows)  [D8 duplicate natural-key rows are summed, not dropped]
INSERT INTO fact_vle_weekly
SELECT e.enrollment_key, w.week_key, ts.activity_key, e.student_key, e.presentation_key,
       SUM(sv.sum_click), COUNT(*), COUNT(DISTINCT sv.date), COUNT(DISTINCT sv.id_site)
FROM stg_student_vle sv
JOIN tmp_site ts        ON ts.id_site = sv.id_site
JOIN dim_enrollment e   ON e.code_module = sv.code_module AND e.code_presentation = sv.code_presentation
                       AND e.id_student = sv.id_student
JOIN dim_course_week w  ON w.week_num = FLOOR(sv.date/7)+1
GROUP BY e.enrollment_key, w.week_key, ts.activity_key;

-- step: agg_enrollment_week (clicked weeks, from staging so active_days is exact)
INSERT INTO agg_enrollment_week
SELECT e.enrollment_key, w.week_key, e.presentation_key,
       SUM(sv.sum_click), COUNT(DISTINCT sv.date), COUNT(DISTINCT sv.id_site), COUNT(DISTINCT ts.activity_key)
FROM stg_student_vle sv
JOIN tmp_site ts        ON ts.id_site = sv.id_site
JOIN dim_enrollment e   ON e.code_module = sv.code_module AND e.code_presentation = sv.code_presentation
                       AND e.id_student = sv.id_student
JOIN dim_course_week w  ON w.week_num = FLOOR(sv.date/7)+1
GROUP BY e.enrollment_key, w.week_key, e.presentation_key;

-- step: registered-span calendar  [D9 zero-activity rows only inside the registered span]
DROP TABLE IF EXISTS tmp_span;
CREATE TABLE tmp_span (enrollment_key INT UNSIGNED, week_key TINYINT UNSIGNED, presentation_key TINYINT UNSIGNED,
                       student_key INT UNSIGNED, PRIMARY KEY (enrollment_key, week_key)) ENGINE=InnoDB
AS SELECT e.enrollment_key, w.week_key, e.presentation_key, e.student_key
FROM dim_enrollment e
JOIN dim_presentation p ON p.presentation_key = e.presentation_key
JOIN dim_course_week w
  ON w.week_num >= GREATEST(1, FLOOR(COALESCE(e.date_registration,0)/7)+1)
 AND w.week_num <= LEAST(p.n_weeks,
                         IF(e.date_unregistration IS NULL, p.n_weeks, FLOOR((e.date_unregistration-1)/7)+1));

-- step: fact_vle_weekly (zero-activity rows)
INSERT INTO fact_vle_weekly
SELECT s.enrollment_key, s.week_key, 0, s.student_key, s.presentation_key, 0, 0, 0, 0
FROM tmp_span s
LEFT JOIN agg_enrollment_week a ON a.enrollment_key = s.enrollment_key AND a.week_key = s.week_key
WHERE a.enrollment_key IS NULL;

-- step: agg_enrollment_week (zero-activity rows)
INSERT INTO agg_enrollment_week
SELECT f.enrollment_key, f.week_key, f.presentation_key, 0, 0, 0, 0
FROM fact_vle_weekly f WHERE f.activity_key = 0;

-- step: agg_pres_week_activity
INSERT INTO agg_pres_week_activity
SELECT presentation_key, week_key, activity_key, SUM(sum_click), SUM(sum_click > 0), COUNT(*)
FROM fact_vle_weekly GROUP BY presentation_key, week_key, activity_key;

-- step: dim_enrollment.has_vle_activity
UPDATE dim_enrollment e
JOIN (SELECT DISTINCT enrollment_key FROM agg_enrollment_week WHERE total_clicks > 0) a
  ON a.enrollment_key = e.enrollment_key
SET e.has_vle_activity = 1;

-- step: fact_assessment_submission  [D10 banked kept + flagged; D11 missing score kept NULL]
INSERT INTO fact_assessment_submission
SELECT ROW_NUMBER() OVER (ORDER BY sa.id_assessment, sa.id_student),
       e.enrollment_key, e.student_key, d.presentation_key, d.assessment_key, w.week_key,
       sa.id_assessment, sa.date_submitted, sa.date_submitted - d.due_day,
       IF(sa.date_submitted > d.due_day, 1, 0), sa.is_banked, sa.score,
       ROUND(sa.score * d.weight / 100, 2)
FROM stg_student_assessment sa
JOIN dim_assessment d   ON d.id_assessment = sa.id_assessment
JOIN dim_presentation p ON p.presentation_key = d.presentation_key
JOIN dim_enrollment e   ON e.code_module = p.code_module AND e.code_presentation = p.code_presentation
                       AND e.id_student = sa.id_student
JOIN dim_course_week w  ON w.week_num = FLOOR(sa.date_submitted/7)+1;

-- step: foreign keys on facts (added after bulk load)
ALTER TABLE fact_vle_weekly
  ADD CONSTRAINT fk_fvw_enr  FOREIGN KEY (enrollment_key)   REFERENCES dim_enrollment(enrollment_key),
  ADD CONSTRAINT fk_fvw_week FOREIGN KEY (week_key)         REFERENCES dim_course_week(week_key),
  ADD CONSTRAINT fk_fvw_act  FOREIGN KEY (activity_key)     REFERENCES dim_activity(activity_key),
  ADD CONSTRAINT fk_fvw_stu  FOREIGN KEY (student_key)      REFERENCES dim_student(student_key),
  ADD CONSTRAINT fk_fvw_pres FOREIGN KEY (presentation_key) REFERENCES dim_presentation(presentation_key);
ALTER TABLE fact_assessment_submission
  ADD CONSTRAINT fk_fas_enr  FOREIGN KEY (enrollment_key)   REFERENCES dim_enrollment(enrollment_key),
  ADD CONSTRAINT fk_fas_asm  FOREIGN KEY (assessment_key)   REFERENCES dim_assessment(assessment_key),
  ADD CONSTRAINT fk_fas_week FOREIGN KEY (submit_week_key)  REFERENCES dim_course_week(week_key),
  ADD CONSTRAINT fk_fas_stu  FOREIGN KEY (student_key)      REFERENCES dim_student(student_key),
  ADD CONSTRAINT fk_fas_pres FOREIGN KEY (presentation_key) REFERENCES dim_presentation(presentation_key);

-- step: drop working tables
DROP TABLE tmp_site;
DROP TABLE tmp_span;
