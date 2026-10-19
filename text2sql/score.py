"""
score.py — score SQL generated elsewhere (e.g. on NRP with evaluate.py --generate-only)
against the local warehouse, producing the same <tag>.jsonl / <tag>_summary.json as evaluate.py.

    python text2sql/score.py out/text2sql/<tag>.generated.jsonl --condition lora --model-name qwen-coder-1.5b-lora
"""
import argparse, json, sys
from pathlib import Path
from sqlalchemy import create_engine
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining")); sys.path.insert(0, str(ROOT / "text2sql"))
from features import engine_url
from questions_test import QUESTIONS
from evaluate import run_sql, norm_rows

ap = argparse.ArgumentParser(); ap.add_argument("generated"); ap.add_argument("--condition", required=True)
ap.add_argument("--model-name", required=True); a = ap.parse_args()
gen = {json.loads(l)["id"]: json.loads(l) for l in open(a.generated)}
tag = Path(a.generated).name.replace(".generated.jsonl", "")
eng = create_engine(engine_url()); recs = []
with eng.connect() as c, open(ROOT / "out" / "text2sql" / f"{tag}.jsonl", "w") as f:
    for q in QUESTIONS:
        if q["id"] not in gen: continue
        g = gen[q["id"]]; gold, _ = run_sql(c, q["gold_sql"]); pred, err = run_sql(c, g["sql"])
        low = g["sql"].lower()
        r = {"id": q["id"], "agg_eligible": q["agg_eligible"], "match": pred is not None and norm_rows(pred) == norm_rows(gold),
             "valid": err is None, "error": err, "uses_agg": "agg_" in low, "scans_fact_vle": "fact_vle_weekly" in low,
             "seconds": g.get("seconds"), "usage": g.get("usage"), "sql": g["sql"]}
        recs.append(r); f.write(json.dumps(r) + "\n")
n = len(recs); el = [r for r in recs if r["agg_eligible"]]
summ = {"tag": tag, "model": a.model_name, "condition": a.condition, "n": n,
        "execution_match": sum(r["match"] for r in recs) / n, "invalid_sql_rate": sum(not r["valid"] for r in recs) / n,
        "agg_navigation_rate": sum(r["uses_agg"] for r in el) / len(el), "agg_eligible_n": len(el),
        "match_on_agg_eligible": sum(r["match"] for r in el) / len(el),
        "match_on_other": sum(r["match"] for r in recs if not r["agg_eligible"]) / max(1, n - len(el)),
        "mean_seconds_per_question": sum((r["seconds"] or 0) for r in recs) / n}
(ROOT / "out" / "text2sql" / f"{tag}_summary.json").write_text(json.dumps(summ, indent=2)); print(json.dumps(summ, indent=1))
