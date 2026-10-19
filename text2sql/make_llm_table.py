"""
make_llm_table.py — builds report/llm_table.tex from out/text2sql/*_summary.json.
Rows for runs that do not exist yet (the NRP GPU conditions) are printed as 'pending NRP run',
so re-running this after scoring the NRP output fills the table without hand-editing.
"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "out" / "text2sql"
ROWS = [  # (tag, label, condition label, where)
    ("qwen7b_none",      "Qwen2.5-Coder-7B (4-bit)",  "no schema",        "CPU"),
    ("qwen7b_schema",    "Qwen2.5-Coder-7B (4-bit)",  "schema in prompt", "CPU"),
    ("qwen1.5b_none",    "Qwen2.5-Coder-1.5B (4-bit)","no schema",        "CPU"),
    ("qwen1.5b_schema",  "Qwen2.5-Coder-1.5B (4-bit)","schema in prompt", "CPU"),
    ("gpu_qwen15b_none",   "Qwen2.5-Coder-1.5B (fp16)",     "no schema",        "NRP GPU"),
    ("gpu_qwen15b_schema", "Qwen2.5-Coder-1.5B (fp16)",     "schema in prompt", "NRP GPU"),
    ("gpu_qwen15b_lora",   "Qwen2.5-Coder-1.5B (fp16)",     "LoRA + schema",    "NRP GPU"),
]
def pct(x): return "---" if x is None else f"{100*x:.1f}\\%"
lines = [r"\begin{table}[H]\centering\small",
         r"\caption{Text-to-SQL results on the 40 held-out questions (22 aggregate-eligible). Execution match = same multiset of rows as the gold query; aggregate navigation = share of aggregate-eligible questions answered from an \tt{agg\_} table.}\label{tab:llm}",
         r"\begin{tabular}{@{}lllrrrr@{}}", r"\toprule",
         r"\textbf{Model} & \textbf{Condition} & \textbf{Run} & \textbf{Exec.\ match} & \textbf{Invalid SQL} & \textbf{Agg.\ navigation} & \textbf{s/q} \\ \midrule"]
for tag, model, cond, where in ROWS:
    f = D / f"{tag}_summary.json"
    if f.exists():
        s = json.loads(f.read_text())
        n_match = round(s["execution_match"] * s["n"])
        lines.append(f"{model} & {cond} & {where} & {pct(s['execution_match'])} ({n_match}/{s['n']}) & {pct(s['invalid_sql_rate'])} & {pct(s['agg_navigation_rate'])} & {s['mean_seconds_per_question']:.0f} \\\\")
    else:
        lines.append(f"{model} & {cond} & {where} & \\multicolumn{{4}}{{c}}{{\\pending}} \\\\")
    if tag in ("qwen7b_schema", "qwen1.5b_schema"): lines.append(r"\addlinespace[2pt]")
lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
(ROOT / "report" / "llm_table.tex").write_text("\n".join(lines) + "\n"); print("\n".join(lines))
