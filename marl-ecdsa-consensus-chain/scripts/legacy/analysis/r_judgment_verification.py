"""
E7 — R 判据边界验证（支撑 C3 改写：贡献度加权的容错增益条件）

背景
----
EXP-3（5 种子 × 2000 轮，**该口径已降级为溯源档、不作为权威依据**）证明：当贡献度权重为均匀（R=1）或真实 MARL
贡献度导出（R≈1.007）时，CW-PBFT 与标准 PBFT 完全等价——贡献度加权本身
不提供额外容错。（此处的 R=1 / R≈1.007 均为**权重带宽** w_max/w_min。）
路线 C PoC 进一步证明：引入参与率驱动的权重展宽把带宽推到 R_final≈15 后，
n=10/40% **省略故障**下成功率 0%→94.5%——该增益成立的前提是省略故障模型，
详见下方口径段与 note_on_scope 字段。

本脚本对权重制 CW-PBFT 的容错判据做**独立、可复跑的数值验证**。

【口径（2026-09-19 更正 —— 旧版在此处误诊，以此为准）】
旧版把 `b < n/(2R+1)` 与 `f_max = R/(R+2)` 描述为"R 取倒数定义时的**互易形式**"。
**这是误诊。** 真实关系是：**同一个权重带宽 R = w_max/w_min 之下的两个极端权重指派**：

    记 ρ = w̄_B / w̄_H（拜占庭/诚实**每节点平均权重比**），安全条件 β < 1/3 的
    一般式为      b < n / (2ρ + 1)                                        (1)
    因 ρ ∈ [1/R, R]，可容忍的拜占庭节点数不是单值，而是一个**区间**：
        最坏情形 n/(2R+1)   ≤   b_可容   <   最好情形 nR/(R+2)             (2)
      · 左端（ρ = R）：b 个拜占庭节点全占 w_max —— 对任意权重指派均成立的
        充分条件，**可保证**，本文以其为设计约束（n=3f+1 保 f 容错需 R < 1+1/(2f)）
      · 右端（ρ = 1/R）：拜占庭节点全落 w_min —— 仅是**存在性上界**，
        只在权重与故障身份呈理想负相关时可达，**不可作安全保障**

故本脚本中出现的 R 一律指 **R_eff = w̄_H/w̄_B = 1/ρ**（均匀时 R_eff = 1），
**不是**权重带宽 R_final = w_max/w_min。二者在展宽 PoC 中数值接近（13.3 vs 14.9）
纯属机制副产品，**不是同一个符号**。把 R_final 代入下式会得到**恒偏乐观**的 β
（低估坏节点权重占比），见 self_checks 中的"回归护栏"自检。

    诚实权重 ≥ 2/3 总权重  ⟺  拜占庭权重占比 β < 1/3
    β = f / ((1-f)·R_eff + f)                  （f = 拜占庭节点占比 = b/n）
    ⟹ 给定 R_eff 时最大可容忍拜占庭节点占比  f_max = R_eff / (R_eff + 2)

校验（R_eff 口径）：
    R_eff=1     → f_max = 1/3      ≈ 标准 PBFT（无增益）
    R_eff=1.007 → f_max ≈ 33.5%    ≈ n/3（无增益，数学必然）
    R_eff=15    → f_max ≈ 88.2%    ← **最好情形端**（ρ=1/15，坏节点全落 w_min）；
                                     PoC 实测诚实权重占比 95.7% 正落在此端。
                                     同一带宽 R=15 的最坏情形界仅 b < n/31 = 0.32（n=10），
                                     两端相差 27.2 倍。**本脚本的 5/5 PoC 配置实测
                                     均违反最坏界**（见 poc_reproduction.violates_worst_case）。

运行（本机 Py3.12，无需服务器，纯 math）：
    python scripts/legacy/analysis/r_judgment_verification.py
"""

import json
import math
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def byzantine_weight_fraction(f: float, R_eff: float) -> float:
    """给定拜占庭节点占比 f=b/n 与平均权重比 R_eff=w̄_H/w̄_B，返回拜占庭权重占比 β。

    注意传入的必须是 R_eff = w̄_H/w̄_B（= 1/ρ），**不是**权重带宽 w_max/w_min。
    """
    return f / ((1.0 - f) * R_eff + f)


def max_byzantine_fraction(R_eff: float) -> float:
    """给定 R_eff=w̄_H/w̄_B 时的最大可容忍拜占庭节点占比 f_max = R_eff/(R_eff+2)。

    这是式 (1) b < n/(2ρ+1) 在 ρ=1/R_eff 下的占比形式，对**给定的 R_eff** 是精确的。
    """
    return R_eff / (R_eff + 2)


def worst_case_max_nodes(n: int, R_band: float) -> float:
    """最坏情形可容忍拜占庭节点数上界 b < n/(2R+1)，R_band = w_max/w_min。

    对任意权重指派均成立的充分条件（可保证）。
    """
    return n / (2.0 * R_band + 1.0)


def best_case_max_nodes(n: int, R_band: float) -> float:
    """最好情形（存在性）上界 b < nR/(R+2)，R_band = w_max/w_min。

    仅当拜占庭节点全部落到 w_min 时可达，**不可作为安全保障**。
    """
    return n * R_band / (R_band + 2.0)


def cw_pbft_safe(n: int, b_nodes: int, R_eff: float) -> bool:
    """在给定 R_eff=w̄_H/w̄_B 的权重指派下，CW-PBFT 是否满足诚实权重 ≥ 2/3 总权重。"""
    h = n - b_nodes
    w_h, w_b = R_eff, 1.0  # 归一化：拜占庭每节点权重单位 1，诚实为 R_eff 倍
    total = h * w_h + b_nodes * w_b
    honest = h * w_h
    return honest >= (2.0 / 3.0) * total


def run() -> dict:
    R_scan = [1.0, 1.5, 3.0, 5.0, 8.0, 15.0]
    n_scan = [4, 7, 10, 16]

    # ── 1. R_eff 扫描：f_max vs R_eff（R_eff = w̄_H/w̄_B = 1/ρ） ──
    scan = []
    for R_eff in R_scan:
        fmax = max_byzantine_fraction(R_eff)
        scan.append({
            "R_eff": R_eff,
            "f_max": round(fmax, 4),
            "f_max_pct": round(fmax * 100, 2),
            "note": "≈ 标准 PBFT (n/3)" if abs(R_eff - 1.0) < 1e-6
                    else ("无增益（≈n/3）" if R_eff < 1.5
                          else "增益显著（但属最好情形端，不可作安全保障）"),
        })

    # ── 2. 复现路线 C PoC ──
    # 口径（2026-09-19 修正）：R_band = w_max/w_min = PoC 报告的 R_final；
    #   R_eff = w̄_H/w̄_B，取自《判据一致性核实 2026-09-19》表 A（独立反解值，保留 2 位小数）；
    #   beta_measured = 1 - honest_share，取自 weight_broadening_poc_report.json（5 种子均值）。
    #   两者**来源相互独立**，故下方"β 与实测一致"自检不是循环论证：任一处抄错都会放大偏差。
    # 旧版把 R_band 当作 R_eff 喂入 byzantine_weight_fraction()，得到恒偏乐观的 β
    #   （相对误差 −0.24%~−12.31%，5/5 全部低估坏节点权重占比）。
    poc = []
    for n, f_ratio, R_band, R_eff, beta_meas, cw_rate in [
        (10, 0.33, 14.9312, 13.32, 0.031180, 0.9859),
        (10, 0.40, 15.0000, 14.96, 0.042657, 0.9452),
        (16, 0.33, 15.0000, 13.48, 0.032617, 0.9866),
        (16, 0.40, 15.0000, 14.63, 0.039385, 0.9730),
        (4,  0.33, 14.2706, 12.47, 0.026029, 0.8945),
    ]:
        b_nodes = int(n * f_ratio)
        f = b_nodes / n
        beta = byzantine_weight_fraction(f, R_eff)
        w_ub = worst_case_max_nodes(n, R_band)
        b_ub = best_case_max_nodes(n, R_band)
        poc.append({
            "config": f"n={n}, byz={int(f_ratio*100)}%",
            "b_nodes": b_nodes,
            "R_band_wmax_wmin": R_band,
            "R_eff_wH_over_wB": round(R_eff, 4),
            "byzantine_weight_fraction": round(beta, 6),
            "beta_measured": round(beta_meas, 6),
            "beta_abs_err_pp": round(abs(beta - beta_meas) * 100, 4),
            "beta_below_1_3": beta < 1 / 3,
            "worst_case_bound_b": round(w_ub, 4),
            "best_case_bound_b": round(b_ub, 4),
            "violates_worst_case": bool(b_nodes > w_ub),
            "within_interval": bool(w_ub <= b_nodes < b_ub),
            "cw_pbft_safe": cw_pbft_safe(n, b_nodes, R_eff),
            "poc_cw_rate": cw_rate,
        })

    # ── 3. 复现 EXP-3 三权重来源（R≈1.007 → 无增益） ──
    exp3 = {
        "uniform_R1": {
            "R_eff": 1.0,
            "f_max_pct": round(max_byzantine_fraction(1.0) * 100, 2),
            "interpretation": "CW ≡ STD（与标准 PBFT 完全等价）",
        },
        "contribution_R1007": {
            "R_eff": 1.007,
            "f_max_pct": round(max_byzantine_fraction(1.007) * 100, 2),
            "interpretation": "CW ≡ STD（增益≈0，无增益是数学必然）",
        },
        "legacy_R8": {
            "R_eff": 8.0,
            "f_max_pct": round(max_byzantine_fraction(8.0) * 100, 2),
            "interpretation": ("R_eff=8 表示故障身份与低权重强负相关（接近最好情形端）。"
                               "若同一数值 8 是**带宽** w_max/w_min，则最坏情形界仅 "
                               "b < n/(2·8+1) = n/17（n=10 时为 0.588），与此处 nR/(R+2)=8.0 "
                               "相差 13.6 倍——两个口径不可混用"),
        },
    }

    # ── 4. 自检（断言已知值） ──
    checks = []
    def chk(name, cond, detail):
        checks.append({"name": name, "pass": bool(cond), "detail": detail})

    # β 容差（百分点）。取值 0.005 的依据：正确口径下 5 配置最大偏差 0.0011pp（仅来自
    # R_eff 的两位小数截断），留 4.5× 余量；而旧口径（把 R_band 当 R_eff）最小偏差
    # 0.0104pp，全部 5 配置越界。故该容差能**单值区分**新旧口径。
    TOL_PP = 0.005

    # ── 4a. 公式自洽（这些只验证代数，对 R 语义不敏感，不能单独作为口径正确的证据）──
    chk("R_eff=1 → f_max≈1/3", abs(max_byzantine_fraction(1.0) - 1/3) < 1e-9,
        f"f_max={max_byzantine_fraction(1.0):.6f}")
    chk("R_eff=1.007 → f_max≈33.5%≈n/3",
        abs(max_byzantine_fraction(1.007) - 1/3) < 0.01,
        f"f_max={max_byzantine_fraction(1.007)*100:.3f}%")
    chk("R_eff=15 → f_max=15/17≈88.2%（最好情形端）",
        abs(max_byzantine_fraction(15.0) - 15/17) < 1e-9,
        f"f_max={max_byzantine_fraction(15.0)*100:.3f}%")

    # ── 4b. 区分力自检（旧版 6 条自检全 PASS 是**空验证**：它们只检验了"最好情形下安全"，
    #        而最好情形本就安全。以下自检专为"能区分 R 语义对错"而设计）──
    # 反例：n=10 / R_band=15 / b=3，在最坏指派（ρ=R_band ⇒ R_eff=1/15）下必须判为**不安全**
    beta_worst = byzantine_weight_fraction(3 / 10, 1 / 15.0)
    chk("反例必被检出：n=10,R_band=15,b=3 在最坏指派(ρ=R)下不安全",
        (not cw_pbft_safe(10, 3, 1 / 15.0)) and beta_worst >= 1 / 3,
        f"β_worst={beta_worst*100:.2f}% ≥ 1/3，cw_pbft_safe=False")
    # 同一配置在**实测**指派（R_eff=13.3167）下安全 —— 两条并存即式 (2) 的区间
    chk("同一配置在实测指派(R_eff=13.32)下安全",
        cw_pbft_safe(10, 3, 13.32) and byzantine_weight_fraction(0.3, 13.32) < 1 / 3,
        f"β={byzantine_weight_fraction(0.3, 13.32)*100:.3f}% < 1/3")
    # 两界分离度：R_band=15 时最好界/最坏界 ≈ 27.35×。若有人把两界当成"同一 R 的两个定义"，
    # 该比值会塌缩为 1，此自检立即转红。
    sep = best_case_max_nodes(10, 15.0) / worst_case_max_nodes(10, 15.0)
    chk("两界分离度：R_band=15 时 best/worst ≈ 27.35×（捕捉 R 语义互换）",
        abs(sep - 15.0 * 31 / 17) < 0.01,
        f"ratio={sep:.2f}×（R=1 时应为 1.00×）")
    chk("R_band=1 时两界重合（退化到 PBFT 的 n/3）",
        abs(best_case_max_nodes(10, 1.0) - worst_case_max_nodes(10, 1.0)) < 1e-9,
        f"worst=best={worst_case_max_nodes(10, 1.0):.4f}")

    # ── 4c. 口径回归护栏：旧口径（把 R_band 当 R_eff）必须被识别为不一致 ──
    legacy_beta = byzantine_weight_fraction(0.3, 14.9312)
    chk("回归护栏：旧口径(把 R_band 当 R_eff)必须被识别为不一致",
        abs(legacy_beta - 0.031180) * 100 > TOL_PP,
        f"旧口径 β={legacy_beta*100:.3f}% vs 实测 3.118%，偏差 "
        f"{abs(legacy_beta-0.031180)*100:.3f}pp > 容差 {TOL_PP}pp（偏乐观）")

    # ── 4d. 与实测对照（5/5 配置）──
    chk(f"全部 5 配置 β 与实测一致（容差 {TOL_PP}pp）",
        all(p["beta_abs_err_pp"] <= TOL_PP for p in poc),
        "最大偏差 " + f"{max(p['beta_abs_err_pp'] for p in poc):.4f}pp")
    chk("全部 5 配置实测 β < 1/3（实际安全）",
        all(p["beta_below_1_3"] for p in poc),
        "β ∈ " + f"{min(p['byzantine_weight_fraction'] for p in poc)*100:.2f}%"
        f"~{max(p['byzantine_weight_fraction'] for p in poc)*100:.2f}%")
    chk("全部 5 配置**违反**最坏界（如实记录，不是失败）",
        all(p["violates_worst_case"] for p in poc),
        f"最坏界 ∈ {min(p['worst_case_bound_b'] for p in poc):.3f}"
        f"~{max(p['worst_case_bound_b'] for p in poc):.3f}；实际 b = "
        + ",".join(str(p["b_nodes"]) for p in poc))
    chk("全部 5 配置落在区间 [最坏界, 最好界) 内",
        all(p["within_interval"] for p in poc),
        "式 (2) 区间包含性成立")
    chk("EXP-3 n=10/40%/R_eff=1 → 不安全（CW=STD 失败）",
        not cw_pbft_safe(10, 4, 1.0), "b_nodes=4, R_eff=1")

    all_pass = all(c["pass"] for c in checks)

    report = {
        "title": "E7 — 权重制容错判据边界验证（一般式 + 最坏/最好情形区间）",
        "formula": ("一般式 b < n/(2ρ+1)，ρ = w̄_B/w̄_H；"
                    "区间 n/(2R+1) ≤ b_可容 < nR/(R+2)，R = w_max/w_min。"
                    "本脚本内 R_eff 恒指 w̄_H/w̄_B = 1/ρ"),
        "clarification": ("2026-09-19 更正：b < n/(2R+1) 与 f_max = R_eff/(R_eff+2) **不是**"
                         "同一个 R 的两种定义（旧版误诊为『R 取倒数时的互易形式』），而是"
                         "**同一个权重带宽 R = w_max/w_min 之下的两个极端权重指派**："
                         "前者为最坏情形（坏节点全占 w_max，对任意指派均成立，可保证），"
                         "后者为最好情形（坏节点全落 w_min，仅存在性上界，不可作安全保障）。"
                         "R≈1 时两端相差 <1%，R=15 时相差 27.2 倍——这也是该歧义此前未暴露的原因。"
                         "另：旧版把 R_final=w_max/w_min 喂给期望 R_eff=w̄_H/w̄_B 的公式，"
                         "得到恒偏乐观的 β（5/5 全部低估坏节点权重占比），本版已按正确口径修正。"),
        "worst_case_violations": sum(1 for p in poc if p["violates_worst_case"]),
        "note_on_scope": ("PoC 的 98.6% 等结果是**省略故障模型下的活性恢复**，"
                          "不是对任意 adversary 的安全界：坏节点静默→参与率 0→权重触底，"
                          "使最坏情形在该模型内结构性不可达。若对手改为满参与维持高权重再作恶，"
                          "则 ρ→R，容错退回最坏界 b < n/(2R+1)。"),
        "r_scan": scan,
        "poc_reproduction": poc,
        "exp3_reproduction": exp3,
        "self_checks": checks,
        "all_checks_pass": all_pass,
    }

    out_path = REPO_ROOT / "results" / "consensus_comparison" / "r_judgment_verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"报告已保存: {out_path}")
    return report


def _print_markdown(report: dict):
    lines = []
    lines.append(f"# {report['title']}\n")
    lines.append(f"**安全条件**：`{report['formula']}`\n")
    lines.append(f"> ⚠️ 口径澄清：{report['clarification']}\n")
    lines.append("## R_eff 扫描：f_max vs R_eff（R_eff = w̄_H/w̄_B = 1/ρ）\n")
    lines.append("| R_eff | f_max | f_max(%) | 说明 |")
    lines.append("|---|---|---|---|")
    for s in report["r_scan"]:
        lines.append(f"| {s['R_eff']} | {s['f_max']} | {s['f_max_pct']} | {s['note']} |")
    lines.append(f"\n> ⚠️ 边界声明：{report['note_on_scope']}\n")
    lines.append("\n## 复现路线 C PoC（R_band≈15）\n")
    lines.append("| 配置 | b | R_band<br>(w_max/w_min) | R_eff<br>(w̄_H/w̄_B) | β 推算 | β 实测 | 偏差(pp) | "
                 "β<1/3 | 最坏界<br>n/(2R+1) | 最好界<br>nR/(R+2) | **违反最坏界** | PoC 实测成功率 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in report["poc_reproduction"]:
        lines.append(f"| {p['config']} | {p['b_nodes']} | {p['R_band_wmax_wmin']} | "
                     f"{p['R_eff_wH_over_wB']} | {p['byzantine_weight_fraction']} | "
                     f"{p['beta_measured']} | {p['beta_abs_err_pp']} | "
                     f"{p['beta_below_1_3']} | {p['worst_case_bound_b']} | "
                     f"{p['best_case_bound_b']} | **{p['violates_worst_case']}** | "
                     f"{p['poc_cw_rate']} |")
    lines.append(f"\n**结论**：{report['worst_case_violations']}/5 配置违反最坏情形界，"
                 "但 5/5 实测 β<1/3（实际安全）——违反的是**保守性**而非**安全性**，"
                 "实测点位于区间 [n/(2R+1), nR/(R+2)) 接近右端（最好情形）一侧。\n")
    lines.append("\n## 复现 EXP-3 三权重来源\n")
    for k, v in report["exp3_reproduction"].items():
        lines.append(f"- **{k}**（R_eff={v['R_eff']}）：f_max={v['f_max_pct']}% — {v['interpretation']}")
    lines.append("\n## 自检\n")
    for c in report["self_checks"]:
        mark = "✅" if c["pass"] else "❌"
        lines.append(f"- {mark} {c['name']} — {c['detail']}")
    lines.append(f"\n**结论**：{'全部自检通过' if report['all_checks_pass'] else '存在失败项，需复查'}\n")
    md_path = REPO_ROOT / "results" / "consensus_comparison" / "r_judgment_verification.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown 已保存: {md_path}")


if __name__ == "__main__":
    rep = run()
    _print_markdown(rep)
    print("\n=== R 扫描 ===")
    for s in rep["r_scan"]:
        print(f"  R_eff={s['R_eff']:<5} f_max={s['f_max_pct']:>6}%  {s['note']}")
    print("\n=== 自检 ===")
    for c in rep["self_checks"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']} ({c['detail']})")
    print(f"\nALL_CHECKS_PASS = {rep['all_checks_pass']}")
    assert rep["all_checks_pass"], "E7 自检存在失败项"
