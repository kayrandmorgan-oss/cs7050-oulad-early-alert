"""
run_olap.py — execute the OLAP query pack, time every variant, and verify that
aggregate-table variants return exactly the same rows as the base-fact variants.

    python olap/run_olap.py [--reps 5]

Writes out/olap_runtimes.csv and out/olap_results/<Qid>.csv.
Timing: one untimed warm-up run, then the median of --reps timed runs
(buffer pool warm, so this measures query work, not disk I/O).
"""
import argparse, csv, os, re, statistics, sys, time
from pathlib import Path
from decimal import Decimal
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"; (OUT / "olap_results").mkdir(parents=True, exist_ok=True)
URL = "mysql+pymysql://{u}:{p}@{h}:{port}/{db}".format(
    u=os.getenv("OULAD_DB_USER", "oulad"), p=os.getenv("OULAD_DB_PASS", "oulad"),
    h=os.getenv("OULAD_DB_HOST", "localhost"), port=os.getenv("OULAD_DB_PORT", "3306"),
    db=os.getenv("OULAD_DB_NAME", "oulad_dw"))

def parse(path):
    """-> list of dicts {id, op, question, variants: {name: sql}}"""
    qs, cur, var = [], None, None
    for line in Path(path).read_text().splitlines():
        m = re.match(r"-- query: *(\S+) *\| *([^|]+)\| *(.*)", line)
        if m:
            cur = {"id": m[1], "op": m[2].strip(), "question": m[3].strip(), "variants": {}}; qs.append(cur); continue
        m = re.match(r"-- variant: *(\w+)", line)
        if m: var = m[1]; cur["variants"][var] = ""; continue
        if cur and var and not line.startswith("--"): cur["variants"][var] += line + "\n"
    return qs

def norm(rows):
    return [tuple(float(v) if isinstance(v, Decimal) else v for v in r) for r in rows]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()
    eng = create_engine(URL)
    rows_out, bad = [], 0
    with eng.connect() as c:
        for q in parse(ROOT / "olap" / "olap_queries.sql"):
            res = {}
            for v, sql in q["variants"].items():
                sql = sql.strip().rstrip(";")
                r = c.execute(text(sql)); cols = list(r.keys()); data = r.fetchall()   # warm-up
                times = []
                for _ in range(a.reps):
                    t0 = time.perf_counter(); c.execute(text(sql)).fetchall(); times.append(time.perf_counter() - t0)
                res[v] = (cols, norm(data), statistics.median(times))
                if v == "base":
                    with open(OUT / "olap_results" / f"{q['id']}.csv", "w", newline="") as f:
                        w = csv.writer(f); w.writerow(cols); w.writerows(data)
            base_t = res["base"][2]
            agg_t = res["agg"][2] if "agg" in res else None
            same = None
            if "agg" in res:
                same = res["agg"][1] == res["base"][1]; bad += not same
            rows_out.append({"query": q["id"], "operation": q["op"], "question": q["question"],
                             "rows": len(res["base"][1]), "base_ms": round(base_t*1000, 1),
                             "agg_ms": round(agg_t*1000, 1) if agg_t else "",
                             "speedup": round(base_t/agg_t, 1) if agg_t else "",
                             "identical_results": same if same is not None else ""})
            print(f"{q['id']:4s} {q['op']:<26s} rows={len(res['base'][1]):4d} base={base_t*1000:9.1f} ms"
                  + (f"  agg={agg_t*1000:8.1f} ms  x{base_t/agg_t:6.1f}  identical={same}" if agg_t else ""), flush=True)
    with open(OUT / "olap_runtimes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys())); w.writeheader(); w.writerows(rows_out)
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
