"""
check_leakage.py — automated no-leakage assertion for the week-4 feature mart.

Independently recomputes every clickstream feature in v_features_week4 from the
RAW studentVle.csv using only rows with day < 28, then asserts that the SQL view
matches it exactly for every enrollment.  Then repeats the computation with
all rows (no cutoff) and asserts that the view does NOT match that, which
proves the test can detect leakage.  Finally checks that the model feature list
contains no label, outcome-timing, assessment or protected columns.

    python mining/check_leakage.py          (exit code 0 = pass)
"""
import json, os, sys
from pathlib import Path
import numpy as np, pandas as pd
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.getenv("OULAD_RAW_DIR", ROOT / "data" / "raw"))
sys.path.insert(0, str(ROOT / "mining"))
from features import FEATURES, FORBIDDEN, engine_url

COLS = ["clicks_prestart", "active_days_prestart", "clicks_w1", "clicks_w2", "clicks_w3", "clicks_w4",
        "clicks_w1_4", "active_days_w1_4", "active_weeks_w1_4", "last_active_week", "sites_w4",
        "clicks_content", "clicks_navigation", "clicks_communication", "clicks_assessment", "n_activity_types"]
GROUP = {"forumng": "communication", "oucollaborate": "communication", "ouelluminate": "communication",
         "ouwiki": "communication", "quiz": "assessment", "externalquiz": "assessment",
         "questionnaire": "assessment", "repeatactivity": "assessment", "homepage": "navigation"}

def recompute(sv, keys, cutoff):
    # Days >= 21 are bucketed into "week 4".  With cutoff=28 this is exactly weeks 1-4; with no
    # cutoff it is what a leaky pipeline would compute (week 4 absorbs the rest of the course).
    d = sv if cutoff is None else sv[sv.date < cutoff]
    d = d.assign(week=np.minimum(np.floor(d.date / 7).astype(int) + 1, 4))
    k = ["code_module", "code_presentation", "id_student"]
    daily = d.groupby(k + ["week"]).agg(clicks=("sum_click", "sum"), days=("date", "nunique"),
                                         sites=("id_site", "nunique")).reset_index()
    early = daily[daily.week <= 4]
    pre = early[early.week <= 0].groupby(k).agg(clicks_prestart=("clicks", "sum"), active_days_prestart=("days", "sum"))
    w = early[early.week >= 1]
    piv = w.pivot_table(index=k, columns="week", values="clicks", aggfunc="sum", fill_value=0)
    piv = piv.reindex(columns=[1, 2, 3, 4], fill_value=0); piv.columns = ["clicks_w1", "clicks_w2", "clicks_w3", "clicks_w4"]
    piv["clicks_w1_4"] = piv.sum(axis=1)
    o = w.groupby(k).agg(active_days_w1_4=("days", "sum"), active_weeks_w1_4=("clicks", lambda s: int((s > 0).sum())),
                         last_active_week=("week", "max"))
    s4 = w[w.week == 4].groupby(k).agg(sites_w4=("sites", "sum"))   # distinct sites within the week-4 bucket
    g = d[(d.week >= 1) & (d.week <= 4)]
    gp = g.pivot_table(index=k, columns="group", values="sum_click", aggfunc="sum", fill_value=0)
    gp = gp.reindex(columns=["content", "navigation", "communication", "assessment"], fill_value=0)
    gp.columns = ["clicks_" + c for c in gp.columns]
    nt = g.groupby(k).activity_type.nunique().rename("n_activity_types")
    out = keys.set_index(k).join([pre, piv, o, s4, gp, nt]).fillna(0)
    return out[COLS].astype(int).reset_index()

def main():
    eng = create_engine(engine_url())
    view = pd.read_sql("SELECT v.*, e.id_student FROM v_features_week4 v JOIN dim_enrollment e USING (enrollment_key)", eng)
    vle = pd.read_csv(RAW / "vle.csv", usecols=["id_site", "activity_type"])
    sv = pd.read_csv(RAW / "studentVle.csv", dtype={"code_module": "category", "code_presentation": "category",
                     "id_student": "int32", "id_site": "int32", "date": "int16", "sum_click": "int32"})
    vle["group"] = vle.activity_type.map(GROUP).fillna("content")
    vle = vle.astype({"activity_type": "category", "group": "category"})
    sv = sv.merge(vle, on="id_site", how="left")
    keys = view[["code_module", "code_presentation", "id_student"]].copy()
    k = ["code_module", "code_presentation", "id_student"]
    v = view.set_index(k)[COLS].astype(int).sort_index()
    res = {}
    for label, cutoff in [("day<28 (expected match)", 28), ("no cutoff (expected mismatch)", None)]:
        r = recompute(sv, keys, cutoff).set_index(k).sort_index()
        mism = int((r.values != v.values).any(axis=1).sum())
        res[label] = {"enrollments": len(v), "enrollments_with_any_mismatch": mism}
        print(f"{label:32s} enrollments={len(v):,}  mismatching={mism:,}")
    bad_feats = sorted(set(FEATURES) & FORBIDDEN)
    res["forbidden_columns_in_feature_list"] = bad_feats
    ok = (res["day<28 (expected match)"]["enrollments_with_any_mismatch"] == 0
          and res["no cutoff (expected mismatch)"]["enrollments_with_any_mismatch"] > 0 and not bad_feats)
    res["PASS"] = ok
    (ROOT / "out" / "leakage_check.json").write_text(json.dumps(res, indent=2))
    print("forbidden columns in feature list:", bad_feats or "none"); print("LEAKAGE CHECK", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
