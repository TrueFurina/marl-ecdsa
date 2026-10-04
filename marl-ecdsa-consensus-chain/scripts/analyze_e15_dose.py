#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E15：自私对照的**训练预算剂量-响应**分析。

按 `deliverables/E15_预注册_训练预算剂量响应_2026-09-23.md` 的判定规则执行，
**不临时改判据**。

预算三档：
  500  ← E13-B step005 臂（已有，greedy_step=0.05，behavioral 合作率口径）
  1000 ← e15_b1000_seed*
  3000 ← e15_b3000_seed*

判据：Δ(50%) = env_reward(greedy) − env_reward(random)
  - 严格单调递减 且 Δ(3000)/Δ(500) < 0.5        → H_A 强支持（免费先验）
  - 单调递减 且 0.5 ≤ 比值 < 0.9                 → H_A 弱支持
  - 比值 ∈ [0.9, 1.1]                            → H_B 支持（自私无害）
  - Δ(3000) 翻负且显著                            → 超预期：贪心真有害
"""
import json, os, glob
import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.normpath(os.path.join(HERE, "..", "results", "dispatch_20260921"))
DERIVED = os.path.join(D, "derived")

RATIOS = ["0pct", "20pct", "50pct"]


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


def pfmt(p):
    if p is None or p != p:
        return "n/a"
    if p == 0 or p < 1e-12:
        return "p<1e-12"
    return f"p={p:.3g}"


def load_e15(budget):
    out = {}
    for f in sorted(glob.glob(os.path.join(D, f"e15_b{budget}_seed*.json"))):
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


def load_e13b_step005():
    """E13-B step005 臂（500 回合，greedy_step=0.05，behavioral 口径）"""
    out = {}
    for f in sorted(glob.glob(os.path.join(DERIVED, "e13b_step005_*_seed*.json"))):
        d = jload(f)
        label = d["config"]
        out.setdefault(label, {})[d["seed"]] = {
            "env": d["avg_env_reward"],
            "coop": d["avg_cooperation_rate"],
            "betray": d["avg_betrayal_rate"],
        }
    return out


def main():
    arms = {500: load_e13b_step005(), 1000: load_e15(1000), 3000: load_e15(3000)}

    print("=" * 100)
    print("E15 训练预算剂量-响应（n=10 同种子配对，greedy_step=0.05，behavioral 合作率口径）")
    print("=" * 100)

    for b in (500, 1000, 3000):
        a = arms[b]
        print(f"\n--- 预算 {b} 回合 ---")
        print(f"{'config':<24}{'n':>3}{'env_reward':>18}{'coop_rate':>18}{'betray':>10}")
        for r in RATIOS:
            for m in ("random", "greedy"):
                lab = f"selfish_{r}_{m}"
                if lab not in a:
                    continue
                recs = [a[lab][s] for s in sorted(a[lab])]
                e, es = ms([x["env"] for x in recs])
                c, cs = ms([x["coop"] for x in recs])
                bt, _ = ms([x["betray"] for x in recs])
                print(f"{lab:<24}{len(recs):>3}{e:>11.4f}±{es:<6.4f}{c:>11.4f}±{cs:<6.4f}{bt:>10.4f}")

    # ── 核心：Δ 随预算的变化 ──
    print("\n" + "=" * 100)
    print("核心判据：Δ(greedy − random) 随训练预算的变化（50% 自私档，效应最大）")
    print("=" * 100)
    print(f"{'预算':>6}{'Δ env_reward':>16}{'配对 p':>14}{'d':>8}{'  ':2}{'Δ 合作率':>14}{'配对 p':>14}")

    delta_env, delta_coop = {}, {}
    for b in (500, 1000, 3000):
        a = arms[b]
        g = a.get("selfish_50pct_greedy")
        r = a.get("selfish_50pct_random")
        if not g or not r:
            continue
        seeds = sorted(set(g) & set(r))
        de, te, pe, dz_e = paired([g[s]["env"] for s in seeds], [r[s]["env"] for s in seeds])
        dc, tc, pc, dz_c = paired([g[s]["coop"] for s in seeds], [r[s]["coop"] for s in seeds])
        delta_env[b] = de
        delta_coop[b] = dc
        print(f"{b:>6}{de:>+16.4f}{pfmt(pe):>14}{dz_e:>+8.2f}{'':2}{dc:>+14.4f}{pfmt(pc):>14}")

    # ── 0% 阴性对照（每档）──
    print("\n阴性对照（0% 自私，greedy vs random 配置应无差异）：")
    for b in (500, 1000, 3000):
        a = arms[b]
        g = a.get("selfish_0pct_greedy")
        r = a.get("selfish_0pct_random")
        if not g or not r:
            continue
        seeds = sorted(set(g) & set(r))
        de, _, pe, _ = paired([g[s]["env"] for s in seeds], [r[s]["env"] for s in seeds])
        dc, _, pc, _ = paired([g[s]["coop"] for s in seeds], [r[s]["coop"] for s in seeds])
        ok = "✅" if (pe == pe and pe > 0.05) else "⚠️ 显著（异常）"
        print(f"  预算 {b:>5}: Δenv={de:+8.4f} {pfmt(pe):>12} | Δcoop={dc:+7.4f} {pfmt(pc):>12}  {ok}")

    # ── 判定 ──
    print("\n" + "=" * 100)
    print("按预注册判定规则执行")
    print("=" * 100)
    if len(delta_env) < 3:
        print("⚠️ 数据不全，无法判定")
        return
    d500, d1000, d3000 = delta_env[500], delta_env[1000], delta_env[3000]
    mono = d500 > d1000 > d3000
    ratio = d3000 / d500 if d500 else float("nan")
    print(f"  Δ(500)={d500:+.4f}  Δ(1000)={d1000:+.4f}  Δ(3000)={d3000:+.4f}")
    print(f"  严格单调递减? {'是' if mono else '否'}")
    print(f"  Δ(3000)/Δ(500) = {ratio:.4f}")
    print()
    if mono and ratio < 0.5:
        print("  → **H_A 强支持**：贪心优势随学习者收敛而大幅衰减，属『手编启发式 vs 未收敛学习者』")
        print("    论文写法：保留『策略质量差异』限定；不把『贪心不劣于噪声』当实质结论")
    elif mono and 0.5 <= ratio < 0.9:
        print("  → **H_A 弱支持**：单调递减但衰减幅度中等")
        print("    论文写法：保留限定，加一句『在收敛设定下差异收窄至 X%』")
    elif 0.9 <= ratio <= 1.1:
        print("  → **H_B 支持**：三档持平，与训练预算无关")
        print("    论文写法：可将『策略性背叛不比噪声背叛更有害』作实质发现，但须三档证据同报")
    elif d3000 < 0:
        print("  → **超预期：Δ(3000) 翻负** —— 收敛设定下贪心真有害")
        print("    论文写法：与 E13-B(500) 结论相反，必须双报，明确『结论依赖训练预算』")
    else:
        print("  → 未落入任何预注册档位，需人工研判（不得临时改判据）")

    out = {
        "delta_env_by_budget": {str(k): v for k, v in delta_env.items()},
        "delta_coop_by_budget": {str(k): v for k, v in delta_coop.items()},
        "monotone_decreasing": bool(mono),
        "ratio_3000_over_500": ratio,
    }
    op = os.path.join(D, "e15_dose_response.json")
    with open(op, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {op}")


if __name__ == "__main__":
    main()
