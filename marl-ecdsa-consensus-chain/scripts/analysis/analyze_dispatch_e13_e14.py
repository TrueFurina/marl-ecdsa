#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E13(自私攻击强度) + E14(四算法) 汇总分析。

口径纪律：
- 竞赛对比统一 env_reward（不含 BC 激励）；主指标 avg_env_reward_last_50 与 avg_env_reward 同报。
- 不跨配置混比；E14 与既有 E1(pure) 为不同批次，报告须标注"跨批比较"。
- E13 两指标（reward 与合作率）方向若相反，如实并列，不挑选。

用法: python analyze_dispatch_e13_e14.py [--json out.json]
"""
import json
import glob
import os
import sys
import argparse
import statistics as st

try:
    from scipy import stats as sps
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(BASE, "..", ".."))
DISPATCH = os.path.join(REPO, "results", "dispatch_20260921")
CHAMP = os.path.join(REPO, "results", "champion_20260919")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _welch(a, b):
    if not HAS_SCIPY or len(a) < 2 or len(b) < 2:
        return None
    t, p = sps.ttest_ind(a, b, equal_var=False)
    return {"t": round(t, 4), "p": round(p, 5)}


def analyze_e13():
    """E13: selfish_{0,20,50}pct_{random,greedy} × 10 seeds, 500 ep."""
    files = sorted(glob.glob(os.path.join(DISPATCH, "e13_expb_seed*.json")))
    if not files:
        return {"error": "no e13 files"}
    buckets = {}  # cfg -> list of summaries
    for fp in files:
        d = _load(fp)
        for exp in d.get("experiments", []):
            for cfg, r in exp.get("results", {}).items():
                buckets.setdefault(cfg, []).append(r)

    out = {}
    for cfg, rows in sorted(buckets.items()):
        # 跳过非指标配置（如 'comparison' 汇总块）与无有效字段者
        if cfg == "comparison" or not any("avg_env_reward" in r for r in rows):
            continue
        def col(k):
            return [r[k] for r in rows if k in r and r[k] is not None]
        rec = {
            "n": len(rows),
            "env_reward": round(st.mean(col("avg_env_reward")), 4),
            "env_reward_sd": round(st.pstdev(col("avg_env_reward")), 4) if len(rows) > 1 else 0.0,
            "env_reward_last50": round(st.mean(col("avg_env_reward_last_50")), 4),
            "reward": round(st.mean(col("avg_reward")), 4),
            "coop_rate": round(st.mean(col("avg_cooperation_rate")), 4),
            "coop_rate_sd": round(st.pstdev(col("avg_cooperation_rate")), 4) if len(rows) > 1 else 0.0,
            "betrayal_rate": round(st.mean(col("avg_betrayal_rate")), 4),
        }
        out[cfg] = rec

    # 关键裁决：同自私比例下 random vs greedy（reward 与合作率是否方向相反）
    verdicts = {}
    for ratio in ("0pct", "20pct", "50pct"):
        rk, gk = f"selfish_{ratio}_random", f"selfish_{ratio}_greedy"
        if rk in out and gk in out:
            rrows = buckets[rk]
            grows = buckets[gk]
            verdicts[ratio] = {
                "reward_delta(greedy-random)": round(out[gk]["reward"] - out[rk]["reward"], 4),
                "coop_delta(greedy-random)": round(
                    out[gk]["coop_rate"] - out[rk]["coop_rate"], 4
                ),
                "welch_env_reward": _welch(
                    [r["avg_env_reward"] for r in grows],
                    [r["avg_env_reward"] for r in rrows],
                ),
                "welch_coop": _welch(
                    [r["avg_cooperation_rate"] for r in grows],
                    [r["avg_cooperation_rate"] for r in rrows],
                ),
            }
    return {"by_config": out, "random_vs_greedy": verdicts}


def analyze_e14():
    """E14: {iql,vdn,qmix,mappo} bc_marl × 10 seeds(100-109), 3000 ep."""
    algos = ["iql", "vdn", "qmix", "mappo"]
    out = {}
    raw = {}
    for algo in algos:
        files = sorted(glob.glob(os.path.join(DISPATCH, f"e14_{algo}_seed*.json")))
        rows = [_load(f)["summary"] for f in files]
        raw[algo] = rows
        if not rows:
            out[algo] = {"error": "no files"}
            continue
        def col(k):
            return [r[k] for r in rows if r.get(k) is not None]
        out[algo] = {
            "n": len(rows),
            "env_reward": round(st.mean(col("avg_env_reward")), 4),
            "env_reward_sd": round(st.pstdev(col("avg_env_reward")), 4) if len(rows) > 1 else 0.0,
            "env_reward_last50": round(st.mean(col("avg_env_reward_last_50")), 4),
            "env_reward_last50_sd": round(st.pstdev(col("avg_env_reward_last_50")), 4) if len(rows) > 1 else 0.0,
            "coop_rate": round(st.mean(col("avg_cooperation_rate")), 4),
            "betrayal_rate": round(st.mean(col("avg_betrayal_rate")), 4),
        }

    # 与既有 E1 pure 对照（跨批，须标注）
    pure = {}
    for algo in algos:
        files = sorted(glob.glob(os.path.join(CHAMP, f"e1_{algo}_pure_marl_seed*.json")))
        rows = []
        for f in files:
            try:
                rows.append(_load(f)["summary"])
            except Exception:
                pass
        if rows:
            pure[algo] = {
                "n": len(rows),
                "env_reward": round(st.mean([r["avg_env_reward"] for r in rows]), 4),
                "env_reward_last50": round(st.mean([r["avg_env_reward_last_50"] for r in rows]), 4),
                "coop_rate": round(st.mean([r["avg_cooperation_rate"] for r in rows]), 4),
            }

    deltas = {}
    for algo in algos:
        if algo in out and "env_reward_last50" in out[algo] and algo in pure:
            bc_last50 = [r["avg_env_reward_last_50"] for r in raw[algo]]
            pfiles = sorted(glob.glob(os.path.join(CHAMP, f"e1_{algo}_pure_marl_seed*.json")))
            pr_last50 = []
            for f in pfiles:
                try:
                    pr_last50.append(_load(f)["summary"]["avg_env_reward_last_50"])
                except Exception:
                    pass
            deltas[algo] = {
                "bc_last50": out[algo]["env_reward_last50"],
                "pure_last50": pure[algo]["env_reward_last50"],
                "delta": round(out[algo]["env_reward_last50"] - pure[algo]["env_reward_last50"], 4),
                "welch_last50": _welch(bc_last50, pr_last50),
                "cross_batch": True,
            }
    return {"bc_marl": out, "pure_marl_e1": pure, "delta_vs_pure": deltas}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    res = {"e13": analyze_e13(), "e14": analyze_e14()}

    print("=" * 70)
    print("E13 自私攻击强度（500 ep, 10 seeds, env_reward 口径）")
    print("=" * 70)
    for cfg, r in res["e13"].get("by_config", {}).items():
        print(f"  {cfg:26s} env_rew={r['env_reward']:9.3f}±{r['env_reward_sd']:6.3f}  "
              f"last50={r['env_reward_last50']:9.3f}  coop={r['coop_rate']:.4f}  "
              f"betray={r['betrayal_rate']:.4f}")
    print("\n  [裁决] random vs greedy（reward Δ / coop Δ）：")
    for ratio, v in res["e13"].get("random_vs_greedy", {}).items():
        print(f"    {ratio:6s} rewardΔ={v['reward_delta(greedy-random)']:+8.3f}  "
              f"coopΔ={v['coop_delta(greedy-random)']:+7.4f}  "
              f"p_env={v['welch_env_reward']}  p_coop={v['welch_coop']}")

    print("\n" + "=" * 70)
    print("E14 四算法（3000 ep, 10 seeds, bc_marl）vs E1 pure（跨批对照）")
    print("=" * 70)
    for algo, r in res["e14"]["bc_marl"].items():
        if "error" in r:
            print(f"  {algo:6s} {r['error']}")
            continue
        pr = res["e14"]["pure_marl_e1"].get(algo, {})
        print(f"  {algo:6s} bc: env_rew={r['env_reward']:9.3f} last50={r['env_reward_last50']:9.3f} "
              f"coop={r['coop_rate']:.4f} | pure(跨批): last50={pr.get('env_reward_last50','NA')}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\n[saved] {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
