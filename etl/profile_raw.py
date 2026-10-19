"""Profiling pass over the seven raw OULAD CSVs. Writes out/profile_report.json and prints a summary.
Every anomaly found here has a documented handling decision in etl/DECISIONS.md."""
import json, sys, pandas as pd, numpy as np
from pathlib import Path
RAW = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw")
OUT = Path("out"); OUT.mkdir(exist_ok=True)
na = ["", "?"]
c = pd.read_csv(RAW/"courses.csv"); a = pd.read_csv(RAW/"assessments.csv", na_values=na)
sa = pd.read_csv(RAW/"studentAssessment.csv", na_values=na); si = pd.read_csv(RAW/"studentInfo.csv", na_values=na)
sr = pd.read_csv(RAW/"studentRegistration.csv", na_values=na); v = pd.read_csv(RAW/"vle.csv", na_values=na)
sv = pd.read_csv(RAW/"studentVle.csv", dtype={"code_module":"category","code_presentation":"category","id_student":"int32","id_site":"int32","date":"int16","sum_click":"int32"})
P = {}
P["rows"] = {k: int(len(x)) for k, x in dict(courses=c, assessments=a, studentAssessment=sa, studentInfo=si, studentRegistration=sr, vle=v, studentVle=sv).items()}
P["nulls"] = {k: {col: int(n) for col, n in x.isna().sum().items() if n} for k, x in dict(courses=c, assessments=a, studentAssessment=sa, studentInfo=si, studentRegistration=sr, vle=v).items()}
P["assess_null_date_types"] = a[a.date.isna()].assessment_type.value_counts().to_dict()
P["imd_band_values"] = si.imd_band.value_counts(dropna=False).to_dict()
P["final_result"] = si.final_result.value_counts().to_dict()
key = ["code_module","code_presentation","id_student"]
P["si_dup_keys"] = int(si.duplicated(key).sum()); P["sr_dup_keys"] = int(sr.duplicated(key).sum())
P["distinct_students"] = int(si.id_student.nunique())
P["students_multi_enroll"] = int((si.groupby("id_student").size() > 1).sum())
demo = ["gender","region","highest_education","imd_band","age_band","disability"]
g = si.groupby("id_student")[demo].nunique(dropna=False)
P["students_with_conflicting_demographics"] = {col: int((g[col] > 1).sum()) for col in demo}
m = si.merge(sr, on=key, how="left")
P["withdrawn_without_unreg"] = int(((m.final_result=="Withdrawn") & m.date_unregistration.isna()).sum())
P["unreg_but_not_withdrawn"] = int(((m.final_result!="Withdrawn") & m.date_unregistration.notna()).sum())
P["unreg_before_day0"] = int((m.date_unregistration <= 0).sum())
P["unreg_before_day28"] = int((m.date_unregistration < 28).sum())
P["sa_unknown_assessment"] = int((~sa.id_assessment.isin(a.id_assessment)).sum())
sa2 = sa.merge(a, on="id_assessment").merge(si[key], on=key[:2]+["id_student"], how="left", indicator=True)
P["sa_without_enrollment"] = int((sa2._merge=="left_only").sum())
P["sa_banked"] = int(sa.is_banked.sum())
P["sa_score_range"] = [float(sa.score.min()), float(sa.score.max())]
P["sa_submitted_before_day0"] = int((sa.date_submitted < 0).sum())
P["vle_activity_types"] = v.activity_type.value_counts().to_dict()
P["vle_week_from_nonnull"] = int(v.week_from.notna().sum())
P["sv_site_not_in_vle"] = int((~sv.id_site.isin(v.id_site)).sum())
P["sv_date_range"] = [int(sv.date.min()), int(sv.date.max())]
cl = sv.merge(c, on=["code_module","code_presentation"])
P["sv_after_course_end"] = int((cl.date > cl.module_presentation_length).sum()); del cl
P["sv_pre_start_rows"] = int((sv.date < 0).sum())
P["sv_dup_natural_key_rows"] = int(sv.duplicated(["code_module","code_presentation","id_student","id_site","date"]).sum())
P["sv_total_clicks"] = int(sv.sum_click.sum()); P["sv_max_click"] = int(sv.sum_click.max())
P["sv_distinct_students"] = int(sv.id_student.nunique())
enr = sv[key].drop_duplicates()
P["sv_enrollments"] = int(len(enr))
P["sv_enrollment_not_in_si"] = int(len(enr.merge(si[key], how="left", indicator=True).query("_merge=='left_only'")))
P["si_enrollments_no_clicks"] = int(len(si[key].merge(enr, how="left", indicator=True).query("_merge=='left_only'")))
(OUT/"profile_report.json").write_text(json.dumps(P, indent=2, default=str))
print(json.dumps(P, indent=1, default=str))
