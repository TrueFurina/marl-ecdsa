"""C2 配送 Shapley 可信激励 A/B：处理臂（框架内真实激励）。

- 配置：复用 E33 的 bc_marl 控制臂（λ=0.1, 8000ep, seed 3001-3030, 默认激励分配）作为对照；
  本脚本只跑处理臂 = bc_marl + --use-shapley-incentive（Shapley 加权分配激励池）。
- 与 E32/E33 同口径：主指标 avg_env_reward_last_50（不含 BC 激励）。
- 断点续跑：输出存在则跳过。
- 用法：~/venv_torch/bin/python run_c2_shapley_delivery.py --workers 16
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
SEEDS = list(range(3001, 3031))                 # 30 种子，配对 E33
ALGOS = ["iql", "qmix"]


def run(alg: str, seed: int):
    out = f"{OUT}/c2_{alg}_shap_seed{seed}.json"
    if os.path.exists(out):
        return f"SKIP {out}"
    cmd = [PY, "-X", "utf8", "run_delivery_main.py",
           "--mode", "bc_marl", "--algorithm", alg,
           "--seed", str(seed), "--n_episodes", str(EP), "--max_steps", "60",
           "--lambda_weight", "0.1", "--n_agents", "3", "--n_landmarks", "2",
           "--use-shapley-incentive",
           "--save", out]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    dt = time.time() - t0
    if r.returncode == 0:
        return f"OK   {out} ({dt/60:.1f}min)"
    return f"FAIL {out} ({dt/60:.1f}min): {r.stderr[-400:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16,
                    help="与 E33 错峰；E33 完成后可提到 32")
    args = ap.parse_args()
    tasks = [(a, s) for s in SEEDS for a in ALGOS]
    total = len(tasks)
    print(f"[C2] {total} tasks (treatment arm), workers={args.workers}, ep={EP}", flush=True)
    done = ok = fail = skip = 0
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
    print(f"[C2] DONE ok={ok} skip={skip} fail={fail}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
