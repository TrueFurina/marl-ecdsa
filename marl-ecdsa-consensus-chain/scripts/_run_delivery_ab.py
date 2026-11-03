from pathlib import Path
"""跑配送 A/B：5 种子 baseline vs credibility"""
import subprocess, sys, os, json, time

PY = sys.executable
SEEDS = [42, 100, 200, 300, 400]
BASE = str(Path(__file__).resolve().parents[1])
OUT = os.path.join(BASE, "results", "delivery_ab")
os.makedirs(OUT, exist_ok=True)

for seed in SEEDS:
    for cred in [False, True]:
        tag = "cred" if cred else "base"
        out = os.path.join(OUT, f"{tag}_s{seed}.json")
        if os.path.exists(out):
            print(f"skip {tag} s{seed}")
            continue
        cmd = [PY, "-X", "utf8", "train_delivery_torch.py",
               "--seed", str(seed), "--episodes", "5000", "--out", out]
        if cred:
            cmd.append("--credibility")
        print(f"running {tag} s{seed}...")
        t0 = time.time()
        r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, encoding="utf-8")
        print(f"  done in {time.time()-t0:.0f}s: {r.stdout.strip().split(chr(10))[-2] if r.stdout else r.stderr[-200:]}")
