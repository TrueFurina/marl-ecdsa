"""C2 配送 Shapley 可信激励统计（框架内 A/B）。

控制臂 = E33 bc_marl（默认激励分配，e33_{algo}_bc_seed{s}.json）
处理臂 = C2 Shapley 加权池（c2_{algo}_shap_seed{s}.json）
主指标：summary.avg_env_reward_last_50（不含 BC 激励）
方法：复用 stats_e32_delivery 的 Welch + MW + Cohen d + 95%CI + posthoc power。

用法（服务器）：
  python scripts/stats_c2_delivery.py --results-dir results/delivery_main
输出：results/delivery_main/c2_stats_summary.json
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
        "mean_control": float(mx), "sd_control": float(np.std(x, ddof=1)), "n_control": nx,
        "mean_treatment": float(my), "sd_treatment": float(np.std(y, ddof=1)), "n_treatment": ny,
        "welch_t": float(t), "welch_df": float(df), "welch_p": float(p),
        "cohens_d": float(d), "ci95_diff": [float(ci[0]), float(ci[1])],
        "improvement_pct": float((my - mx) / abs(mx) * 100) if mx != 0 else float("nan"),
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
        control, treat = [], []
        for s in range(3001, 3031):
            fc = rd / f"e33_{algo}_bc_seed{s}.json"          # 控制臂：E33 默认分配
            ft = rd / f"c2_{algo}_shap_seed{s}.json"         # 处理臂：Shapley 加权
            if not fc.exists() or not ft.exists():
                print(f"[warn] missing {algo} seed {s}: control={fc.exists()} treat={ft.exists()}")
                continue
            dc = json.load(open(fc, encoding="utf-8"))
            dt = json.load(open(ft, encoding="utf-8"))
            control.append(dc["summary"]["avg_env_reward_last_50"])
            treat.append(dt["summary"]["avg_env_reward_last_50"])
        if len(control) != 30 or len(treat) != 30:
            print(f"[ERROR] {algo}: 只有 {len(control)} 对，中止该算法（先等 E33 与控制臂齐备）")
            continue
        st = welch(np.asarray(control), np.asarray(treat))
        st["seed_range"] = [3001, 3030]
        st["contrast"] = "bc_uniform(E33) vs bc_shapley(C2)"
        out[algo] = st
        print(f"==== {algo} (n={len(control)}/组, seed3001-3030) ====")
        print(json.dumps(st, ensure_ascii=False, indent=1))

    with open(rd / "c2_stats_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved:", rd / "c2_stats_summary.json")


if __name__ == "__main__":
    main()
