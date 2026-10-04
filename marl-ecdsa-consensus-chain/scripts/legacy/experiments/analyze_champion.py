#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""冠军冲刺批次结果汇总：读取 results/champion_20260919/*.json，按实验分组统计。
统一口径：avg_env_reward_last_50（env 主口径，不含 BC 激励）。
统计：n / mean / std / Welch t / p / Cohen d / 95%CI / TOST 等价性检验。

用法:
    python analyze_champion.py [--dir results/champion_20260919] [--out report.json]
"""
import argparse
import glob
import json
import math
import os
import re
import statistics
from pathlib import Path

try:
    import numpy as np
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
        p = 2 * (1 - _norm_cdf(abs(t)))
    pooled_sd = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)) if (na + nb - 2) > 0 else 0.0
    d = diff / pooled_sd if pooled_sd > 0 else 0.0
    tcrit = sp.t.ppf(0.975, df) if HAVE_SCIPY else 1.96
    lo = diff - tcrit * se
    hi = diff + tcrit * se
    return t, p, d, lo, hi


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def tost(a, b, eps=2.0):
    na, nb = len(a), len(b)
    ma, mb = statistics.mean(a), statistics.mean(b)
    va = statistics.variance(a) if na > 1 else 0.0
    vb = statistics.variance(b) if nb > 1 else 0.0
    se = math.sqrt(va / na + vb / nb) if (na > 1 and nb > 1) else 1e-9
    t_low = ((ma - mb) - (-eps)) / se
    t_high = ((ma - mb) - eps) / se
    if HAVE_SCIPY:
        df = (va / na + vb / nb) ** 2 / (
            (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
        ) if (na > 1 and nb > 1 and (va > 0 or vb > 0)) else (na + nb - 2)
        p_low = 1 - sp.t.cdf(t_low, df)
        p_high = 1 - sp.t.cdf(t_high, df)
    else:
        p_low = 1 - _norm_cdf(t_low)
        p_high = 1 - _norm_cdf(t_high)
    return (p_low < 0.05) and (p_high < 0.05), p_low, p_high


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
    ap.add_argument("--tost-eps", type=float, default=2.0)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    groups = {}
    for fp in files:
        name = os.path.basename(fp)
        m = re.match(r"(e[123])_(.+)_seed(\d+)\.json", name)
        if not m:
            continue
        tag, body, seed = m.groups()
        val = load_env(fp)
        if val is None:
            continue
        if tag == "e1":
            parts = body.split("_")
            algo = parts[0]
            mode = "_".join(parts[1:])
            key = (tag, algo, mode)
        elif tag == "e2":
            lam = re.search(r"lam([\d.]+)", body)
            lam = lam.group(1) if lam else body
            algo = body.split("_")[-1]
            key = (tag, lam, algo)
        else:
            eta = re.search(r"cars([\d.]+)", body)
            eta = eta.group(1) if eta else body
            algo = body.split("_")[-1]
            key = (tag, eta, algo)
        groups.setdefault(key, []).append(val)

    report = {"tost_eps": a.tost_eps, "n_files": len(files), "groups": {}, "comparisons": {}}
    for key, vals in sorted(groups.items()):
        report["groups"]["/".join(map(str, key))] = summarize(vals)

    # E1: 每算法 bc vs pure (env 口径)
    for algo in ("iql", "vdn", "qmix"):
        pure = groups.get(("e1", algo, "pure_marl"))
        bc = groups.get(("e1", algo, "bc_marl"))
        if pure and bc and len(pure) >= 2 and len(bc) >= 2:
            t, p, d, lo, hi = welch(bc, pure)
            eq, pl, ph = tost(bc, pure, a.tost_eps)
            report["comparisons"][f"e1_{algo}_bc_vs_pure"] = {
                "pure_n": len(pure), "pure_mean": round(statistics.mean(pure), 4),
                "bc_n": len(bc), "bc_mean": round(statistics.mean(bc), 4),
                "delta_bc_minus_pure": round(statistics.mean(bc) - statistics.mean(pure), 4),
                "welch_t": round(t, 4), "welch_p": round(p, 5),
                "cohen_d": round(d, 4), "ci95_lo": round(lo, 4), "ci95_hi": round(hi, 4),
                "within_eps_equiv": bool(eq), "tost_p_low": round(pl, 5), "tost_p_high": round(ph, 5),
            }

    # E2: lambda 扫描 (bc iql) — 越低越好(env)；相对 lambda=0 的 pairwise Welch
    e2 = {k[1]: round(statistics.mean(v), 4) for k, v in groups.items() if k[0] == "e2"}
    if e2:
        report["comparisons"]["e2_lambda_scan"] = e2
        base = groups.get(("e2", "0.00", "iql"))
        if base and len(base) >= 2:
            e2_pw = {}
            for lam in ("0.05", "0.10", "0.15"):
                arm = groups.get(("e2", lam, "iql"))
                if arm and len(arm) >= 2:
                    t, p, d, lo, hi = welch(arm, base)
                    e2_pw[lam] = {
                        "mean": round(statistics.mean(arm), 4),
                        "delta_vs_0": round(statistics.mean(arm) - statistics.mean(base), 4),
                        "welch_p": round(p, 5), "cohen_d": round(d, 4),
                    }
            report["comparisons"]["e2_lambda_pairwise_vs_0"] = e2_pw

    # E3: CARS eta 扫描 (bc iql, consensus-shaping) — 越低越差；相对 eta=0 的 pairwise Welch
    e3 = {k[1]: round(statistics.mean(v), 4) for k, v in groups.items() if k[0] == "e3"}
    if e3:
        report["comparisons"]["e3_cars_scan"] = e3
        base = groups.get(("e3", "0.00", "iql"))
        if base and len(base) >= 2:
            e3_pw = {}
            for eta in ("0.02", "0.05", "0.075", "0.10", "0.15", "0.20"):
                arm = groups.get(("e3", eta, "iql"))
                if arm and len(arm) >= 2:
                    t, p, d, lo, hi = welch(arm, base)
                    e3_pw[eta] = {
                        "mean": round(statistics.mean(arm), 4),
                        "delta_vs_0": round(statistics.mean(arm) - statistics.mean(base), 4),
                        "welch_p": round(p, 5), "cohen_d": round(d, 4),
                    }
            report["comparisons"]["e3_cars_pairwise_vs_0"] = e3_pw

    out = a.out or os.path.join(a.dir, "champion_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
