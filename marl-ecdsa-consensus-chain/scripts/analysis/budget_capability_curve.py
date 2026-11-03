"""预算—能力曲线（budget–capability curve）—— 预注册 20261011 的前瞻分析部分。

依据《深入理解 AI Agent》ch7：短预算下的领先**不能外推**到长预算（RE-Bench：2h 预算
Agent 是人类 4 倍，8h 人类反超）。因此必须报告「能力随预算如何变化」，而不是只报终点。

方法：对同一批 3000-episode 轨迹做**预算截断**，计算各预算档位下的平均环境奖励，
逐档做配对检验（两臂同种子 ⇒ 配对设计）。不重新训练、不引入新随机性。

⚠️ 口径纪律：
- 预算轴各点**嵌套不独立**（B=500 是 B=1000 的子集），曲线用于观察趋势，
  不用于「某档显著/某档不显著」式的逐点显著性宣称。
- 截断 ≠ 重新训练：不替代 E8 规划中的真实 500/1000 档实验。
- 不改写 number_registry.json 的任何数字。

用法：
    python scripts/analysis/budget_capability_curve.py
输出：
    results/eval_methodology/budget_capability_curve.json
    results/eval_methodology/budget_capability_curve.png
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
OUT_JSON = OUT_DIR / "budget_capability_curve.json"
OUT_PNG = OUT_DIR / "budget_capability_curve.png"

DATA_DIR = RES / "convergence_3000"
BUDGETS = [100, 250, 500, 1000, 1500, 2000, 2500, 3000]
WINDOW = 100          # 滑动窗口宽度（达成时间分析）
BOOT = 20_000
SEED_RNG = 20261011   # 与预注册一致

SEED_RE = re.compile(r"seed(\d+)")
DATA_FINGERPRINT = "ca022afec14274ed5f8ac785910bbcd44dd206e6c6b4a694498a1408defb9e3e"


def load_series(pattern_dir: Path, arm: str) -> dict[int, np.ndarray]:
    """返回 {seed: env_rewards 数组}。"""
    out: dict[int, np.ndarray] = {}
    for path in sorted(glob(str(pattern_dir / f"{arm}_marl_seed*.json"))):
        m = SEED_RE.search(os.path.basename(path))
        if not m:
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        series = np.asarray(data["env_rewards"], dtype=float)
        out[int(m.group(1))] = series
    return out


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [float(max(0.0, centre - half)), float(min(1.0, centre + half))]


def paired_stats(a: np.ndarray, b: np.ndarray, rng: np.random.Generator) -> dict:
    """预注册 §3 的全套配对检验，不挑选、不切换。"""
    diff = a - b
    n = len(diff)
    tt, pt = stats.ttest_rel(a, b)
    try:
        _, wp = stats.wilcoxon(a, b, zero_method="zsplit")
    except ValueError:
        wp = float("nan")
    wins = int((diff > 0).sum())
    sign_p = float(stats.binomtest(wins, n, 0.5, alternative="two-sided").pvalue)
    idx = rng.integers(0, n, size=(BOOT, n))
    boot = diff[idx].mean(axis=1)
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    dz = float(diff.mean() / diff.std(ddof=1)) if diff.std(ddof=1) > 0 else float("nan")
    return {
        "n_pairs": n,
        "bc_mean": float(a.mean()),
        "pure_mean": float(b.mean()),
        "mean_diff": float(diff.mean()),
        "pct_diff": float(diff.mean() / abs(b.mean()) * 100) if b.mean() != 0 else float("nan"),
        "paired_t": float(tt),
        "paired_p": float(pt),
        "wilcoxon_p": float(wp),
        "sign_test_wins": wins,
        "sign_test_p": sign_p,
        "win_rate": wins / n,
        "win_rate_wilson_ci95": wilson_ci(wins, n),
        "cohens_dz": dz,
        "bootstrap_ci95": ci,
        # 预注册 §3.5 判定规则
        "verdict": _verdict(pt, wp, sign_p, ci, wins, n),
    }


def _verdict(p_t: float, p_w: float, p_s: float, ci: list[float], wins: int, n: int) -> str:
    alpha = 0.05
    main_sig = p_t < alpha
    ci_ok = ci[0] > 0 or ci[1] < 0
    robust = sum([p_w < alpha, p_s < alpha, ci_ok])
    if main_sig and robust >= 2:
        return "SUPPORTED"
    if main_sig:
        return "DIRECTIONAL_ONLY"
    return "NOT_SIGNIFICANT"


def time_to_threshold(series: np.ndarray, threshold: float, window: int = WINDOW) -> int:
    """首次达到阈值所需的 episode 数（滑动窗口均值）；未达到返回 len(series)（右删失）。"""
    if len(series) < window:
        return len(series)
    csum = np.cumsum(np.concatenate([[0.0], series]))
    mov = (csum[window:] - csum[:-window]) / window
    hit = np.nonzero(mov >= threshold)[0]
    if hit.size == 0:
        return len(series)
    return int(hit[0] + window)


def plot(budgets, bc_means, pure_means, diffs, cis, out_png: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # 降级：无绘图库不影响数字产出
        print(f"[warn] 跳过绘图（{exc}）")
        return False

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    ax1.plot(budgets, bc_means, "o-", color="#c0392b", label="BC 激励")
    ax1.plot(budgets, pure_means, "s-", color="#2471a3", label="PURE 基线")
    ax1.set_xlabel("训练预算（episode）")
    ax1.set_ylabel("平均环境奖励（越大越好）")
    ax1.set_title("能力—预算曲线（71 对种子均值）")
    ax1.legend()
    ax1.grid(alpha=0.3)

    lo = [c[0] for c in cis]
    hi = [c[1] for c in cis]
    ax2.plot(budgets, diffs, "o-", color="#6c3483", label="BC − PURE 均值差")
    ax2.fill_between(budgets, lo, hi, color="#6c3483", alpha=0.18, label="配对 bootstrap 95%CI")
    ax2.axhline(0, color="#555", ls="--", lw=1)
    ax2.set_xlabel("训练预算（episode）")
    ax2.set_ylabel("配对差值")
    ax2.set_title("优势随预算的演化（CI 含 0 则不显著）")
    ax2.legend()
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return True


def main() -> None:
    rng = np.random.default_rng(SEED_RNG)
    bc = load_series(DATA_DIR, "bc")
    pure = load_series(DATA_DIR, "pure")
    seeds = sorted(set(bc) & set(pure))
    if not seeds:
        raise SystemExit("未找到配对种子，检查数据目录")

    lengths = {len(bc[s]) for s in seeds} | {len(pure[s]) for s in seeds}
    print(f"配对种子数: {len(seeds)} | 序列长度集合: {sorted(lengths)}")

    per_budget = {}
    bc_means, pure_means, diffs, cis = [], [], [], []
    for B in BUDGETS:
        a = np.array([bc[s][:B].mean() for s in seeds])
        b = np.array([pure[s][:B].mean() for s in seeds])
        st = paired_stats(a, b, rng)
        per_budget[str(B)] = st
        bc_means.append(st["bc_mean"])
        pure_means.append(st["pure_mean"])
        diffs.append(st["mean_diff"])
        cis.append(st["bootstrap_ci95"])
        print(
            f"B={B:>4}  BC={st['bc_mean']:+8.3f}  PURE={st['pure_mean']:+8.3f}  "
            f"Δ={st['mean_diff']:+7.3f} ({st['pct_diff']:+6.2f}%)  "
            f"p_t={st['paired_p']:.3g}  胜率={st['sign_test_wins']}/{st['n_pairs']}  "
            f"CI[{st['bootstrap_ci95'][0]:+.3f},{st['bootstrap_ci95'][1]:+.3f}]  {st['verdict']}"
        )

    # 达成效率分析：目标阈值 = PURE 在满预算下的平均能力
    full = str(BUDGETS[-1])
    T = float(per_budget[full]["pure_mean"])
    t_bc = np.array([time_to_threshold(bc[s], T) for s in seeds], dtype=float)
    t_pure = np.array([time_to_threshold(pure[s], T) for s in seeds], dtype=float)
    cens_bc = int((t_bc >= BUDGETS[-1]).sum())
    cens_pure = int((t_pure >= BUDGETS[-1]).sum())
    try:
        _, tt_p = stats.wilcoxon(t_pure, t_bc, zero_method="zsplit")  # 方向：pure 更慢
    except ValueError:
        tt_p = float("nan")
    speedup = float(np.median(t_pure) / np.median(t_bc)) if np.median(t_bc) > 0 else float("nan")

    efficiency = {
        "target_threshold_T": T,
        "threshold_definition": "PURE 在 B=3000 的平均能力（mean over seeds of mean(env_rewards[:3000])）",
        "window": WINDOW,
        "bc_episodes_median": float(np.median(t_bc)),
        "bc_episodes_iqr": [float(np.percentile(t_bc, 25)), float(np.percentile(t_bc, 75))],
        "pure_episodes_median": float(np.median(t_pure)),
        "pure_episodes_iqr": [float(np.percentile(t_pure, 25)), float(np.percentile(t_pure, 75))],
        "bc_censored_seeds": cens_bc,
        "pure_censored_seeds": cens_pure,
        "censoring_note": "未达阈值记为 3000（右删失），仍纳入秩检验",
        "wilcoxon_p_pure_slower": float(tt_p),
        "median_speedup_pure_over_bc": speedup,
    }
    print(
        f"\n达成效率（目标 T={T:.3f}, 窗口={WINDOW}）：\n"
        f"  BC   中位数 {np.median(t_bc):.0f} ep (IQR {np.percentile(t_bc,25):.0f}~{np.percentile(t_bc,75):.0f})，删失 {cens_bc}/{len(seeds)}\n"
        f"  PURE 中位数 {np.median(t_pure):.0f} ep (IQR {np.percentile(t_pure,25):.0f}~{np.percentile(t_pure,75):.0f})，删失 {cens_pure}/{len(seeds)}\n"
        f"  中位加速比 PURE/BC = {speedup:.2f}×，Wilcoxon p = {tt_p:.3g}"
    )

    plotted = plot(BUDGETS, bc_means, pure_means, diffs, cis, OUT_PNG)

    report = {
        "purpose": "预算—能力曲线（预注册 20261011 前瞻部分）",
        "methodology_source": "《深入理解 AI Agent》ch7 评估方法学：预算—能力曲线，短预算领先不可外推",
        "data_root": str(DATA_DIR.relative_to(ROOT)),
        "data_fingerprint_sha256": DATA_FINGERPRINT,
        "n_pairs": len(seeds),
        "budgets": BUDGETS,
        "capability_definition": "mean(env_rewards[0:B])，同一批 3000-episode 轨迹的截断重算，不重新训练",
        "caveat": "预算轴各点嵌套不独立；截断分析不替代真实 500/1000 档实验（E8）",
        "per_budget": per_budget,
        "efficiency": efficiency,
        "plot_path": str(OUT_PNG.relative_to(ROOT)) if plotted else None,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入: {OUT_JSON}" + (f"\n已写入: {OUT_PNG}" if plotted else ""))


if __name__ == "__main__":
    main()
