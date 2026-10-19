"""
schema_context.py — builds the schema-aware prompt context programmatically from the LIVE
warehouse (information_schema), so it can never drift from the real schema:
  * compact DDL for every dim_/fact_/agg_ table (columns, types, primary key, foreign keys)
  * the table's grain statement (table COMMENT)
  * a data dictionary of the allowed values of every low-cardinality text column
Staging tables and views are deliberately excluded.

    python text2sql/schema_context.py   -> writes text2sql/schema_context.txt
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining"))
from features import engine_url

SKIP_VALUES = {"id_student", "module_presentation"}  # high-cardinality / derivable

def build(eng=None, max_distinct=25):
    eng = eng or create_engine(engine_url())
    out = []
    with eng.connect() as c:
        db = c.execute(text("SELECT DATABASE()")).scalar()
        tabs = c.execute(text("""SELECT table_name, table_comment FROM information_schema.tables
                 WHERE table_schema=:d AND table_type='BASE TABLE' AND
                 (table_name LIKE 'dim\\_%' OR table_name LIKE 'fact\\_%' OR table_name LIKE 'agg\\_%')
                 ORDER BY FIELD(LEFT(table_name,3),'dim','fac','agg'), table_name"""), {"d": db}).fetchall()
        for t, comment in tabs:
            cols = c.execute(text("""SELECT column_name, column_type, is_nullable, column_key FROM information_schema.columns
                     WHERE table_schema=:d AND table_name=:t ORDER BY ordinal_position"""), {"d": db, "t": t}).fetchall()
            fks = c.execute(text("""SELECT column_name, referenced_table_name, referenced_column_name
                     FROM information_schema.key_column_usage WHERE table_schema=:d AND table_name=:t
                     AND referenced_table_name IS NOT NULL"""), {"d": db, "t": t}).fetchall()
            pk = [r[0] for r in cols if r[3] == "PRI"]
            lines = [f"  {n} {ty.upper()}{'' if nl == 'YES' else ' NOT NULL'}" for n, ty, nl, _ in cols]
            if pk: lines.append(f"  PRIMARY KEY ({', '.join(pk)})")
            for col, rt, rc in fks: lines.append(f"  FOREIGN KEY ({col}) REFERENCES {rt}({rc})")
            out.append(f"-- {comment}\nCREATE TABLE {t} (\n" + ",\n".join(lines) + "\n);")
        # data dictionary
        dd = []
        for t, _ in tabs:
            if not t.startswith("dim_"): continue
            for (col,) in c.execute(text("""SELECT column_name FROM information_schema.columns WHERE table_schema=:d
                     AND table_name=:t AND data_type IN ('char','varchar')"""), {"d": db, "t": t}).fetchall():
                if col in SKIP_VALUES: continue
                n = c.execute(text(f"SELECT COUNT(DISTINCT `{col}`) FROM {t}")).scalar()
                if n <= max_distinct:
                    vals = [r[0] for r in c.execute(text(f"SELECT DISTINCT `{col}` FROM {t} ORDER BY 1")).fetchall()]
                    dd.append(f"  {t}.{col}: " + ", ".join(repr(v) for v in vals))
        wk = c.execute(text("SELECT MIN(week_num), MAX(week_num) FROM dim_course_week")).one()
        dd.append(f"  dim_course_week.week_num: integer {wk[0]} .. {wk[1]}")
        mp = c.execute(text("SELECT GROUP_CONCAT(module_presentation ORDER BY 1) FROM dim_presentation")).scalar()
        dd.append(f"  dim_presentation.module_presentation: {mp}")
    return ("-- MySQL 8 star-schema warehouse of the Open University Learning Analytics Dataset.\n"
            + "\n\n".join(out) + "\n\n-- DATA DICTIONARY (allowed values)\n" + "\n".join(dd) + "\n")

if __name__ == "__main__":
    s = build(); (ROOT / "text2sql" / "schema_context.txt").write_text(s); print(s); print(len(s), "chars")
