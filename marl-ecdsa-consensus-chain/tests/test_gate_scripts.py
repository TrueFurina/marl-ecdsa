#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三个轻量门禁脚本（honesty_scan / structure_guard / test_file_guard）的契约测试。

这三个脚本是 pre-commit 第 2/4/5 步，此前**零测试**。本测试直接调它们的纯函数
（scan_text / violations_for / check），钉死核心契约：

- honesty_scan：假水位短语/正则命中；引号包裹（「提及」非「使用」）不误报；
  且 FORBIDDEN_PHRASES/PATTERNS 是**单一真值源**（scan_text 引用它们，不再硬编码副本）。
- structure_guard：根级平铺违规检测、ROOT_ALLOW 白名单放行、子目录放行。
- test_file_guard：测试+实现同 commit 拦截（exit 1）、纯测试/纯实现放行（exit 0）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))

import honesty_scan  # noqa: E402
import structure_guard  # noqa: E402
import test_file_guard  # noqa: E402


# ── honesty_scan ────────────────────────────────────────────────────────────

def test_honesty_forbidden_phrase_hits():
    hits = honesty_scan.scan_text("本轮解出数提升，冲第一")
    assert hits, "假水位短语应命中"
    assert any("冲第一" in h for h in hits)


def test_honesty_forbidden_pattern_hits():
    hits = honesty_scan.scan_text("解出数 5→13 个")
    assert hits, "假水位正则（解出数 X→Y）应命中"
    assert any("假水位正则" in h for h in hits)


def test_honesty_quoted_mention_not_hit():
    # 引号包裹 = 「提及」非「使用」，剥离后不应命中
    hits = honesty_scan.scan_text("他提到「解出数 5→13」这个词")
    assert not hits, f"引号包裹的提及不应命中：{hits}"


def test_honesty_clean_text_no_hit():
    hits = honesty_scan.scan_text("本轮通过 1600 项测试，全部通过")
    assert not hits, f"干净文本不应命中：{hits}"


def test_honesty_single_source_of_truth():
    """FORBIDDEN_PHRASES 是单一真值源：scan_text 应引用顶层常量而非硬编码副本。

    回归背景：曾发现 scan_text 内部硬编码了一份与 FORBIDDEN_PHRASES 完全相同的副本，
    导致「新增假水位短语要改两处、漏一处静默失效」。此处用 inspect 断言 scan_text
    源码里不再出现第二份硬编码短语字面量。
    """
    import inspect
    src = inspect.getsource(honesty_scan.scan_text)
    # scan_text 应引用 FORBIDDEN_PHRASES / FORBIDDEN_PATTERNS，而非字面量
    assert "FORBIDDEN_PHRASES" in src and "FORBIDDEN_PATTERNS" in src, \
        "scan_text 未引用顶层常量（单一真值源被破坏）"


# ── structure_guard ─────────────────────────────────────────────────────────

def test_structure_root_flat_violation():
    v = structure_guard.violations_for("stray_notes.md")
    assert v is not None, "根级平铺 md 应违规"


def test_structure_root_allowlist_pass():
    for name in ["README.md", "requirements.txt", "pyproject.toml", "config.json",
                 "number_registry.json", "LICENSE", ".gitignore"]:
        assert structure_guard.violations_for(name) is None, f"白名单 {name} 不应违规"


def test_structure_subdir_pass():
    assert structure_guard.violations_for("docs/notes.md") is None
    assert structure_guard.violations_for("deliverables/report.pdf") is None


def test_structure_unmanaged_ext_pass():
    # .py 不在受管后缀里（源码不进结构守卫），根级 .py 不违规
    assert structure_guard.violations_for("run.py") is None


# ── test_file_guard ─────────────────────────────────────────────────────────

def test_file_guard_mixed_blocks():
    # 测试 + 实现同 commit → 拦截（exit 1）
    files = ["tests/test_x.py", "blockchain/foo.py"]
    assert test_file_guard.check(files) == 1


def test_file_guard_only_tests_pass():
    assert test_file_guard.check(["tests/test_x.py"]) == 0


def test_file_guard_only_impl_pass():
    assert test_file_guard.check(["blockchain/foo.py"]) == 0


def test_file_guard_non_py_ignored():
    # 非代码文件（.md/.json）不参与判定
    assert test_file_guard.check(["docs/readme.md", "data/x.json"]) == 0
