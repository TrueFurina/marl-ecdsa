#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E9 机制归因分析（通用版，支持 500 / 1000 回合预算）。

对比 baseline（全开 bc_marl）vs 三 ablate 臂（security/consensus/incentive）的 Welch t/p/d。
500 回合：验证方向2（扩种子到 n=60 后效应是否稳定）。
1000 回合：验证方向3（机制归因同构——incentive 是否仍是主驱动）。

用法:
    python analyze_e9_attribution.py --dir <results/champion_20260919> --budget 500
    python analyze_e9_attribution.py --dir <results/champion_20260919> --budget 1000
"""
import argparse
import glob
import json
import math
import os
import statistics

try:
    from scipy import stats as sp
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False


def load_env(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    s = d.get("summary", d)
    return s.get("avg_env_reward_last_50", s.get("avg_reward_last_50"))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--budget", type=int, required=True, choices=(500, 1000))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    b = a.budget

    if b == 500:
        # 500-ep 基线 = 原始 30 (e8_budget500_bc_marl) + 扩种 30 (e9_b500_baseline, 原 D2 扩展种子)
        # 注意：扩种文件改名以区别于 E8 的 NR-28 bc/pure 对照（NR-28 仅用原始 30）。
        base_files = sorted(glob.glob(os.path.join(a.dir, "e8_budget500_bc_marl_seed*.json"))) + \
                     sorted(glob.glob(os.path.join(a.dir, "e9_b500_baseline_seed*.json")))
    else:
        base_files = sorted(glob.glob(os.path.join(a.dir, f"e8_budget{b}_bc_marl_seed*.json")))
    base = [v for v in (load_env(f) for f in base_files) if v is not None]

    report = {"budget": b, "baseline": {"n": len(base),
                                        "mean": round(statistics.mean(base), 4) if base else None}}
    print(f"[budget={b}] baseline (全开bc_marl): n={len(base)} mean={statistics.mean(base):.4f}")

    for arm in ("security", "consensus", "incentive"):
        files = sorted(glob.glob(os.path.join(a.dir, f"e9_b{b}_ablate_{arm}_seed*.json")))
        vals = [v for v in (load_env(f) for f in files) if v is not None]
        if len(vals) >= 2 and len(base) >= 2:
            t, p, d = welch(vals, base)
            delta = statistics.mean(vals) - statistics.mean(base)
            report[f"ablate_{arm}"] = {
                "n": len(vals), "mean": round(statistics.mean(vals), 4),
                "delta_vs_baseline": round(delta, 4),
                "welch_p": round(p, 5), "cohen_d": round(d, 4),
            }
            flag = " ***显著变差" if (p < 0.05 and delta < 0) else (
                " *边缘变差" if (p < 0.1 and delta < 0) else "")
            print(f"  ablate-{arm}: n={len(vals)} mean={statistics.mean(vals):.4f} "
                  f"Δ={delta:+.4f} p={p:.4f} d={d:+.4f}{flag}")
        else:
            print(f"  ablate-{arm}: 数据不足 (vals={len(vals)}, base={len(base)})")

    out = a.out or os.path.join(a.dir, f"e9_budget{b}_ablation_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"已写出: {out}")


if __name__ == "__main__":
    main()
