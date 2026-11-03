# -*- coding: utf-8 -*-
"""E36 分析：λ × 三口径敏感性汇总（@3000ep）
=================================
输入：results/e36_lambda_3000ep/e36_w3x3_seed*_{arm}_lam*.json
输出：results/e36_lambda_3000ep_summary.json + 控制台表

统计：对每个 λ 档，bc_marl vs pure_marl 的三口径 Welch t 检验
      （末50 env_reward / 全程 env_reward / 合作率）
多重比较：4 档 × 3 口径 = 12 个检验，报告 Bonferroni(α/12) 与 BH-FDR 两种校正
"""
import json, glob, os, sys, itertools
from pathlib import Path
import numpy as np

ROOT = Path("/home/user/marl-ecdsa-consensus-chain")
OUTDIR = ROOT / "results" / "e36_lambda_3000ep"
LAMBDAS = [0.1, 0.3, 0.5, 0.7]
FIELDS = [("avg_env_reward_last_50", "末50 env_reward"),
          ("avg_env_reward", "全程 env_reward"),
          ("avg_cooperation_rate", "合作率")]


def load(arm, lam, field):
    lam_s = str(lam).replace(".", "p")
    vals = []
    for p in sorted(OUTDIR.glob(f"e36_w3x3_seed*_{arm}_lam{lam_s}.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        # 兼容扁平结构与 summary 嵌套
        v = d.get(field)
        if v is None:
            v = (d.get("summary") or {}).get(field)
        if v is not None:
            vals.append(float(v))
    return np.array(vals)


def welch(a, b):
    """Welch t 检验 + Cohen's d + 95%CI（差）"""
    na, nb = len(a), len(b)
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(va / na + vb / nb)
    if se == 0:
        return dict(mean_a=ma, mean_b=mb, diff=ma - mb, p=1.0, d=0.0,
                    ci=[ma - mb, ma - mb], n_a=na, n_b=nb)
    t = (ma - mb) / se
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    # 双尾 p（t 分布）
    try:
        from scipy import stats
        p = 2 * stats.t.sf(abs(t), df)
        tcrit = stats.t.ppf(0.975, df)
    except Exception:
        # 正态近似兜底
        p = 2 * (1 - 0.5 * (1 + np.math.erf(abs(t) / np.sqrt(2))))
        tcrit = 1.96
    d = (ma - mb) / np.sqrt((va + vb) / 2)
    diff = ma - mb
    return dict(mean_a=round(float(ma), 4), mean_b=round(float(mb), 4),
                diff=round(float(diff), 4),
                p=float(p), d=round(float(d), 4),
                ci=[round(float(diff - tcrit * se), 4),
                    round(float(diff + tcrit * se), 4)],
                n_a=na, n_b=nb)


def main():
    # 完整性检查
    missing = []
    for lam in LAMBDAS:
        nb = len(load("bc_marl", lam, "avg_env_reward_last_50"))
        if nb < 20:
            missing.append(f"bc λ={lam}: 仅 {nb}/20")
    npu = len(load("pure_marl", 0.1, "avg_env_reward_last_50"))
    if npu < 20:
        missing.append(f"pure: 仅 {npu}/20")
    if missing:
        print("[INCOMPLETE]", missing)
        print("实验未跑完，暂不汇总")
        return 1

    res = {"experiment": "E36 λ×三口径敏感性",
           "design": "w3x3 / IQL / 3000ep / n=20 per λ per arm / seeds 3001-3020",
           "lambdas": LAMBDAS, "fields": {f: c for f, c in FIELDS},
           "by_lambda": {}, "prereg": "docs/PREREG_e36_lambda_3000ep.md"}

    all_p = []   # (lambda, field, p) 用于多重比较
    for lam in LAMBDAS:
        res["by_lambda"][str(lam)] = {}
        for field, cname in FIELDS:
            a = load("bc_marl", lam, field)
            b = load("pure_marl", 0.1, field)
            st = welch(a, b)
            # 提升百分比（对 env_reward 用 |pure| 归一；对合作率用绝对差）
            if "reward" in field:
                st["improve_pct"] = round(
                    (st["mean_a"] - st["mean_b"]) / abs(st["mean_b"]) * 100, 2)
            else:
                st["improve_pct"] = round(st["diff"] * 100, 2)
            res["by_lambda"][str(lam)][field] = st
            all_p.append((lam, field, st["p"]))

    # 多重比较校正
    m = len(all_p)
    ps_sorted = sorted(all_p, key=lambda x: x[2])
    bh_thr = [(i + 1) * 0.05 / m for i in range(m)]
    bh_pass = 0
    for i, (lam, field, p) in enumerate(ps_sorted):
        if p <= bh_thr[i]:
            bh_pass = i + 1
    res["multiple_comparison"] = {
        "n_tests": m,
        "bonferroni_alpha": round(0.05 / m, 5),
        "bh_fdr_significant_count": bh_pass,
        "bonferroni_significant_count": sum(
            1 for _, _, p in all_p if p < 0.05 / m),
        "note": "Bonferroni α/12≈0.0042（最严）；BH-FDR 为逐步校正",
    }

    out = ROOT / "results" / "e36_lambda_3000ep_summary.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    # 控制台表
    print("=" * 92)
    print("  E36 λ × 三口径敏感性 @3000ep（w3x3 / IQL / 3000ep / n=20 每档每组）")
    print("=" * 92)
    print(f"{'λ':>5} {'口径':<16}{'bc':>10}{'pure':>10}{'差':>9}{'p':>11}{'d':>7}{'提升%':>8}  显著性")
    print("-" * 92)
    for lam in LAMBDAS:
        for field, cname in FIELDS:
            st = res["by_lambda"][str(lam)][field]
            sig = ("Bonf+BH" if st["p"] < 0.05 / m else
                   ("BH only" if st["p"] < 0.05 else "ns"))
            print(f"{lam:>5.1f} {cname:<16}{st['mean_a']:>10.3f}{st['mean_b']:>10.3f}"
                  f"{st['diff']:>9.3f}{st['p']:>11.2e}{st['d']:>7.2f}"
                  f"{st['improve_pct']:>8.2f}  {sig}")
        print("-" * 92)
    mc = res["multiple_comparison"]
    print(f"多重比较：{mc['n_tests']} 个检验 | Bonferroni α={mc['bonferroni_alpha']} "
          f"过 {mc['bonferroni_significant_count']} | BH-FDR 过 {mc['bh_fdr_significant_count']}")
    print(f"\n✅ 已写出: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
