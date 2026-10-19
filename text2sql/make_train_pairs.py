"""
make_train_pairs.py — ~200 (question, SQL) pairs for the LoRA condition, generated from
parameterised templates over this schema.  Every pair is executed against the warehouse
(must run and return >= 1 row), and any pair whose SQL or question duplicates a held-out
test item is discarded, so the 40 test questions stay unseen.

    python text2sql/make_train_pairs.py  -> text2sql/train_pairs.jsonl
"""
import json, random, sys
from pathlib import Path
from sqlalchemy import create_engine, text
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining")); sys.path.insert(0, str(ROOT / "text2sql"))
from features import engine_url
from questions_test import QUESTIONS

R = random.Random(7050)
MODS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]
PRES = {"AAA": ["2013J", "2014J"], "BBB": ["2013B", "2013J", "2014B", "2014J"], "CCC": ["2014B", "2014J"],
        "DDD": ["2013B", "2013J", "2014B", "2014J"], "EEE": ["2013J", "2014B", "2014J"],
        "FFF": ["2013B", "2013J", "2014B", "2014J"], "GGG": ["2013J", "2014B", "2014J"]}
ACTS = ["resource", "oucontent", "subpage", "url", "forumng", "quiz", "homepage", "ouwiki", "page", "oucollaborate"]
GROUPS = ["content", "communication", "assessment", "navigation"]
RESULTS = ["Pass", "Fail", "Withdrawn", "Distinction"]
ATYPES = ["TMA", "CMA", "Exam"]

def mp():
    m = R.choice(MODS); return m, R.choice(PRES[m])

def t_total_clicks_mp():
    m, p = mp(); return (f"Total clicks in {m}-{p}. Return one number.",
        f"SELECT SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}'")
def t_clicks_week_range():
    m, p = mp(); w1 = R.randint(1, 8); w2 = w1 + R.randint(2, 6)
    return (f"Weekly total clicks in {m}-{p} for course weeks {w1} to {w2}. Return week_num and total clicks.",
        f"SELECT w.week_num, SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' AND w.week_num BETWEEN {w1} AND {w2} GROUP BY w.week_num")
def t_activity_clicks_module():
    m = R.choice(MODS); a = R.choice(ACTS)
    return (f"Total clicks on {a} activities in module {m}, per presentation. Return code_presentation and total clicks.",
        f"SELECT p.code_presentation, SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_presentation p USING (presentation_key) JOIN dim_activity d USING (activity_key) WHERE p.code_module='{m}' AND d.activity_type='{a}' GROUP BY p.code_presentation")
def t_group_share_mp():
    m, p = mp(); return (f"In {m}-{p}, total clicks per activity type, excluding the no-activity member. Return activity_type and total clicks.",
        f"SELECT d.activity_type, SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_activity d USING (activity_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' AND d.activity_key>0 GROUP BY d.activity_type")
def t_active_students_week():
    m, p = mp(); w = R.randint(1, 12)
    return (f"How many registered students made at least one click in course week {w} of {m}-{p}? Return one number.",
        f"SELECT COUNT(*) FROM agg_enrollment_week g JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' AND w.week_num={w} AND g.total_clicks>0")
def t_zero_week():
    m, p = mp(); w = R.randint(2, 12)
    return (f"How many registered students in {m}-{p} had no clicks at all in course week {w}? Return one number.",
        f"SELECT COUNT(*) FROM agg_enrollment_week g JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' AND w.week_num={w} AND g.total_clicks=0")
def t_enrolled():
    m = R.choice(MODS); r = R.choice(RESULTS)
    return (f"Number of enrollments with final result {r} in each presentation of module {m}. Return code_presentation and count.",
        f"SELECT code_presentation, COUNT(*) FROM dim_enrollment WHERE code_module='{m}' AND final_result='{r}' GROUP BY code_presentation")
def t_at_risk_rate():
    m = R.choice(MODS); return (f"Percentage of enrollments that are at risk (Fail or Withdrawn) in each presentation of module {m}, rounded to 1 decimal. Return code_presentation and percentage.",
        f"SELECT code_presentation, ROUND(100*AVG(is_at_risk),1) FROM dim_enrollment WHERE code_module='{m}' GROUP BY code_presentation")
def t_avg_score_type():
    m = R.choice(MODS); t = R.choice(ATYPES)
    return (f"Average {t} score in each presentation of module {m}, excluding banked submissions, rounded to 1 decimal. Return code_presentation and average.",
        f"SELECT p.code_presentation, ROUND(AVG(s.score),1) FROM fact_assessment_submission s JOIN dim_assessment d USING (assessment_key) JOIN dim_presentation p ON p.presentation_key=s.presentation_key WHERE p.code_module='{m}' AND d.assessment_type='{t}' AND s.is_banked=0 GROUP BY p.code_presentation")
def t_late_rate_mp():
    m, p = mp(); return (f"Percentage of submissions that were late in {m}-{p}, by assessment type, rounded to 1 decimal. Return assessment_type and percentage.",
        f"SELECT d.assessment_type, ROUND(100*AVG(s.is_late),1) FROM fact_assessment_submission s JOIN dim_assessment d USING (assessment_key) JOIN dim_presentation p ON p.presentation_key=s.presentation_key WHERE p.module_presentation='{m}-{p}' GROUP BY d.assessment_type")
def t_clicks_by_outcome_act():
    m, p = mp(); a = R.choice(ACTS)
    return (f"In {m}-{p}, total clicks on {a} for each final_result. Return final_result and total clicks.",
        f"SELECT e.final_result, SUM(f.sum_click) FROM fact_vle_weekly f JOIN dim_enrollment e USING (enrollment_key) JOIN dim_activity d USING (activity_key) WHERE e.code_module='{m}' AND e.code_presentation='{p}' AND d.activity_type='{a}' GROUP BY e.final_result")
def t_clicks_by_region():
    m, p = mp(); return (f"Total clicks by student region in {m}-{p}. Return region and total clicks.",
        f"SELECT s.region, SUM(f.sum_click) FROM fact_vle_weekly f JOIN dim_student s USING (student_key) JOIN dim_presentation p ON p.presentation_key=f.presentation_key WHERE p.module_presentation='{m}-{p}' GROUP BY s.region")
def t_avg_clicks_outcome_early():
    m, p = mp(); w = R.choice([2, 3, 6, 8])
    return (f"In {m}-{p}, average total clicks per student over course weeks 1-{w} for each final_result, counting students with no clicks as 0, rounded to 1 decimal. Return final_result and average.",
        f"SELECT e.final_result, ROUND(AVG(COALESCE(t.c,0)),1) FROM dim_enrollment e LEFT JOIN (SELECT g.enrollment_key, SUM(g.total_clicks) c FROM agg_enrollment_week g JOIN dim_course_week w USING (week_key) WHERE w.week_num BETWEEN 1 AND {w} GROUP BY g.enrollment_key) t ON t.enrollment_key=e.enrollment_key WHERE e.code_module='{m}' AND e.code_presentation='{p}' GROUP BY e.final_result")
def t_phase_clicks_mp():
    m, p = mp(); return (f"Total clicks in each course phase for {m}-{p}. Return phase and total clicks.",
        f"SELECT w.phase, SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' GROUP BY w.phase")
def t_rollup_group():
    m = R.choice(MODS); return (f"For module {m}, total clicks by activity group and activity type with subtotals (WITH ROLLUP), excluding the no-activity member. Return activity_group, activity_type and total clicks.",
        f"SELECT d.activity_group, d.activity_type, SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_activity d USING (activity_key) JOIN dim_presentation p USING (presentation_key) WHERE p.code_module='{m}' AND d.activity_key>0 GROUP BY d.activity_group, d.activity_type WITH ROLLUP")
def t_pivot_weeks():
    m, p = mp(); g = R.choice(GROUPS)
    return (f"For {m}-{p}, {g} clicks pivoted by term phase: one column each for 'pre-start', 'early (1-4)' and 'weeks 5-13'. Return the three numbers.",
        f"SELECT SUM(IF(w.phase='pre-start',a.total_clicks,0)), SUM(IF(w.phase='early (1-4)',a.total_clicks,0)), SUM(IF(w.phase='weeks 5-13',a.total_clicks,0)) FROM agg_pres_week_activity a JOIN dim_activity d USING (activity_key) JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' AND d.activity_group='{g}'")
def t_top_week():
    m, p = mp(); return (f"Which course week had the most clicks in {m}-{p}? Return week_num and total clicks.",
        f"SELECT w.week_num, SUM(a.total_clicks) c FROM agg_pres_week_activity a JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' GROUP BY w.week_num ORDER BY c DESC LIMIT 1")
def t_assess_count():
    m, p = mp(); return (f"How many submissions were made for each assessment in {m}-{p}? Return id_assessment and count.",
        f"SELECT d.id_assessment, COUNT(*) FROM fact_assessment_submission s JOIN dim_assessment d USING (assessment_key) JOIN dim_presentation p ON p.presentation_key=d.presentation_key WHERE p.module_presentation='{m}-{p}' GROUP BY d.id_assessment")
def t_credits():
    m = R.choice(MODS); return (f"Average studied_credits per final_result in module {m}, rounded to 1 decimal. Return final_result and average.",
        f"SELECT final_result, ROUND(AVG(studied_credits),1) FROM dim_enrollment WHERE code_module='{m}' GROUP BY final_result")
def t_term_compare():
    a = R.choice(ACTS); return (f"Total {a} clicks in February-start versus October-start presentations. Return term_name and total clicks.",
        f"SELECT p.term_name, SUM(a.total_clicks) FROM agg_pres_week_activity a JOIN dim_presentation p USING (presentation_key) JOIN dim_activity d USING (activity_key) WHERE d.activity_type='{a}' GROUP BY p.term_name")
def t_active_days():
    m, p = mp(); w = R.randint(1, 10)
    return (f"Average active days in course week {w} of {m}-{p} among students who clicked that week, rounded to 2 decimals. Return one number.",
        f"SELECT ROUND(AVG(g.active_days),2) FROM agg_enrollment_week g JOIN dim_course_week w USING (week_key) JOIN dim_presentation p USING (presentation_key) WHERE p.module_presentation='{m}-{p}' AND w.week_num={w} AND g.total_clicks>0")

TEMPLATES = [v for k, v in dict(globals()).items() if k.startswith("t_")]

def main(target=200):
    eng = create_engine(engine_url())
    test_sql = {" ".join(q["gold_sql"].split()).lower() for q in QUESTIONS}
    test_q = {q["question"].lower() for q in QUESTIONS}
    seen, pairs = set(), []
    with eng.connect() as c:
        tries = 0
        while len(pairs) < target and tries < 3000:
            tries += 1
            tmpl = TEMPLATES[len(pairs) % len(TEMPLATES)] if tries < 2000 else R.choice(TEMPLATES)
            q, s = tmpl()
            key = " ".join(s.split()).lower()
            if key in seen or key in test_sql or q.lower() in test_q: continue
            try: rows = c.execute(text(s)).fetchall()
            except Exception as e: print("BAD", s, e); continue
            if not rows or all(v is None for v in rows[0]): continue
            seen.add(key); pairs.append({"template": tmpl.__name__, "question": q, "sql": s})
    with open(ROOT / "text2sql" / "train_pairs.jsonl", "w") as f:
        for p in pairs: f.write(json.dumps(p) + "\n")
    agg = sum("agg_" in p["sql"] for p in pairs)
    print(f"{len(pairs)} pairs from {len(TEMPLATES)} templates; {agg} use agg_ tables")

if __name__ == "__main__":
    main()
