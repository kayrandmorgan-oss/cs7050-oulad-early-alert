"""
train_lora.py — LoRA fine-tune of a Qwen2.5-Coder instruct model on the 200 template-generated
(question, SQL) pairs, with the SAME schema-aware system prompt used at evaluation time
(condition "LoRA + schema").  Written for the CS 7050 NRP JupyterHub GPU profile
("GPU — 1x standard"), which may be an older 11 GB card without bf16:
  * default base model: Qwen/Qwen2.5-Coder-1.5B-Instruct  (fp16 weights ~3 GB)
  * --model Qwen/Qwen2.5-Coder-7B-Instruct --load-4bit    (QLoRA; needs bitsandbytes, >= 16 GB GPU)
  * loss only on the assistant (SQL) tokens; gradient checkpointing; checkpoint every epoch
    (NRP culls idle servers after 1 h and caps sessions at ~6 h — FAQ Q12)

    python train_lora.py --pairs train_pairs.jsonl --schema schema_context.txt --out lora_qwen15b
"""
import argparse, json, math, os, random, sys, time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model

SYSTEM_SCHEMA = ("You are an expert data analyst. Write one MySQL 8 query that answers the user's question, "
                 "using only the tables and columns in the schema below. Prefer the agg_ tables whenever they "
                 "can answer the question exactly. Reply with only the SQL in a ```sql code block.\n\n{schema}")

def encode(tok, schema, q, sql, max_len):
    msgs = [{"role": "system", "content": SYSTEM_SCHEMA.format(schema=schema)}, {"role": "user", "content": q}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    answer = f"```sql\n{sql}\n```" + tok.eos_token
    p_ids = tok(prompt, add_special_tokens=False).input_ids
    a_ids = tok(answer, add_special_tokens=False).input_ids
    p_ids = p_ids[-(max_len - len(a_ids)):]          # never truncate the answer
    return torch.tensor(p_ids + a_ids), len(a_ids)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    ap.add_argument("--pairs", default="train_pairs.jsonl"); ap.add_argument("--schema", default="schema_context.txt")
    ap.add_argument("--out", default="lora_out"); ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-4); ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--rank", type=int, default=16); ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--load-4bit", action="store_true"); ap.add_argument("--seed", type=int, default=7050)
    a = ap.parse_args()
    random.seed(a.seed); torch.manual_seed(a.seed)
    smoke = bool(os.getenv("CS7050_SMOKE"))          # CPU smoke test of the code path only
    assert torch.cuda.is_available() or smoke, "run on the GPU profile (setup guide step 5)"
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    bf16 = dev == "cuda" and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else (torch.float16 if dev == "cuda" else torch.float32)
    gpu = torch.cuda.get_device_name(0) if dev == "cuda" else "cpu (smoke test)"
    print("device:", gpu, "| dtype:", dtype, flush=True)
    if smoke: data_limit = int(os.getenv("CS7050_SMOKE_N", "3"))
    tok = AutoTokenizer.from_pretrained(a.model)
    kw = {"torch_dtype": dtype, "device_map": "auto"} if dev == "cuda" else {"torch_dtype": dtype}
    if a.load_4bit:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=dtype)
    model = AutoModelForCausalLM.from_pretrained(a.model, **kw)
    model.gradient_checkpointing_enable(); model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                           target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    for p in model.parameters():           # fp32 master copies for the trainable LoRA weights (fp16-safe)
        if p.requires_grad: p.data = p.data.float()
    model.print_trainable_parameters()
    schema = Path(a.schema).read_text()
    data = [encode(tok, schema, d["question"], d["sql"], a.max_len) for d in map(json.loads, open(a.pairs))]
    if smoke: data = data[:data_limit]
    print(f"{len(data)} examples, mean length {sum(len(x) for x, _ in data)/len(data):.0f} tokens", flush=True)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    steps = math.ceil(len(data) / a.grad_accum) * a.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 10) * max(0.0, 1 - s / steps))
    scaler = torch.amp.GradScaler("cuda", enabled=(dev == "cuda" and not bf16))
    model.train(); step, t0, log = 0, time.time(), []
    for ep in range(a.epochs):
        random.shuffle(data); run = 0.0
        for i, (ids, lab) in enumerate(data):
            with torch.autocast(dev, dtype=dtype, enabled=(dev == "cuda")):
                # Only the answer positions need logits: a 2.5k-token prompt x 151k vocabulary of
                # full logits would not fit an 11 GB card, so keep just the last n_ans+1 positions.
                x = ids[None].to(dev)
                try:
                    logits = model(input_ids=x, logits_to_keep=lab + 1).logits
                except TypeError:
                    logits = model(input_ids=x).logits[:, -(lab + 1):]
                loss = torch.nn.functional.cross_entropy(logits[0, :-1].float(), x[0, -lab:]) / a.grad_accum
            scaler.scale(loss).backward(); run += loss.item()
            if (i + 1) % a.grad_accum == 0 or i == len(data) - 1:
                scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt); scaler.update(); opt.zero_grad(); sched.step(); step += 1
                log.append({"epoch": ep, "step": step, "loss": run, "elapsed_s": round(time.time() - t0)})
                print(f"epoch {ep} step {step}/{steps} loss {run:.4f} {time.time()-t0:.0f}s", flush=True); run = 0.0
        model.save_pretrained(Path(a.out) / f"epoch{ep}")
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    Path(a.out, "train_log.json").write_text(json.dumps({"args": vars(a), "gpu": gpu,
        "dtype": str(dtype), "log": log, "train_seconds": round(time.time() - t0)}, indent=2))
    print("saved", a.out)

if __name__ == "__main__":
    main()
