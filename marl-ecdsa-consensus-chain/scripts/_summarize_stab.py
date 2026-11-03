# -*- coding: utf-8 -*-
from pathlib import Path
import json, os, sys, io, glob
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
d = str(Path(__file__).resolve().parents[1] / "results" / "contribution_stab")
rows = []
for f in sorted(glob.glob(os.path.join(d,"stab_seed*.json"))):
    j = json.load(open(f, encoding="utf-8"))
    s = j.get("summary", {})
    rows.append(dict(
        seed=int(os.path.basename(f).replace("stab_seed","").replace(".json","")),
        reward=s.get("avg_reward",0),
        coop=s.get("avg_cooperation_rate",0),
        betrayal=s.get("avg_betrayal_rate",0),
        ep=len(j.get("episode_rewards",[])),
        t=s.get("elapsed_time",0),
    ))
print(f"{'seed':>6} {'reward':>10} {'coop':>8} {'betrayal':>10} {'ep':>5} {'sec':>6}")
for r in rows:
    print(f"{r['seed']:>6} {r['reward']:>10.2f} {r['coop']:>8.3f} {r['betrayal']:>10.3f} {r['ep']:>5} {r['t']:>6.1f}")
rs = np.array([r["reward"] for r in rows])
cs = np.array([r["coop"] for r in rows])
print(f"\nreward: mean={rs.mean():.2f} std={rs.std():.2f}")
print(f"coop:   mean={cs.mean():.3f} std={cs.std():.3f}")
print(f"全部 1000 episodes 完成: {all(r['ep']==1000 for r in rows)}/10")
