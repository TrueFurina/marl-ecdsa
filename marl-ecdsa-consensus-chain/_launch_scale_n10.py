#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""③-A 规模提升 · 通用启动器（n=10 / n=20 / 更多 seed 共用）

Q 标定（规模实验口径，跑前必读）：
  Q1 n_landmarks = n_agents（1:1：每个智能体认领一个路标，own_landmark_idx = i % n_landmarks 语义不变）
  Q2 world_size = 1.0（env 默认，train.py 无该 CLI；密度上升属"预期难度提升"——跨规模只并列、不做类比）
  Q3 max_steps：n=10 用 40（从 25 上调，更多智能体覆盖需要更多步）；n=20 用 50（2× 智能体，给更多覆盖步）
      ⚠️ 跨 n 的 max_steps 不同，bc/pure 对比**只在同一 n 内**做，绝不做跨规模数值类比。

幂等：结果已存在则跳过（所以"加 seed"只需把 --seeds 扩到更多值，旧 seed 自动 skip）。

用法（在仓库根 marl-ecdsa-consensus-chain/ 下，或任意位置，脚本自定位仓库根）：
  python -X utf8 _launch_scale_n10.py --tag n10 --seeds 1 2 3 4
  python -X utf8 _launch_scale_n10.py --tag n20 --n_agents 20 --n_landmarks 20 --max_steps 50 --seeds 1 2
"""
import os
import sys
import itertools
import subprocess
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))   # 仓库根（脚本所在目录）
REPO = HERE


def main():
    ap = argparse.ArgumentParser(description="MARL-ECDSA 规模提升训练启动器")
    ap.add_argument("--tag", default="n10", help="输出子目录标签：results/scale_<tag>_smoke")
    ap.add_argument("--n_agents", type=int, default=10)
    ap.add_argument("--n_landmarks", type=int, default=None, help="默认 = n_agents（1:1）")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--max_steps", type=int, default=40)
    ap.add_argument("--n_episodes", type=int, default=3000)
    ap.add_argument("--algos", nargs="+", default=["iql", "vdn", "qmix", "mappo"])
    ap.add_argument("--modes", nargs="+", default=["bc_marl", "pure_marl"])
    args = ap.parse_args()

    n_landmarks = args.n_landmarks or args.n_agents
    OUT = os.path.join(REPO, "results", f"scale_{args.tag}_smoke")
    os.makedirs(OUT, exist_ok=True)

    jobs = list(itertools.product(args.modes, args.algos, args.seeds))
    print(f"③-A scale[{args.tag}]：共 {len(jobs)} 次（n={args.n_agents}, "
          f"landmarks={n_landmarks}, ep={args.n_episodes}, steps={args.max_steps}）")
    done = fail = skip = 0
    for i, (mode, algo, seed) in enumerate(jobs, 1):
        save = os.path.join(OUT, f"{mode}_{algo}_seed{seed}.json")
        if os.path.exists(save):
            skip += 1
            print(f"[{i}/{len(jobs)}] skip（已存在） {os.path.basename(save)}", flush=True)
            continue
        cmd = [sys.executable, "-X", "utf8", "-u", "train.py",
               "--mode", mode,
               "--n_agents", str(args.n_agents),
               "--n_landmarks", str(n_landmarks),
               "--n_episodes", str(args.n_episodes),
               "--max_steps", str(args.max_steps),
               "--algorithm", algo,
               "--seed", str(seed),
               "--save", save]
        print(f"[{i}/{len(jobs)}] run {mode}/{algo}/seed{seed} ...", flush=True)
        r = subprocess.run(cmd, cwd=REPO)
        if r.returncode == 0:
            done += 1
        else:
            fail += 1
            print(f"    !! 退出码 {r.returncode}（继续跑其余，勿中断）", flush=True)
    print(f"完成：ok={done} fail={fail} skip={skip}")


if __name__ == "__main__":
    main()
