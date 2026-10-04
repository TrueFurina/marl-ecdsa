#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D5：``secrets_scan.py`` 门禁本身必须被变异测试钉死（fail-closed 不被误修击穿）。

背景
----
``secrets_scan.py`` 是 pre-commit 第 1 步（密钥扫描，fail-closed）。它此前**没有自己的
测试**——如果某次改错了 40 位 base64 正则（AWS Secret 模式），门禁会静默失效：
要么放行真实密钥（漏报），要么误伤绝对路径/区块哈希（误报），且没有任何测试会红。

本测试钉死三组契约：
1. **真密钥必检出**：AWS Access Key / Secret、GitHub token、RSA 私钥块；
2. **非密钥必豁免**：绝对路径（/Users/...、C:/Users/...）、40 位纯 hex（区块哈希/种子）、
   ``hash=``/``sha256=`` 字段上下文；
3. **空参数直接通过**：pre-commit 第 1 步 ``$(git diff --cached --name-only)`` 空暂存时
   展开为空，``secrets_scan.py`` 必须直接返回 0，而非退化成全仓 rglob 扫描（否则扫到
   未跟踪脚本产生误报 + 拖慢提交）。

变异验证：见 tests/_mutate_secrets_scan.py（把负向前瞻删掉 → 路径/hex 误报必然复现）。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = REPO_ROOT / "scripts" / "pre-commit" / "secrets_scan.py"
PY = sys.executable


def _run_scan(*files: str) -> tuple[int, str]:
    """运行 secrets_scan.py，返回 (exit_code, 合并输出)。"""
    proc = subprocess.run(
        [PY, str(SCAN), *files],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _write_tmp(content: str) -> str:
    # 写到系统临时目录（而非 tests/），避免触发 scan_file 的「tests 下私钥块 = 固定向量豁免」，
    # 从而能真实测出「真密钥必检出」契约。
    fd, path = tempfile.mkstemp(suffix=".py", prefix="secscan_")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# ── 1. 真密钥必检出（fail-closed 的"closed"半边） ────────────────────────
# 注意：真实密钥字符串在**运行时拼接**构造，而非字面量——否则 pre-commit 的
# secrets_scan 扫到本测试文件会把它们当泄漏拦截（门禁自锁，无法提交本文件）。

def test_detects_aws_access_key_id():
    key = "AKIA" + "IOSFODNN7" + "EXAMPLE"
    p = _write_tmp(f"ACCESS_KEY_ID = '{key}'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 1, f"真 AWS Access Key ID 应检出并 exit 1，实得 {code}\n{out}"
    assert "AWS Access Key ID" in out, f"输出应含密钥类型描述，实得\n{out}"


def test_detects_aws_secret_access_key():
    # AWS 文档示例 40 位 base64（含 '/'），运行时拼接避免门禁自锁
    key = "wJalrXUtnFEMI/" + "K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
    p = _write_tmp(f"SECRET = '{key}'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 1, f"真 AWS Secret 应检出并 exit 1，实得 {code}\n{out}"


def test_detects_github_token():
    tok = "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJKL"
    p = _write_tmp(f"TOKEN = '{tok}'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 1, f"GitHub token 应检出，实得 {code}\n{out}"


def test_detects_private_key_block():
    p = _write_tmp("KEY = '-----BEGIN RSA PRIVATE KEY-----'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 1, f"私钥块应检出，实得 {code}\n{out}"


# ── 2. 非密钥必豁免（fail-closed 的"open"半边——不能误伤） ────────────────

def test_exempts_absolute_path():
    p = _write_tmp("PY = 'C:/Users/Lenovo/AppData/Local/Programs/Python/python.exe'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 0, f"绝对路径不应误报，实得 {code}\n{out}"


def test_exempts_pure_hex_40():
    p = _write_tmp("seed = '36727819239baabaf4634d93f1e98668de254a20'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 0, f"40 位纯 hex（种子/哈希）不应误报，实得 {code}\n{out}"


def test_exempts_hash_field_context():
    p = _write_tmp("block_hash = 'd7042aeb6929f6694bc89b1c35d9456ef5417f79'\n")
    try:
        code, out = _run_scan(p)
    finally:
        Path(p).unlink(missing_ok=True)
    assert code == 0, f"hash= 上下文的 40 位 hex 不应误报，实得 {code}\n{out}"


# ── 3. 空参数直接通过（不退化全仓扫描） ───────────────────────────────────

def test_empty_args_passes_immediately():
    proc = subprocess.run(
        [PY, str(SCAN)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert proc.returncode == 0, f"空参数应直接通过，实得 {proc.returncode}\n{proc.stderr}"
    assert "无暂存文件" in (proc.stdout or "")
