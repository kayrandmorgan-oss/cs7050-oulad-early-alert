"""Shared feature definitions for the week-4 early-alert models."""
import os
import numpy as np, pandas as pd
from sqlalchemy import create_engine

def engine_url():
    return "mysql+pymysql://{u}:{p}@{h}:{port}/{db}".format(
        u=os.getenv("OULAD_DB_USER", "oulad"), p=os.getenv("OULAD_DB_PASS", "oulad"),
        h=os.getenv("OULAD_DB_HOST", "localhost"), port=os.getenv("OULAD_DB_PORT", "3306"),
        db=os.getenv("OULAD_DB_NAME", "oulad_dw"))

CLICKS = ["clicks_prestart", "clicks_w1", "clicks_w2", "clicks_w3", "clicks_w4", "clicks_w1_4",
          "clicks_content", "clicks_navigation", "clicks_communication", "clicks_assessment"]
COUNTS = ["active_days_prestart", "active_days_w1_4", "active_weeks_w1_4", "last_active_week",
          "sites_w4", "n_activity_types"]
REG = ["num_of_prev_attempts", "studied_credits", "date_registration", "reg_date_missing"]
DERIVED = ["rel_clicks_w1_4", "trend_w4_vs_w1"]
MODULES = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]
MOD_COLS = [f"mod_{m}" for m in MODULES]
# clicks_w1_4 stays in the mart (and the ARFF) but is not a model input: it is the sum of the
# four weekly columns and, with rel_clicks_w1_4, made the logistic coefficients collinear and
# uninterpretable (+1.19 / -1.11 in the first run).
FEATURES = [c for c in REG + CLICKS + COUNTS + DERIVED + MOD_COLS if c != "clicks_w1_4"]

# Columns that must never be model inputs (label, outcome timing, post-cutoff data, protected attributes).
FORBIDDEN = {"is_at_risk", "final_result", "outcome_group", "date_unregistration", "score", "weighted_score",
             "days_from_due", "is_late", "gender", "age_band", "imd_band", "disability", "region",
             "highest_education", "has_vle_activity"}

def load(eng=None):
    eng = eng or create_engine(engine_url())
    df = pd.read_sql("SELECT * FROM v_features_week4 ORDER BY enrollment_key", eng)
    aud = pd.read_sql("SELECT * FROM v_audit_attributes", eng)
    return add_derived(df), aud

def add_derived(df):
    df = df.copy()
    lc = np.log1p(df.clicks_w1_4)
    # Relative engagement: uses only other students' week-1-4 clicks in the same presentation,
    # which are also observable at the alert point.
    df["rel_clicks_w1_4"] = lc - lc.groupby(df.presentation_key).transform("median")
    df["trend_w4_vs_w1"] = np.log1p(df.clicks_w4) - np.log1p(df.clicks_w1)
    for m in MODULES:
        df[f"mod_{m}"] = (df.code_module == m).astype(int)
    return df

def model_matrix(df, log_clicks=True):
    X = df[FEATURES].astype(float).copy()
    if log_clicks:
        for c in [c for c in CLICKS if c in X] + ["active_days_prestart", "sites_w4"]:
            X[c] = np.log1p(X[c])
    return X

def write_arff(df, path, relation="oulad_week4_early_alert"):
    cols = [c for c in REG + CLICKS + COUNTS + DERIVED if c in FEATURES]   # same inputs as the Python models
    with open(path, "w") as f:
        f.write(f"@RELATION {relation}\n\n")
        f.write("@ATTRIBUTE code_module {" + ",".join(MODULES) + "}\n")
        for c in cols: f.write(f"@ATTRIBUTE {c} NUMERIC\n")
        f.write("@ATTRIBUTE is_at_risk {0,1}\n\n@DATA\n")
        for row in df[["code_module"] + cols + ["is_at_risk"]].itertuples(index=False):
            f.write(",".join(str(round(v, 6)) if isinstance(v, float) else str(v) for v in row) + "\n")
