#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test-file-guard — "测试文件禁改" 下沉为 hook
用法（三种入口，同一逻辑）：
  1) git pre-commit hook：  python test_file_guard.py --staged
  2) CodeBuddy PreToolUse： python test_file_guard.py --pretooluse   （stdin: tool_input.command）
  3) 自证：                 python test_file_guard.py --self-test
判定逻辑（tdd-discipline 红线的机制化）：
  - 暂存区同时含 测试文件 + 实现文件（测试目录之外的 .py/.js/.ts）→
    ⚠️ 警告（退出 1）：实现"恰好通过"且测试同 commit 被改 = 逃逸信号；
    修复建议：测试改动单独提交（git reset HEAD <测试文件> 后分两次 commit），或在 message 中显式说明测试变更理由。
  - 只改测试文件（如重构测试/加新测试，实现未动）→ 放行（合法：TDD 红灯阶段）。
  - 只改实现 → 放行。
退出码：0=放行；1=警告拦截 / 环境错误（一个文件都没检查）；2=用法错误。

2026-11-07 修的三处「查了等于没查」（实测复现，见 CHANGELOG）：
  1. ``--pretooluse`` 的 stdin 不是 JSON → ``except: return 0``，静默放行。
  2. 同一分支里 ``check(staged_files())`` 抛异常 → ``return 0``，注释自称
     "不在 git 仓库等场景 fail-open"：git 不可用时这道守卫等于不存在。
  3. ``staged_files()`` 用 ``check_output(stderr=DEVNULL)`` + ``splitlines()``：
     非仓库目录的 ``--staged`` 直接抛 traceback（看不到 git 的真实原因），
     文件名含换行会被切成两条不存在的路径。改为 ``-z`` + 错误说明。
"""
import re
import subprocess
import sys
from typing import List, Optional, Tuple

TEST_PATTERNS = [
    re.compile(r"(^|/)tests?/", re.I),
    re.compile(r"(^|/)test_[^/]+\.py$", re.I),
    re.compile(r"(^|/)[^/]+_test\.py$", re.I),
    re.compile(r"(^|/)[^/]+\.test\.(js|ts|tsx)$", re.I),
    re.compile(r"(^|/)spec/", re.I),
]

IMPL_EXT = re.compile(r"\.(py|js|ts|tsx|jsx|go|java|rs)$", re.I)


def is_test(path: str) -> bool:
    return any(p.search(path) for p in TEST_PATTERNS)


def staged_files(cwd: Optional[str] = None) -> Tuple[List[str], str]:
    """返回 ``(暂存文件路径, 错误说明)``。错误说明非空 ⇒ 调用方必须判失败。"""
    cmd = ["git", "-c", "core.quotePath=false", "diff", "--cached",
           "--name-only", "-z", "--diff-filter=ACMR"]
    try:
        proc = subprocess.run(cmd, capture_output=True, cwd=cwd)
    except OSError as exc:
        return [], f"无法执行 git：{exc}"
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.decode("utf-8", "replace").splitlines()
                 if ln.strip()]
        detail = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))),
                      lines[0] if lines else "无错误输出")
        return [], f"git 退出码 {proc.returncode}：{detail}"
    return staged_files_from(proc.stdout, "")


def check(files: list) -> int:
    """既有契约：返回 0（放行）/ 1（测试与实现同 commit，拦截）。"""
    tests = [f for f in files if is_test(f)]
    impls = [f for f in files if (not is_test(f)) and IMPL_EXT.search(f)]
    if tests and impls:
        print("⚠️ 测试与实现同 commit 变更（tdd-discipline 红线）：", file=sys.stderr)
        for t in tests[:5]:
            print(f"   测试: {t}", file=sys.stderr)
        for i in impls[:5]:
            print(f"   实现: {i}", file=sys.stderr)
        print(
            "   实现『恰好通过』且测试同 commit 被改 = 逃逸信号（可能为过测试而改测试）。\n"
            "   建议：拆分提交——先提交实现+原测试通过的证据，再单独提交测试变更并说明理由；\n"
            "   或确认本次是合法的 TDD 红灯→绿灯（新测试+新实现），在 commit message 中写明。",
            file=sys.stderr,
        )
        return 1
    return 0


def decide(files: List[str], error: str) -> int:
    """唯一的判定入口（纯函数，便于自证与变异测试）。"""
    if error:
        print(f"❌ 测试文件禁改守卫：环境错误：{error} —— 一个文件都没检查，不等于合规",
              file=sys.stderr)
        return 1
    return check(files)


def run_self_test(verbose: bool = True) -> int:
    import os
    import tempfile

    failures: List[str] = []
    passed = 0

    def ck(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<30} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<30} → FAIL {detail}")

    ck("mixed_blocks", check(["tests/test_x.py", "blockchain/foo.py"]) == 1)
    ck("only_tests_pass", check(["tests/test_x.py"]) == 0)
    ck("only_impl_pass", check(["blockchain/foo.py"]) == 0)
    ck("non_code_ignored", check(["docs/readme.md", "data/x.json"]) == 0)

    raw = "tests/test_a.py\0a\nb.md\0".encode("utf-8")
    names, err = staged_files_from(raw, "")
    ck("z_split_keeps_newline", names == ["tests/test_a.py", "a\nb.md"], str(names))
    # decide 的环境错误分支会往 stderr 打印人读提示；自证里收起来，避免日志误读
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        ck("git_error_blocks", decide([], "fatal: not a git repository") == 1)
    ck("clean_passes", decide(["tests/test_x.py"], "") == 0)

    with tempfile.TemporaryDirectory(prefix="tfg_selftest_") as tmp:
        old = os.getcwd()
        try:
            os.chdir(tmp)
            _, e = staged_files()
            ck("non_repo_error_reported", bool(e), (e or "无错误")[:40])
        finally:
            os.chdir(old)

    total = passed + len(failures)
    if failures:
        for item in failures:
            print(f"❌ [自证失败] {item}")
        print(f"❌ 自证失败 {len(failures)}/{total} 项")
        return 1
    print(f"✅ 自证通过 {passed}/{total}")
    return 0


def staged_files_from(raw: bytes, error: str) -> Tuple[List[str], str]:
    """把 ``git -z`` 的原始输出解析成路径列表（抽成纯函数便于自证/变异）。"""
    if error:
        return [], error
    names = [f for f in raw.decode("utf-8", "replace").split("\x00") if f]
    return [f.replace("\\", "/") for f in names], ""


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        return run_self_test()
    if "--pretooluse" in args:
        import json
        try:
            data = json.load(sys.stdin)
        except Exception as exc:
            print(f"❌ test_file_guard --pretooluse：stdin 不是合法 JSON（{exc}）",
                  file=sys.stderr)
            return 2
        cmd = (data.get("tool_input") or {}).get("command", "")
        if "git commit" not in cmd:
            return 0
        files, error = staged_files()
        return decide(files, error)
    if "--staged" in args:
        files, error = staged_files()
        return decide(files, error)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
