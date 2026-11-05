#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""honesty_scan 的四类「扫了等于没扫」回归测试（2026-11-06）。

本文件钉死的是**覆盖面**，不是正则本身（正则契约在 test_gate_scripts.py）：

1. ``git diff --name-only`` 的输出不能按空白切分 —— 文件名含空格时，
   原实现把 ``报告 记录.md`` 切成两个不存在的路径，读失败被吞成「无命中」。
2. 编码必须探测 —— ``errors="ignore"`` 读 UTF-16/GBK 文档时中文被整段丢弃，
   假水位短语不可能命中。
3. 跳过规则只认路径段 —— 子串匹配会因 ``".git" in ".github/workflows/ci.yml"``
   而永不扫描 CI 配置本身，并连带吞掉 ``scripts/build_*.py``、``static/v9-distributed.*``。
4. 读不出 / 零扫描不得报「通过」。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))

import honesty_scan as hs  # noqa: E402

PHRASE = "本轮解出数 5→13 个"


# ── 1. -z 解析：文件名可含空格 / 换行 ───────────────────────────────────────

def test_split_z_keeps_space_in_name():
    names = hs.split_z("报告 记录.md\0b.md\0".encode("utf-8"))
    assert names == ["报告 记录.md", "b.md"], names


def test_split_z_keeps_newline_in_name():
    names = hs.split_z("a\nb.md\0c.md\0".encode("utf-8"))
    assert names == ["a\nb.md", "c.md"], names


def test_split_z_drops_trailing_empty():
    assert hs.split_z(b"a.md\0\0") == ["a.md"]
    assert hs.split_z(b"") == []


def test_git_failure_is_reported_not_swallowed(monkeypatch):
    class FakeProc:
        returncode = 129
        stdout = b""
        stderr = b"usage: git diff ...\nerror: unknown option `cached'\nmore usage\n"

    monkeypatch.setattr(hs.subprocess, "run", lambda *a, **k: FakeProc())
    files, error = hs.get_staged_files()
    assert files == []
    assert "129" in error
    # 结论必须落在 error/ 那行，而不是最后一行 usage
    assert "unknown option" in error, error


def test_git_exec_missing_is_reported(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(hs.subprocess, "run", boom)
    files, error = hs.get_staged_files()
    assert files == [] and "git" in error


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
def test_staged_file_with_space_is_listed_intact(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    target = tmp_path / "报告 记录.md"
    target.write_text(PHRASE + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    files, error = hs.get_staged_files(cwd=tmp_path)
    assert error == ""
    names = {p.name for p in files}
    assert "报告 记录.md" in names, names
    assert "报告" not in names and "记录.md" not in names, f"文件名被空白切碎了：{names}"


# ── 2. 编码探测 ────────────────────────────────────────────────────────────

def test_utf16_with_bom_is_decoded_and_hits():
    text, status, enc = hs.classify_bytes(PHRASE.encode("utf-16"))
    assert status == hs.STATUS_TEXT, (status, enc)
    assert enc == "utf-16"
    assert hs.scan_text(text), "UTF-16 文档里的假水位必须能命中"


def test_gbk_is_decoded_and_hits():
    text, status, enc = hs.classify_bytes(PHRASE.encode("gbk"))
    assert status == hs.STATUS_TEXT, (status, enc)
    assert enc == "gbk"
    assert hs.scan_text(text)


def test_utf8_still_preferred():
    text, status, enc = hs.classify_bytes(PHRASE.encode("utf-8"))
    assert status == hs.STATUS_TEXT and enc == "utf-8"


def test_binary_with_nul_is_binary_not_text():
    blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    text, status, _ = hs.classify_bytes(blob)
    assert status == hs.STATUS_BINARY and text == ""


def test_undecodable_bytes_is_a_failure_not_empty():
    _, status, reason = hs.classify_bytes(b"\xff\xff\xff\xff")
    assert status == hs.STATUS_DECODE_FAILED, (status, reason)


def test_control_heavy_decode_is_binary():
    # 没有 NUL、也能按 UTF-8「解出来」，但整片是控制字符 —— 可读性闸门必须挡住
    _, status, _ = hs.classify_bytes(b"\x01\x02\x03\x04" * 500)
    assert status == hs.STATUS_BINARY, status


def test_empty_file_is_empty_status():
    _, status, _ = hs.classify_bytes(b"")
    assert status == hs.STATUS_EMPTY


# ── 3. 读不出 ≠ 没违规 ─────────────────────────────────────────────────────

def test_directory_is_unreadable(tmp_path):
    doc = hs.scan_document(tmp_path)
    assert doc["status"] == hs.STATUS_UNREADABLE
    assert "目录" in str(doc["reason"])


def test_missing_file_is_unreadable(tmp_path):
    doc = hs.scan_document(tmp_path / "nope.md")
    assert doc["status"] == hs.STATUS_UNREADABLE
    assert doc["hits"] == []


# ── 4. 跳过规则只认路径段 ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    ".github/workflows/ci.yml",
    ".gitignore",
    "scripts/build_dashboard_data.py",
    "scripts/build_demo_video.py",
    "static/v9-distributed.js",
    "scripts/network_demo_distributed.py",
])
def test_substring_lookalikes_are_scanned(path):
    assert not hs.is_skipped(Path(path)), f"{path} 被子串规则误伤"


@pytest.mark.parametrize("path", [
    "build/out.py",
    ".git/config",
    "node_modules/x/index.js",
    "__pycache__/m.pyc",
    "_archive_2025/note.md",
])
def test_real_skip_dirs_are_skipped(path):
    assert hs.is_skipped(Path(path))


def test_no_substring_filter_regression():
    """回归：主循环里不允许再出现「按子串判断跳过」的第二个过滤层。"""
    src = (REPO_ROOT / "scripts" / "pre-commit" / "honesty_scan.py").read_text(encoding="utf-8")
    body = src.split("def main(", 1)[1]
    assert "for ign in" not in body, "main() 里又出现了子串过滤层"


# ── 5. 判定与端到端 ────────────────────────────────────────────────────────

def test_decide_exit_hits():
    assert hs.decide_exit(["x"], [], 5, False)[0] == 1


def test_decide_exit_problems_fail_without_strict():
    assert hs.decide_exit([], [{"path": "a"}], 5, False)[0] == 1


def test_decide_exit_zero_scan_strict_fails():
    code, why = hs.decide_exit([], [], 0, True)
    assert code == 1 and "什么都没有" not in why


def test_decide_exit_zero_scan_non_strict_passes_but_says_so():
    code, why = hs.decide_exit([], [], 0, False)
    assert code == 0 and "零个文件" in why


def test_decide_exit_clean_passes():
    assert hs.decide_exit([], [], 3, True)[0] == 0


def test_main_reports_git_error_as_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(hs, "get_staged_files", lambda cwd=None: ([], "not a git repository"))
    code = hs.main(["--cached"])
    out = capsys.readouterr().out
    assert code == 2
    assert "未扫描不等于通过" in out


def test_main_flags_directory_argument(tmp_path, capsys):
    code = hs.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1 and "读不出" in out, out


def test_main_strict_zero_scan_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = hs.main(["--strict"])
    out = capsys.readouterr().out
    assert code == 1 and "零个文件" in out, out


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
def test_main_cached_catches_spaced_and_github_files(tmp_path, monkeypatch, capsys):
    """端到端：暂存区里 .github/ 与含空格文件名中的假水位必须都被抓到。"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(PHRASE + "\n", encoding="utf-8")
    (tmp_path / "报告 记录.md").write_text(PHRASE + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    monkeypatch.chdir(tmp_path)
    code = hs.main(["--cached"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "ci.yml" in out and "报告 记录.md" in out, out


def test_main_utf16_file_hits(tmp_path, capsys):
    target = tmp_path / "u16.md"
    target.write_bytes(PHRASE.encode("utf-16"))
    code = hs.main([str(target)])
    assert code == 1
    assert "假水位" in capsys.readouterr().out


def test_self_test_passes():
    assert hs.run_self_test(verbose=False) == 0
