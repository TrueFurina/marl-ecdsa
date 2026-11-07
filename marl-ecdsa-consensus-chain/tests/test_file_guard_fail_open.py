#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``test_file_guard.py``（pre-commit 第 5 步）的 fail-open 回归测试（2026-11-07）。

实测复现的三处放行：
1. ``--pretooluse`` 的 stdin 不是合法 JSON → ``except: return 0``，静默放行；
2. 同一分支里 ``check(staged_files())`` 抛异常 → ``return 0``（注释自称
   "不在 git 仓库等场景 fail-open"）⇒ git 不可用时守卫等于不存在；
3. ``staged_files()`` 用 ``check_output(stderr=DEVNULL)`` + ``splitlines()``：
   非仓库目录的 ``--staged`` 直接抛 traceback，看不到 git 的真实原因；
   文件名含换行会被切成两条不存在的路径。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "pre-commit" / "test_file_guard.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))
import test_file_guard as tfg  # noqa: E402


def _cli(*args: str, stdin: bytes = b"", cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run([PY, "-X", "utf8", str(GUARD), *args],
                          cwd=str(cwd or REPO_ROOT), input=stdin, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace") + \
          (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out


# ── 1. 三条入口的失败语义 ─────────────────────────────────────────────────

def test_pretooluse_bad_stdin_is_usage_error():
    code, out = _cli("--pretooluse", stdin=b"not json")
    assert code == 2, f"stdin 不是 JSON 不得静默放行，实得 {code}\n{out}"
    assert "stdin 不是合法 JSON" in out, out


def test_pretooluse_git_error_blocks(tmp_path):
    code, out = _cli("--pretooluse",
                     stdin=b'{"tool_input":{"command":"git commit -m x"}}',
                     cwd=tmp_path)
    assert code == 1, f"非仓库目录下不得 fail-open，实得 {code}\n{out}"
    assert "一个文件都没检查" in out, out


def test_staged_git_error_blocks_without_traceback(tmp_path):
    code, out = _cli("--staged", cwd=tmp_path)
    assert code == 1, f"非仓库目录 --staged 应给出可读错误，实得 {code}\n{out}"
    assert "Traceback" not in out, out
    assert "环境错误" in out, out


def test_no_args_is_usage_error():
    code, _ = _cli()
    assert code == 2


def test_pretooluse_non_commit_command_passes():
    code, _ = _cli("--pretooluse",
                   stdin=b'{"tool_input":{"command":"echo hello"}}')
    assert code == 0


# ── 2. git 清单与既有契约 ─────────────────────────────────────────────────

def test_staged_files_reports_error_outside_repo(tmp_path):
    paths, err = tfg.staged_files(cwd=str(tmp_path))
    assert isinstance(paths, list) and err, "非仓库目录必须拿到错误说明，而不是空清单"


def test_staged_files_from_keeps_newline_in_name():
    raw = "tests/test_a.py\0a\nb.md\0".encode("utf-8")
    names, err = tfg.staged_files_from(raw, "")
    assert not err and names == ["tests/test_a.py", "a\nb.md"], names


def test_staged_files_from_propagates_error():
    names, err = tfg.staged_files_from(b"x\0", "fatal: not a git repository")
    assert not names and "not a git repository" in err


def test_decide_error_blocks():
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        assert tfg.decide([], "fatal: not a git repository") == 1


@pytest.mark.parametrize("files,expect", [
    (["tests/test_x.py", "blockchain/foo.py"], 1),
    (["tests/test_x.py"], 0),
    (["blockchain/foo.py"], 0),
    (["docs/readme.md", "data/x.json"], 0),
])
def test_existing_check_contract(files, expect):
    assert tfg.check(files) == expect


def test_source_has_no_fail_open_return_zero():
    """回归锁：不得再出现 ``except ... return 0`` 这种把异常折叠成放行的写法。"""
    import ast
    src = (REPO_ROOT / "scripts" / "pre-commit" / "test_file_guard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler):
            for r in ast.walk(n):
                if isinstance(r, ast.Return) and isinstance(r.value, ast.Constant) \
                        and r.value.value == 0:
                    bad.append(r.lineno)
    assert not bad, f"except 里不得 return 0（fail-open）：行 {bad}"


def test_self_test_passes():
    proc = subprocess.run([PY, "-X", "utf8", str(GUARD), "--self-test"],
                          cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
