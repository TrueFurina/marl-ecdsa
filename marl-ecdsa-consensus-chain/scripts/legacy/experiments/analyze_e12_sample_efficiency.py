#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E12 — 样本效率：BC 是否更快让协作跨过阈值（time-to-threshold）。

用 E1 既有数据（IQL/VDN/QMIX x bc/pure x 30 种子，3000回合，cooperation_rates）。
对每个种子，取 trailing-mean(窗=50) 的协作率序列，找首次稳定跨过阈值 T 的回合。
仅取 bc/pure 两边都跨过的种子做配对（paired），对 (bc_cross - pure_cross) 做单样本 Welch(t 检验)≠0。
负向显著 ⇒ BC 更快抵达协作水平（样本效率增益）。

口径：p 值 scipy t 分布；T∈{0.6, 0.65}；warmup=100 跳过初始噪声。
"""
import argparse
import glob
import json
import os

import numpy as np
from scipy import stats as sp

D = "results/champion_20260919"
ALGOS = ("iql", "vdn", "qmix")
WARMUP = 100
WIN = 50


def crossing(series, T):
    s = np.asarray(series, float)
    sm = np.convolve(s, np.ones(WIN) / WIN, mode="same")
    idx = np.where(sm[WARMUP:] >= T)[0]
    return (idx[0] + WARMUP) if len(idx) else None


def load(pattern, key):
    files = sorted(glob.glob(os.path.join(D, pattern)))
    return [np.array(json.load(open(f, encoding="utf-8"))[key], dtype=float) for f in files]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=D)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    D_ = a.dir
    report = {"algorithms": {}}
    for T in (0.6, 0.65):
        for algo in ALGOS:
            bc = load(f"e1_{algo}_bc_marl_seed*.json", "cooperation_rates")
            pu = load(f"e1_{algo}_pure_marl_seed*.json", "cooperation_rates")
            nb, npu = len(bc), len(pu)
            cb = [crossing(x, T) for x in bc]
            cp = [crossing(x, T) for x in pu]
            cross_both = [i for i in range(min(nb, npu)) if cb[i] is not None and cp[i] is not None]
            diffs = np.array([cb[i] - cp[i] for i in cross_both], dtype=float)
            n_cross_b = sum(1 for x in cb if x is not None)
            n_cross_p = sum(1 for x in cp if x is not None)
            if len(diffs) >= 2:
                t, p = sp.ttest_1samp(diffs, 0.0)
                d = diffs.mean() / diffs.std(ddof=1) if diffs.std(ddof=1) > 0 else 0.0
                med_b = float(np.median([cb[i] for i in cross_both]))
                med_p = float(np.median([cp[i] for i in cross_both]))
            else:
                t = p = d = float("nan"); med_b = med_p = float("nan")
            rec = {
                "T": T, "n_bc": nb, "n_pure": npu,
                "n_cross_bc": n_cross_b, "n_cross_pure": n_cross_p,
                "n_paired_cross": len(diffs),
                "median_cross_bc": round(med_b, 1) if med_b == med_b else None,
                "median_cross_pure": round(med_p, 1) if med_p == med_p else None,
                "mean_delta_bc_minus_pure": round(float(diffs.mean()), 2) if len(diffs) else None,
                "welch_t": round(float(t), 4) if t == t else None,
                "p_value": round(float(p), 5) if p == p else None,
                "cohen_d": round(float(d), 4) if d == d else None,
            }
            report.setdefault("algorithms", {})[f"{algo}_T{T}"] = rec
            flag = " ***BC更快" if (p == p and p < 0.05 and diffs.mean() < 0) else (" *边缘" if (p == p and p < 0.1) else "")
            print(f"{algo.upper()} T={T}: 跨阈 bc={n_cross_b}/{nb} pure={n_cross_p}/{npu} | 配对跨阈={len(diffs)} | "
                  f"中位 bc={med_b} pure={med_p} | Δ(bc-pure)={rec['mean_delta_bc_minus_pure']} p={rec['p_value']} d={rec['cohen_d']}{flag}")
    out = a.out or os.path.join(D_, "e12_sample_efficiency_report.json")
    json.dump(report, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("写出:", out)


if __name__ == "__main__":
    main()
