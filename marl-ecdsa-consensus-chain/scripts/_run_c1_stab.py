# -*- coding: utf-8 -*-
from pathlib import Path
"""C1 接口级稳定性：10 种子 × 1000 episodes，验证 contribution 模块在全量训练下稳定"""
import subprocess, sys, io, os, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = str(Path(__file__).resolve().parents[1])
PY = sys.executable
seeds = [42, 100, 200, 300, 400, 500, 600, 700, 800, 900]
results = []
for sd in seeds:
    t0 = time.time()
    r = subprocess.run([PY, "-X","utf8", "train.py",
                        "--mode","bc_marl","--n_episodes","1000","--seed",str(sd),
                        "--save", os.path.join("results","contribution_stab",f"stab_seed{sd}.json")],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    dt = time.time()-t0
    # 解析 stdout 最后几行
    out_lines = r.stdout.splitlines()
    last = [l for l in out_lines if "结果已导出" in l or "贡献度" in l or "Error" in l]
    print(f"seed={sd} rc={r.returncode} {dt:.0f}s | {last[-1] if last else 'no marker'}")
    results.append((sd, r.returncode, dt))

ok = sum(1 for _,rc,_ in results if rc==0)
print(f"\n=== 稳定性：{ok}/10 种子成功 ===")
