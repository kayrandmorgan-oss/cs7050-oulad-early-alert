"""
audit.py — post-hoc disparate-impact audit of the deployed early-alert model.

Uses the held-out (October-presentation) predictions of the best model at its tuned
threshold.  Protected attributes come from v_audit_attributes and are joined ONLY here,
after prediction.  Reports, per group: n, actual at-risk rate, flag rate, precision,
recall (TPR) and false-positive rate, plus the disparate-impact ratio of flag rates
(lowest group flag rate / highest, screened against the four-fifths rule) and the
TPR / FPR gaps — all in aggregate; no individual-level output is written.
"""
import json, sys
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining"))
from features import engine_url
OUT = ROOT / "out"
MIN_N = 100  # groups smaller than this are reported but not used in ratio screens

def main():
    pred = pd.read_csv(OUT / "holdout_predictions_best.csv")
    aud = pd.read_sql("SELECT * FROM v_audit_attributes", create_engine(engine_url()))
    d = pred.merge(aud, on="enrollment_key", how="left")
    imd = {"0-10%": "0-20%", "10-20%": "0-20%", "20-30%": "20-40%", "30-40%": "20-40%", "40-50%": "40-60%",
           "50-60%": "40-60%", "60-70%": "60-80%", "70-80%": "60-80%", "80-90%": "80-100%", "90-100%": "80-100%"}
    d["imd_quintile"] = d.imd_band.map(imd).fillna("Unknown")
    rows, summary = [], {}
    for attr in ["gender", "age_band", "imd_quintile", "disability"]:
        g = d.groupby(attr)
        t = pd.DataFrame({"n": g.size(), "actual_at_risk_rate": g.y.mean(), "flag_rate": g.flag.mean(),
                          "precision": g.apply(lambda x: x.y[x.flag == 1].mean()),
                          "recall_tpr": g.apply(lambda x: x.flag[x.y == 1].mean()),
                          "fpr": g.apply(lambda x: x.flag[x.y == 0].mean())})
        t["flag_to_actual_ratio"] = t.flag_rate / t.actual_at_risk_rate
        big = t[t.n >= MIN_N]
        summary[attr] = {"flag_rate_min_max_ratio": float(big.flag_rate.min() / big.flag_rate.max()),
                         "four_fifths_screen_on_flag_rate": bool(big.flag_rate.min() / big.flag_rate.max() >= 0.8),
                         "tpr_gap": float(big.recall_tpr.max() - big.recall_tpr.min()),
                         "fpr_gap": float(big.fpr.max() - big.fpr.min()),
                         "actual_rate_min_max_ratio": float(big.actual_at_risk_rate.min() / big.actual_at_risk_rate.max())}
        for k, r in t.iterrows(): rows.append({"attribute": attr, "group": k, **r.to_dict()})
    tab = pd.DataFrame(rows); tab.to_csv(OUT / "disparate_impact_audit.csv", index=False)
    (OUT / "disparate_impact_summary.json").write_text(json.dumps(summary, indent=2))
    print(tab.round(3).to_string(index=False)); print(json.dumps(summary, indent=1))

if __name__ == "__main__":
    main()
