-- =====================================================================
-- schema.sql  —  OULAD learning-analytics warehouse (MySQL 8)
-- CS 7050 term project, Kay Rand Morgan
--
-- Three layers in one database:
--   stg_*   staging: raw CSVs loaded as-is (strings/nullable ints)
--   dim_*   conformed dimensions with integer surrogate keys
--   fact_*  two fact tables (fact constellation)
--   agg_*   two materialized aggregate tables for aggregate navigation
-- Rebuilt end to end by:  python etl/build_warehouse.py
-- =====================================================================

SET FOREIGN_KEY_CHECKS = 0;
DROP VIEW  IF EXISTS v_features_week4;
DROP TABLE IF EXISTS agg_enrollment_week, agg_pres_week_activity,
                     fact_assessment_submission, fact_vle_weekly,
                     dim_assessment, dim_activity, dim_course_week,
                     dim_enrollment, dim_student, dim_presentation;
DROP TABLE IF EXISTS stg_courses, stg_assessments, stg_vle, stg_student_info,
                     stg_student_registration, stg_student_assessment, stg_student_vle;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------
-- STAGING  (column names and types mirror the source CSVs)
-- ---------------------------------------------------------------------
CREATE TABLE stg_courses (
  code_module VARCHAR(5), code_presentation VARCHAR(5), module_presentation_length INT);
CREATE TABLE stg_assessments (
  code_module VARCHAR(5), code_presentation VARCHAR(5), id_assessment INT,
  assessment_type VARCHAR(5), date INT NULL, weight DECIMAL(5,1));
CREATE TABLE stg_vle (
  id_site INT, code_module VARCHAR(5), code_presentation VARCHAR(5),
  activity_type VARCHAR(20), week_from INT NULL, week_to INT NULL);
CREATE TABLE stg_student_info (
  code_module VARCHAR(5), code_presentation VARCHAR(5), id_student INT,
  gender VARCHAR(1), region VARCHAR(40), highest_education VARCHAR(40),
  imd_band VARCHAR(10) NULL, age_band VARCHAR(10), num_of_prev_attempts INT,
  studied_credits INT, disability VARCHAR(1), final_result VARCHAR(12));
CREATE TABLE stg_student_registration (
  code_module VARCHAR(5), code_presentation VARCHAR(5), id_student INT,
  date_registration INT NULL, date_unregistration INT NULL);
CREATE TABLE stg_student_assessment (
  id_assessment INT, id_student INT, date_submitted INT, is_banked TINYINT, score DECIMAL(5,1) NULL);
CREATE TABLE stg_student_vle (
  code_module VARCHAR(5), code_presentation VARCHAR(5), id_student INT,
  id_site INT, date SMALLINT, sum_click INT) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- DIMENSIONS
-- ---------------------------------------------------------------------

-- One row per module presentation (22).  Hierarchy: module > presentation; year > term.
CREATE TABLE dim_presentation (
  presentation_key   TINYINT UNSIGNED PRIMARY KEY,
  code_module        CHAR(3)  NOT NULL,
  code_presentation  CHAR(5)  NOT NULL,          -- natural key kept as degenerate attribute
  module_presentation CHAR(9) NOT NULL,          -- e.g. 'AAA-2013J'
  pres_year          SMALLINT NOT NULL,          -- 2013 / 2014
  pres_term          CHAR(1)  NOT NULL,          -- 'B' (Feb start) / 'J' (Oct start)
  term_name          VARCHAR(8) NOT NULL,        -- 'February' / 'October'
  length_days        SMALLINT NOT NULL,
  n_weeks            TINYINT  NOT NULL,          -- CEIL(length_days/7)
  UNIQUE KEY uq_pres (code_module, code_presentation)
);

-- One row per real student (28,785).  Type-1 attributes that never vary across a
-- student's enrollments in the source.  PROTECTED ATTRIBUTES: gender, imd_band,
-- disability (and age_band on dim_enrollment) are NOT used by any model; they are
-- retained only for the aggregate disparate-impact audit.
CREATE TABLE dim_student (
  student_key        INT UNSIGNED PRIMARY KEY,
  id_student         INT NOT NULL UNIQUE,
  gender             CHAR(1)      NOT NULL,
  region             VARCHAR(40)  NOT NULL,
  highest_education  VARCHAR(40)  NOT NULL,
  imd_band           VARCHAR(10)  NOT NULL,      -- 'Unknown' when missing in source
  disability         CHAR(1)      NOT NULL
);

-- One row per student x module presentation (32,593).  Carries the attributes that
-- describe the registration itself, including the outcome label.
CREATE TABLE dim_enrollment (
  enrollment_key       INT UNSIGNED PRIMARY KEY,
  student_key          INT UNSIGNED NOT NULL,
  presentation_key     TINYINT UNSIGNED NOT NULL,
  id_student           INT NOT NULL,             -- degenerate natural key
  code_module          CHAR(3) NOT NULL,
  code_presentation    CHAR(5) NOT NULL,
  age_band             VARCHAR(10) NOT NULL,     -- protected; varies across enrollments for 72 students
  num_of_prev_attempts TINYINT UNSIGNED NOT NULL,
  studied_credits      SMALLINT UNSIGNED NOT NULL,
  date_registration    SMALLINT NULL,            -- days relative to presentation start
  date_unregistration  SMALLINT NULL,
  final_result         VARCHAR(12) NOT NULL,
  outcome_group        VARCHAR(16) NOT NULL,     -- 'Pass/Distinction' | 'Fail/Withdrawn'
  is_at_risk           TINYINT NOT NULL,         -- 1 = Fail or Withdrawn
  has_vle_activity     TINYINT NOT NULL,
  UNIQUE KEY uq_enr (code_module, code_presentation, id_student),
  KEY ix_enr_pres (presentation_key),
  CONSTRAINT fk_enr_student FOREIGN KEY (student_key) REFERENCES dim_student(student_key),
  CONSTRAINT fk_enr_pres    FOREIGN KEY (presentation_key) REFERENCES dim_presentation(presentation_key)
);

-- Relative course week, conformed across all presentations.
-- week_num = FLOOR(day/7)+1, so week 1 = days 0-6; weeks <= 0 are pre-start.
CREATE TABLE dim_course_week (
  week_key         TINYINT UNSIGNED PRIMARY KEY,
  week_num         SMALLINT NOT NULL UNIQUE,
  week_label       VARCHAR(8) NOT NULL,          -- 'W-03' .. 'W39'
  first_day        SMALLINT NOT NULL,
  last_day         SMALLINT NOT NULL,
  phase            VARCHAR(12) NOT NULL,         -- pre-start | early (1-4) | weeks 5-13 | weeks 14-26 | weeks 27+
  is_early_window  TINYINT NOT NULL              -- 1 if last_day <= 27 (observable at the week-4 alert)
);

-- VLE activity type (20 types + member 0 = '(no activity)').  Hierarchy: type > group.
CREATE TABLE dim_activity (
  activity_key    TINYINT UNSIGNED PRIMARY KEY,
  activity_type   VARCHAR(20) NOT NULL UNIQUE,
  activity_group  VARCHAR(16) NOT NULL           -- content | navigation | communication | assessment | none
);

-- One row per assessment (206).
CREATE TABLE dim_assessment (
  assessment_key    SMALLINT UNSIGNED PRIMARY KEY,
  id_assessment     INT NOT NULL UNIQUE,
  presentation_key  TINYINT UNSIGNED NOT NULL,
  assessment_type   VARCHAR(5) NOT NULL,         -- TMA | CMA | Exam
  weight            DECIMAL(5,1) NOT NULL,
  due_day           SMALLINT NOT NULL,
  due_day_imputed   TINYINT NOT NULL,            -- 1 for the 11 exams with no date (set to last day)
  due_week_num      SMALLINT NOT NULL,
  CONSTRAINT fk_asm_pres FOREIGN KEY (presentation_key) REFERENCES dim_presentation(presentation_key)
);

-- ---------------------------------------------------------------------
-- FACT 1  —  weekly VLE engagement
-- Grain: one row per enrollment x course week x activity type in which the
-- student clicked, PLUS exactly one activity_key=0 '(no activity)' row for each
-- enrollment-week inside the registered span with no clicks at all.
-- Measures: sum_click and interaction_rows are fully additive; active_days and
-- distinct_sites are additive across weeks but NOT across activity types.
-- ---------------------------------------------------------------------
CREATE TABLE fact_vle_weekly (
  enrollment_key    INT UNSIGNED NOT NULL,
  week_key          TINYINT UNSIGNED NOT NULL,
  activity_key      TINYINT UNSIGNED NOT NULL,
  student_key       INT UNSIGNED NOT NULL,
  presentation_key  TINYINT UNSIGNED NOT NULL,
  sum_click         INT UNSIGNED NOT NULL,
  interaction_rows  INT UNSIGNED NOT NULL,
  active_days       TINYINT UNSIGNED NOT NULL,
  distinct_sites    SMALLINT UNSIGNED NOT NULL,
  PRIMARY KEY (enrollment_key, week_key, activity_key),
  KEY ix_fvw_pres_week (presentation_key, week_key, activity_key),
  KEY ix_fvw_week (week_key),
  KEY ix_fvw_act (activity_key),
  KEY ix_fvw_student (student_key)
);

-- ---------------------------------------------------------------------
-- FACT 2  —  assessment submissions
-- Grain: one row per submitted assessment (studentAssessment row).
-- ---------------------------------------------------------------------
CREATE TABLE fact_assessment_submission (
  submission_key    INT UNSIGNED PRIMARY KEY,
  enrollment_key    INT UNSIGNED NOT NULL,
  student_key       INT UNSIGNED NOT NULL,
  presentation_key  TINYINT UNSIGNED NOT NULL,
  assessment_key    SMALLINT UNSIGNED NOT NULL,
  submit_week_key   TINYINT UNSIGNED NOT NULL,
  id_assessment     INT NOT NULL,                -- degenerate
  date_submitted    SMALLINT NOT NULL,
  days_from_due     SMALLINT NOT NULL,           -- positive = late
  is_late           TINYINT NOT NULL,
  is_banked         TINYINT NOT NULL,
  score             DECIMAL(5,1) NULL,           -- 173 source rows have no score
  weighted_score    DECIMAL(7,2) NULL,           -- score * weight / 100
  KEY ix_fas_enr (enrollment_key),
  KEY ix_fas_pres (presentation_key, assessment_key),
  KEY ix_fas_week (submit_week_key)
);

-- ---------------------------------------------------------------------
-- MATERIALIZED AGGREGATES
-- ---------------------------------------------------------------------
-- A1: presentation x week x activity (rolls the student dimension away)
CREATE TABLE agg_pres_week_activity (
  presentation_key  TINYINT UNSIGNED NOT NULL,
  week_key          TINYINT UNSIGNED NOT NULL,
  activity_key      TINYINT UNSIGNED NOT NULL,
  total_clicks      BIGINT UNSIGNED NOT NULL,
  active_students   INT UNSIGNED NOT NULL,     -- students with >0 clicks in that cell
  fact_rows         INT UNSIGNED NOT NULL,
  PRIMARY KEY (presentation_key, week_key, activity_key)
);
-- A2: enrollment x week (rolls the activity dimension away; true weekly active_days)
CREATE TABLE agg_enrollment_week (
  enrollment_key    INT UNSIGNED NOT NULL,
  week_key          TINYINT UNSIGNED NOT NULL,
  presentation_key  TINYINT UNSIGNED NOT NULL,
  total_clicks      INT UNSIGNED NOT NULL,
  active_days       TINYINT UNSIGNED NOT NULL,
  distinct_sites    SMALLINT UNSIGNED NOT NULL,
  activity_types    TINYINT UNSIGNED NOT NULL,
  PRIMARY KEY (enrollment_key, week_key),
  KEY ix_aew_pres_week (presentation_key, week_key)
);

-- ---------------------------------------------------------------------
-- GRAIN STATEMENTS (table comments).  These are read back from
-- information_schema by text2sql/schema_context.py, so the data dictionary
-- given to the language model is built from the live warehouse.
-- ---------------------------------------------------------------------
ALTER TABLE dim_presentation COMMENT = 'One row per module presentation (22). code_presentation like 2013J: year + term (B = February start, J = October start).';
ALTER TABLE dim_student      COMMENT = 'One row per student (28,785). Protected attributes (gender, imd_band, disability) are for aggregate audit only.';
ALTER TABLE dim_enrollment   COMMENT = 'One row per student x module presentation (32,593). Holds final_result and is_at_risk (1 = Fail or Withdrawn). COUNT(*) per presentation = enrolled students.';
ALTER TABLE dim_course_week  COMMENT = 'One row per relative course week. week_num 1 = days 0-6 of the presentation. week_num <= 0 is before the start.';
ALTER TABLE dim_activity     COMMENT = 'One row per VLE activity type, grouped into activity_group. activity_key 0 = (no activity), used for zero-click weeks.';
ALTER TABLE dim_assessment   COMMENT = 'One row per assessment (206): TMA, CMA or Exam, with weight and due day.';
ALTER TABLE fact_vle_weekly  COMMENT = 'GRAIN: one row per enrollment x course week x activity type with clicks, plus one activity_key=0 row with zero clicks for each registered week with no clicks. 2.87M rows. prefer the agg_ tables when the question does not need individual students.';
ALTER TABLE fact_assessment_submission COMMENT = 'GRAIN: one row per submitted assessment (173,912). score 0-100. is_late = submitted after due day. is_banked = carried over from an earlier presentation.';
ALTER TABLE agg_pres_week_activity COMMENT = 'AGGREGATE of fact_vle_weekly: one row per presentation x course week x activity type. total_clicks = SUM(sum_click). Use for any click question that does not split by student attributes.';
ALTER TABLE agg_enrollment_week COMMENT = 'AGGREGATE of fact_vle_weekly: one row per enrollment x course week (all activity types combined), including zero-click weeks. Use for per-student weekly totals.';
