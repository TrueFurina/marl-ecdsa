#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NR-19「下限式」口径在**比对器**里必须真正生效（D3 守卫）。

背景
----
NR-19（自动化测试总数）2026-09-23 已由并发会话改为**下限式表述**：

* 对外材料统一写「**1600+ 项自动化测试全部通过（0 失败）**」；
* 设计意图是「**只要实测 passed ≥ 1600，测试数变化就不需要更新任何材料**」
  （此前精确数硬编码进 ~43 处材料，每加一批测试就要全链更新一次）。

但改造只落在**措辞**上：``scripts/verify_numbers.py`` 的 ``compare()`` 仍对
``declared`` 做**精确**比对（容差 0.01）⇒ 每新增一批测试，``--run-tests``
必然变红，与下限式口径的动因**自相矛盾**。本会话新增 10 项守卫测试后即刻复现：
实测 1685 vs declared 1665 ⇒ 差 20 ⇒ FAIL。

修法（已落地于 ``scripts/verify_numbers.py``，只影响 ``evidence_kind ==
"test_count"`` 的条目，当前仅 NR-19）：

* ``passed`` / ``collected`` 按**下限**比对（``computed >= declared``）；
* ``failed`` / ``skipped`` 等其余键仍**精确**比对 ⇒ 真回归照样被抓。

本测试把三条边界钉死，并额外守住「下限语义不得泄漏到常规条目」。

变异验证：把 ``compare()`` 里的 ``floor_mode`` 判断去掉（回到精确比对），
``test_test_count_growth_passes`` 必须 FAIL；把 ``floor_mode`` 改成恒真，
``test_normal_entry_keeps_exact_compare`` 必须 FAIL。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIRROR_REGISTRY = REPO_ROOT / "number_registry.json"

# 真正的比对器（conftest 已把仓库根与 scripts/** 注入 sys.path）
import verify_numbers as vn  # noqa: E402


def _nr19_entry():
    """从仓库内镜像登记表取 NR-19（权威在仓库外，镜像随仓库分发，CI 可用）。"""
    if not MIRROR_REGISTRY.exists():
        pytest.skip("仓库内无登记表镜像 %s" % MIRROR_REGISTRY.name)
    data = json.loads(MIRROR_REGISTRY.read_text(encoding="utf-8"))
    for e in data.get("entries", []):
        if e.get("id") == "NR-19":
            return e
    pytest.skip("镜像登记表中无 NR-19")


# --------------------------------------------------------------------------
# 与真实登记表的耦合：NR-19 必须被标为 test_count（下限语义的唯一触发条件）
# --------------------------------------------------------------------------

def test_nr19_is_marked_as_test_count():
    entry = _nr19_entry()
    assert entry.get("evidence_kind") == "test_count", (
        "NR-19 的 evidence_kind 不再是 test_count —— 下限式比对将不再生效，"
        "每新增一批测试都会让 verify_numbers --run-tests 变红")
    dec = entry.get("declared", {})
    for k in ("passed", "collected", "failed"):
        assert isinstance(dec.get(k), int), "NR-19 declared.%s 应为整数" % k
    assert dec["passed"] >= 1600, "下限式口径声明的是「1600+ 项」，declared 不应低于 1600"


def test_real_nr19_accepts_test_count_growth():
    """真实 NR-19 条目：计数只增不减时必须通过。"""
    entry = _nr19_entry()
    dec = entry["declared"]
    grown = {k: v for k, v in dec.items()}
    grown["passed"] += 37          # 模拟新增一批测试
    grown["collected"] += 37
    ok, deltas = vn.compare(entry, grown)
    assert ok, "计数增长被误判为失败：%s" % deltas


# --------------------------------------------------------------------------
# 三条边界
# --------------------------------------------------------------------------

_SYNTHETIC = {
    "id": "NR-19",
    "evidence_kind": "test_count",
    "declared": {"passed": 1665, "skipped": 2, "failed": 0, "collected": 1667},
    "tolerance": {"abs": 0.01},
}


def test_test_count_growth_passes():
    ok, deltas = vn.compare(_SYNTHETIC, {
        "passed": 1700, "skipped": 2, "failed": 0, "collected": 1702})
    assert ok, "下限式口径下计数增长不应失败：%s" % deltas


def test_test_count_below_floor_fails():
    ok, _ = vn.compare(_SYNTHETIC, {
        "passed": 1600, "skipped": 2, "failed": 0, "collected": 1602})
    assert not ok, "计数低于已记录下限时必须失败（可能是测试被误删）"


def test_test_count_failure_is_still_caught():
    """``failed`` 不是计数键：出现失败必须被抓住（下限语义不得把它放过去）。"""
    ok, _ = vn.compare(_SYNTHETIC, {
        "passed": 1700, "skipped": 2, "failed": 3, "collected": 1705})
    assert not ok, "有失败用例时不得通过"


# --------------------------------------------------------------------------
# 反向边界：下限语义只能作用于 test_count 条目
# --------------------------------------------------------------------------

def test_normal_entry_keeps_exact_compare():
    """常规条目（无 evidence_kind）仍必须精确比对 —— 下限语义不得泄漏。"""
    plain = {"id": "NR-99", "declared": {"passed": 100}, "tolerance": {"abs": 0.01}}
    ok, _ = vn.compare(plain, {"passed": 200})
    assert not ok, "常规条目的数值被按「下限」放过了 —— 下限语义泄漏，会放过真实偏差"
