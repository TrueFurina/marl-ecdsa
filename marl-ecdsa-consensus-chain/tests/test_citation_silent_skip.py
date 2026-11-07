#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``scan_citation_blacklist.py`` 的「查了等于没查」回归测试（2026-11-08）。

背景
----
这是 CI 的 `Citation gate — synthetic references`，与 PR #20 的作废令牌门禁同族。
修前实测（同一行 `参考文献见 freederia.com 请核对`）：

* UTF-8 → ``blocking=1 / rc=1``
* UTF-16 → ``hits=0`` 却 ``files_scanned=1 / rc=0``
  （``scan_text_lines(errors="replace")`` 把 ASCII 拆成 ``f\\x00r\\x00e\\x00...``）
* 空目录 / 目录内只有 .pdf → ``files_scanned=0、0 命中、rc=0``，无 strict、无计数

合成域名一律**运行时拼接**：本文件也在扫描范围内，写字面量会自锁。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "scan_citation_blacklist.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import scan_citation_blacklist as scb  # noqa: E402


def _domain() -> str:
    return "freederia" + ".com"


def _cli(root: Path, report: Path, *extra: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [PY, "-X", "utf8", str(GATE), "--root", str(root),
         "--report", str(report), "--overwrite", *extra],
        cwd=REPO_ROOT, capture_output=True,
    )
    doc = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    return proc.returncode, doc


def _external(tmp_path: Path, name: str, data: bytes) -> tuple[Path, Path]:
    d = tmp_path / ("case_" + name)
    d.mkdir()
    (d / ("README_" + name + ".md")).write_bytes(data)
    return d, tmp_path / ("rep_" + name + ".json")


# ── 1. 读不懂是状态，不是空列表 ──────────────────────────────────────────

@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-8-sig", "gbk"])
def test_encoded_documents_are_scanned(tmp_path, encoding):
    line = f"参考文献见 {_domain()} 请核对\n"
    d, rep = _external(tmp_path, "enc_" + encoding, line.encode(encoding))
    code, doc = _cli(d, rep)
    s = doc["summary"]
    assert code == 1, f"{encoding} 里的伪引用必须检出，实得 {code}\n{s}"
    assert s["blocking"] == 1 and s["files_scanned"] == 1, s


def test_binary_document_is_not_counted_as_scanned(tmp_path):
    d, rep = _external(tmp_path, "binary", b"\x00\x01binary\x00freederia.com")
    code, doc = _cli(d, rep)
    s = doc["summary"]
    assert code == 2, f"读不出必须判「没检查」，实得 {code}\n{s}"
    assert s["files_scanned"] == 0 and s["unreadable"] == 1, s
    assert doc["unreadable_files"][0]["status"] == scb.STATUS_UNREADABLE


def test_decode_bytes_text_reports_binary():
    text, status, reason = scb.decode_bytes_text(b"\x00\x01binary")
    assert status == scb.STATUS_UNREADABLE and not text, (status, reason)


def test_read_lines_utf16_keeps_text():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "README.md"
        p.write_bytes(f"参考文献见 {_domain()}\n".encode("utf-16"))
        lines, status, _ = scb.read_lines(p)
        assert status == scb.STATUS_TEXT and _domain() in lines[0][1], lines


def test_source_does_not_use_errors_replace_reader():
    """回归锁：读取层不得再调用 ``ac.scan_text_lines``（errors="replace"）。"""
    import ast
    src = (REPO_ROOT / "scripts" / "scan_citation_blacklist.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in {"scan_text_lines", "read_text"}:
            bad.append((n.func.attr, n.lineno))
    assert not bad, f"读取层不得用容错解码 API：{bad}"


# ── 2. 零文件与路径基准 ──────────────────────────────────────────────────

def test_empty_root_passes_without_strict_but_reports_zero(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    code, doc = _cli(empty, tmp_path / "rep_empty.json")
    assert code == 0 and doc["summary"]["files_scanned"] == 0, doc["summary"]


def test_empty_root_fails_with_strict(tmp_path):
    empty = tmp_path / "empty2"
    empty.mkdir()
    code, doc = _cli(empty, tmp_path / "rep_empty2.json", "--strict")
    assert code == 2, doc["summary"]


def test_pdf_only_root_has_no_scan_and_fails_strict(tmp_path):
    d = tmp_path / "pdf_only"
    d.mkdir()
    (d / "README.pdf").write_bytes(b"%PDF fake\nfreederia.com\n")
    code, doc = _cli(d, tmp_path / "rep_pdf.json")
    assert code == 0 and doc["summary"]["files_scanned"] == 0, doc["summary"]
    code2, _ = _cli(d, tmp_path / "rep_pdf2.json", "--strict")
    assert code2 == 2


def test_resolve_root_prefers_cwd(tmp_path, monkeypatch):
    d = tmp_path / "sub"
    d.mkdir()
    old = Path.cwd()
    try:
        monkeypatch.chdir(tmp_path)
        assert scb.resolve_root("sub", {}) == d
    finally:
        import os
        os.chdir(old)


# ── 3. 降级证据与判定入口 ────────────────────────────────────────────────

def test_downgrade_records_which_marker_fired(tmp_path):
    line = f"该域名已排除：{_domain()}\n"
    d, rep = _external(tmp_path, "mention", line.encode("utf-8"))
    code, doc = _cli(d, rep)
    assert code == 0, doc["summary"]
    assert doc["hits"][0]["context"] == "mention", doc["hits"]
    # 配置里同时有「排除」与「已排除」，按配置顺序取第一个匹配；关键是证据字段存在
    reason = doc["hits"][0]["downgrade_reason"]
    assert reason.startswith("mention:") and "排除" in reason, doc["hits"]


def test_mention_marker_returns_first_hit():
    assert scb.mention_marker("黑名单：已排除", ["已排除", "黑名单"]) == "已排除"
    assert scb.mention_marker("纯引用", ["已排除"]) is None


@pytest.mark.parametrize("args,expect", [
    ((0, 0, 3, True), 0),
    ((1, 0, 3, False), 1),
    ((0, 1, 3, False), 2),
    ((0, 0, 0, True), 2),
    ((0, 0, 0, False), 0),
])
def test_decide_exit(args, expect):
    assert scb.decide_exit(*args)[0] == expect


def test_self_test_passes():
    proc = subprocess.run([PY, "-X", "utf8", str(GATE), "--self-test"],
                          cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
