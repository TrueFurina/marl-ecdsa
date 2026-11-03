"""E33 配送 8000ep 扩展统计：bc_marl vs pure_marl（同 E32 口径）。

控制/处理：bc_marl (λ=0.1) vs pure_marl (λ=0)。
主指标：summary.avg_env_reward_last_50（不含 BC 激励）。
命名兼容：优先 e33_{algo}_{bc|pure}_seed{s}.json（严格命名），缺则回退
          e33_{algo}_{bc_marl|pure_marl}_seed{s}.json（历史命名，完整 120）。
输出：results/delivery_main/e33_stats_summary.json

用法（服务器）：
  python scripts/stats_e33_delivery.py --results-dir results/delivery_main
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
    sp = math.sqrt(((nx - 1) * vx + (ny - 1) * vy) / (nx + ny - 2)) if nx + ny > 2 else 0.0
    d = (mx - my) / sp if sp > 0 else 0.0
    z = 1.96
    ci = (mx - my - z * se, mx - my + z * se)
    power = float("nan")
    if HAS_SCIPY and se > 0:
        nc = abs(mx - my) / se
        try:
            power = sps.nct.sf(sps.t.ppf(0.975, df), df, nc)
        except Exception:
            power = float("nan")
    return {
        "mean_bc": float(mx), "sd_bc": float(np.std(x, ddof=1)), "n_bc": nx,
        "mean_pure": float(my), "sd_pure": float(np.std(y, ddof=1)), "n_pure": ny,
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
            fb_strict = rd / f"e33_{algo}_bc_seed{s}.json"
            fb_non = rd / f"e33_{algo}_bc_marl_seed{s}.json"
            fp_strict = rd / f"e33_{algo}_pure_seed{s}.json"
            fp_non = rd / f"e33_{algo}_pure_marl_seed{s}.json"
            fb = fb_strict if fb_strict.exists() else fb_non
            fp = fp_strict if fp_strict.exists() else fp_non
            if not fb.exists() or not fp.exists():
                print(f"[warn] missing {algo} seed {s}: bc={fb.name} pure={fp.name}")
                continue
            db = json.load(open(fb, encoding="utf-8"))
            dp = json.load(open(fp, encoding="utf-8"))
            bc.append(db["summary"]["avg_env_reward_last_50"])
            pu.append(dp["summary"]["avg_env_reward_last_50"])
        if len(bc) != 30 or len(pu) != 30:
            print(f"[ERROR] {algo}: 只有 {len(bc)} 对，中止该算法")
            continue
        st = welch(np.asarray(bc), np.asarray(pu))
        st["seed_range"] = [3001, 3030]
        st["contrast"] = "bc_marl(8000ep) vs pure_marl(8000ep)"
        out[algo] = st
        print(f"==== {algo} (n={len(bc)}/组, seed3001-3030) ====")
        print(json.dumps(st, ensure_ascii=False, indent=1))

    with open(rd / "e33_stats_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved:", rd / "e33_stats_summary.json")


if __name__ == "__main__":
    main()
