"""
cluster.py — engagement archetypes from week-1-4 behaviour.

  * Features (standardised): log1p weekly clicks pre-start, w1..w4; active days w1-4;
    share of week-1-4 clicks in assessment / communication activities; distinct activity types.
  * k-means for k = 2..10 (n_init=10): inertia (elbow) + mean silhouette (on a 10k sample).
  * Independent cross-check: Ward hierarchical clustering on a stratified (by presentation)
    sample of 4,000 enrollments, cut at the chosen k; agreement with k-means = adjusted Rand index.
  * Clusters profiled against the outcome distribution (outcomes are NOT clustering inputs).
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score, adjusted_rand_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining"))
from features import load
OUT, FIG = ROOT / "out", ROOT / "figures"
SEED = 42
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.6, "savefig.dpi": 200})
NAMES = {0: "C0 Minimal", 1: "C1 Steady/forum", 2: "C2 Assess.-spike", 3: "C3 Broad"}  # set after inspecting k=4 profiles
CF = ["log_prestart", "log_w1", "log_w2", "log_w3", "log_w4", "active_days_w1_4",
      "share_assessment", "share_communication", "n_activity_types"]

def build(df):
    X = pd.DataFrame(index=df.index)
    X["log_prestart"] = np.log1p(df.clicks_prestart)
    for w in range(1, 5): X[f"log_w{w}"] = np.log1p(df[f"clicks_w{w}"])
    X["active_days_w1_4"] = df.active_days_w1_4
    tot = df.clicks_w1_4.replace(0, np.nan)
    X["share_assessment"] = (df.clicks_assessment / tot).fillna(0)
    X["share_communication"] = (df.clicks_communication / tot).fillna(0)
    X["n_activity_types"] = df.n_activity_types
    return X

def main(k_choice=None):
    df, _ = load(); X = build(df); Z = StandardScaler().fit_transform(X)
    rng = np.random.default_rng(SEED); samp = rng.choice(len(Z), 10_000, replace=False)
    rows = []
    for k in range(2, 11):
        km = KMeans(k, n_init=10, random_state=SEED).fit(Z)
        rows.append({"k": k, "inertia": km.inertia_, "silhouette": silhouette_score(Z[samp], km.labels_[samp])})
        print(rows[-1], flush=True)
    sel = pd.DataFrame(rows); sel.to_csv(OUT / "kmeans_model_selection.csv", index=False)
    k = k_choice or int(sel.loc[sel.silhouette.idxmax(), "k"])
    km = KMeans(k, n_init=20, random_state=SEED).fit(Z); lab = km.labels_
    # order clusters by mean week-1-4 clicks for stable naming
    order = pd.Series(df.clicks_w1_4.values).groupby(lab).mean().sort_values().index
    remap = {old: new for new, old in enumerate(order)}; lab = np.array([remap[l] for l in lab])
    df["cluster"] = lab
    # Ward cross-check on a stratified sample
    ws = df.groupby("presentation_key", group_keys=False).apply(
        lambda g: g.sample(frac=4000 / len(df), random_state=SEED)).index.values
    ward = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(Z[ws])
    ari = adjusted_rand_score(lab[ws], ward)
    # profiles
    prof = X.assign(cluster=lab, clicks_w1_4=df.clicks_w1_4, at_risk=df.is_at_risk).groupby("cluster").agg(
        n=("at_risk", "size"), median_clicks_w1_4=("clicks_w1_4", "median"),
        mean_prestart_clicks=("log_prestart", lambda s: np.expm1(s).mean()),
        **{f"mean_clicks_w{w}": (f"log_w{w}", lambda s: np.expm1(s).mean()) for w in range(1, 5)},
        mean_active_days=("active_days_w1_4", "mean"), share_assessment=("share_assessment", "mean"),
        share_communication=("share_communication", "mean"), n_activity_types=("n_activity_types", "mean"),
        pct_at_risk=("at_risk", "mean"))
    prof["pct_of_population"] = prof.n / prof.n.sum()
    # need final_result breakdown -> from warehouse view join
    from sqlalchemy import create_engine
    from features import engine_url
    fr = pd.read_sql("SELECT enrollment_key, final_result FROM dim_enrollment", create_engine(engine_url()))
    ct = pd.crosstab(df.merge(fr, on="enrollment_key").cluster, df.merge(fr, on="enrollment_key").final_result, normalize="index")
    prof = prof.join(ct[["Distinction", "Pass", "Fail", "Withdrawn"]])
    prof.to_csv(OUT / "cluster_profiles.csv")
    df[["enrollment_key", "cluster"]].to_csv(OUT / "cluster_assignments.csv", index=False)
    res = {"k": k, "selection": rows, "ward_sample_n": int(len(ws)), "ward_vs_kmeans_ARI": ari,
           "centroids_z": pd.DataFrame(km.cluster_centers_, columns=CF).iloc[list(order)].round(3).values.tolist()}
    (OUT / "cluster_results.json").write_text(json.dumps(res, indent=2, default=float))
    print(prof.round(3).to_string()); print("k", k, "ARI", round(ari, 3))

    # figures: elbow + silhouette
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.8))
    ax[0].plot(sel.k, sel.inertia / 1e3, "-o", color="#2a78d6", lw=2, ms=6, mec="white", mew=1.5)
    ax[0].set_title("Elbow: within-cluster SS (thousands)", loc="left", fontsize=9.5, color=INK)
    ax[1].plot(sel.k, sel.silhouette, "-o", color="#2a78d6", lw=2, ms=6, mec="white", mew=1.5)
    ax[1].plot([k], [sel.set_index("k").silhouette[k]], "o", color="#eb6834", ms=9, mec="white", mew=2)
    ax[1].set_title("Mean silhouette (10k sample)", loc="left", fontsize=9.5, color=INK)
    for a in ax: a.set_xlabel("k"); a.set_xticks(range(2, 11))
    fig.tight_layout(); fig.savefig(FIG / "kmeans_elbow_silhouette.pdf"); fig.savefig(FIG / "kmeans_elbow_silhouette.png"); plt.close(fig)
    # cluster weekly profile (median-free: mean clicks per week, log scale)
    pal = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.0), gridspec_kw={"width_ratios": [1.4, 1]})
    xs = ["pre", "W1", "W2", "W3", "W4"]
    for c in prof.index:
        ys = [prof.loc[c, "mean_prestart_clicks"]] + [prof.loc[c, f"mean_clicks_w{w}"] for w in range(1, 5)]
        ax[0].plot(xs, np.array(ys) + 1, "-o", color=pal[c], lw=2, ms=5, mec="white", mew=1.2, label=NAMES.get(c, f"C{c}"))
    ax[0].set_yscale("log"); ax[0].set_ylabel("mean clicks + 1 (log)")
    ax[0].set_title("Weekly engagement by cluster", loc="left", fontsize=9.5, color=INK)
    ax[0].legend(frameon=False, fontsize=7.5, ncol=2)
    left = np.zeros(len(prof)); outc = [("Distinction", "#1c5cab"), ("Pass", "#86b6ef"), ("Fail", "#f2a07f"), ("Withdrawn", "#c4471b")]
    for o, colr in outc:
        ax[1].barh([NAMES.get(c, f"C{c}") for c in prof.index], prof[o], left=left, color=colr, edgecolor="white", linewidth=1, label=o)
        left += prof[o].values
    ax[1].invert_yaxis(); ax[1].set_xlim(0, 1); ax[1].grid(axis="y", visible=False)
    ax[1].set_title("Final outcome mix", loc="left", fontsize=9.5, color=INK)
    ax[1].legend(frameon=False, fontsize=7, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout(); fig.savefig(FIG / "cluster_profiles.pdf"); fig.savefig(FIG / "cluster_profiles.png"); plt.close(fig)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
