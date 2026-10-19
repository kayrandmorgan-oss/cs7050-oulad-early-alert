"""Record real command runs with timestamps: python record.py scenes.json out_dir"""
import json, os, subprocess, sys, time
from pathlib import Path
scenes = json.load(open(sys.argv[1])); out = Path(sys.argv[2]); out.mkdir(exist_ok=True)
env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONWARNINGS="ignore", COLUMNS="110", TERM="dumb")
for sc in scenes:
    if "cmd" not in sc or (out / f"{sc['id']}.json").exists(): continue
    print("recording", sc["id"], sc["cmd"], flush=True)
    t0 = time.time(); ev = []
    p = subprocess.Popen(["bash", "-lc", sc["cmd"]], cwd=sc.get("cwd", "/home/claude/proj"), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    while True:
        b = os.read(p.stdout.fileno(), 4096)
        if not b: break
        ev.append([round(time.time() - t0, 3), b.decode("utf-8", "replace")])
    p.wait()
    json.dump({"id": sc["id"], "cmd": sc["shown"] if "shown" in sc else sc["cmd"], "duration": round(time.time() - t0, 2),
               "returncode": p.returncode, "events": ev}, open(out / f"{sc['id']}.json", "w"))
    print("  done", round(time.time() - t0, 1), "s rc", p.returncode, flush=True)
