#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E9 受限预算×消融分析：定位"BC 加速协作"的机制来源。
问题：500 回合预算下 BC 加速协作，是哪个组件（security/consensus/incentive）在起作用？
方法：baseline（全开，复用 e8_budget500_bc_marl）vs 三 ablate 臂（e9_b500_ablate_*）的 Welch t/p/d。
关键判据：若 ablate-incentive 相对 baseline 显著变差，说明激励合约是加速协作的关键。

用法:
    python analyze_e9_budget_ablation.py [--dir results/champion_20260919] [--out e9_report.json]
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
    ap.add_argument("--dir", default="results/champion_20260919")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    # baseline = 500 回合全开 bc（复用 E8 的 budget500 bc）
    base_files = sorted(glob.glob(os.path.join(a.dir, "e8_budget500_bc_marl_seed*.json")))
    base = [load_env(f) for f in base_files if load_env(f) is not None]

    report = {"baseline": {"n": len(base), "mean": round(statistics.mean(base), 4) if base else None}}
    print(f"baseline (500回合全开): n={len(base)} mean={statistics.mean(base):.4f}")

    for arm in ("security", "consensus", "incentive"):
        files = sorted(glob.glob(os.path.join(a.dir, f"e9_b500_ablate_{arm}_seed*.json")))
        vals = [load_env(f) for f in files if load_env(f) is not None]
        if len(vals) >= 2 and len(base) >= 2:
            t, p, d = welch(vals, base)
            report[f"ablate_{arm}"] = {
                "n": len(vals), "mean": round(statistics.mean(vals), 4),
                "delta_vs_baseline": round(statistics.mean(vals) - statistics.mean(base), 4),
                "welch_p": round(p, 5), "cohen_d": round(d, 4),
            }
            flag = " ***显著变差" if (p < 0.05 and statistics.mean(vals) < statistics.mean(base)) else \
                   (" *边缘变差" if (p < 0.1 and statistics.mean(vals) < statistics.mean(base)) else "")
            print(f"ablate-{arm}: n={len(vals)} mean={statistics.mean(vals):.4f} "
                  f"Δ={statistics.mean(vals)-statistics.mean(base):+.4f} p={p:.4f} d={d:+.4f}{flag}")

    out = a.out or os.path.join(a.dir, "e9_budget_ablation_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n已写出: {out}")


if __name__ == "__main__":
    main()
