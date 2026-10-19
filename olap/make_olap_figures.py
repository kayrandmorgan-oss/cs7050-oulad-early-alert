"""Descriptive charts from the OLAP layer (uses the aggregate tables only)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from sqlalchemy import create_engine
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "mining"))
from features import engine_url
FIG = ROOT / "figures"; FIG.mkdir(exist_ok=True)
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "savefig.dpi": 220, "axes.axisbelow": True})
BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
eng = create_engine(engine_url())
d = pd.read_sql("""SELECT p.module_presentation mp, w.week_num, SUM(a.total_clicks)/MAX(n.c) cps
  FROM agg_pres_week_activity a JOIN dim_presentation p USING (presentation_key) JOIN dim_course_week w USING (week_key)
  JOIN (SELECT presentation_key, COUNT(*) c FROM dim_enrollment GROUP BY presentation_key) n USING (presentation_key)
  WHERE w.week_num BETWEEN -3 AND 39 GROUP BY p.module_presentation, w.week_num""", eng)
m = d.pivot(index="mp", columns="week_num", values="cps").reindex(columns=range(-3, 40)).fillna(0)
fig, ax = plt.subplots(figsize=(7.2, 4.0))
im = ax.imshow(m.values + 0.1, aspect="auto", cmap=LinearSegmentedColormap.from_list("b", BLUE),
               norm=LogNorm(vmin=0.5, vmax=m.values.max()))
ax.set_yticks(range(len(m.index))); ax.set_yticklabels(m.index, fontsize=7)
xt = [c for c in m.columns if c in (-3, 1, 5, 10, 15, 20, 25, 30, 35, 39)]
ax.set_xticks([list(m.columns).index(c) for c in xt]); ax.set_xticklabels(xt)
ax.axvline(list(m.columns).index(1) - 0.5, color=INK, lw=0.8); ax.axvline(list(m.columns).index(4) + 0.5, color="#eb6834", lw=1.4)
ax.text(list(m.columns).index(4) + 0.9, len(m.index) - 0.7, "week-4 alert", color="#c4471b", fontsize=7.5,
        rotation=90, va="bottom", ha="left", bbox=dict(facecolor="white", edgecolor="none", pad=1))
ax.set_xlabel("Relative course week (week 1 = days 0-6; left of black line = pre-start)")
cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01); cb.set_label("clicks per enrolled student (log)", fontsize=7.5)
cb.ax.tick_params(labelsize=7)
ax.set_title("Engagement heatmap: weekly clicks per enrolled student, all 22 presentations", loc="left", fontsize=9.5, color=INK)
fig.tight_layout(); fig.savefig(FIG / "engagement_heatmap.pdf"); fig.savefig(FIG / "engagement_heatmap.png")

# outcome by week-1-4 engagement decile (Q06 result)
q = pd.read_csv(ROOT / "out" / "olap_results" / "Q06.csv")
fig, ax = plt.subplots(figsize=(4.6, 2.9))
cols = [("distinction", "Distinction", "#1c5cab"), ("pass", "Pass", "#86b6ef"), ("fail", "Fail", "#f2a07f"), ("withdrawn", "Withdrawn", "#c4471b")]
left = np.zeros(len(q))
for c, lab, colr in cols:
    v = q[c] / q.n; ax.bar(q.decile, v, bottom=left, color=colr, edgecolor="white", linewidth=1, label=lab, width=0.8); left += v
ax.set_xticks(q.decile); ax.set_xlabel("Week 1-4 click decile (1 = lowest)"); ax.set_ylabel("share of enrollments")
ax.spines[["top", "right"]].set_visible(False); ax.set_ylim(0, 1); ax.grid(False)
ax.legend(frameon=False, fontsize=7, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.13))
fig.tight_layout(); fig.savefig(FIG / "outcome_by_decile.pdf"); fig.savefig(FIG / "outcome_by_decile.png")
print("ok")
