# -*- coding: utf-8 -*-
"""攻击测试框架自身单测（任务 C）。

覆盖：用例元数据完整性、harness 可导入、小规模批量可完成、报告 schema 对齐。
运行：python -m pytest tests/test_attack_harness.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

# 仓库根注入
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.security.attack_cases import (  # noqa: E402
    ATTACK_CASES,
    CASE_FIELDS,
    ordered_case_names,
    validate_cases,
)
from scripts.security import attack_harness as harness  # noqa: E402


def test_cases_metadata_complete():
    """六类用例声明结构完整。"""
    problems = validate_cases()
    assert problems == [], f"用例元数据问题: {problems}"


def test_cases_count_and_fields():
    """恰好六类，每类含全部声明字段。"""
    names = ordered_case_names()
    assert len(names) == 6
    for n in names:
        assert n in ATTACK_CASES
        for f in CASE_FIELDS:
            assert f in ATTACK_CASES[n] and str(ATTACK_CASES[n][f]).strip(), f"{n}.{f} 缺失"


def test_harness_imports_demo_logic():
    """harness 正确复用 demo 模块 ALL_ATTACKS，不重实现攻击。"""
    assert set(harness._demo.ALL_ATTACKS.keys()) == set(ordered_case_names())


def test_run_single_small():
    """单类小样本运行：拦截数 == 试验数（确定性逻辑演示）。"""
    rec = harness.run_single("message_tampering", n_trials=3)
    assert rec["n_trials"] == 3
    assert rec["blocked"] == 3
    assert rec["defense_rate"] == 1.0
    assert len(rec["wilson_ci_95"]) == 2
    assert rec["sample_with_bc"] is not None


def test_run_all_schema_aligned():
    """run_all 产出的 summary 与现有 attack_defense_report.json schema 对齐。"""
    report = harness.run_all(n_trials=4)
    s = report["summary"]
    for key in ("total_attacks", "no_bc_success", "with_bc_success", "defense_rate"):
        assert key in s, f"summary 缺字段 {key}"
    assert s["total_attacks"] == 6
    assert s["no_bc_success"] == 6
    assert s["with_bc_success"] == 0
    assert s["defense_rate"] == "24/24 = 100%"
    assert report["summary"]["overall_defense_rate"] == 1.0
    assert len(report["per_attack"]) == 6
    # 每类含声明元数据 + 统计量
    for r in report["per_attack"]:
        for f in CASE_FIELDS:
            assert f in r and str(r[f]).strip(), f"per_attack 缺 {f}"
        assert r["blocked"] == r["n_trials"]


def test_byzantine_excluded():
    """报告明确排除拜占庭主节点（口径边界）。"""
    report = harness.run_all(n_trials=2)
    assert "failover" in report["scope_note"].lower() or "拜占庭" in report["scope_note"]
    assert "failover" in report["caliber"]["byzantine_primary"].lower()


def test_report_writes_and_roundtrips(tmp_path):
    """报告可落盘且可回读为合法 JSON。"""
    out = tmp_path / "r.json"
    report = harness.run_all(n_trials=2)
    harness.write_report(report, str(out))
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["total_attacks"] == 6
