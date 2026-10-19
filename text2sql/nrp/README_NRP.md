# NRP kit: the LoRA condition (proposal section 5)

This kit runs the GPU part of the text-to-SQL evaluation on the CS 7050 NRP JupyterHub (`https://cs7050-ksu.nrp-nautilus.io`). It produces three runs on Qwen2.5-Coder-1.5B-Instruct: a LoRA fine-tune on the 200 template pairs, then SQL for the 40 held-out questions under **no schema**, **schema in prompt** and **LoRA + schema**. NRP cannot reach the MySQL warehouse, so it only *generates* SQL. Scoring happens back on the warehouse machine.

The code path (train → save adapter → generate with adapter) was smoke-tested on CPU with the 0.5B model before release.

## On NRP

Do the one-time setup first: Setup Guide steps 1–6, including the course's pip installs. Then, in a terminal on the **GPU** profile:

```bash
pip install --user sqlalchemy                       # the evaluator imports it (no database is used)
cd ~ && git clone https://github.com/kayrandmorgan-oss/cs7050-oulad-early-alert.git
cd cs7050-oulad-early-alert
bash text2sql/nrp/run_all_nrp.sh
```

`run_all_nrp.sh` checks the GPU, trains the adapter (it saves after every epoch), generates SQL for all three conditions, and writes **`nrp_results.tar.gz`**. If the server is culled partway through, run the same command again; finished steps are skipped. Download the tar file from the Jupyter file browser (right-click → Download).

## Back on the warehouse machine

```bash
tar xzf nrp_results.tar.gz                           # from the repo root
python text2sql/score.py out/text2sql/gpu_qwen15b_none.generated.jsonl   --condition none   --model-name Qwen2.5-Coder-1.5B-Instruct
python text2sql/score.py out/text2sql/gpu_qwen15b_schema.generated.jsonl --condition schema --model-name Qwen2.5-Coder-1.5B-Instruct
python text2sql/score.py out/text2sql/gpu_qwen15b_lora.generated.jsonl   --condition lora   --model-name Qwen2.5-Coder-1.5B-Instruct+LoRA
python text2sql/make_llm_table.py                     # fills the "pending NRP run" rows of the report table
```

## Notes

* **Memory.** The trainer computes logits only for the SQL answer tokens. The 2.4k-token schema prompt × 151k-token vocabulary would otherwise not fit on an 11 GB card.
* **Precision.** bf16 is used where the GPU supports it, otherwise fp16 with loss scaling, so older cards such as the GTX 1080 Ti (FAQ Q5) work.
* **Credit.** A run is credited only if it used a GPU, ran at least 2 minutes and finished cleanly (FAQ Q10). Follow the starter README for producing a receipt (`cs7050_receipt.py`).
* **7B (optional, ≥ 24 GB card).** `pip install --user bitsandbytes`, then run `MODEL=Qwen/Qwen2.5-Coder-7B-Instruct` with `--load-4bit` added to the `train_lora.py` line.
