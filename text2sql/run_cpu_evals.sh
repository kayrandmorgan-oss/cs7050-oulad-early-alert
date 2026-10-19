#!/usr/bin/env bash
# CPU fallback run (proposal section 5 degradation path): prompt-only conditions, llama.cpp, Q4_K_M GGUF.
# Generation runs with the database stopped (an 8 GB machine cannot hold MySQL and a 7B model at once);
# scoring against the warehouse happens afterwards with score.py.
set -e; cd "$(dirname "$0")/.."
M=${MODELS_DIR:-/home/claude/models}
# schema_context.txt is kept frozen (the context used for the reported runs); regenerate with: python3 text2sql/schema_context.py
service mysql stop
python3 text2sql/evaluate.py --generate-only --model $M/q7.gguf  --condition schema --tag qwen7b_schema
python3 text2sql/evaluate.py --generate-only --model $M/q7.gguf  --condition none   --tag qwen7b_none
python3 text2sql/evaluate.py --generate-only --model $M/q15.gguf --condition schema --tag qwen1.5b_schema
python3 text2sql/evaluate.py --generate-only --model $M/q15.gguf --condition none   --tag qwen1.5b_none
service mysql start
for t in qwen7b_schema:schema:Qwen2.5-Coder-7B-Instruct-Q4_K_M qwen7b_none:none:Qwen2.5-Coder-7B-Instruct-Q4_K_M \
         qwen1.5b_schema:schema:Qwen2.5-Coder-1.5B-Instruct-Q4_K_M qwen1.5b_none:none:Qwen2.5-Coder-1.5B-Instruct-Q4_K_M; do
  IFS=: read tag cond name <<< "$t"
  python3 text2sql/score.py out/text2sql/$tag.generated.jsonl --condition $cond --model-name $name
done
