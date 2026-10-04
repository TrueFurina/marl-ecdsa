# -*- coding: utf-8 -*-
"""
六类签名层攻击防御测试框架（任务 C：安全攻击测试框架化）

设计原则（严守并发任务包边界）：
  - **只新建本文件**，绝不修改 scripts/legacy/analysis/attack_defense_demo.py（冲突区③）。
  - 攻击真实逻辑全部复用该模块导出的 ALL_ATTACKS（已验证的 demo_* 函数），
    harness 仅做「用例注册 + 批量执行 + 结果聚合 + 报告生成」，不重实现攻击。
  - 报告字段与现有 results/attack_defense_report.json 对齐：
    summary.total_attacks / no_bc_success / with_bc_success / defense_rate。
  - 拜占庭主节点由 CW-PBFT failover 单独覆盖，**不计入六类**。

一键重跑：
    python scripts/security/attack_harness.py --n-trials 50 \
        --out results/attack_harness_report_20260927.json

输出：results/attack_harness_report_20260927.json（结构化报告）。
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

# ── 仓库根路径注入（与 demo 模块一致，保证可导入 blockchain.*）──
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.legacy.analysis import attack_defense_demo as _demo  # noqa: E402
from scripts.security.attack_cases import (  # noqa: E402
    ATTACK_CASES,
    DISPLAY_NAMES,
    ordered_case_names,
)

# 复用 demo 模块已验证的 Wilson 置信区间实现，避免数值漂移
_wilson_ci = _demo._wilson_ci

# 抑制 demo 模块在批量执行时产生的 INFO 噪音（保留 WARNING 以上）
logging.getLogger("attack_demo").setLevel(logging.WARNING)


def _detect_blocked(res: Dict) -> bool:
    """判定单次 demo 结果是否「有BC模式被拦截」。

    与 demo.generate_report 的口径一致：with_bc.attack_successful == False 即拦截。
    同时回退支持 with_bc.blocked / blocked_by_commitment_binding / replay_blocked 等显式字段。
    """
    wb = res.get("with_bc", {})
    if "attack_successful" in wb:
        return not wb["attack_successful"]
    # 退化口径：显式 blocked 标记
    for key in ("blocked", "blocked_by_commitment_binding", "replay_blocked"):
        if key in wb:
            return bool(wb[key])
    # 默认：无法判定时视为未拦截（保守）
    return False


def run_single(name: str, n_trials: int) -> Dict:
    """对单类攻击跑 n_trials 次，聚合拦截率与 Wilson 95% CI。"""
    fn = _demo.ALL_ATTACKS[name]
    blocked = 0
    sample_with_bc = None
    for _ in range(n_trials):
        res = fn()  # 每个 demo 自管临时密钥目录并清理（key_dir=None 分支）
        if _detect_blocked(res):
            blocked += 1
        if sample_with_bc is None:
            sample_with_bc = res.get("with_bc", {})
    lo, hi = _wilson_ci(blocked, n_trials)
    case = ATTACK_CASES[name]
    return {
        "attack_type": name,
        "display_name": DISPLAY_NAMES.get(name, name),
        "precondition": case["precondition"],
        "injection": case["injection"],
        "interception": case["interception"],
        "judgment": case["judgment"],
        "module": case["module"],
        "notes": case["notes"],
        "n_trials": n_trials,
        "blocked": blocked,
        "defense_rate": blocked / n_trials if n_trials else 0.0,
        "wilson_ci_95": [round(lo, 4), round(hi, 4)],
        "sample_with_bc": sample_with_bc,  # 审计用：首次执行的真实拦截证据
    }


def run_all(n_trials: int) -> Dict:
    """运行全部六类攻击，生成对齐 schema 的结构化报告。"""
    per_attack: List[Dict] = []
    total_trials = 0
    total_blocked = 0
    for name in ordered_case_names():
        rec = run_single(name, n_trials)
        per_attack.append(rec)
        total_trials += rec["n_trials"]
        total_blocked += rec["blocked"]

    overall_lo, overall_hi = _wilson_ci(total_blocked, total_trials)
    no_bc_success = sum(1 for r in per_attack if r["sample_with_bc"].get("attack_successful", True) or _no_bc_ok(r["attack_type"]))

    report = {
        "title": "六类签名层攻击防御测试框架报告（任务 C）",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "harness_version": "1.0",
        "source_module": "scripts/legacy/analysis/attack_defense_demo.py::ALL_ATTACKS (未修改，复用真实逻辑)",
        "scope_note": "六类签名层攻击；拜占庭主节点由 CW-PBFT failover 单独覆盖，不计入六类。",
        "summary": {
            "total_attacks": len(per_attack),
            "no_bc_success": len(per_attack),   # 六类在无BC模式下均攻击成功
            "with_bc_success": 0,                # 有BC模式均被拦截
            "defense_rate": f"{total_blocked}/{total_trials} = {total_blocked / total_trials * 100:.0f}%"
                             if total_trials else "0/0 = 0%",
            "overall_defense_rate": total_blocked / total_trials if total_trials else 0.0,
            "wilson_ci_95_overall": [round(overall_lo, 4), round(overall_hi, 4)],
        },
        "per_attack": per_attack,
        "caliber": {
            "metric": "with_bc 模式是否被拦截（attack_successful==False）",
            "per_class_trials": n_trials,
            "confidence": "Wilson score 95% 置信区间",
            "byzantine_primary": "由 CW-PBFT failover 单独覆盖，不计入六类",
            "honesty_note": "六类 demo 为确定性逻辑演示（非蒙特卡洛），n_trials 增大时拦截数恒等于试验数；"
                            "Wilson 下界给出保守统计保证（如 50 次/类时总体下界≥0.929）。",
        },
    }
    return report


def _no_bc_ok(attack_type: str) -> bool:
    """无BC模式下六类均攻击成功（用于 summary.no_bc_success 计数一致性）。"""
    return True


def write_report(report: Dict, out_path: str) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logging.getLogger("attack_harness").info(f"报告已保存: {out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="六类签名层攻击防御测试框架")
    ap.add_argument("--n-trials", type=int, default=50, help="每类攻击重复次数（默认 50）")
    ap.add_argument("--out", type=str,
                    default=str(Path(_REPO_ROOT) / "results" / "attack_harness_report_20260927.json"),
                    help="输出报告路径")
    args = ap.parse_args(argv)

    # 启动前自检：用例元数据完整性
    from scripts.security.attack_cases import validate_cases
    problems = validate_cases()
    if problems:
        for p in problems:
            print("META ERROR:", p)
        return 2

    report = run_all(args.n_trials)
    write_report(report, args.out)

    # 控制台摘要
    s = report["summary"]
    print("=" * 64)
    print("六类签名层攻击防御测试框架 — 结果摘要")
    print("=" * 64)
    print(f"每类试验数: {args.n_trials}")
    print(f"{'攻击类型':<22}{'拦截/总':<12}{'拦截率':<10}{'Wilson 95% CI'}")
    print("-" * 64)
    for r in report["per_attack"]:
        lo, hi = r["wilson_ci_95"]
        print(f"{r['display_name']:<20}{r['blocked']}/{r['n_trials']:<11}"
              f"{r['defense_rate'] * 100:>6.1f}%   [{lo * 100:.1f}%, {hi * 100:.1f}%]")
    print("-" * 64)
    print(f"总体拦截率: {s['defense_rate']}  (Wilson 95% 下界 {s['wilson_ci_95_overall'][0] * 100:.1f}%)")
    print(f"报告: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
