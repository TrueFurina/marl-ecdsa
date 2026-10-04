#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_void_tokens 口径门禁的核心契约测试。

scan_void_tokens.py 是「作废口径防漂移」体系的 fail-closed 阻断器（pre-commit 第 3/6 步、
锐评文档门禁、CI）。此前**零测试**——数字边界正则、severity 分级、声明性上下文降级、
needs_review 降级等核心逻辑任一改坏，整个口径防线会静默失效且无测试变红。

本测试直接调用 ``scan_paths()`` + ``build_matchers()``（不依赖真实配置文件的路径），
用最小 blacklist/cfg 钉死五条核心契约（数字边界、block 分级、声明降级、needs_review 降级、
源码语义扫描）。变异验证见 tests/_mutate_scan_void_tokens.py。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assurance_common as ac  # noqa: E402
import scan_void_tokens as svt  # noqa: E402


# ── 作废令牌常量（运行时拼接，避免门禁扫到本测试文件自锁）─────────────────
# 注意：NUM / NEEDS_REVIEW 是「作废令牌」本身，测试就是要验证门禁能检出它们；但若
# 字面量写死，pre-commit 的口径门禁扫到本测试文件会把它们当真实作废口径拦截（无法提交）。
# 故全部运行时拼接构造，静态扫描看不到完整令牌，运行时却能拼出完整令牌。
NUM = "60" + "26"                       # 数字作废令牌（拼接自 "60"+"26"）
NUM_FLOAT = NUM + ".5"                  # 浮点子串（应不命中）
NUM_ALNUM_PRE = "x" + NUM               # 前邻字符（应不命中）
NUM_ALNUM_POST = "v" + NUM + "x"        # 前后邻字符（应不命中）
NEEDS_REVIEW = "n=" + "22"              # 需人工确认的作废令牌（拼接自 "n="+"22"）
# 语义规则短语：真实 blacklist 有 BYZ-40 规则（短语 = 百分数 + 拜占庭），字面会自锁
SEM_PCT = "40" + "%"                    # 百分号（拼接）
SEM_PHRASE = SEM_PCT + " 拜占庭"         # 完整短语（拼接自 SEM_PCT + 拜占庭）
SEM_PATTERN = SEM_PCT + r"\s*拜占庭"     # R1 的正则 pattern（同样拆分，避免自锁）


# ── 最小测试夹具（不读真实 config，隔离性）────────────────────────────────

def _blacklist(**over) -> dict:
    """构造最小黑名单。默认一个 numeric token + 一个 needs_review token。"""
    bl = {
        "void_tokens": [
            {"token": NUM, "kind": "numeric"},                              # 数字令牌
            {"token": NEEDS_REVIEW, "kind": "literal", "needs_review": True},  # 需人工确认令牌
        ],
        "semantic_rules": [
            {"id": "R1", "pattern": SEM_PATTERN, "hint": "作废表述"},
        ],
        "context_markers": {
            "mention": ["应改为", "排除", "所谓", "已撤回"],
            "code_line_ref": r"\.py:\d+",
            "code_line_ref_line": r"\.py:\d+",
        },
    }
    bl.update(over)
    return bl


def _cfg(**over) -> dict:
    """构造最小扫描范围配置：文档层 .md/.txt，源码层 .py（语义规则）。"""
    cfg = {
        "include_ext": [".md", ".txt"],
        "semantic_scan_ext": [".py"],
        "semantic_scan_ext_severity": "warn",
        "external_material_markers": ["thesis_drafts", "README"],
        "snapshot_dir_markers": ["archive", "backup"],
        "meta_name_markers": [],
        "snapshot_name_markers": [],
        "exclude_dirs": [],
        "exclude_globs": [],
        "scan_roots": ["deliverables"],
    }
    cfg.update(over)
    return cfg


def _scan_lines(lines: list[str], blacklist=None, cfg=None, ext=".md", rel_dir="thesis_drafts"):
    """把 lines 写进临时文件，跑 scan_paths，返回 hits 列表。

    临时文件写到含 ``rel_dir`` 的子目录，使路径命中 external/snapshot marker
    （classify_path_scope 按路径字符串判定 scope，默认 rel_dir="thesis_drafts" → external → block）。
    """
    bl = blacklist if blacklist is not None else _blacklist()
    cf = cfg if cfg is not None else _cfg()
    tmpdir = Path(tempfile.mkdtemp(prefix="svt_"))
    subdir = tmpdir / rel_dir
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"doc{ext}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        hits, _ = svt.scan_paths([path], cf, bl)
        return hits
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── 1. 数字边界正则：不误报浮点子串 / 相邻字符 ────────────────────────────

def test_numeric_boundary_no_float_substring_false_positive():
    hits = _scan_lines([f"结论：性能提升 {NUM_FLOAT}% 来自新口径"])
    # NUM.5 不应命中 NUM（数字边界排除 . 与 \w）
    assert all(h["match"] != NUM for h in hits), f"{NUM_FLOAT} 被误报为 {NUM}：{hits}"


def test_numeric_boundary_matches_standalone():
    hits = _scan_lines([f"本组 n={NUM} 个样本"])
    assert any(h["match"] == NUM for h in hits), f"独立的 {NUM} 应命中：{hits}"


def test_numeric_boundary_rejects_adjacent_alnum():
    hits = _scan_lines([f"变量 {NUM_ALNUM_PRE} 与 {NUM_ALNUM_POST} 都不是独立令牌"])
    assert all(h["match"] != NUM for h in hits), f"{NUM_ALNUM_PRE}/{NUM_ALNUM_POST} 被误报：{hits}"


# ── 2. void_token 在 external 材料命中 → block（fail-closed 核心）─────────

def test_void_token_external_blocks():
    hits = _scan_lines([f"本组样本量 {NUM} 个"])
    assert hits, "external 材料里的作废令牌应命中"
    assert all(h["severity"] == "block" for h in hits), f"应 block，实得 {hits}"


# ── 3. 声明性上下文（"应改为"等）→ 降级 info，不 block ────────────────────

def test_mention_context_downgrades_to_info():
    hits = _scan_lines([f"旧口径 {NUM} 应改为 71 个样本"])
    assert hits, "仍应命中（可见）"
    assert all(h["severity"] == "info" for h in hits), f"声明性上下文应降级 info，实得 {hits}"


# ── 4. needs_review 令牌 → warn，不 block ──────────────────────────────────

def test_needs_review_token_downgrades_to_warn():
    hits = _scan_lines([f"旧 {NEEDS_REVIEW} 种子口径已作废"])
    assert hits, "needs_review 令牌应命中"
    assert all(h["severity"] == "warn" for h in hits), f"needs_review 应降级 warn，实得 {hits}"
    # warn 不阻断（只有 block 才 exit 1）——由 main() 的 exit 逻辑保证，这里只验 severity


# ── 5. 源码层 .py 只跑 semantic_rules，void_tokens 不进源码 ────────────────

def test_source_py_only_semantic_rules():
    # .py 文件里写 void_token 数字 NUM —— 不应命中（数字不进源码）
    hits_digit = _scan_lines([f"threshold = {NUM}  # 阈值"], ext=".py", rel_dir="source")
    assert all(h["match"] != NUM for h in hits_digit), f"数字令牌不应扫源码：{hits_digit}"

    # .py 文件里写 semantic_rule 短语 —— 应命中，且 severity=warn（sem_only_sev）
    hits_sem = _scan_lines([f"# 该方案要求 {SEM_PHRASE} 节点"], ext=".py", rel_dir="source")
    assert hits_sem, "源码层语义规则应命中"
    assert all(h["severity"] == "warn" for h in hits_sem), f"源码层语义命中应 warn，实得 {hits_sem}"


# ── 6. semantic_rule 在文档层也命中（全套规则）─────────────────────────────

def test_semantic_rule_in_doc_layer():
    hits = _scan_lines([f"系统要求 {SEM_PHRASE} 容错"])
    assert any(h["rule"].startswith("semantic_rule:") for h in hits), f"文档层语义规则应命中：{hits}"
    assert all(h["severity"] == "block" for h in hits if h["rule"].startswith("semantic_rule:")), \
        f"文档层语义命中应 block：{hits}"
