"""E33 配送 8000ep 扩展：批量调度器（服务器后台）。

- 配置：同 E32 种子 3001–3030；算法 iql/qmix；BC(λ=0.1) vs PURE(λ=0)；max_steps=60；8000ep。
- 断点续跑：输出文件已存在则跳过。
- 并发：max_workers（默认 32）；每跑 run_delivery_main.py 内部 OMP=2。
- 用法：~/venv_torch/bin/python run_e33_delivery_ext.py --workers 32
"""
import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO = "/home/user/marl-ecdsa-consensus-chain"
OUT = os.path.join(REPO, "results", "delivery_main")
PY = "/home/user/venv_torch/bin/python"
EP = 8000
SEEDS = list(range(3001, 3031))                 # 30 种子，与 E32 配对
ALGOS = ["iql", "qmix"]
MODES = [("bc_marl", "bc"), ("pure_marl", "pure")]


def run(alg: str, mode: str, tag: str, seed: int):
    out = f"{OUT}/e33_{alg}_{tag}_seed{seed}.json"
    if os.path.exists(out):
        return f"SKIP {out}"
    cmd = [PY, "-X", "utf8", "run_delivery_main.py",
           "--mode", mode, "--algorithm", alg,
           "--seed", str(seed), "--n_episodes", str(EP), "--max_steps", "60",
           "--lambda_weight", "0.1", "--n_agents", "3", "--n_landmarks", "2",
           "--save", out]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    dt = time.time() - t0
    if r.returncode == 0:
        return f"OK   {out} ({dt/60:.1f}min)"
    return f"FAIL {out} ({dt/60:.1f}min): {r.stderr[-400:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    tasks = [(a, m, t, s) for s in SEEDS for a in ALGOS for (m, t) in MODES]
    total = len(tasks)
    print(f"[E33] {total} tasks, workers={args.workers}, ep={EP}", flush=True)
    done = 0
    ok = 0
    fail = 0
    skip = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run, *t): t for t in tasks}
        for f in as_completed(futs):
            res = f.result()
            done += 1
            if res.startswith("OK"):
                ok += 1
            elif res.startswith("FAIL"):
                fail += 1
            else:
                skip += 1
            print(f"[{done}/{total}] {res}", flush=True)
    print(f"[E33] DONE ok={ok} skip={skip} fail={fail}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
