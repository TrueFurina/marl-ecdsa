#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E1 时序机制分析：BC 是否作为"协作形成加速器"（而非稳态性能提升器）。

核心假设：BC 的协作增强效应集中在训练中期（协作形成阶段），收敛后趋同。
方法：把 3000 回合按窗口分段，逐段做 bc vs pure 的 Welch 检验（env_reward 与 cooperation_rate）。

用法:
    python analyze_e1_temporal.py [--dir results/champion_20260919] [--out e1_temporal_report.json]
"""
import argparse
import glob
import json
import math
import os
import statistics

import numpy as np

try:
    from scipy import stats as sp
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False


def load_series(pattern, key, data_dir):
    files = sorted(glob.glob(os.path.join(data_dir, pattern)))
    arr = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        a = d.get(key)
        if a and len(a) > 0:
            arr.append(np.array(a, dtype=float))
    return np.array(arr)  # (n_seed, n_ep)


def welch(a, b):
    na, nb = len(a), len(b)
    ma, mb = statistics.mean(a), statistics.mean(b)
    va = statistics.variance(a) if na > 1 else 0.0
    vb = statistics.variance(b) if nb > 1 else 0.0
    diff = ma - mb
    se = math.sqrt(va / na + vb / nb) if (na > 1 and nb > 1) else 1e-9
    t = diff / se if se > 0 else 0.0
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    ) if (na > 1 and nb > 1 and (va > 0 or vb > 0)) else (na + nb - 2)
    if HAVE_SCIPY:
        p = 2 * (1 - sp.t.cdf(abs(t), df))
    else:
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    pooled_sd = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)) if (na + nb - 2) > 0 else 0.0
    d = diff / pooled_sd if pooled_sd > 0 else 0.0
    return t, p, d


WINDOWS = [(0, 100), (100, 500), (500, 1000), (1000, 2000), (2000, 3000)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/champion_20260919")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    report = {"windows": {}, "metrics": {}}
    for key in ("cooperation_rates", "env_rewards"):
        bc = load_series("e1_iql_bc_marl_seed*.json", key, a.dir)
        pure = load_series("e1_iql_pure_marl_seed*.json", key, a.dir)
        seg = []
        for lo, hi in WINDOWS:
            a_win = bc[:, lo:hi].mean(axis=1)
            b_win = pure[:, lo:hi].mean(axis=1)
            t, p, d = welch(list(a_win), list(b_win))
            seg.append({
                "window": f"ep{lo}-{hi}",
                "bc_mean": round(float(a_win.mean()), 4),
                "pure_mean": round(float(b_win.mean()), 4),
                "delta": round(float(a_win.mean() - b_win.mean()), 4),
                "welch_p": round(p, 5),
                "cohen_d": round(d, 4),
            })
        report["metrics"][key] = seg
        print(f"\n=== {key} 分段 Welch (bc vs pure) ===")
        for s in seg:
            flag = " ***显著" if s["welch_p"] < 0.05 else (" *边缘" if s["welch_p"] < 0.1 else "")
            print(f"  {s['window']:>12}: Δ={s['delta']:+.4f} p={s['welch_p']:.4f} d={s['cohen_d']:+.4f}{flag}")

    out = a.out or os.path.join(a.dir, "e1_temporal_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n已写出: {out}")


if __name__ == "__main__":
    main()
