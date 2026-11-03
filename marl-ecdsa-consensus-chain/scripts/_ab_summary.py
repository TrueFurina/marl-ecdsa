# -*- coding: utf-8 -*-
from pathlib import Path
import json, os, sys, io, glob
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def load_dir(d, prefix):
    rows = {}
    for f in glob.glob(os.path.join(d, f"{prefix}*.json")):
        j = json.load(open(f, encoding="utf-8"))
        s = j.get("summary", {})
        seed = int(os.path.basename(f).replace(prefix,"").replace(".json","").replace("stab_seed","").replace("shap_seed",""))
        rows[seed] = dict(
            reward=s.get("avg_reward",0),
            coop=s.get("avg_cooperation_rate",0),
        )
    return rows

A = load_dir(str(Path(__file__).resolve().parents[1] / "results" / "contribution_stab"), "stab_seed")
B = load_dir(str(Path(__file__).resolve().parents[1] / "results" / "shapley_ab"), "shap_seed")

seeds = sorted(set(A) & set(B))
print(f"{'seed':>6} {'A_reward':>10} {'B_reward':>10} {'Δ':>8} {'A_coop':>8} {'B_coop':>8} {'Δpp':>7}")
dr, dc = [], []
for s in seeds:
    ar, br = A[s]["reward"], B[s]["reward"]
    ac, bc = A[s]["coop"], B[s]["coop"]
    d_r = br - ar
    d_c = (bc - ac)*100
    dr.append(d_r); dc.append(d_c)
    print(f"{s:>6} {ar:>10.2f} {br:>10.2f} {d_r:>+8.2f} {ac:>8.3f} {bc:>8.3f} {d_c:>+7.2f}")

print(f"\nA reward: {np.mean([A[s]['reward'] for s in seeds]):.2f} ± {np.std([A[s]['reward'] for s in seeds]):.2f}")
print(f"B reward: {np.mean([B[s]['reward'] for s in seeds]):.2f} ± {np.std([B[s]['reward'] for s in seeds]):.2f}")
print(f"A coop:   {np.mean([A[s]['coop'] for s in seeds]):.3f} ± {np.std([A[s]['coop'] for s in seeds]):.3f}")
print(f"B coop:   {np.mean([B[s]['coop'] for s in seeds]):.3f} ± {np.std([B[s]['coop'] for s in seeds]):.3f}")
print(f"\nΔreward mean: {np.mean(dr):+.2f} (paired)")
print(f"Δcoop mean:   {np.mean(dc):+.2f} pp (paired)")
