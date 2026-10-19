#!/usr/bin/env bash
# One-shot GPU run for the CS 7050 NRP hub (GPU profile). From the repo root:
#     bash text2sql/nrp/run_all_nrp.sh
# 1) checks the GPU  2) LoRA fine-tune (Qwen2.5-Coder-1.5B-Instruct)  3) generates SQL for the
# 40 held-out questions under none / schema / LoRA+schema  4) bundles everything into
# nrp_results.tar.gz to download. Safe to re-run: finished steps are skipped.
set -euo pipefail
cd "$(dirname "$0")/../.."
MODEL=${MODEL:-Qwen/Qwen2.5-Coder-1.5B-Instruct}
ADAPTER=lora_qwen15b
mkdir -p out/text2sql
python -c "import torch; assert torch.cuda.is_available(), 'No GPU: switch to the GPU profile'; print('GPU:', torch.cuda.get_device_name(0))"
if [ ! -f "$ADAPTER/adapter_model.safetensors" ]; then
  python text2sql/nrp/train_lora.py --model "$MODEL" --pairs text2sql/train_pairs.jsonl \
         --schema text2sql/schema_context.txt --out "$ADAPTER" 2>&1 | tee train_log.txt
fi
for cond in none schema lora; do
  tag=gpu_qwen15b_$cond
  [ -s out/text2sql/$tag.generated.jsonl ] && [ "$(wc -l < out/text2sql/$tag.generated.jsonl)" -ge 40 ] && continue
  extra=""; [ "$cond" = lora ] && extra="--adapter $ADAPTER"
  python text2sql/evaluate.py --generate-only --backend hf --model "$MODEL" $extra --condition $cond --tag $tag 2>&1 | tee gen_$cond.txt
done
tar czf nrp_results.tar.gz out/text2sql/gpu_qwen15b_*.generated.jsonl "$ADAPTER/train_log.json" train_log.txt gen_*.txt
echo; echo "DONE. Download nrp_results.tar.gz (right-click it in the file browser > Download)."
