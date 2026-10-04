#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 E13-B 重跑结果（两臂 × 10 种子 × 6 配置）。

对比三层：
  legacy   = 旧代码（合作率=标签计数器，greedy_step=0.5）   → results/dispatch_20260921/derived/
  step050  = 新合作率口径 + greedy_step 0.5（隔离"口径修复"）
  step005  = 新合作率口径 + greedy_step 0.05（隔离"步长修复"）
"""
import json, os, glob
import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.normpath(os.path.join(HERE, "..", "results", "dispatch_20260921"))

RATIOS = ["0pct", "20pct", "50pct"]
MODES = ["greedy", "random"]


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def ms(xs):
    a = np.asarray(xs, float)
    return a.mean(), (a.std(ddof=1) if len(a) > 1 else 0.0)


def paired(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = a - b
    if len(d) < 2 or np.allclose(d, d[0]):
        return float(d.mean()), float("nan"), float("nan"), float("nan")
    t, p = stats.ttest_rel(a, b)
    sd = d.std(ddof=1)
    return float(d.mean()), float(t), float(p), float(d.mean() / sd) if sd else float("nan")


def load_arm(arm):
    """返回 {label: {seed: {'env','coop','betray'}}}"""
    out = {}
    for f in sorted(glob.glob(os.path.join(D, f"e13b_{arm}_seed*.json"))):
        d = jload(f)
        seed = int(os.path.basename(f).split("_seed")[1].split(".")[0])
        res = d["experiments"][0]["results"]
        for label, v in res.items():
            if label == "comparison":
                continue
            out.setdefault(label, {})[seed] = {
                "env": v["avg_env_reward"],
                "coop": v["avg_cooperation_rate"],
                "betray": v["avg_betrayal_rate"],
            }
    return out


def load_legacy():
    out = {}
    for f in sorted(glob.glob(os.path.join(D, "derived", "e13_selfish_*_seed*.json"))):
        d = jload(f)
        base = os.path.basename(f)[len("e13_selfish_"):-len(".json")]
        label = "selfish_" + base.rsplit("_seed", 1)[0]
        seed = int(base.rsplit("_seed", 1)[1])
        out.setdefault(label, {})[seed] = {
            "env": d["avg_env_reward"],
            "coop": d["avg_cooperation_rate"],
            "betray": d["avg_betrayal_rate"],
        }
    return out


def show(arm_name, data, metrics=("env", "coop", "betray")):
    print(f"\n{'='*96}\n{arm_name}\n{'='*96}")
    print(f"{'config':<22}{'n':>3}{'env_reward':>18}{'coop_rate':>18}{'betray_rate':>12}")
    for r in RATIOS:
        for m in MODES:
            lab = f"selfish_{r}_{m}"
            if lab not in data:
                continue
            recs = [data[lab][s] for s in sorted(data[lab])]
            e, es = ms([x["env"] for x in recs])
            c, cs = ms([x["coop"] for x in recs])
            b, _ = ms([x["betray"] for x in recs])
            print(f"{lab:<22}{len(recs):>3}{e:>11.4f}±{es:<6.4f}{c:>11.4f}±{cs:<6.4f}{b:>12.4f}")
    print("\n配对比较 greedy − random（同种子）：")
    for r in RATIOS:
        g = data.get(f"selfish_{r}_greedy")
        rr = data.get(f"selfish_{r}_random")
        if not g or not rr:
            continue
        seeds = sorted(set(g) & set(rr))
        for key, name in [("env", "env "), ("coop", "coop")]:
            dlt, t, p, dz = paired([g[s][key] for s in seeds], [rr[s][key] for s in seeds])
            flag = "显著" if p == p and p < 0.05 else "不显著"
            print(f"  {r:<6} {name} Δ={dlt:+8.4f}  t={t:+8.3f}  p={p:.3e}  d={dz:+7.3f}  [{flag}]")


if __name__ == "__main__":
    legacy = load_legacy()
    a050 = load_arm("step050")
    a005 = load_arm("step005")

    show("【legacy】旧代码：合作率=标签计数器，greedy_step=0.5", legacy)
    show("【step050】新合作率口径 + greedy_step=0.5（隔离『口径修复』）", a050)
    show("【step005】新合作率口径 + greedy_step=0.05（隔离『步长修复』）", a005)

    print(f"\n{'='*96}\n三臂对比：合作率（greedy − random）\n{'='*96}")
    print(f"{'比例':<8}{'legacy':>16}{'step050':>16}{'step005':>16}   （数值为配对差 Δcoop）")
    for r in RATIOS:
        row = []
        for data in (legacy, a050, a005):
            g, rr = data.get(f"selfish_{r}_greedy"), data.get(f"selfish_{r}_random")
            if not g or not rr:
                row.append("—")
                continue
            seeds = sorted(set(g) & set(rr))
            dlt, _, p, _ = paired([g[s]["coop"] for s in seeds], [rr[s]["coop"] for s in seeds])
            row.append(f"{dlt:+.4f}{'*' if p == p and p < 0.05 else ' '}")
        print(f"{r:<8}{row[0]:>16}{row[1]:>16}{row[2]:>16}")

    print(f"\n{'='*96}\n三臂对比：合作率绝对值（greedy 侧）\n{'='*96}")
    print(f"{'比例':<8}{'legacy':>18}{'step050':>18}{'step005':>18}")
    for r in RATIOS:
        cells = []
        for data in (legacy, a050, a005):
            g = data.get(f"selfish_{r}_greedy")
            if not g:
                cells.append("—")
                continue
            m, s = ms([g[k]["coop"] for k in sorted(g)])
            cells.append(f"{m:.4f}±{s:.4f}")
        print(f"{r:<8}{cells[0]:>18}{cells[1]:>18}{cells[2]:>18}")
