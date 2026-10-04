# -*- coding: utf-8 -*-
"""收敛曲线图（中文，替换测试报告里那张 V2 口径的 ASCII 字符画）。

口径：env_reward（不含 BC 激励）、3000 回合、n=71/臂（results/convergence_3000）、
曲线为 71 个种子的逐回合均值再做 50 回合滑动平均，阴影为 ±SEM（跨种子）。

⚠️ 之所以要替换：原字符画画的是 V2/legacy 口径（pure −63.91 / bc −45.02 / selfish −50.53），
该口径在报告正文里已被明确标为"已作废、不作申报数字"。给作废数字配一张漂亮图 = 反向美化，
故本图改用权威口径（NR-1/NR-2 的数据源）重画。

输出：figures_zh/fig5_convergence_zh.png
"""
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["savefig.dpi"] = 200
plt.rcParams["savefig.bbox"] = "tight"

OUT = "figures_zh"
WIN = 50


def curves(pattern):
    runs = []
    for f in sorted(glob.glob(pattern)):
        d = json.load(open(f, encoding="utf-8"))
        v = d.get("env_rewards")
        if v:
            runs.append(np.asarray(v, dtype=float))
    n = min(len(r) for r in runs)
    M = np.vstack([r[:n] for r in runs])
    mean = M.mean(axis=0)
    sem = M.std(axis=1, ddof=1).mean() / np.sqrt(M.shape[0])   # 跨种子的均值标准误（保守常量）
    k = np.ones(WIN) / WIN
    return np.convolve(mean, k, mode="valid"), sem, M.shape[0], n


bc, sem_bc, n_bc, T = curves("results/convergence_3000/bc_marl_seed*.json")
pu, sem_pu, n_pu, _ = curves("results/convergence_3000/pure_marl_seed*.json")
x = np.arange(WIN, T + 1)

fig, ax = plt.subplots(figsize=(7.2, 4.4))
ax.plot(x, bc, color="#000000", lw=1.8, label=f"BC-MARL（n={n_bc}）")
ax.fill_between(x, bc - sem_bc, bc + sem_bc, color="#000000", alpha=0.12, lw=0)
ax.plot(x, pu, color="#000000", lw=1.8, ls="--", label=f"纯 MARL（n={n_pu}）")
ax.fill_between(x, pu - sem_pu, pu + sem_pu, color="#000000", alpha=0.06, lw=0)
ax.set_xlabel("训练回合", fontsize=11)
ax.set_ylabel("env_reward（50 回合滑动平均）", fontsize=11)
ax.set_title("训练收敛曲线（IQL，λ=0.1，3000 回合，n=71/臂）", fontsize=12)
ax.legend(frameon=False, fontsize=10)
ax.grid(alpha=0.25)
fig.savefig(f"{OUT}/fig5_convergence_zh.png")
plt.close(fig)
print(f"[图5] n={n_bc}/{n_pu}, T={T}, 末值 bc={bc[-1]:.3f} pure={pu[-1]:.3f}, "
      f"Δ={bc[-1]-pu[-1]:+.3f}; SEM≈{sem_bc:.3f}")
