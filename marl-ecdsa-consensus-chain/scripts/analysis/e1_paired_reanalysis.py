"""E1（BC 激励 vs PURE）配对重分析 —— **补充分析，不替代登记簿 NR-1 / NR-2**。

背景与动机（来自《深入理解 AI Agent》ch7 评估方法学）：
- 两臂使用**同一批随机种子** ⇒ 这是配对设计，而非独立两样本。
- 配对比较（paired t / Wilcoxon 符号秩 / 符号检验 / 配对 bootstrap）比独立两样本 Welch
  检验利用了「同种子下的共同噪声」，检验力更高、结论更稳。
- 本脚本先**复现登记簿的 Welch 数字**做数据对齐校验（能对上才说明读对了数据），
  再给出配对口径的结果，供答辩与文档补充使用。

口径纪律（项目红线）：
- 不得据此改写 NR-1 / NR-2，也不得单点宣称「证明激励有效」。
- 所有输出为**补充证据**，须与两样本口径同报。

用法：
    python scripts/analysis/e1_paired_reanalysis.py
输出：
    results/eval_methodology/e1_paired_reanalysis.json
"""

from __future__ import annotations

import json
import os
import re
from glob import glob
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results"
OUT_DIR = RES / "eval_methodology"
OUT_FILE = OUT_DIR / "e1_paired_reanalysis.json"

FIELDS = {
    "NR-1_last50_env_reward": "summary.avg_env_reward_last_50",
    "NR-2_full_env_reward": "summary.avg_env_reward",
    "NR-3_cooperation_rate": "summary.avg_cooperation_rate",
}

# 登记簿口径（用于校验数据读取是否正确）
REGISTRY_REFERENCE = {
    "NR-1_last50_env_reward": {"pct_diff": 28.17, "p": 0.009524, "d": 0.4412},
    "NR-2_full_env_reward": {"pct_diff": 7.92, "p": 1e-10, "d": 1.1962},
}

SEED_RE = re.compile(r"seed(\d+)")


def load_arm(pattern: str, field_path: str):
    """返回 {seed: value}，按文件名中的 seed 匹配。"""
    out = {}
    for path in glob(str(RES / pattern)):
        m = SEED_RE.search(os.path.basename(path))
        if not m:
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cur = data
        for key in field_path.split("."):
            cur = cur[key]
        out[int(m.group(1))] = float(cur)
    return out


def welch(a: np.ndarray, b: np.ndarray):
    t, p = stats.ttest_ind(a, b, equal_var=False)
    n1, n2 = len(a), len(b)
    s1, s2 = a.var(ddof=1), b.var(ddof=1)
    pooled = np.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    d = (a.mean() - b.mean()) / pooled
    se = np.sqrt(s1 / n1 + s2 / n2)
    df = se**4 / ((s1 / n1) ** 2 / (n1 - 1) + (s2 / n2) ** 2 / (n2 - 1))
    tcrit = stats.t.ppf(0.975, df)
    diff = a.mean() - b.mean()
    return {
        "mean_a": float(a.mean()), "mean_b": float(b.mean()),
        "diff": float(diff),
        "pct_diff": float(diff / abs(b.mean()) * 100),
        "t": float(t), "p": float(p), "df": float(df),
        "cohens_d": float(d),
        "ci95": [float(diff - tcrit * se), float(diff + tcrit * se)],
    }


def paired_analysis(a: np.ndarray, b: np.ndarray, rng: np.random.Generator):
    diff = a - b
    n = len(diff)
    tt, pt = stats.ttest_rel(a, b)
    try:
        w_stat, w_p = stats.wilcoxon(a, b, zero_method="zsplit")
    except ValueError:
        w_stat, w_p = float("nan"), float("nan")
    # 符号检验：每对种子谁赢
    wins = int((diff > 0).sum())
    sign_p = float(stats.binomtest(wins, n, 0.5, alternative="two-sided").pvalue)
    # 配对 bootstrap
    idx = rng.integers(0, n, size=(20000, n))
    boot = diff[idx].mean(axis=1)
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    dz = float(diff.mean() / diff.std(ddof=1))
    # Wilson 比例置信区间（单臂胜率）
    lo, hi = wilson_ci(wins, n)
    return {
        "n_pairs": n,
        "mean_diff": float(diff.mean()),
        "pct_diff": float(diff.mean() / abs(b.mean()) * 100),
        "paired_t": float(tt), "paired_p": float(pt),
        "wilcoxon_stat": float(w_stat), "wilcoxon_p": float(w_p),
        "sign_test_wins": wins, "sign_test_p": sign_p,
        "win_rate": wins / n, "win_rate_wilson_ci95": [lo, hi],
        "cohens_dz": dz,
        "bootstrap_ci95": ci,
    }


def wilson_ci(k: int, n: int, z: float = 1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [float(max(0.0, centre - half)), float(min(1.0, centre + half))]


def pass_at_k(p: float, k: int) -> float:
    """k 次中至少 1 次通过（能力上限口径）。"""
    return 1.0 - (1.0 - p) ** k


def pass_consecutive_k(p: float, k: int) -> float:
    """k 次连续全部通过（可靠交付口径）。"""
    return p**k


def main():
    rng = np.random.default_rng(20261011)
    report = {
        "note": "补充分析：配对口径。不替代 number_registry.json 的 NR-1/NR-2（two_sample/Welch）。",
        "data_root": "results/convergence_3000/{bc,pure}_marl_seed*.json",
        "metrics": {},
    }
    for name, field in FIELDS.items():
        bc = load_arm("convergence_3000/bc_marl_seed*.json", field)
        pure = load_arm("convergence_3000/pure_marl_seed*.json", field)
        seeds = sorted(set(bc) & set(pure))
        if not seeds:
            print(f"[skip] {name}: 无配对种子")
            continue
        a = np.array([bc[s] for s in seeds])
        b = np.array([pure[s] for s in seeds])
        w = welch(a, b)
        pr = paired_analysis(a, b, rng)
        ref = REGISTRY_REFERENCE.get(name)
        check = {}
        if ref:
            check = {
                "pct_diff_matches": bool(abs(w["pct_diff"] - ref["pct_diff"]) < 0.5),
                "p_matches": bool(abs(w["p"] - ref["p"]) < max(1e-4, ref["p"] * 0.2)),
                "registry_pct_diff": ref["pct_diff"], "registry_p": ref["p"],
            }
        report["metrics"][name] = {
            "n_per_arm": len(seeds),
            "field": field,
            "two_sample_welch": w,
            "paired": pr,
            "registry_alignment_check": check,
        }
        print(f"\n=== {name} (n={len(seeds)}/组) ===")
        print(f"  两样本 Welch : Δ={w['diff']:+.4f} ({w['pct_diff']:+.2f}%)  p={w['p']:.3g}  d={w['cohens_d']:.3f}")
        if check:
            print(f"  对齐登记簿   : pct_diff {'✓' if check['pct_diff_matches'] else '✗'} / p {'✓' if check['p_matches'] else '✗'}"
                  f"  (登记簿 {ref['pct_diff']}% / p={ref['p']:.3g})")
        print(f"  配对 t 检验  : Δ={pr['mean_diff']:+.4f} ({pr['pct_diff']:+.2f}%)  p={pr['paired_p']:.3g}  d_z={pr['cohens_dz']:.3f}")
        print(f"  Wilcoxon     : p={pr['wilcoxon_p']:.3g}")
        print(f"  符号检验     : BC 胜出 {pr['sign_test_wins']}/{pr['n_pairs']} = {pr['win_rate']*100:.1f}%"
              f"  Wilson95%CI[{pr['win_rate_wilson_ci95'][0]*100:.1f}%, {pr['win_rate_wilson_ci95'][1]*100:.1f}%]  p={pr['sign_test_p']:.3g}")
        print(f"  配对 bootstrap 95%CI: [{pr['bootstrap_ci95'][0]:+.4f}, {pr['bootstrap_ci95'][1]:+.4f}]")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入: {OUT_FILE}")


if __name__ == "__main__":
    main()
