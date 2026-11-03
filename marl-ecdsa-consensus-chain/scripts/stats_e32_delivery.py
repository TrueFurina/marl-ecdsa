"""E32 配送场景主证据统计（复用 E18-E31 口径：Welch + MW + Cohen d + 95%CI + posthoc power）。

用法（服务器）：
  python scripts/stats_e32_delivery.py --results-dir results/delivery_main

主指标：summary.avg_env_reward_last_50（bc vs pure，同种子对）
输出：控制台 + results/delivery_main/e32_stats_summary.json
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

try:
    from scipy import stats as sps
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False


def welch(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    nx, ny = len(x), len(y)
    mx, my = x.mean(), y.mean()
    vx, vy = x.var(ddof=1), y.var(ddof=1)
    se = math.sqrt(vx / nx + vy / ny)
    t = (mx - my) / se if se > 0 else 0.0
    df_num = (vx / nx + vy / ny) ** 2
    df_den = (vx / nx) ** 2 / (nx - 1) + (vy / ny) ** 2 / (ny - 1)
    df = df_num / df_den if df_den > 0 else 1.0
    p = 2 * (1 - sps.t.cdf(abs(t), df)) if HAS_SCIPY else float("nan")
    # 合并标准差（pooled，用于 Cohen d）
    sp = math.sqrt(((nx - 1) * vx + (ny - 1) * vy) / (nx + ny - 2)) if nx + ny > 2 else 0.0
    d = (mx - my) / sp if sp > 0 else 0.0
    z = 1.96
    ci = (mx - my - z * se, mx - my + z * se)
    # posthoc power（近似：非中心 t）
    power = float("nan")
    if HAS_SCIPY and se > 0:
        nc = abs(mx - my) / se
        try:
            power = sps.nct.sf(sps.t.ppf(0.975, df), df, nc)
        except Exception:
            power = float("nan")
    return {
        "mean_a": float(mx), "sd_a": float(np.std(x, ddof=1)), "n_a": nx,
        "mean_b": float(my), "sd_b": float(np.std(y, ddof=1)), "n_b": ny,
        "welch_t": float(t), "welch_df": float(df), "welch_p": float(p),
        "cohens_d": float(d), "ci95_diff": [float(ci[0]), float(ci[1])],
        "improvement_pct": float((mx - my) / abs(my) * 100) if my != 0 else float("nan"),
        "posthoc_power": float(power),
        "mw_p": float(sps.mannwhitneyu(x, y, alternative="two-sided").pvalue) if HAS_SCIPY else float("nan"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default="results/delivery_main")
    args = ap.parse_args()
    rd = Path(args.results_dir)

    out = {}
    for algo in ("iql", "qmix"):
        bc, pu = [], []
        for s in range(3001, 3031):
            fb = rd / f"e32_{algo}_bc_marl_seed{s}.json"
            fp = rd / f"e32_{algo}_pure_marl_seed{s}.json"
            if not fb.exists() or not fp.exists():
                print(f"[warn] missing {algo} seed {s}: bc={fb.exists()} pure={fp.exists()}")
                continue
            db = json.load(open(fb, encoding="utf-8"))
            dp = json.load(open(fp, encoding="utf-8"))
            bc.append(db["summary"]["avg_env_reward_last_50"])
            pu.append(dp["summary"]["avg_env_reward_last_50"])
        if len(bc) != 30 or len(pu) != 30:
            print(f"[ERROR] {algo}: 只有 {len(bc)} 对，中止该算法")
            continue
        st = welch(bc, pu)
        st["seed_range"] = [3001, 3030]
        out[algo] = st
        print(f"==== {algo} (n={len(bc)}/组, seed3001-3030) ====")
        print(json.dumps(st, ensure_ascii=False, indent=1))

    with open(rd / "e32_stats_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved:", rd / "e32_stats_summary.json")


if __name__ == "__main__":
    main()
