# -*- coding: utf-8 -*-
"""只重绘图2「BC 激励的跨算法效应量」（E14 扩种 n=20 对齐后）

不重画其余图，避免无关 md5 变化导致需要重新嵌入全部材料。
样式与 _gen_figures_zh.py 的图2 完全一致（黑柱=显著，白柱=不显著）。
每个数字都在 stdout 打印，供图注逐字核对（禁手抄）。
"""
import glob
import json
import os
import shutil
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.dpi"] = 200
plt.rcParams["savefig.bbox"] = "tight"

OUT = "figures_zh"
METRIC = "avg_env_reward_last_50"
GREY_BC, GREY_LIGHT = "#000000", "#ffffff"

ALGOS = [("QMIX", "e14_qmix", "e14pure_qmix"),
         ("IQL", "e14_iql", "e14pure_iql"),
         ("VDN", "e14_vdn", "e14pure_vdn"),
         ("MAPPO", "e14_mappo", "e14pure_mappo")]

EXPECT_N = 20


def load(pattern, metric=METRIC):
    vals = []
    for f in sorted(glob.glob(pattern)):
        d = json.load(open(f, encoding="utf-8"))
        s = d.get("summary", d)
        v = s.get(metric)
        if v is not None:
            vals.append(v)
    return np.array(vals)


def welch(a, b):
    diff = a.mean() - b.mean()
    _, p = stats.ttest_ind(a, b, equal_var=False)
    pooled = np.sqrt(((len(a) - 1) * a.std(ddof=1) ** 2 + (len(b) - 1) * b.std(ddof=1) ** 2)
                     / (len(a) + len(b) - 2))
    d = diff / pooled if pooled > 0 else 0.0
    return diff, p, d


def star(p):
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "n.s."


def main():
    os.makedirs(OUT, exist_ok=True)
    names, ds, ps, ns, diffs = [], [], [], [], []
    incomplete = []
    for name, pre, pure_pre in ALGOS:
        a = load(f"results/dispatch_20260921/{pre}_seed*.json")
        b = load(f"results/dispatch_20260921/{pure_pre}_seed*.json")
        if not len(a) or not len(b):
            print(f"[跳过] {name}: bc={len(a)} pure={len(b)}")
            continue
        if len(a) != len(b):
            incomplete.append(f"{name} 双臂不等长 bc={len(a)} pure={len(b)}")
        if len(a) != EXPECT_N:
            incomplete.append(f"{name} n={len(a)}≠{EXPECT_N}")
        diff, p, d = welch(a, b)
        names.append(name)
        ds.append(d)
        ps.append(p)
        ns.append(len(a))
        diffs.append(diff)
        print(f"[{name:6s}] n={len(a):2d}/{len(b):2d}  bc={a.mean():8.3f}  pure={b.mean():8.3f}  "
              f"Δ={diff:+7.3f}  p={p:.5f}  d={d:+.4f}  {star(p)}")

    if incomplete:
        print()
        print("⚠️ 完整性告警（仍会出图，但数字不可锁定）：")
        for x in incomplete:
            print("   -", x)
        print()

    fig, ax = plt.subplots(figsize=(7, 4.6))
    ax.bar(names, ds, color=[GREY_BC if x < 0.05 else GREY_LIGHT for x in ps],
           edgecolor="black", linewidth=0.9, width=0.45)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_ylabel("Cohen's d（BC − 纯 MARL）", fontsize=11)
    ax.set_title("BC 激励的跨算法效应量（同批同种子对照）", fontsize=12)
    for i, (di, pi, n) in enumerate(zip(ds, ps, ns)):
        ax.text(i, di + (0.04 if di >= 0 else -0.10), f"{di:.2f}\n{star(pi)}\n(n={n})",
                ha="center", va="bottom" if di >= 0 else "top", fontsize=9)
    ax.set_ylim(min(ds) - 0.35, max(ds) + 0.5)
    ax.grid(axis="y", alpha=0.3)

    dst = f"{OUT}/fig2_cross_algorithm_zh.png"
    bak = f"{OUT}/fig2_cross_algorithm_zh.OLD.png"
    if os.path.exists(dst) and not os.path.exists(bak):
        shutil.copy2(dst, bak)
        print(f"\n旧图已备份 -> {bak}")
    fig.savefig(dst)
    plt.close(fig)
    print(f"新图已写出 -> {dst}")


if __name__ == "__main__":
    main()
