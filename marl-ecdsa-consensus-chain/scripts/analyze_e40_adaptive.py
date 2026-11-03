"""E40 分析：λ 在线自适应深度对照（预注册判定，Bonferroni α/4）

四主判定（全程 env_reward 主口径 + 三口径并列）:
  H1: C(adaptive β=5) vs A(static 0.1)   —— 灵敏自适应 vs 真静态 ★核心
  H2: B(adaptive 默认) vs A               —— 默认自适应 vs 真静态
  H3: C vs F / B vs F                     —— 主效应复现（跨种子区间）
  H4: E(static 0.15) vs A                 —— 静态上界参照

诚实条款：λ 轨迹汇总（B/C 臂稳态）；C 若显著须剥离"等效 λ 水平"混杂（vs E）。
"""
import glob
import json
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
LOC = ROOT / "results" / "e40_adaptive_lambda"
BONF = 0.05 / 4

ARMS = {
    "A": "A_static01", "B": "B_adaptDef", "C": "C_adaptB5",
    "E": "E_static015", "F": "F_pure",
}
FIELDS = [("avg_env_reward", "全程"), ("avg_env_reward_last_50", "末50"),
          ("avg_cooperation_rate", "合作率")]


def load(arm: str, field: str):
    vals = []
    for p in sorted(glob.glob(str(LOC / f"e40_{ARMS[arm]}_seed*.json"))):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if d.get(field) is not None:
            vals.append(float(d[field]))
    return np.array(vals)


def welch(a, b):
    na, nb = len(a), len(b)
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = np.sqrt(va / na + vb / nb)
    t = (a.mean() - b.mean()) / se
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    p = 2 * stats.t.sf(abs(t), df)
    d = (a.mean() - b.mean()) / np.sqrt((va + vb) / 2)
    return p, d


def main():
    # ── 数据完整性 ──
    print("=" * 84)
    print("  E40 λ 在线自适应深度对照 — 预注册分析（Bonferroni α/4=0.0125）")
    print("=" * 84)
    for k, tag in ARMS.items():
        n = len(glob.glob(str(LOC / f"e40_{tag}_seed*.json")))
        print(f"  臂{k}({tag}): {n}/20 场")
    print()

    # ── 基础统计 + λ 轨迹 ──
    print("=== 各臂三口径均值 ± sd ===")
    data = {}
    for k in ARMS:
        data[k] = {}
        for f, cn in FIELDS:
            v = load(k, f)
            data[k][f] = v
            if len(v):
                print(f"  {k} {cn}: {v.mean():.4f} ± {v.std(ddof=1):.4f} (n={len(v)})")
    print()
    print("=== λ 轨迹（自适应臂） ===")
    for k in ("B", "C"):
        mus, fis, los, his = [], [], [], []
        for p in sorted(glob.glob(str(LOC / f"e40_{ARMS[k]}_seed*.json"))):
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            if d.get("lambda_mean") is not None:
                mus.append(d["lambda_mean"]); fis.append(d["lambda_final"])
                los.append(d["lambda_min"]); his.append(d["lambda_max"])
        if mus:
            print(f"  {k}: λ_mean={np.mean(mus):.5f}±{np.std(mus):.5f} "
                  f"λ_final={np.mean(fis):.5f} range=[{min(los):.4f},{max(his):.4f}] (n={len(mus)})")
    print()

    # ── 预注册判定 ──
    print("=== 预注册主判定（全程 env_reward）===")
    verdicts = []
    pairs = [("H1", "C", "A", "灵敏自适应 vs 真静态 ★核心"),
             ("H2", "B", "A", "默认自适应 vs 真静态"),
             ("H3a", "C", "F", "主效应复现(β=5)"),
             ("H3b", "B", "F", "主效应复现(默认)"),
             ("H4", "E", "A", "静态上界参照")]
    for hid, a, b, desc in pairs:
        va, vb = data[a]["avg_env_reward"], data[b]["avg_env_reward"]
        if len(va) < 5 or len(vb) < 5:
            print(f"  {hid} {a} vs {b} ({desc}): 数据不足")
            continue
        p, d = welch(va, vb)
        sig = "✅ 显著" if p < BONF else "❌ 不显著"
        imp = (va.mean() - vb.mean()) / abs(vb.mean()) * 100
        verdicts.append((hid, p))
        print(f"  {hid} {a} vs {b} ({desc}): "
              f"Δ={va.mean()-vb.mean():+.4f} ({imp:+.2f}%) p={p:.3g} d={d:.3f} {sig}")
    print()

    # ── 三口径并列 ──
    print("=== 三口径并列（A/B/C/E vs F + A）===")
    for k in ("A", "B", "C", "E"):
        row = []
        for f, cn in FIELDS:
            p, d = welch(data[k][f], data["F"][f])
            row.append(f"{cn} p={p:.2e}")
        p_static, _ = welch(data[k]["avg_env_reward"], data["A"]["avg_env_reward"])
        print(f"  {k} vs F: {' | '.join(row)}   vs A(全程): p={p_static:.3g}")
    print()

    # ── 预注册结论 ──
    pd = dict((h, p) for h, p in verdicts)
    print("=== 预注册结论 ===")
    h1 = pd.get("H1", 1); h2 = pd.get("H2", 1)
    if h1 < BONF:
        print("  H1 显著 → C(β=5) 优于真静态；⚠️ 须核对 C 臂 λ 稳态与 E(static 0.15) 剥离等效 λ 混杂")
    elif h2 < BONF:
        print("  H2 显著而 H1 不显著 → 异常（β 更灵敏反而更弱），须核查")
    else:
        print("  H1/H2 均不显著 → 默认与 β=5 配置下自适应与真静态统计等价")
        print("    （稳态偏移 −2.5% 不足以产生可测差异）——有效结论，支撑 E35-E38 稳健性")
    # 汇总文件
    out = {"bonferroni_alpha": BONF, "verdicts": {h: {"p": p} for h, p in verdicts}}
    for k in ARMS:
        out[k] = {f: {"mean": float(data[k][f].mean()), "sd": float(data[k][f].std(ddof=1)),
                      "n": len(data[k][f])} for f, _ in FIELDS if len(data[k][f])}
    fp = ROOT / "results" / "e40_adaptive_lambda_summary.json"
    fp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  汇总已写: {fp.name}")


if __name__ == "__main__":
    main()
