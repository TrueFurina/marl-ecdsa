# -*- coding: utf-8 -*-
"""
扩种 n=30 后的统计量计算（程序化取数，禁止手抄数字）。

## 立场
这个脚本存在的唯一理由：**不能手算**。登记簿里每一个 declared 值都必须由脚本从原始
JSON 复算得出，否则又会出现"手抄漂移"。

## 口径（与 number_registry 严格一致）
- 字段：`summary.avg_env_reward_last_50`（末 50 回合的 env_reward，不含 BC 激励）
- a 臂 = bc_marl，b 臂 = pure_marl
- Welch t 检验（不等方差）；Cohen's d 用 pooled SD；
  95% CI 用 Welch–Satterthwaite 自由度

## 自校验（--check）
用既有 seed 100-119 重算，**必须复现** NR-87 已登记的 declared 值：
    mean_a=-93.4042  sd_a=5.779  mean_b=-97.0644  sd_b=5.6992
    welch_p=0.05083  cohens_d=0.6377  ci95_diff=[-0.0139, 7.3343]  n=20/20
复现不出来 ⇒ 公式与登记簿不对齐，跑完扩种也是错的，必须先查。

## 用法
    python scripts/analyze_expand_n30.py --check                 # 自校验（seed 100-119）
    python scripts/analyze_expand_n30.py --env moving5           # 全量（当前目录下所有 seed）
    python scripts/analyze_expand_n30.py --algo iql              # E14 某算法
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELD = "summary.avg_env_reward_last_50"

# 已登记的 NR-87（moving5, n=20）真值，用于自校验
EXPECTED_N20 = {
    "mean_a": -93.4042, "sd_a": 5.779,
    "mean_b": -97.0644, "sd_b": 5.6992,
    "welch_p": 0.05083, "cohens_d": 0.6377,
    "ci95_diff": [-0.0139, 7.3343], "n_a": 20, "n_b": 20,
}


def _dig(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def load_values(pattern: str, seeds: set | None):
    """按 glob 读文件，返回 (值列表, 用到的 seed 列表)。"""
    vals, used = [], []
    for path in sorted(glob.glob(pattern, recursive=True)):
        base = os.path.basename(path)
        token = None
        for t in base.replace(".json", "").split("_"):
            if t.startswith("seed") and t[4:].isdigit():
                token = int(t[4:])
        if seeds is not None and (token is None or token not in seeds):
            continue
        try:
            j = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        v = _dig(j, FIELD)
        if v is None:
            continue
        vals.append(float(v))
        used.append(token)
    return vals, used


def stats_two(a: list, b: list) -> dict:
    a_arr, b_arr = np.array(a, dtype=float), np.array(b, dtype=float)
    n_a, n_b = len(a_arr), len(b_arr)
    if n_a < 2 or n_b < 2:
        return {"error": f"样本不足 n_a={n_a} n_b={n_b}"}
    mean_a, mean_b = float(a_arr.mean()), float(b_arr.mean())
    sd_a, sd_b = float(a_arr.std(ddof=1)), float(b_arr.std(ddof=1))

    # Welch
    t_stat, welch_p = stats.ttest_ind(a_arr, b_arr, equal_var=False)

    # Cohen's d (pooled)
    pooled = math.sqrt(((n_a - 1) * sd_a ** 2 + (n_b - 1) * sd_b ** 2) / (n_a + n_b - 2))
    d = (mean_a - mean_b) / pooled if pooled > 0 else float("nan")

    # 95% CI for mean difference, Welch–Satterthwaite df
    se = math.sqrt(sd_a ** 2 / n_a + sd_b ** 2 / n_b)
    df = (sd_a ** 2 / n_a + sd_b ** 2 / n_b) ** 2 / (
        (sd_a ** 2 / n_a) ** 2 / (n_a - 1) + (sd_b ** 2 / n_b) ** 2 / (n_b - 1)
    )
    tcrit = stats.t.ppf(0.975, df)
    diff = mean_a - mean_b
    ci = [diff - tcrit * se, diff + tcrit * se]

    return {
        "n_a": n_a, "n_b": n_b,
        "mean_a": round(mean_a, 4), "sd_a": round(sd_a, 4),
        "mean_b": round(mean_b, 4), "sd_b": round(sd_b, 4),
        "delta": round(diff, 4),
        "welch_p": round(float(welch_p), 5),
        "cohens_d": round(float(d), 4),
        "ci95_diff": [round(ci[0], 4), round(ci[1], 4)],
        "significant_005": bool(welch_p < 0.05),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", help="moving3/moving5 等环境名（走 results/env_diversity_*）")
    ap.add_argument("--algo", help="iql/vdn/mappo/qmix（E14，走 results/dispatch_20260921）")
    ap.add_argument("--check", action="store_true", help="自校验：seed100-119 复现 NR-87")
    ap.add_argument("--seed-min", type=int, default=None)
    ap.add_argument("--seed-max", type=int, default=None)
    ap.add_argument("--out", default=None, help="结果 JSON 落盘路径")
    args = ap.parse_args()

    if args.check:
        seeds = set(range(100, 120))
        pat_a = os.path.join(ROOT, "results", "env_diversity_moving5_n20", "moving5_bc_marl_seed*.json")
        pat_b = os.path.join(ROOT, "results", "env_diversity_moving5_n20", "moving5_pure_marl_seed*.json")
        label = "moving5 (seed100-119, 期望复现 NR-87)"
    elif args.env:
        seeds = None
        base = os.path.join(ROOT, "results", "env_diversity_moving5_n20")
        pat_a = os.path.join(base, f"{args.env}_bc_marl_seed*.json")
        pat_b = os.path.join(base, f"{args.env}_pure_marl_seed*.json")
        label = f"{args.env} (全量 seed)"
    elif args.algo:
        seeds = None
        base = os.path.join(ROOT, "results", "dispatch_20260921")
        pat_a = os.path.join(base, f"e14_{args.algo}_seed*.json")
        pat_b = os.path.join(base, f"e14pure_{args.algo}_seed*.json")
        label = f"E14/{args.algo} (全量 seed)"
    else:
        print("需要 --check / --env / --algo 之一")
        return 2

    if args.seed_min is not None and args.seed_max is not None:
        seeds = set(range(args.seed_min, args.seed_max + 1))

    a, seeds_a = load_values(pat_a, seeds)
    b, seeds_b = load_values(pat_b, seeds)

    print(f"== {label}")
    print(f"   a 臂(bc_marl)   n={len(a)}  seeds={sorted(x for x in seeds_a if x is not None)}")
    print(f"   b 臂(pure_marl) n={len(b)}  seeds={sorted(x for x in seeds_b if x is not None)}")

    # 配对检查：两臂必须同 seed 集合
    sa, sb = set(seeds_a), set(seeds_b)
    if sa != sb:
        print(f"   ⚠️ 两臂 seed 集合不一致：仅 a={sorted(sa - sb)} 仅 b={sorted(sb - sa)}")

    res = stats_two(a, b)
    print("   " + json.dumps(res, ensure_ascii=False))

    if args.check:
        print("\n== 自校验：与已登记 NR-87 declared 比对 ==")
        ok = True
        for k, exp in EXPECTED_N20.items():
            got = res.get(k)
            if isinstance(exp, list):
                match = got is not None and all(abs(g - e) < 0.02 for g, e in zip(got, exp))
                print(f"   {k:12s} 期望={exp} 实得={got} -> {'OK' if match else 'FAIL'}")
                ok = ok and match
            else:
                match = got is not None and abs(got - exp) < 0.02
                print(f"   {k:12s} 期望={exp} 实得={got} -> {'OK' if match else 'FAIL'}")
                ok = ok and match
        print("   自校验:", "PASS（公式与登记簿一致）" if ok else "FAIL（公式未对齐，禁止用本脚本出数）")
        return 0 if ok else 1

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"   已落盘: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
