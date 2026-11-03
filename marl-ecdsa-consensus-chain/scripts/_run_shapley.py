# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess, sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = str(Path(__file__).resolve().parents[1])
PY = sys.executable
batch = [int(x) for x in sys.argv[1].split(",")]
for sd in batch:
    t0=time.time()
    r=subprocess.run([PY,"-X","utf8","train.py","--mode","bc_marl","--n_episodes","1000","--seed",str(sd),
                      "--use-shapley-incentive",
                      "--save",os.path.join("results","shapley_ab",f"shap_seed{sd}.json")],
                     capture_output=True,text=True,encoding="utf-8",cwd=ROOT)
    print(f"seed={sd} rc={r.returncode} {time.time()-t0:.0f}s")
