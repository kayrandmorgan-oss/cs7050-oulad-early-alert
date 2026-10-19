"""
model.py — week-4 early-alert classification.

  * Population and features: v_features_week4 (see sql/feature_mart.sql, mining/features.py)
  * Models: majority-class baseline, logistic regression, CART decision tree, Gaussian naive Bayes
  * Validation A: 5-fold stratified CV over all presentations (mean +- sd)
  * Validation B: presentation-held-out — train on February (B) presentations, test on October (J)
  * Threshold: tuned on TRAINING out-of-fold probabilities to maximise recall subject to
    precision >= PRECISION_FLOOR, then applied unchanged to the held-out test set
  * Exports: feature mart CSV + ARFF, metrics JSON/CSV, ROC / lift / PR figures, tree rules,
    LR coefficients, test-set predictions (for the disparate-impact audit)
"""
import json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, GridSearchCV, cross_val_predict
from sklearn.metrics import (accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
                             roc_curve, precision_recall_curve, brier_score_loss, confusion_matrix)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining"))
from features import load, model_matrix, write_arff, FEATURES, CLICKS

OUT, FIG = ROOT / "out", ROOT / "figures"; OUT.mkdir(exist_ok=True); FIG.mkdir(exist_ok=True)
SEED, PRECISION_FLOOR = 42, 0.60
FLOOR_GRID = [0.55, 0.60, 0.65, 0.70]   # sensitivity table reported alongside the primary floor
warnings.filterwarnings("ignore")
C = {"Logistic regression": "#2a78d6", "Decision tree (CART)": "#eb6834", "Naive Bayes": "#1baf7a"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.6, "savefig.dpi": 200})

def models():
    lr = GridSearchCV(make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
                      {"logisticregression__C": [0.01, 0.1, 1, 10]}, cv=3, scoring="roc_auc")
    dt = GridSearchCV(DecisionTreeClassifier(random_state=SEED),
                      {"max_depth": [3, 4, 5, 6, 8, 10], "min_samples_leaf": [20, 50, 100]}, cv=3, scoring="roc_auc")
    return {"Majority baseline": (DummyClassifier(strategy="most_frequent"), True),
            "Logistic regression": (lr, True),
            "Decision tree (CART)": (dt, False),     # trees use raw counts
            "Naive Bayes": (GaussianNB(), True)}

def metrics(y, p, thr=0.5):
    yhat = (p >= thr).astype(int)
    auc = roc_auc_score(y, p) if len(np.unique(p)) > 1 else 0.5
    return {"accuracy": accuracy_score(y, yhat), "precision": precision_score(y, yhat, zero_division=0),
            "recall": recall_score(y, yhat), "f1": f1_score(y, yhat, zero_division=0), "roc_auc": auc,
            "brier": brier_score_loss(y, p), "flag_rate": yhat.mean()}

def tune_threshold(y, p, floor):
    prec, rec, thr = precision_recall_curve(y, p)
    ok = np.where(prec[:-1] >= floor)[0]
    if len(ok) == 0: return 0.5, None
    i = ok[np.argmax(rec[ok])]
    return float(thr[i]), {"precision": float(prec[i]), "recall": float(rec[i])}

def lift_table(y, p, bins=10):
    d = pd.DataFrame({"y": y, "p": p}).sort_values("p", ascending=False).reset_index(drop=True)
    d["decile"] = (np.arange(len(d)) * bins // len(d)) + 1
    t = d.groupby("decile").agg(n=("y", "size"), at_risk=("y", "sum"))
    t["rate"] = t.at_risk / t.n; t["lift"] = t.rate / d.y.mean()
    t["cum_capture"] = t.at_risk.cumsum() / d.y.sum()
    return t

def main():
    df, aud = load()
    y = df.is_at_risk.values
    print(f"population {len(df):,} enrollments; at-risk rate {y.mean():.3f}")
    # ---- exports: feature mart -------------------------------------------------------
    df.to_csv(OUT / "feature_mart_week4.csv", index=False)
    write_arff(df, OUT / "feature_mart_week4.arff")
    is_b = df.code_presentation.str.endswith("B").values
    write_arff(df[is_b], OUT / "feature_mart_week4_trainB.arff")
    write_arff(df[~is_b], OUT / "feature_mart_week4_testJ.arff")
    Xlog, Xraw = model_matrix(df, True), model_matrix(df, False)
    res = {"population": int(len(df)), "at_risk_rate": float(y.mean()), "n_features": len(FEATURES),
           "features": FEATURES, "precision_floor": PRECISION_FLOOR, "cv": {}, "holdout": {}}

    # ---- Validation A: 5-fold stratified CV -----------------------------------------
    skf = StratifiedKFold(5, shuffle=True, random_state=SEED)
    for name, (m, use_log) in models().items():
        X = Xlog if use_log else Xraw
        fold = []
        for tr, te in skf.split(X, y):
            mm = clone(m).fit(X.iloc[tr], y[tr]); fold.append(metrics(y[te], mm.predict_proba(X.iloc[te])[:, 1]))
        f = pd.DataFrame(fold)
        res["cv"][name] = {k: {"mean": float(f[k].mean()), "sd": float(f[k].std(ddof=1))} for k in f.columns}
        print(f"CV  {name:22s} " + "  ".join(f"{k}={f[k].mean():.3f}±{f[k].std(ddof=1):.3f}" for k in ["accuracy", "precision", "recall", "f1", "roc_auc"]))

    # ---- Validation B: train February (B), test October (J) -------------------------
    tr, te = is_b, ~is_b
    res["holdout"]["n_train"], res["holdout"]["n_test"] = int(tr.sum()), int(te.sum())
    res["holdout"]["at_risk_rate_train"], res["holdout"]["at_risk_rate_test"] = float(y[tr].mean()), float(y[te].mean())
    probs, fitted = {}, {}
    for name, (m, use_log) in models().items():
        X = Xlog if use_log else Xraw
        oof = cross_val_predict(clone(m), X[tr], y[tr], cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
                                method="predict_proba")[:, 1]
        thr, at = tune_threshold(y[tr], oof, PRECISION_FLOOR) if name != "Majority baseline" else (0.5, None)
        mm = clone(m).fit(X[tr], y[tr]); fitted[name] = mm
        p = mm.predict_proba(X[te])[:, 1]; probs[name] = p
        res["holdout"][name] = {"default_0.5": metrics(y[te], p), "tuned_threshold": thr,
                                "train_oof_at_tuned": at, "tuned": metrics(y[te], p, thr),
                                "confusion_tuned": confusion_matrix(y[te], (p >= thr).astype(int)).tolist()}
        if hasattr(mm, "best_params_"): res["holdout"][name]["best_params"] = mm.best_params_
        h = res["holdout"][name]
        print(f"HO  {name:22s} AUC={h['default_0.5']['roc_auc']:.3f} acc@.5={h['default_0.5']['accuracy']:.3f} "
              f"thr={thr:.3f} P={h['tuned']['precision']:.3f} R={h['tuned']['recall']:.3f} F1={h['tuned']['f1']:.3f}")

    real = [n for n in probs if n != "Majority baseline"]
    # operating-point sensitivity: thresholds chosen on TRAIN out-of-fold probs for several floors
    sens = []
    lrm, _ = models()["Logistic regression"]
    oof_lr = cross_val_predict(clone(lrm), Xlog[tr], y[tr], cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
                               method="predict_proba")[:, 1]
    for fl in FLOOR_GRID:
        t, at = tune_threshold(y[tr], oof_lr, fl)
        m = metrics(y[te], probs["Logistic regression"], t)
        sens.append({"precision_floor": fl, "threshold": t, "train_precision": at["precision"], "train_recall": at["recall"],
                     "test_precision": m["precision"], "test_recall": m["recall"], "test_f1": m["f1"], "test_flag_rate": m["flag_rate"]})
    pd.DataFrame(sens).to_csv(OUT / "threshold_sensitivity_lr.csv", index=False); res["threshold_sensitivity_lr"] = sens
    # robustness: temporal split, train 2013 presentations -> test 2014 presentations (AUC only)
    t13 = df.code_presentation.str.startswith("2013").values
    res["temporal_2013_to_2014_auc"] = {}
    for name, (m, use_log) in models().items():
        if name == "Majority baseline": continue
        X = Xlog if use_log else Xraw
        mm = clone(m).fit(X[t13], y[t13])
        res["temporal_2013_to_2014_auc"][name] = float(roc_auc_score(y[~t13], mm.predict_proba(X[~t13])[:, 1]))
    print("temporal AUC", res["temporal_2013_to_2014_auc"])
    best = max(real, key=lambda n: res["holdout"][n]["default_0.5"]["roc_auc"])
    res["best_model"] = best
    base_acc = res["holdout"]["Majority baseline"]["default_0.5"]["accuracy"]
    res["best_vs_baseline_accuracy_points"] = 100 * (res["holdout"][best]["default_0.5"]["accuracy"] - base_acc)

    # ---- interpretability ------------------------------------------------------------
    lr = fitted["Logistic regression"].best_estimator_
    coef = pd.Series(lr.named_steps["logisticregression"].coef_[0], index=FEATURES).sort_values()
    coef.to_csv(OUT / "lr_standardized_coefficients.csv", header=["coef"])
    shallow = DecisionTreeClassifier(max_depth=3, min_samples_leaf=100, random_state=SEED).fit(Xraw[tr], y[tr])
    rules = export_text(shallow, feature_names=FEATURES, show_weights=True)
    (OUT / "tree_rules_depth3.txt").write_text(rules)
    res["rule_tree_depth3_auc_test"] = float(roc_auc_score(y[te], shallow.predict_proba(Xraw[te])[:, 1]))
    imp = pd.Series(fitted["Decision tree (CART)"].best_estimator_.feature_importances_, index=FEATURES).sort_values(ascending=False)
    imp.to_csv(OUT / "tree_feature_importance.csv", header=["importance"])
    # naive-Bayes independence assumption: correlation among the (log) click features
    cc = Xlog[[c for c in CLICKS if c in Xlog]].corr().values; iu = np.triu_indices_from(cc, 1)
    res["nb_click_feature_corr"] = {"mean_abs_pairwise_r": float(np.abs(cc[iu]).mean()),
                                    "pairs_r_over_0.7": int((np.abs(cc[iu]) > 0.7).sum()), "pairs": int(len(iu[0]))}
    # lift
    lt = lift_table(y[te], probs[best]); lt.to_csv(OUT / "lift_table_best.csv")
    res["lift_top_decile"] = float(lt.lift.iloc[0]); res["capture_top_3_deciles"] = float(lt.cum_capture.iloc[2])
    # test predictions for audit
    thr = res["holdout"][best]["tuned_threshold"]
    pred = pd.DataFrame({"enrollment_key": df.enrollment_key[te].values, "code_module": df.code_module[te].values,
                         "y": y[te], "p": probs[best], "flag": (probs[best] >= thr).astype(int)})
    pred.to_csv(OUT / "holdout_predictions_best.csv", index=False)

    # ---- figures ---------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls=(0, (3, 3)))
    for n in real:
        fpr, tpr, _ = roc_curve(y[te], probs[n])
        ax.plot(fpr, tpr, color=C[n], lw=2, label=f"{n} (AUC {res['holdout'][n]['default_0.5']['roc_auc']:.3f})")
    ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate (recall)")
    ax.set_title("ROC, held-out October presentations", color=INK, fontsize=10, loc="left")
    ax.legend(frameon=False, loc="lower right", fontsize=8); ax.set_xlim(0, 1); ax.set_ylim(0, 1.01)
    fig.tight_layout(); fig.savefig(FIG / "roc_holdout.pdf"); fig.savefig(FIG / "roc_holdout.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    ax.bar(lt.index, lt.lift, color="#2a78d6", width=0.8)
    ax.axhline(1, color=INK2, lw=1, ls=(0, (3, 3)))
    for i, v in zip(lt.index, lt.lift):
        if i in (1, 2, 10): ax.text(i, v + 0.03, f"{v:.2f}", ha="center", color=INK, fontsize=8)
    ax.set_xticks(range(1, 11)); ax.set_xlabel("Risk-score decile (1 = highest predicted risk)")
    ax.set_ylabel("Lift over base rate"); ax.grid(axis="x", visible=False)
    ax.set_title(f"Lift, {best}, held-out test", color=INK, fontsize=10, loc="left")
    fig.tight_layout(); fig.savefig(FIG / "lift_holdout.pdf"); fig.savefig(FIG / "lift_holdout.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    for n in real:
        pr, rc, _ = precision_recall_curve(y[te], probs[n]); ax.plot(rc, pr, color=C[n], lw=2, label=n)
        h = res["holdout"][n]["tuned"]; ax.plot(h["recall"], h["precision"], "o", ms=8, color=C[n], mec="white", mew=2)
    ax.axhline(PRECISION_FLOOR, color=INK2, lw=1, ls=(0, (3, 3)))
    ax.text(0.02, PRECISION_FLOOR + 0.01, f"precision floor {PRECISION_FLOOR:.2f}", color=INK2, fontsize=8)
    ax.set_xlabel("Recall"); ax.set_ylabel("Precision"); ax.set_xlim(0, 1); ax.set_ylim(0.3, 1.01)
    ax.set_title("Precision-recall; dots = tuned thresholds", color=INK, fontsize=10, loc="left")
    ax.legend(frameon=False, loc="lower left", fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "pr_holdout.pdf"); fig.savefig(FIG / "pr_holdout.png"); plt.close(fig)

    (OUT / "model_results.json").write_text(json.dumps(res, indent=2, default=float))
    print("best:", best, " lift@top decile", round(res["lift_top_decile"], 2))

if __name__ == "__main__":
    main()
