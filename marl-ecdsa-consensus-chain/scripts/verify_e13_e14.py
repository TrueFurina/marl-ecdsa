#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立复算 E13 / E14 —— 只读原始 JSON，不信任任何既有聚合文件。

用法: python scripts/verify_e13_e14.py
输出: 控制台表格 + scripts/../results/dispatch_20260921/verify_e13_e14.json
"""
import json, os, glob, math
import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.normpath(os.path.join(HERE, "..", "results", "dispatch_20260921"))
DERIVED = os.path.join(D, "derived")


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def mean_sd(xs):
    a = np.asarray(xs, dtype=float)
    return float(a.mean()), float(a.std(ddof=1)) if len(a) > 1 else 0.0


def paired(a, b, label):
    """配对差 + 配对 t 检验（同种子）"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    d = a - b
    if len(d) < 2 or np.allclose(d, d[0]):
        return dict(delta=float(d.mean()), t=float("nan"), p=float("nan"),
                    d_cohen=float("nan"), note="degenerate")
    t, p = stats.ttest_rel(a, b)
    sd = d.std(ddof=1)
    return dict(delta=float(d.mean()), t=float(t), p=float(p),
                d_cohen=float(d.mean() / sd) if sd > 0 else float("nan"),
                n=int(len(d)))


# ---------------- E13 ----------------
def run_e13():
    cfgs = ["selfish_0pct_greedy", "selfish_0pct_random",
            "selfish_20pct_greedy", "selfish_20pct_random",
            "selfish_50pct_greedy", "selfish_50pct_random"]
    data = {}
    for c in cfgs:
        files = sorted(glob.glob(os.path.join(DERIVED, f"e13_{c}_seed*.json")))
        recs = []
        for f in files:
            r = jload(f)
            recs.append(dict(seed=r["seed"],
                             env=r["avg_env_reward"],
                             env50=r["avg_env_reward_last_50"],
                             coop=r["avg_cooperation_rate"],
                             betray=r["avg_betrayal_rate"]))
        recs.sort(key=lambda r: r["seed"])
        data[c] = recs

    out = dict(by_config={}, greedy_vs_random={})
    print("\n" + "=" * 88)
    print("E13 自私攻击强度对照（10 种子 × 500 回合，同种子配对）")
    print("=" * 88)
    print(f"{'config':<24}{'n':>3}{'env_reward':>18}{'coop_rate':>18}{'betrayal':>10}")
    for c in cfgs:
        r = data[c]
        m, s = mean_sd([x["env"] for x in r])
        cm, cs = mean_sd([x["coop"] for x in r])
        bm, _ = mean_sd([x["betray"] for x in r])
        out["by_config"][c] = dict(n=len(r), env_reward=m, env_reward_sd=s,
                                   coop_rate=cm, coop_rate_sd=cs, betrayal_rate=bm)
        print(f"{c:<24}{len(r):>3}{m:>11.4f}±{s:<6.4f}{cm:>11.4f}±{cs:<6.4f}{bm:>10.4f}")

    print("\n配对比较（greedy − random，同种子）：")
    for pct in ["0pct", "20pct", "50pct"]:
        g = data[f"selfish_{pct}_greedy"]
        r = data[f"selfish_{pct}_random"]
        assert [x["seed"] for x in g] == [x["seed"] for x in r], "seed 未对齐！"
        e = paired([x["env"] for x in g], [x["env"] for x in r], "env")
        c = paired([x["coop"] for x in g], [x["coop"] for x in r], "coop")
        out["greedy_vs_random"][pct] = dict(env=e, coop=c)
        print(f"  {pct:<6} env  Δ={e['delta']:+8.4f}  t={e['t']:+8.3f}  p={e['p']:.3e}  d={e['d_cohen']:+6.3f}")
        print(f"  {pct:<6} coop Δ={c['delta']:+8.4f}  t={c['t']:+8.3f}  p={c['p']:.3e}  d={c['d_cohen']:+6.3f}")
    return out


# ---------------- E14 ----------------
def run_e14():
    algs = ["iql", "qmix", "vdn", "mappo"]
    out = dict(bc_marl={}, pure_same_batch={}, files_found={})
    print("\n" + "=" * 88)
    print("E14 四算法对比（10 种子 × 3000 回合）")
    print("=" * 88)

    for tag, key in [("e14", "bc_marl"), ("e14pure", "pure_same_batch")]:
        print(f"\n--- {tag} ({key}) ---")
        found = 0
        print(f"{'alg':<8}{'n':>3}{'env_reward':>18}{'env_last50':>18}{'coop_rate':>16}")
        for a in algs:
            files = sorted(glob.glob(os.path.join(D, f"{tag}_{a}_seed*.json")))
            out["files_found"][f"{tag}_{a}"] = len(files)
            if not files:
                print(f"{a:<8}{0:>3}{'— 缺失 —':>18}")
                continue
            found += 1
            env, env50, coop = [], [], []
            for f in files:
                s = jload(f)["summary"]
                env.append(s["avg_env_reward"])
                env50.append(s["avg_env_reward_last_50"])
                coop.append(s["avg_cooperation_rate"])
            m, sd = mean_sd(env)
            m50, sd50 = mean_sd(env50)
            cm, cs = mean_sd(coop)
            out[key][a] = dict(n=len(files), env_reward=m, env_reward_sd=sd,
                               env_last50=m50, env_last50_sd=sd50,
                               coop_rate=cm, coop_rate_sd=cs)
            print(f"{a:<8}{len(files):>3}{m:>11.4f}±{sd:<6.4f}{m50:>11.4f}±{sd50:<6.4f}{cm:>9.4f}±{cs:<6.4f}")
        if not found:
            print("  ⚠️ 该臂结果文件本地完全缺失")

    # 同批配对（若两侧都有）
    if out["pure_same_batch"]:
        print("\n同批配对 Δ（bc − pure，末50 env_reward）：")
        out["delta_same_batch"] = {}
        for a in algs:
            if a not in out["bc_marl"] or a not in out["pure_same_batch"]:
                continue
            b = [jload(f)["summary"]["avg_env_reward_last_50"]
                 for f in sorted(glob.glob(os.path.join(D, f"e14_{a}_seed*.json")))]
            p = [jload(f)["summary"]["avg_env_reward_last_50"]
                 for f in sorted(glob.glob(os.path.join(D, f"e14pure_{a}_seed*.json")))]
            r = paired(b, p, "last50")
            out["delta_same_batch"][a] = r
            print(f"  {a:<6} Δ={r['delta']:+8.4f}  t={r['t']:+7.3f}  p={r['p']:.4f}  d={r['d_cohen']:+6.3f}")
    return out


if __name__ == "__main__":
    res = dict(e13=run_e13(), e14=run_e14())
    op = os.path.join(D, "verify_e13_e14.json")
    with open(op, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {op}")
