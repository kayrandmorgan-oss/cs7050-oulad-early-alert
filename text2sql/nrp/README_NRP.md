# NRP kit: the LoRA condition (proposal section 5)

This folder holds everything needed to run the GPU part of the text-to-SQL evaluation on the CS 7050 NRP JupyterHub (`https://cs7050-ksu.nrp-nautilus.io`). It follows the course's NRP Setup Guide. The prompt-only conditions have already been run on CPU (see the report, section 7). This kit adds the **LoRA + schema** condition, plus a matching GPU rerun of the prompt-only conditions on the same base model, so that all three conditions are compared on one model.

NRP cannot reach the MySQL warehouse. The GPU side therefore only **generates** SQL, and scoring happens back on the warehouse machine.

## Files to upload to `~/project` on NRP

| File | Where it comes from |
|---|---|
| `train_lora.py` | this folder |
| `evaluate.py`, `questions_test.py` | `text2sql/` |
| `schema_context.txt` | `text2sql/` (built from the live warehouse) |
| `train_pairs.jsonl` | `text2sql/` (200 template pairs, none overlapping the 40 test questions) |

`evaluate.py` imports `features` and `schema_context`, but only on the database path. On NRP, always run it with `--generate-only`; that path needs neither module. If an import error appears anyway, upload `mining/features.py` and `text2sql/schema_context.py` too. They import cleanly without a database.

## Steps (GPU profile "GPU — 1x standard", after Setup Guide steps 1–6)

```bash
cd ~/project
# 0. one-time: make the packages from Setup Guide step 3 available (+ bitsandbytes only if you try 7B QLoRA)
# 1. LoRA fine-tune (1.5B default; about 20-40 min on one standard GPU; checkpoints each epoch)
python train_lora.py --pairs train_pairs.jsonl --schema schema_context.txt --out lora_qwen15b

# 2. Generate SQL for the 40 held-out questions under all three conditions on the SAME base model
mkdir -p out/text2sql
python evaluate.py --generate-only --backend hf --model Qwen/Qwen2.5-Coder-1.5B-Instruct --condition none   --tag gpu_qwen15b_none
python evaluate.py --generate-only --backend hf --model Qwen/Qwen2.5-Coder-1.5B-Instruct --condition schema --tag gpu_qwen15b_schema
python evaluate.py --generate-only --backend hf --model Qwen/Qwen2.5-Coder-1.5B-Instruct --adapter lora_qwen15b --condition lora --tag gpu_qwen15b_lora
```

Download `out/text2sql/*.generated.jsonl` and `lora_qwen15b/train_log.json`, and copy them into the project's `out/text2sql/` on the warehouse PC. Then score:

```bash
python text2sql/score.py out/text2sql/gpu_qwen15b_none.generated.jsonl   --condition none   --model-name Qwen2.5-Coder-1.5B-Instruct
python text2sql/score.py out/text2sql/gpu_qwen15b_schema.generated.jsonl --condition schema --model-name Qwen2.5-Coder-1.5B-Instruct
python text2sql/score.py out/text2sql/gpu_qwen15b_lora.generated.jsonl   --condition lora   --model-name Qwen2.5-Coder-1.5B-Instruct+LoRA
```

Each command writes `<tag>_summary.json`, containing execution-match, invalid-SQL rate and aggregate-navigation rate. Those numbers go into Table 9 of the report.

## Optional: the proposal's 7B model

The proposal named Qwen2.5-Coder-7B-Instruct as the first choice. In bf16 it needs about 16 GB just for the weights. On a 24 GB+ card, use QLoRA:

```bash
pip install --user bitsandbytes
python train_lora.py --model Qwen/Qwen2.5-Coder-7B-Instruct --load-4bit --out lora_qwen7b
```

## Course-specific notes

* Wrap or start runs the way the starter README says, so that each run produces a **receipt** (`cs7050_receipt.py`). A run is credited only if it used a GPU, ran at least 2 minutes and finished cleanly (FAQ Q10). Training qualifies.
* Servers are culled after 1 hour idle, and sessions are capped at about 6 hours (FAQ Q12). `train_lora.py` saves an adapter after every epoch.
* If no GPU is available on two different days, screenshot it and post in Teams (FAQ Q3). The proposal's fallback (prompt-only conditions) is already complete, so no core deliverable depends on this run.
