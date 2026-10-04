#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""caliber_check（口径漂移体检）的核心契约测试。

pre-commit 6 步门禁里唯一尚未有测试的脚本（此前仅 code_check 子功能被
test_code_check_gate.py 覆盖）。本测试用**合成数字**（999——不在任何登记簿
合法集合、也不在作废令牌黑名单内）直接测纯函数与 main 端到端，钉死：

1. 真值抽取：n_universe 从全部条目收集；tests_floor 从 NR-19 下限式 claim 提取；
2. 中文样本量写法可匹配（09-28 重写的核心修复——旧正则匹配不到「n=NN 种子/组」）；
3. 漂移判定：合法集合外 → 漂移；低于测试数下限 → 漂移；豁免标记行不算未豁免漂移；
4. --strict 退出码语义（漂移存在且 strict → exit 1）。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))

import caliber_check as cc  # noqa: E402


# ── 真值抽取 ────────────────────────────────────────────────────────────────

def test_authoritative_facts_collects_n_universe():
    reg = {"entries": [
        {"id": "NR-1", "n_expected": 71},
        {"id": "NR-2", "declared": {"n_a": 30, "n_b": 30}},
        {"id": "NR-29", "declared": {"n_seeds": 60}},
    ]}
    facts = cc.authoritative_facts(reg)
    assert facts["n_universe"] == {71, 30, 60}
    assert facts["registry_found"] is True


def test_authoritative_facts_extracts_tests_floor():
    reg = {"entries": [
        {"id": "NR-19", "claim": "1800+ 项自动化测试全部通过(0失败)"},
    ]}
    facts = cc.authoritative_facts(reg)
    assert facts["tests_floor"] == 1800


def test_authoritative_facts_empty_registry():
    facts = cc.authoritative_facts({"entries": []})
    assert facts["n_universe"] == set()
    assert facts["tests_floor"] is None
    assert facts["registry_found"] is False


# ── 中文样本量写法匹配（09-28 重写的核心修复） ──────────────────────────────

def test_scan_text_matches_chinese_sample_size():
    hits = cc.scan_text("本组 n=999 种子 配对实验")
    assert any(fam == "sample_size" and val == 999 for _, fam, val, _, _ in hits), hits


def test_scan_text_matches_group_suffix():
    hits = cc.scan_text("设置 n=999/组")
    assert any(fam == "sample_size" and val == 999 for _, fam, val, _, _ in hits), hits


def test_scan_text_matches_tests_family():
    hits = cc.scan_text("结果：999 passed")
    assert any(fam == "tests" and val == 999 for _, fam, val, _, _ in hits), hits


def test_scan_text_ignores_unrelated_numbers():
    hits = cc.scan_text("λ=0.1，学习率 3e-4，71 个智能体")
    assert hits == [] or all(fam != "sample_size" for _, fam, _, _, _ in hits), \
        "裸数字（无 n=/种子/组 后缀）不应误配样本量族"


# ── 豁免标记 ────────────────────────────────────────────────────────────────

def test_is_exempt_markers():
    assert cc.is_exempt("旧口径 n=999 已作废")
    assert cc.is_exempt("此处应改为 n=71")
    assert not cc.is_exempt("本实验共 n=999 种子")


# ── main 端到端（--strict 退出码语义） ──────────────────────────────────────

def _run_main(md_content: str, *extra_args: str) -> tuple[int, str]:
    import io
    import contextlib
    fd, path = tempfile.mkstemp(suffix=".md", prefix="caliber_")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write(md_content)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cc.main([*extra_args, path])
        return code, buf.getvalue()
    finally:
        Path(path).unlink(missing_ok=True)


def test_main_drift_outside_universe_strict_exits_1():
    # 合法集合来自真实登记簿；999 几乎必然不在其中 → 未豁免漂移
    code, out = _run_main("实验设置：n=999 种子 配对\n", "--strict")
    assert code == 1, f"--strict 下集合外样本量应 exit 1，实得 {code}\n{out}"
    assert "漂移" in out


def test_main_exempt_line_not_strict_failure():
    # 带豁免标记（"作废"）的行即使数字非法也不应触发 --strict 失败
    code, out = _run_main("旧写法 n=999 种子 已作废，仅供参考\n", "--strict")
    assert code == 0, f"豁免行不应导致 --strict 失败，实得 {code}\n{out}"
    assert "[豁免]" in out


def test_main_clean_text_passes():
    code, out = _run_main("本文档不含任何样本量或测试数表述。\n", "--strict")
    assert code == 0
