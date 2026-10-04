# -*- coding: utf-8 -*-
"""重绘 fig4_env_diversity_zh.png（2026-09-30）。

## 为什么要重绘
旧图（09-29 生成）画的是 **moving3 n=10（种子 42-51，p=0.218 n.s.）**，且**没有 moving5**；
而正文表格在 NR-86/NR-87 升级后已是 **moving3 n=20（p=0.0233 显著）+ moving5 n=20（p=0.051）**。
图与表直接矛盾（图说不显著、表说显著），属交付物内部自相矛盾，必须修。

## 新口径（三子图，全部 n=20/臂、种子 100-119）
  静态 SimpleSpread : results/dispatch_20260921/{e14,e14pure}_qmix_seed*.json   (NR-63)
  动态漂移 moving3  : results/env_diversity/moving3_{bc,pure}_marl_seed*.json  (NR-86)
  动态漂移 moving5  : results/env_diversity_moving5_n20/moving5_{bc,pure}_marl_seed*.json (NR-87)

风格与 _gen_figures_zh.py 完全一致（同一套 load/welch/sem/star）。
"""
import glob
import json
import os

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


def sem(a):
    return a.std(ddof=1) / np.sqrt(len(a))


def star(p):
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "n.s."


PANELS = [
    ("静态 SimpleSpread", "results/dispatch_20260921/e14_qmix_seed*.json",
     "results/dispatch_20260921/e14pure_qmix_seed*.json"),
    ("动态漂移 moving3", "results/env_diversity/moving3_bc_marl_seed*.json",
     "results/env_diversity/moving3_pure_marl_seed*.json"),
    ("动态漂移 moving5", "results/env_diversity_moving5_n20/moving5_bc_marl_seed*.json",
     "results/env_diversity_moving5_n20/moving5_pure_marl_seed*.json"),
]

fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.4), sharey=True)
for ax, tag, pa, pb in zip(axes, [p[0] for p in PANELS], [p[1] for p in PANELS], [p[2] for p in PANELS]):
    a, b = load(pa), load(pb)
    ax.bar(["BC-MARL", "纯 MARL"], [a.mean(), b.mean()], yerr=[sem(a), sem(b)],
           capsize=6, color=[GREY_BC, GREY_LIGHT], edgecolor="black", linewidth=0.9, width=0.45)
    dd, pp, ddd = welch(a, b)
    ax.set_title(f"{tag}（n={len(a)}）", fontsize=11)
    ax.text(0.5, 0.04, f"Δ={dd:+.2f}\np={pp:.3f}，d={ddd:.2f} {star(pp)}",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", edgecolor="#999999"))
    ax.grid(axis="y", alpha=0.3)
    print(f"[fig4] {tag}: n={len(a)}/{len(b)} bc={a.mean():.3f} pure={b.mean():.3f} "
          f"Δ={dd:+.3f} p={pp:.4f} d={ddd:+.3f} {star(pp)}")

axes[0].set_ylabel("末 50 回合平均 env_reward", fontsize=11)
fig.suptitle("环境泛化：静态环境 vs 动态漂移环境（QMIX，3000 回合，n=20/臂）", fontsize=12)
fig.tight_layout()
dst = os.path.join(OUT, "fig4_env_diversity_zh.png")
fig.savefig(dst)
plt.close(fig)
print("\n已写出:", dst, f"{os.path.getsize(dst)/1024:.1f} KB")
