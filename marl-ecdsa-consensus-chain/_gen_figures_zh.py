# -*- coding: utf-8 -*-
"""竞赛材料用中文图表生成（供 设计报告/测试报告 内嵌）

与 _gen_figures.py 的区别：
  1. 全中文标题/坐标轴/标注（matplotlib 用 Microsoft YaHei），消除"英文图混排"的拼装感；
  2. 数据集为**当前真实样本量**：主口径 n=71/臂、跨算法 n=20(QMIX)/10(其余)、
     消融 n=20/条件（seed110-129）、环境多样性 n=20/臂；
  3. 输出到 figures_zh/，不覆盖既有英文图（避免打断已引用它们的文档）；
  4. 每个数字都在 stdout 打印，供图注逐字核对（禁手抄）。

统一的统计口径：env_reward（不含 BC 激励）、末 50 回合、Welch t 检验、Cohen's d。
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
os.makedirs(OUT, exist_ok=True)
METRIC = "avg_env_reward_last_50"
GREY_BC, GREY_PURE, GREY_DARK, GREY_LIGHT = "#000000", "#ffffff", "#000000", "#ffffff"


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


# ── 图1：主结局（n=71/臂） ────────────────────────────────────────────
bc = load("results/convergence_3000/bc_marl_seed*.json")
pure = load("results/convergence_3000/pure_marl_seed*.json")
diff, p, d = welch(bc, pure)
fig, ax = plt.subplots(figsize=(6, 4.6))
ax.bar(["BC-MARL", "纯 MARL"], [bc.mean(), pure.mean()], yerr=[sem(bc), sem(pure)],
       capsize=8, color=[GREY_BC, GREY_LIGHT], edgecolor="black", linewidth=0.9, width=0.45)
ax.set_ylabel("末 50 回合平均 env_reward", fontsize=11)
ax.set_title(f"主结局对比（IQL，3000 回合，n={len(bc)}/{len(pure)}）", fontsize=12)
ax.text(0.5, 0.06, f"Δ={diff:+.2f}（{diff/abs(pure.mean())*100:+.2f}%）\n"
                   f"Welch p={p:.4f}，Cohen's d={d:.2f}",
        transform=ax.transAxes, ha="center", va="bottom", fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", edgecolor="#999999"))
ax.grid(axis="y", alpha=0.3)
fig.savefig(f"{OUT}/fig1_main_result_zh.png")
plt.close(fig)
print(f"[图1] n={len(bc)}/{len(pure)} bc={bc.mean():.3f} pure={pure.mean():.3f} "
      f"Δ={diff:+.3f} p={p:.5f} d={d:.3f}")

# ── 图2：跨算法效应量 ────────────────────────────────────────────────
algos = [("QMIX", "e14_qmix", "e14pure_qmix"), ("IQL", "e14_iql", "e14pure_iql"),
         ("VDN", "e14_vdn", "e14pure_vdn"), ("MAPPO", "e14_mappo", "e14pure_mappo")]
names, ds, ps, ns = [], [], [], []
for name, pre, pure_pre in algos:
    a = load(f"results/dispatch_20260921/{pre}_seed*.json")
    b = load(f"results/dispatch_20260921/{pure_pre}_seed*.json")
    if len(a) and len(b):
        _, pi, di = welch(a, b)
        names.append(name); ds.append(di); ps.append(pi); ns.append(len(a))
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
fig.savefig(f"{OUT}/fig2_cross_algorithm_zh.png")
plt.close(fig)
for n_, d_, p_ in zip(names, ds, ps):
    print(f"[图2] {n_}: d={d_:+.3f} p={p_:.5f} {star(p_)}")

# ── 图3：消融（n=20/条件） ───────────────────────────────────────────
conds = ["baseline", "security", "consensus", "incentive"]
zh = {"baseline": "完整系统", "security": "去安全校验", "consensus": "去共识加权", "incentive": "去 BC 激励"}
data = {c: load(f"results/ablation/{c}_seed*.json") for c in conds}
data = {k: v for k, v in data.items() if len(v)}
base = data["baseline"]
fig, ax = plt.subplots(figsize=(7, 4.6))
xs = list(data.keys())
ax.bar([zh[k] for k in xs], [data[k].mean() for k in xs],
       yerr=[sem(data[k]) for k in xs], capsize=6,
       color=[GREY_BC, GREY_LIGHT, GREY_LIGHT, GREY_DARK][:len(xs)],
       edgecolor="black", linewidth=0.9, width=0.5)
ax.set_ylabel("末 50 回合平均 env_reward", fontsize=11)
ax.set_title(f"受控消融：各组件贡献（IQL，500 回合，n={len(base)}/条件）", fontsize=12)
ax.grid(axis="y", alpha=0.3)
for i, k in enumerate(xs):
    if k == "baseline":
        continue
    dd, pp, ddd = welch(data[k], base)   # Δ = 该条件 − 完整系统（负=变差），与其它图一致
    ax.text(i, data[k].mean() - 1.6, f"Δ={dd:+.2f}\nd={ddd:+.2f}\np={pp:.3f}\n{star(pp)}",
            ha="center", fontsize=8, color="#111111")
fig.savefig(f"{OUT}/fig3_ablation_zh.png")
plt.close(fig)
print(f"[图3] baseline mean={base.mean():.3f} n={len(base)}")
for k in xs:
    if k != "baseline":
        dd, pp, ddd = welch(data[k], base)
        print(f"       {k}: mean={data[k].mean():.3f} Δ={dd:+.3f} p={pp:.4f} d={ddd:+.3f} n={len(data[k])}")

# ── 图4：环境多样性（静态 vs 动态 moving3 / moving5） ───────────────
# 数据源与登记簿 **NR-63 / NR-86 / NR-87 现口径** 对齐：三者均 n=20/臂、种子 100-119。
# 2026-09-30 修正：旧版画的是 env_diversity_20260927 的 moving3 n=10（p=0.218 n.s.）且无 moving5，
# 与 NR-86/87 升级到 n=20 后的正文表格矛盾（图说不显著、表说显著）——图必须跟表同口径。
st_bc = load("results/dispatch_20260921/e14_qmix_seed*.json")
st_pure = load("results/dispatch_20260921/e14pure_qmix_seed*.json")
m3_bc = load("results/env_diversity/moving3_bc_marl_seed*.json")
m3_pure = load("results/env_diversity/moving3_pure_marl_seed*.json")
m5_bc = load("results/env_diversity_moving5_n20/moving5_bc_marl_seed*.json")
m5_pure = load("results/env_diversity_moving5_n20/moving5_pure_marl_seed*.json")
panels = [(f"静态 SimpleSpread（n={len(st_bc)}）", st_bc, st_pure),
          (f"动态漂移 moving3（n={len(m3_bc)}）", m3_bc, m3_pure),
          (f"动态漂移 moving5（n={len(m5_bc)}）", m5_bc, m5_pure)]
fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.4), sharey=True)
for ax, (title, a, b) in zip(axes, panels):
    ax.bar(["BC-MARL", "纯 MARL"], [a.mean(), b.mean()], yerr=[sem(a), sem(b)],
           capsize=6, color=[GREY_BC, GREY_LIGHT], edgecolor="black", linewidth=0.9, width=0.45)
    dd, pp, ddd = welch(a, b)
    ax.set_title(title, fontsize=11)
    ax.text(0.5, 0.04, f"Δ={dd:+.2f}\np={pp:.3f}，d={ddd:.2f} {star(pp)}",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", edgecolor="#999999"))
    ax.grid(axis="y", alpha=0.3)
axes[0].set_ylabel("末 50 回合平均 env_reward", fontsize=11)
fig.suptitle("环境泛化：静态环境 vs 动态漂移环境（QMIX，3000 回合，n=20/臂）", fontsize=12)
fig.tight_layout()
fig.savefig(f"{OUT}/fig4_env_diversity_zh.png")
plt.close(fig)
for tag, a, b in [(t, a, b) for t, a, b in panels]:
    dd, pp, ddd = welch(a, b)
    print(f"[图4] {tag}: n={len(a)}/{len(b)} Δ={dd:+.3f} p={pp:.4f} d={ddd:+.3f}")

print("\n=== 输出 ===")
for f in sorted(os.listdir(OUT)):
    print(f"  {f}: {os.path.getsize(os.path.join(OUT, f))/1024:.1f} KB")
