"""
show_example.py — show one held-out question from a recorded text-to-SQL run: the question,
the model's SQL, the gold SQL, and both result sets, executed live against the warehouse.

    python text2sql/show_example.py T04 [--tag qwen7b_schema]
"""
import argparse, json, sys
from pathlib import Path
from sqlalchemy import create_engine
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining")); sys.path.insert(0, str(ROOT / "text2sql"))
from features import engine_url
from questions_test import QUESTIONS
from evaluate import run_sql, norm_rows

ap = argparse.ArgumentParser(); ap.add_argument("qid"); ap.add_argument("--tag", default="qwen7b_schema")
a = ap.parse_args()
q = next(x for x in QUESTIONS if x["id"] == a.qid)
gen = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "out" / "text2sql" / f"{a.tag}.jsonl")}[a.qid]
def show(rows, err):
    if err: print("   ERROR:", err[:150]); return
    for r in rows[:6]: print("   ", " | ".join(str(v) for v in r))
    if len(rows) > 6: print(f"    ... {len(rows)} rows")
with create_engine(engine_url()).connect() as c:
    print(f"[{a.qid}] {q['question']}\n")
    print("MODEL SQL (" + a.tag + "):"); print("  " + " ".join(gen["sql"].split())[:400])
    pr, pe = run_sql(c, gen["sql"]); show(pr, pe)
    print("\nGOLD SQL:"); print("  " + " ".join(q["gold_sql"].split())[:400])
    gr, ge = run_sql(c, q["gold_sql"]); show(gr, ge)
    ok = pr is not None and norm_rows(pr) == norm_rows(gr)
    print("\nEXECUTION MATCH:", "YES" if ok else "NO", "| reads an agg_ table:", "yes" if "agg_" in gen["sql"].lower() else "no")
