#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``structure_guard.py`` 的 fail-open 回归测试（2026-11-06）。

背景
----
这道门禁是 pre-commit 第 4 步、也是 CI `Pre-commit gates — repo-wide` 的最后一步，
职责是拦「散落在仓库根的受管文件」。它此前三处会把「没检查」当成「检查通过」：

1. **git 调用失败 ⇒ 退出码 0**。旧码用 ``check_output(..., stderr=DEVNULL)`` 包在
   ``try`` 里，异常被 ``except Exception`` 接住后打印「⚠️ 自身异常，跳过检查」并
   ``return 0``，注释里自己写着 "fail-open for self"。可它吞掉的不是自身 bug，
   而是「一个文件都没检查」——在非仓库目录 / git 不在 PATH 的容器里就是假绿。
2. **只取 ``--diff-filter=A``（新增）**。``git mv docs/report.md ./report.md`` 在 git
   眼里是 ``R100``（重命名），不是新增 ⇒ 文件列表为空 ⇒ 放行。而「根级平铺」恰恰
   最常由搬运既有文件产生：先有文档、再被挪到根目录。
3. **零文件也是通过**，且不打任何计数——cwd 跑偏时看到的 ✅ 与「检查了 610 个文件」
   长得一模一样。

对应三组断言：环境错误必须 exit 2、重命名必须被看见、零文件在 --strict 下必须失败。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "pre-commit" / "structure_guard.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))
import structure_guard as sg  # noqa: E402


def _run(cwd: Path, *args: str, env: dict | None = None) -> tuple[int, str]:
    proc = subprocess.run([PY, str(GUARD), *args], cwd=str(cwd), capture_output=True,
                          env=env)
    out = (proc.stdout or b"").decode("utf-8", "replace") + \
          (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """一个真 git 仓库：已提交 ``data/report.md``，工作区干净。"""
    assert _git(tmp_path, "init", "-q").returncode == 0, "本机缺 git，无法验证重命名场景"
    _git(tmp_path, "config", "user.email", "selftest@example.invalid")
    _git(tmp_path, "config", "user.name", "selftest")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "report.md").write_text("# 报告\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "add data/report.md")
    return tmp_path


# ── 1. 环境错误必须判失败（旧版 return 0） ───────────────────────────────

def test_not_a_git_repository_exits_2(tmp_path):
    code, out = _run(tmp_path, "--all")
    assert code == 2, f"非仓库目录必须判环境错误，实得 {code}\n{out}"
    assert "not a git repository" in out, out
    assert "一个文件都没检查" in out, out


def test_git_missing_from_path_exits_2(tmp_path):
    env = dict(os.environ)
    env["PATH"] = ""          # 让 subprocess 找不到 git
    code, out = _run(tmp_path, "--all", env=env)
    assert code == 2, f"git 不在 PATH 时必须判环境错误，实得 {code}\n{out}"
    assert "无法执行 git" in out, out


def test_staged_mode_in_non_repo_exits_2(tmp_path):
    code, out = _run(tmp_path)
    assert code == 2, f"默认（暂存区）模式同样不得 fail-open，实得 {code}\n{out}"


# ── 2. 重命名到根级必须被看见（旧版只取 A，看不见 R） ──────────────────────

def test_rename_into_root_is_blocked(repo: Path):
    mv = _git(repo, "mv", "data/report.md", "report.md")
    assert mv.returncode == 0, mv.stderr
    code, out = _run(repo)
    assert code == 1, f"git mv 到根级必须拦住，实得 {code}\n{out}"
    assert "report.md" in out, out


def test_rename_into_root_would_be_invisible_to_a_only(repo: Path):
    """对照：证明「只取 A」确实看不到这次重命名（旧规则的失效点）。"""
    _git(repo, "mv", "data/report.md", "report.md")
    only_a = _git(repo, "diff", "--cached", "--name-only", "--diff-filter=A").stdout
    assert only_a.strip() == b"", f"只取 A 时应当为空（这正是旧版放行的原因）：{only_a!r}"
    both = sg.staged_changed_files(cwd=str(repo))[0]
    assert both == ["report.md"], both


def test_new_root_file_is_blocked(repo: Path):
    (repo / "stray.md").write_text("# x\n", encoding="utf-8")
    _git(repo, "add", "stray.md")
    code, out = _run(repo)
    assert code == 1, f"根级新增受管文件必须拦住，实得 {code}\n{out}"


def test_subdir_change_passes(repo: Path):
    (repo / "data" / "other.md").write_text("# y\n", encoding="utf-8")
    _git(repo, "add", "data/other.md")
    code, out = _run(repo)
    assert code == 0, f"子目录内文件合规，实得 {code}\n{out}"


# ── 3. 零文件：不打计数就是假绿的温床 ────────────────────────────────────

def test_zero_staged_without_strict_passes_but_says_so(repo: Path):
    code, out = _run(repo)
    assert code == 0, out
    assert "零个变更文件" in out, out


def test_zero_staged_with_strict_fails(repo: Path):
    code, out = _run(repo, "--strict")
    assert code == 2, f"--strict 下零个文件必须失败，实得 {code}\n{out}"
    assert "零个文件" in out, out


# ── 4. 路径归一与 NUL 切分 ──────────────────────────────────────────────

@pytest.mark.parametrize("path", ["stray.md", "./stray.md", ".\\stray.md"])
def test_dot_prefix_still_counts_as_root(path):
    assert sg.violations_for(path) is not None, path


@pytest.mark.parametrize("path", ["docs/notes.md", "results/x.json", "run.py", "README.md"])
def test_compliant_paths(path):
    assert sg.violations_for(path) is None, path


def test_split_z_keeps_newline():
    assert sg.split_z("a\nb.md\0c.md\0".encode("utf-8")) == ["a\nb.md", "c.md"]


# ── 5. 仓库自身与本目录的现状 ────────────────────────────────────────────

def test_repo_itself_has_no_root_violation():
    code, out = _run(REPO_ROOT, "--all")
    assert code == 0, f"本仓 --all 应为 0 违规，实得 {code}\n{out[-800:]}"
    # 必须打印检查范围与计数：否则「检查了全部」和「一个没检查」在输出上无法区分
    assert "检查范围" in out, out


def test_self_test_passes():
    proc = subprocess.run([PY, str(GUARD), "--self-test"], cwd=str(REPO_ROOT),
                          capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
