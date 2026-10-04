"""
任务 A｜环境多样性扩展 —— 聚合分析（本地运行，与主口径统一）。

读取 results/env_diversity_20260927/<env>_<mode>_seed<seed>.json，
对每类环境（moving3 / moving5）做 bc_marl vs pure_marl 的 Welch 检验：
- 主指标：env_reward（不含 BC 激励）的 avg_env_reward_last_50（与全项目一致）
- 统计四件套：n、均值±标准差、Welch p、Cohen d
- 附加：分段（early/mid/late）Welch，呼应 NR-54/NR-85「随训练单调放大」叙事
- 合作率 last-50 同步报告

口径纪律：
- 统一用 scipy t 分布（与 number_registry 权威校验一致；不用正态近似）
- 禁跨配置混比：每组内部 n_episodes / lambda / mode / algorithm / seed 一致
- 诚实报告：无论显著与否都写出，并给可能原因
"""
import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np
from scipy import stats

WIN = {"early": (0, 1000), "mid": (1000, 2000), "late": (2000, 3000)}


def load_seeds(result_dir, env, mode):
    files = sorted(glob.glob(os.path.join(result_dir, f"{env}_{mode}_seed*.json")))
    rows = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        env_r = d.get("env_rewards")
        coop = d.get("cooperation_rates")
        if not env_r:
            continue
        rows.append({
            "file": os.path.basename(f),
            "env_rewards": np.array(env_r, dtype=float),
            "coop": np.array(coop, dtype=float) if coop else None,
        })
    return rows


def last50_mean(arr):
    return float(np.mean(arr[-50:])) if len(arr) >= 50 else float(np.mean(arr))


def welch(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    t, p = stats.ttest_ind(a, b, equal_var=False)
    n1, n2 = len(a), len(b)
    s1, s2 = np.std(a, ddof=1), np.std(b, ddof=1)
    sp = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2)) if (n1 + n2 - 2) > 0 else 0.0
    d = (np.mean(a) - np.mean(b)) / sp if sp > 0 else 0.0
    return float(np.mean(a) - np.mean(b)), float(p), float(d), n1, n2


def analyze_env(env, rows_bc, rows_pure):
    bc_last = [last50_mean(r["env_rewards"]) for r in rows_bc]
    pu_last = [last50_mean(r["env_rewards"]) for r in rows_pure]
    delta, p, d, n1, n2 = welch(bc_last, pu_last)

    # 分段 Welch（env_reward）
    win_rows = {}
    for wname, (s, e) in WIN.items():
        bcw = [float(np.mean(r["env_rewards"][s:e])) for r in rows_bc if len(r["env_rewards"]) >= e]
        puw = [float(np.mean(r["env_rewards"][s:e])) for r in rows_pure if len(r["env_rewards"]) >= e]
        if bcw and puw:
            dw, pw, dd, _, _ = welch(bcw, puw)
            win_rows[wname] = {"delta": dw, "welch_p": pw, "cohen_d": dd,
                               "bc_mean": float(np.mean(bcw)), "pure_mean": float(np.mean(puw)),
                               "n_bc": len(bcw), "n_pure": len(puw)}
        else:
            win_rows[wname] = None

    # 合作率 last-50
    coop_bc = [last50_mean(r["coop"]) for r in rows_bc if r["coop"] is not None]
    coop_pu = [last50_mean(r["coop"]) for r in rows_pure if r["coop"] is not None]
    coop_delta, coop_p, coop_d, _, _ = welch(coop_bc, coop_pu) if (coop_bc and coop_pu) else (None, None, None, 0, 0)

    return {
        "env": env,
        "n_bc": n1, "n_pure": n2,
        "bc_last50_mean": float(np.mean(bc_last)), "bc_last50_std": float(np.std(bc_last, ddof=1)),
        "pure_last50_mean": float(np.mean(pu_last)), "pure_last50_std": float(np.std(pu_last, ddof=1)),
        "delta": delta, "welch_p": p, "cohen_d": d,
        "significant_005": bool(p < 0.05),
        "windows_env": win_rows,
        "coop_last50": {"bc_mean": float(np.mean(coop_bc)) if coop_bc else None,
                        "pure_mean": float(np.mean(coop_pu)) if coop_pu else None,
                        "delta": coop_delta, "welch_p": coop_p, "cohen_d": coop_d},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/env_diversity_20260927")
    ap.add_argument("--out", default="results/env_diversity_20260927/env_diversity_analysis.json")
    args = ap.parse_args()

    envs = ["moving3", "moving5"]
    report = {"caliber": "env_reward avg_last50, Welch(scipy t-dist), Cohen d; λ=0.1; QMIX; 3000ep",
              "environments": {}}
    for env in envs:
        bc = load_seeds(args.dir, env, "bc_marl")
        pu = load_seeds(args.dir, env, "pure_marl")
        if not bc or not pu:
            report["environments"][env] = {"error": f"missing data: bc={len(bc)} pure={len(pu)}"}
            continue
        report["environments"][env] = analyze_env(env, bc, pu)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(report, open(args.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    # 控制台摘要
    print("=" * 70)
    print("环境多样性扩展 · bc_marl vs pure_marl（env_reward last-50, Welch）")
    print("=" * 70)
    for env, r in report["environments"].items():
        if "error" in r:
            print(f"[{env}] {r['error']}")
            continue
        sig = "显著" if r["significant_005"] else "不显著"
        print(f"\n[{env}]  n_bc={r['n_bc']} n_pure={r['n_pure']}")
        print(f"  BC  last50 = {r['bc_last50_mean']:.3f} ± {r['bc_last50_std']:.3f}")
        print(f"  PURE last50 = {r['pure_last50_mean']:.3f} ± {r['pure_last50_std']:.3f}")
        print(f"  Δ = {r['delta']:+.3f}  Welch p = {r['welch_p']:.4f}  Cohen d = {r['cohen_d']:.3f}  → {sig}")
        w = r["windows_env"]
        for wn in ("early", "mid", "late"):
            if w.get(wn):
                print(f"    [{wn}] Δ={w[wn]['delta']:+.3f} p={w[wn]['welch_p']:.4f} d={w[wn]['cohen_d']:.3f}")
        c = r["coop_last50"]
        if c.get("welch_p") is not None:
            print(f"  合作率 last50: BC={c['bc_mean']:.3f} PURE={c['pure_mean']:.3f} Δ={c['delta']:+.3f} p={c['welch_p']:.4f}")
    print(f"\n报告已写出: {args.out}")


if __name__ == "__main__":
    main()
