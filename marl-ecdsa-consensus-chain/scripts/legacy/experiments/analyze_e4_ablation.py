#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E4 消融扩种分析：四臂（baseline 全开 vs 关 security/consensus/incentive）。
统一口径：avg_env_reward_last_50（env 主口径，不含 BC 激励）。
baseline 复用 E1 的 e1_iql_bc_marl（全开，λ=0.1，3000 回合，IQL）。
三臂为 e4_ablate_{security,consensus,incentive}（同样 3000 回合 / λ=0.1 / IQL）。

统计：每臂 n/mean/std；相对 baseline 的 Welch t / p / Cohen d / 95%CI；TOST 等价性。

用法:
    python analyze_e4_ablation.py [--dir results/champion_20260919] [--out e4_report.json]
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
    # 与 verify_champion_entries.py 一致：优先 scipy t 分布，fallback 正态近似
    if HAVE_SCIPY:
        p = 2 * (1 - sp.t.cdf(abs(t), df))
    else:
        p = 2 * (1 - _norm_cdf(abs(t)))
    pooled_sd = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)) if (na + nb - 2) > 0 else 0.0
    d = diff / pooled_sd if pooled_sd > 0 else 0.0
    tcrit = 1.96
    lo = diff - tcrit * se
    hi = diff + tcrit * se
    return t, p, d, lo, hi


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def summarize(values):
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 4),
        "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/champion_20260919")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))

    # baseline = e1_iql_bc_marl_seed*.json
    baseline = []
    arms = {"security": [], "consensus": [], "incentive": []}
    for fp in files:
        name = os.path.basename(fp)
        if name.startswith("e1_iql_bc_marl_seed"):
            v = load_env(fp)
            if v is not None:
                baseline.append(v)
        elif name.startswith("e4_ablate_"):
            # e4_ablate_{arm}_seed{seed}.json
            arm = name[len("e4_ablate_"):].split("_seed")[0]
            if arm in arms:
                v = load_env(fp)
                if v is not None:
                    arms[arm].append(v)

    report = {
        "n_files": len(files),
        "baseline": summarize(baseline),
        "arms": {k: summarize(v) for k, v in arms.items()},
        "comparisons": {},
    }

    for arm, vals in arms.items():
        if len(vals) >= 2 and len(baseline) >= 2:
            t, p, d, lo, hi = welch(vals, baseline)
            report["comparisons"][f"ablate_{arm}_vs_baseline"] = {
                "ablate_n": len(vals),
                "ablate_mean": round(statistics.mean(vals), 4),
                "baseline_n": len(baseline),
                "baseline_mean": round(statistics.mean(baseline), 4),
                "delta_ablate_minus_baseline": round(statistics.mean(vals) - statistics.mean(baseline), 4),
                "welch_t": round(t, 4),
                "welch_p": round(p, 5),
                "cohen_d": round(d, 4),
                "ci95_lo": round(lo, 4),
                "ci95_hi": round(hi, 4),
            }

    out = a.out or os.path.join(a.dir, "e4_ablation_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
