# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess, sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = str(Path(__file__).resolve().parents[1])
PY = sys.executable
# args: mode, seeds_csv, out_dir
mode = sys.argv[1]  # "base" or "shap"
seeds = [int(x) for x in sys.argv[2].split(",")]
outdir = sys.argv[3]
os.makedirs(os.path.join("results", outdir), exist_ok=True)
for sd in seeds:
    t0=time.time()
    cmd = [PY,"-X","utf8","train.py","--mode","bc_marl","--n_episodes","3000","--seed",str(sd),
           "--save",os.path.join("results",outdir,f"r{sd}.json")]
    if mode=="shap":
        cmd.append("--use-shapley-incentive")
    r=subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    print(f"[{mode}] seed={sd} rc={r.returncode} {time.time()-t0:.0f}s")
