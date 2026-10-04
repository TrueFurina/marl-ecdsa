#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D4：``code_check`` 类「口径 vs 代码」一致性必须接入终检且 fail-closed。

背景
----
此前 ``verify_numbers.py --run-tests`` 会算出 **NR-15 FAIL**（并发会话给
``blockchain/consensus/cw_pbft.py`` 新增 ``MAX_WEIGHT = 1.5``，打破了
「权重无上界」的口径），但该工具**不在 CI、也不在提交前门禁链上** ⇒
任何会话改源码打破口径都是**静默漂移**（不红 CI，只在本会话手动复跑时才暴露）。

D4 把 ``code_check`` 类条目独立成一个可快速运行的原子（``--code-check-only``），
并接入 ``scripts/pre_submission_gate.py`` 第 6 步：任一 code_check 条目 FAIL
→ 终检变红报警（fail-closed）。本测试钉死两件事：

1. ``--code-check-only`` **只**处理 ``analysis == "code_check"`` 的条目
   （与 benchmark / attack_report / test_count 类漂移解耦，可安全进终检）；
2. 门禁函数 ``check_claim_code_consistency`` 在报告出现 broken 时返回
   ``(False, ...)``，全部通过时返回 ``(True, ...)``。

变异验证：把循环里的过滤行删掉 ⇒ ``--code-check-only`` 会处理全部条目
⇒ 「报告里只有 code_check 条目」的断言必然失败（见 ``_mutate_d4_gate.py``）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIRROR_REGISTRY = REPO_ROOT / "number_registry.json"
PY = sys.executable


def _code_check_ids() -> set[str]:
    """从仓库内镜像登记表取所有 code_check 条目 id。"""
    if not MIRROR_REGISTRY.exists():
        pytest.skip("仓库内无登记表镜像 %s" % MIRROR_REGISTRY.name)
    data = json.loads(MIRROR_REGISTRY.read_text(encoding="utf-8"))
    return {e["id"] for e in data.get("entries", []) if e.get("analysis") == "code_check"}


def _run_code_check_only(report: Path) -> int:
    cmd = [PY, "-X", "utf8", "scripts/verify_numbers.py", "--code-check-only",
           "--registry", str(MIRROR_REGISTRY),
           "--report", str(report), "--overwrite"]
    p = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode


# --------------------------------------------------------------------------
# 核心：--code-check-only 必须只产出 code_check 条目
# --------------------------------------------------------------------------

def test_code_check_only_filters_to_code_check_entries(tmp_path):
    """``--code-check-only`` 产出的条目集 == 登记表中 code_check 条目集。"""
    expect = _code_check_ids()
    assert expect, "登记表里至少应有 1 个 code_check 条目（NR-15 / NR-18）"
    report = tmp_path / "claim.json"
    _run_code_check_only(report)
    assert report.exists(), "--code-check-only 未产出报告（工具可能报错）"
    doc = json.loads(report.read_text(encoding="utf-8"))
    got_ids = {e["id"] for e in doc.get("entries", [])}
    assert got_ids == expect, (
        "--code-check-only 产出条目集 %s 与登记表 code_check 条目集 %s 不一致"
        % (sorted(got_ids), sorted(expect)))
    for e in doc.get("entries", []):
        assert e.get("analysis") == "code_check", (
            "非 code_check 条目 %s 泄漏进了 --code-check-only 报告" % e["id"])


def test_code_check_only_total_matches_registry(tmp_path):
    """报告 total 必须等于 code_check 条目数（不得多算/少算）。"""
    expect = _code_check_ids()
    report = tmp_path / "claim2.json"
    _run_code_check_only(report)
    doc = json.loads(report.read_text(encoding="utf-8"))
    total = doc.get("summary", {}).get("total")
    assert total == len(expect), "报告 total=%s 与 code_check 条目数 %s 不符" % (total, len(expect))


# --------------------------------------------------------------------------
# 门禁决策逻辑：与报告里的 broken 列表一致（fail-closed）
# --------------------------------------------------------------------------

def test_gate_decision_matches_report():
    """``check_claim_code_consistency`` 的 ok 必须与报告 broken 列表一致。

    不写死 True/False（NR-15 当前是否被并发会话 reconcile 会变），只断言
    门禁函数对「报告有没有 broken」的映射正确 —— 这正是不变量。
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import pre_submission_gate as g  # noqa: E402

    ok, detail = g.check_claim_code_consistency()
    assert isinstance(ok, bool), "门禁 ok 应为布尔"
    assert isinstance(detail, str) and detail, "门禁 detail 应为非空字符串"

    doc = json.loads(g.CLAIM_REPORT.read_text(encoding="utf-8"))
    broken = [e["id"] for e in doc.get("entries", []) if e.get("status") == "FAIL"]
    assert ok == (not broken), (
        "门禁 ok=%s 与报告 broken=%s 不一致 —— fail-closed 映射被破坏" % (ok, broken))
