# -*- coding: utf-8 -*-
"""E38 分析 + E36∪E38 合并判定（预注册 docs/PREREG_e38_lambda_extend.md）
=====================================================================
输出：
  1. E38 单独（n=30，seeds 3031-3060）
  2. E36 单独（n=20，seeds 3001-3020）
  3. **合并（n=50，seeds 3001-3060）** ← 预注册判定标准的主依据
三段并列，不隐去任何一段。
"""
import json, glob
import numpy as np
from scipy import stats
from pathlib import Path

ROOT = Path("/home/user/marl-ecdsa-consensus-chain")
LAMBDAS = [0.1, 0.3, 0.5, 0.7]
FIELDS = [("avg_env_reward_last_50", "末50 env_reward"),
          ("avg_env_reward", "全程 env_reward"),
          ("avg_cooperation_rate", "合作率")]


def load(dirs, arm, lam_s, field):
    v = []
    for d in dirs:
        for p in sorted((ROOT / "results" / d).glob(f"e3*_w3x3_seed*_{arm}_lam{lam_s}.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            x = doc.get(field)
            if x is not None:
                v.append(float(x))
    return np.array(v)


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return None
    t = (a.mean() - b.mean()) / se
    df = (va / len(a) + vb / len(b)) ** 2 / (
        (va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1))
    p = float(2 * stats.t.sf(abs(t), df))
    d = (a.mean() - b.mean()) / np.sqrt((va + vb) / 2)
    return dict(n_a=len(a), n_b=len(b), mean_a=a.mean(), mean_b=b.mean(),
                p=p, d=d, diff=a.mean() - b.mean())


BONF = 0.05 / 12
out = {"experiment": "E38 扩种 + E36∪E38 合并", "by_lambda": {}}

for lam in LAMBDAS:
    lam_s = str(lam).replace(".", "p")
    out["by_lambda"][str(lam)] = {}
    for field, cname in FIELDS:
        a38 = load(["e38_lambda_extend"], "bc_marl", lam_s, field)
        b38 = load(["e38_lambda_extend"], "pure_marl", "0p1", field)
        a36 = load(["e36_lambda_3000ep"], "bc_marl", lam_s, field)
        b36 = load(["e36_lambda_3000ep"], "pure_marl", "0p1", field)
        aM = np.concatenate([a36, a38])
        bM = np.concatenate([b36, b38])
        out["by_lambda"][str(lam)][field] = {
            "E38_only": welch(a38, b38),
            "E36_only": welch(a36, b36),
            "MERGED_n50": welch(aM, bM),
        }

p = ROOT / "results" / "e38_merge_summary.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")

print("=" * 100)
print("  E38 扩种 + E36∪E38 合并（w3x3 / IQL / 3000ep）")
print("=" * 100)
print(f"{'λ':>5} {'口径':<16}{'段':>10}{'n':>7}{'bc':>10}{'pure':>10}{'差':>9}{'p':>11}{'d':>7}  显著性")
print("-" * 100)
for lam in LAMBDAS:
    for field, cname in FIELDS:
        for seg in ["E36_only", "E38_only", "MERGED_n50"]:
            st = out["by_lambda"][str(lam)][field][seg]
            if not st:
                continue
            sig = ("Bonf+BH" if st["p"] < BONF else ("BH only" if st["p"] < 0.05 else "ns"))
            lbl = {"E36_only": "E36(n=20)", "E38_only": "E38(n=30)",
                   "MERGED_n50": "合并(n=50)"}[seg]
            print(f"{lam:>5.1f} {cname:<16}{lbl:>10}{st['n_a']:>7}"
                  f"{st['mean_a']:>10.3f}{st['mean_b']:>10.3f}{st['diff']:>9.3f}"
                  f"{st['p']:>11.2e}{st['d']:>7.2f}  {sig}")
        print("-" * 100)
print(f"多重比较：12 检验/段 | Bonferroni α={BONF:.5f}")
print(f"\n✅ 已写出: {p}")
