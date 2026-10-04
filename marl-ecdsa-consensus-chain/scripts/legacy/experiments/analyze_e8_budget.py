#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E8 受限预算对照分析：验证"BC 是协作形成加速器"推论。
推论：BC 在训练中期加速协作 → 受限预算下 bc 的稳态优势应更突出。
方法：对每个预算（500/1000），比较 bc_marl vs pure_marl 的末50 env_reward（Welch t/p/d）。
并与 NR-1（3000回合，末50 +29.2% p=0.126）对照，看预算越短是否显著性越强。

用法:
    python analyze_e8_budget.py [--dir results/champion_20260919] [--out e8_budget_report.json]
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

    report = {"budgets": {}}
    # E8 各预算
    for budget in (500, 1000):
        bc = sorted(glob.glob(os.path.join(a.dir, f"e8_budget{budget}_bc_marl_seed*.json")))
        pure = sorted(glob.glob(os.path.join(a.dir, f"e8_budget{budget}_pure_marl_seed*.json")))
        bc_vals = [load_env(f) for f in bc if load_env(f) is not None]
        pure_vals = [load_env(f) for f in pure if load_env(f) is not None]
        if len(bc_vals) >= 2 and len(pure_vals) >= 2:
            t, p, d = welch(bc_vals, pure_vals)
            report["budgets"][str(budget)] = {
                "bc_n": len(bc_vals), "bc_mean": round(statistics.mean(bc_vals), 4),
                "pure_n": len(pure_vals), "pure_mean": round(statistics.mean(pure_vals), 4),
                "delta_bc_minus_pure": round(statistics.mean(bc_vals) - statistics.mean(pure_vals), 4),
                "welch_p": round(p, 5), "cohen_d": round(d, 4),
            }
            flag = " ***显著" if p < 0.05 else (" *边缘" if p < 0.1 else "")
            print(f"预算 {budget}: bc={statistics.mean(bc_vals):.4f} pure={statistics.mean(pure_vals):.4f} "
                  f"Δ={statistics.mean(bc_vals)-statistics.mean(pure_vals):+.4f} p={p:.4f} d={d:+.4f}{flag}")

    # 对照：E1 3000 回合（末50 env）
    bc3000 = sorted(glob.glob(os.path.join(a.dir, "e1_iql_bc_marl_seed*.json")))
    pure3000 = sorted(glob.glob(os.path.join(a.dir, "e1_iql_pure_marl_seed*.json")))
    bc3 = [load_env(f) for f in bc3000 if load_env(f) is not None]
    pu3 = [load_env(f) for f in pure3000 if load_env(f) is not None]
    if len(bc3) >= 2 and len(pu3) >= 2:
        t, p, d = welch(bc3, pu3)
        report["budgets"]["3000"] = {
            "bc_n": len(bc3), "bc_mean": round(statistics.mean(bc3), 4),
            "pure_n": len(pu3), "pure_mean": round(statistics.mean(pu3), 4),
            "delta_bc_minus_pure": round(statistics.mean(bc3) - statistics.mean(pu3), 4),
            "welch_p": round(p, 5), "cohen_d": round(d, 4),
        }
        print(f"预算 3000 (对照): bc={statistics.mean(bc3):.4f} pure={statistics.mean(pu3):.4f} "
              f"Δ={statistics.mean(bc3)-statistics.mean(pu3):+.4f} p={p:.4f} d={d:+.4f}")

    out = a.out or os.path.join(a.dir, "e8_budget_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n已写出: {out}")


if __name__ == "__main__":
    main()
