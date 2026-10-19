"""
evaluate.py — execution-match evaluation of a text-to-SQL model on the 40 held-out questions.

    python text2sql/evaluate.py --model models/qwen2.5-coder-7b-instruct-q4_k_m.gguf --condition schema
    python text2sql/evaluate.py --backend hf --model <hf-dir> --adapter <lora-dir> --condition lora   (GPU/NRP)

Conditions (proposal section 5):
  none    no schema context: dialect + question only
  schema  schema-in-prompt: DDL + grain statements + data dictionary from text2sql/schema_context.py
  lora    LoRA-adapted model + the same schema prompt

Metrics:
  execution-match accuracy  generated and gold SQL return the same multiset of rows
                            (numbers compared at 2 decimals, column order ignored)
  invalid-SQL rate          generated SQL fails to execute (syntax/unknown column/timeout)
  aggregate-navigation rate among the agg-eligible questions, share of generated queries that
                            read an agg_ table instead of scanning fact_vle_weekly
"""
import argparse, json, re, sys, time
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mining")); sys.path.insert(0, str(ROOT / "text2sql"))
from features import engine_url
from questions_test import QUESTIONS
from schema_context import build

SYSTEM_NONE = ("You are an expert data analyst. Write one MySQL 8 query that answers the user's question "
               "about the database oulad_dw. Reply with only the SQL in a ```sql code block.")
SYSTEM_SCHEMA = ("You are an expert data analyst. Write one MySQL 8 query that answers the user's question, "
                 "using only the tables and columns in the schema below. Prefer the agg_ tables whenever they "
                 "can answer the question exactly. Reply with only the SQL in a ```sql code block.\n\n{schema}")

def prompt_messages(question, condition, schema):
    sys_msg = SYSTEM_NONE if condition == "none" else SYSTEM_SCHEMA.format(schema=schema)
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": question}]

def extract_sql(s):
    m = re.search(r"```(?:sql)?\s*(.*?)```", s, re.S | re.I)
    sql = (m.group(1) if m else s).strip()
    return sql.split(";")[0].strip()

def norm_rows(rows):
    def nv(v):
        if v is None: return "NULL"
        if isinstance(v, (int, float, Decimal)): return f"{round(float(v), 2):.2f}"
        return str(v)
    return sorted(tuple(sorted(nv(v) for v in r)) for r in rows)

def run_sql(conn, sql):
    try:
        conn.execute(text("SET SESSION max_execution_time = 60000"))
        return conn.execute(text(sql)).fetchall(), None
    except Exception as e:
        conn.rollback(); return None, str(e).split("\n")[0][:300]

class LlamaCppBackend:
    def __init__(self, path, threads, n_ctx=4096):
        from llama_cpp import Llama
        self.llm = Llama(model_path=path, n_ctx=n_ctx, n_threads=threads, verbose=False, seed=0)
    def __call__(self, messages):
        r = self.llm.create_chat_completion(messages=messages, temperature=0.0, max_tokens=450)
        return r["choices"][0]["message"]["content"], r["usage"]

class HFBackend:   # used on NRP / any CUDA machine; optional LoRA adapter
    def __init__(self, path, adapter=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(path)
        dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if torch.cuda.is_available() else torch.float32
        self.m = AutoModelForCausalLM.from_pretrained(path, torch_dtype=dtype, device_map="auto")
        if adapter:
            from peft import PeftModel
            self.m = PeftModel.from_pretrained(self.m, adapter)
        self.m.eval()
    def __call__(self, messages):
        import torch
        text = self.tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        ids = self.tok(text, return_tensors="pt", add_special_tokens=False).input_ids.to(self.m.device)
        with torch.no_grad():
            out = self.m.generate(ids, max_new_tokens=450, do_sample=False)
        gen = out[0][ids.shape[1]:]
        return self.tok.decode(gen, skip_special_tokens=True), {"prompt_tokens": int(ids.shape[1]), "completion_tokens": int(len(gen))}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True); ap.add_argument("--condition", choices=["none", "schema", "lora"], required=True)
    ap.add_argument("--backend", choices=["llamacpp", "hf"], default="llamacpp"); ap.add_argument("--adapter")
    ap.add_argument("--threads", type=int, default=2); ap.add_argument("--tag", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--generate-only", action="store_true",
                    help="no database needed (e.g. on NRP): read text2sql/schema_context.txt, write SQL only; "
                         "score later on the warehouse machine with text2sql/score.py")
    a = ap.parse_args()
    if a.generate_only:
        return generate_only(a)
    eng = create_engine(engine_url()); schema = build(eng)
    gen = LlamaCppBackend(a.model, a.threads) if a.backend == "llamacpp" else HFBackend(a.model, a.adapter)
    tag = a.tag or f"{Path(a.model).stem}_{a.condition}"
    out_dir = ROOT / "out" / "text2sql"; out_dir.mkdir(parents=True, exist_ok=True)
    recs = []
    qs = QUESTIONS[: a.limit] if a.limit else QUESTIONS
    with eng.connect() as c, open(out_dir / f"{tag}.jsonl", "w") as f:
        for q in qs:
            t0 = time.perf_counter(); raw, usage = gen(prompt_messages(q["question"], a.condition, schema))
            dt = time.perf_counter() - t0
            sql = extract_sql(raw)
            gold, _ = run_sql(c, q["gold_sql"]); pred, err = run_sql(c, sql)
            match = pred is not None and norm_rows(pred) == norm_rows(gold)
            low = sql.lower()
            r = {"id": q["id"], "agg_eligible": q["agg_eligible"], "match": match, "valid": err is None, "error": err,
                 "uses_agg": "agg_" in low, "scans_fact_vle": "fact_vle_weekly" in low,
                 "seconds": round(dt, 1), "usage": usage, "sql": sql}
            recs.append(r); f.write(json.dumps(r) + "\n"); f.flush()
            print(f"{q['id']} match={match!s:5} valid={err is None!s:5} agg={r['uses_agg']!s:5} {dt:6.1f}s  {sql[:110]!r}", flush=True)
    n = len(recs); el = [r for r in recs if r["agg_eligible"]]
    summ = {"tag": tag, "model": Path(a.model).name, "condition": a.condition, "n": n,
            "execution_match": sum(r["match"] for r in recs) / n,
            "invalid_sql_rate": sum(not r["valid"] for r in recs) / n,
            "agg_navigation_rate": (sum(r["uses_agg"] for r in el) / len(el)) if el else None,
            "agg_eligible_n": len(el),
            "match_on_agg_eligible": (sum(r["match"] for r in el) / len(el)) if el else None,
            "match_on_other": sum(r["match"] for r in recs if not r["agg_eligible"]) / max(1, n - len(el)),
            "mean_seconds_per_question": sum(r["seconds"] for r in recs) / n}
    (out_dir / f"{tag}_summary.json").write_text(json.dumps(summ, indent=2)); print(json.dumps(summ, indent=1))

def generate_only(a):
    schema = (ROOT / "text2sql" / "schema_context.txt").read_text()
    gen = LlamaCppBackend(a.model, a.threads) if a.backend == "llamacpp" else HFBackend(a.model, a.adapter)
    tag = a.tag or f"{Path(a.model).stem}_{a.condition}"
    out_dir = ROOT / "out" / "text2sql"; out_dir.mkdir(parents=True, exist_ok=True)
    qs = QUESTIONS[: a.limit] if a.limit else QUESTIONS
    with open(out_dir / f"{tag}.generated.jsonl", "w") as f:
        for q in qs:
            t0 = time.perf_counter(); raw, usage = gen(prompt_messages(q["question"], a.condition, schema))
            r = {"id": q["id"], "sql": extract_sql(raw), "raw": raw, "seconds": round(time.perf_counter() - t0, 1), "usage": usage}
            f.write(json.dumps(r) + "\n"); f.flush(); print(q["id"], r["seconds"], r["sql"][:100], flush=True)
    print("wrote", out_dir / f"{tag}.generated.jsonl")

if __name__ == "__main__":
    main()
