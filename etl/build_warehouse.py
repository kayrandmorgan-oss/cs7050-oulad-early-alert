"""
build_warehouse.py — one-command rebuild of the OULAD warehouse from the raw CSVs.

    python etl/build_warehouse.py                 # chunked pandas load (default)
    python etl/build_warehouse.py --load-data     # fall back to LOAD DATA LOCAL INFILE for the clickstream

Connection settings come from environment variables (defaults in brackets):
    OULAD_DB_HOST [localhost]  OULAD_DB_PORT [3306]  OULAD_DB_USER [oulad]
    OULAD_DB_PASS [oulad]      OULAD_DB_NAME [oulad_dw] OULAD_RAW_DIR [data/raw]

Layers:  1 staging (raw CSV -> stg_*)  2 transform+load (sql/transform_load.sql)
         3 reconciliation (sql/reconciliation.sql + raw-file checks); the build
           exits non-zero if any assertion fails, so analysis never runs on a bad load.
"""
import argparse, csv, json, os, re, sys, time
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.getenv("OULAD_RAW_DIR", ROOT / "data" / "raw"))
OUT = ROOT / "out"; OUT.mkdir(exist_ok=True)
H, P = os.getenv("OULAD_DB_HOST", "localhost"), os.getenv("OULAD_DB_PORT", "3306")
U, W = os.getenv("OULAD_DB_USER", "oulad"), os.getenv("OULAD_DB_PASS", "oulad")
DB = os.getenv("OULAD_DB_NAME", "oulad_dw")
CHUNK = 200_000

SMALL = {  # csv -> staging table
    "courses.csv": "stg_courses", "assessments.csv": "stg_assessments", "vle.csv": "stg_vle",
    "studentInfo.csv": "stg_student_info", "studentRegistration.csv": "stg_student_registration",
    "studentAssessment.csv": "stg_student_assessment"}
VLE_DTYPES = {"code_module": str, "code_presentation": str, "id_student": "int32",
              "id_site": "int32", "date": "int16", "sum_click": "int32"}

log = []
def step(name, t0):
    dt = time.perf_counter() - t0; log.append({"step": name, "seconds": round(dt, 2)})
    print(f"  {name:<55s} {dt:8.2f} s", flush=True)

def engine(db=None):
    url = f"mysql+pymysql://{U}:{W}@{H}:{P}/{db or ''}?charset=utf8mb4&local_infile=1"
    return create_engine(url, pool_pre_ping=True, connect_args={"local_infile": True})

def run_script(conn, path, marker):
    """Split a .sql file on '-- <marker>:' lines and execute each block, timed."""
    blocks = re.split(rf"^-- {marker}: *(.*)$", Path(path).read_text(), flags=re.M)
    for name, body in zip(blocks[1::2], blocks[2::2]):
        t0 = time.perf_counter()
        for stmt in strip_comments(body).split(";"):
            if stmt.strip(): conn.execute(text(stmt))
        conn.commit(); step(name.strip(), t0)

def strip_comments(sql):
    """Drop full-line and trailing '-- ' comments (none of our string literals contain '--')."""
    return "\n".join(re.sub(r"--\s.*$|^--.*$", "", l) for l in sql.splitlines())

def csv_rows(path):
    with open(path, newline="") as f: return sum(1 for _ in f) - 1

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--load-data", action="store_true")
    args = ap.parse_args()
    T = time.perf_counter()
    with engine().connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {DB}")); c.execute(text(f"CREATE DATABASE {DB}")); c.commit()
    eng = engine(DB)
    print("[0] schema"); t0 = time.perf_counter()
    with eng.connect() as c:
        for stmt in strip_comments((ROOT/"sql"/"schema.sql").read_text()).split(";"):
            if stmt.strip(): c.execute(text(stmt))
        c.commit()
    step("create schema", t0)

    print("[1] staging")
    for fname, tbl in SMALL.items():
        t0 = time.perf_counter()
        df = pd.read_csv(RAW/fname, keep_default_na=False, na_values=[""])
        df.to_sql(tbl, eng, if_exists="append", index=False, chunksize=20_000)
        step(f"{tbl} ({len(df):,} rows)", t0)
    t0 = time.perf_counter(); n = 0
    if args.load_data:
        p = str((RAW/"studentVle.csv").resolve()).replace("\\", "/")
        with eng.connect() as c:
            c.execute(text(f"LOAD DATA LOCAL INFILE '{p}' INTO TABLE stg_student_vle FIELDS TERMINATED BY ',' "
                           "OPTIONALLY ENCLOSED BY '\"' LINES TERMINATED BY '\\n' IGNORE 1 LINES"))
            c.commit(); n = c.execute(text("SELECT COUNT(*) FROM stg_student_vle")).scalar()
        step(f"stg_student_vle LOAD DATA ({n:,} rows)", t0)
    else:
        for chunk in pd.read_csv(RAW/"studentVle.csv", dtype=VLE_DTYPES, chunksize=CHUNK):
            chunk.to_sql("stg_student_vle", eng, if_exists="append", index=False, chunksize=CHUNK)
            n += len(chunk); print(f"    ... {n:,} rows", end="\r", flush=True)
        step(f"stg_student_vle chunked pandas ({n:,} rows)", t0)

    print("[2] transform + load")
    with eng.connect() as c:
        run_script(c, ROOT/"sql"/"transform_load.sql", "step")
        t0 = time.perf_counter()
        for stmt in strip_comments((ROOT/"sql"/"feature_mart.sql").read_text()).split(";"):
            if stmt.strip(): c.execute(text(stmt))
        c.commit(); step("feature-mart views (v_features_week4, v_audit_attributes)", t0)

    print("[3] reconciliation")
    failures, results = 0, []
    with eng.connect() as c:
        for fname, tbl in list(SMALL.items()) + [("studentVle.csv", "stg_student_vle")]:
            exp, act = csv_rows(RAW/fname), c.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
            results.append((f"R00 {tbl} rows = {fname} lines", exp, act))
        tot = 0
        with open(RAW/"studentVle.csv", newline="") as f:
            r = csv.reader(f); hdr = next(r); i = hdr.index("sum_click")
            for row in r: tot += int(row[i])
        results.append(("R00 studentVle.csv click total = fact clicks", tot,
                        c.execute(text("SELECT SUM(sum_click) FROM fact_vle_weekly")).scalar()))
        blocks = re.split(r"^-- check: *.*$", (ROOT/"sql"/"reconciliation.sql").read_text(), flags=re.M)[1:]
        for b in blocks:
            q = b.strip().rstrip(";")
            name, exp, act = c.execute(text(q)).one(); results.append((name, exp, act))
    for name, exp, act in results:
        ok = (exp == act) or (exp is not None and act is not None and float(exp) == float(act))
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<55s} expected={exp}  actual={act}")
    with eng.connect() as c:
        sizes = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in
                 ["dim_presentation","dim_student","dim_enrollment","dim_course_week","dim_activity",
                  "dim_assessment","fact_vle_weekly","fact_assessment_submission",
                  "agg_pres_week_activity","agg_enrollment_week"]}
        sizes["fact_vle_weekly_zero_rows"] = c.execute(text("SELECT COUNT(*) FROM fact_vle_weekly WHERE activity_key=0")).scalar()
    total = round(time.perf_counter() - T, 1)
    (OUT/"build_log.json").write_text(json.dumps({"steps": log, "total_seconds": total, "table_rows": sizes,
        "reconciliation": [{"check": n, "expected": str(e), "actual": str(a)} for n, e, a in results],
        "failures": failures, "loader": "LOAD DATA" if args.load_data else "chunked pandas"}, indent=2))
    print(f"table rows: {sizes}\nTOTAL {total} s — {len(results)-failures}/{len(results)} checks passed")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
