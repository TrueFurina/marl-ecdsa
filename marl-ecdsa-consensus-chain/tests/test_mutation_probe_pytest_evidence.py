# -*- coding: utf-8 -*-
"""变异探针的「判定取证」契约（2026-11-06 假红事故后的回归网）。

事故现场：全量探针从第 25 个目标起，每个基线子进程都是
「用例进度全是点 + 没有 pytest 汇总行 + 退出码 1」。旧判定只看退出码，
于是基线侧把它读成「关联测试本来就红」（把人引去改根本没坏的测试），
变异侧同一个 1 会被读成「守卫承重」（用一个来路不明的 1 给守卫背书）。

根因实测在运行环境：pytest 收尾清理临时目录时触发了批量删除守卫，进程在
打印汇总行之前就退出（证据见 CHANGELOG）。仓库这边能做的是**不再只信退出码**：

* 判定必须先从 stdout 解析出 pytest 的计数汇总行；
* 变异侧必须看到 `N failed`（N≥1）才认承重；
* 拿不到汇总行一律 fail-closed，并把「解释不了的非零」归类成环境问题。
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts.mutation_probe import (  # noqa: E402
    _fmt_counts,
    guard_hint,
    judge_baseline,
    judge_mutated,
    parse_pytest_summary,
)

# ── 现场样本（照抄子进程输出，含 Windows 反斜杠路径与 `=` 装饰） ────────────
GREEN_63 = (
    "============================= test session starts =============================\n"
    "collected 63 items\n"
    "\n"
    "tests\\test_contribution_weight_single_source.py ........................ [ 38%]\n"
    ".......................................                                  [100%]\n"
    "\n"
    "============================= 63 passed in 0.40s ==============================\n"
)
# 假红现场：进度打完就没了，汇总行一行都没有
TRUNCATED_63 = (
    "collected 63 items\n"
    "\n"
    "tests\\test_contribution_weight_single_source.py ........................ [ 38%]\n"
    ".......................................                                  [100%]"
)
# 真正的变异被守卫抓到
FAILED_13 = (
    "collected 23 items\n"
    "\n"
    "tests\\test_signing_service_contract.py .sFFFFFFFFFFFF.F.......           [100%]\n"
    "\n"
    "=========================== short test summary info ===========================\n"
    "FAILED tests/test_signing_service_contract.py::test_c2_invalid_backend\n"
    "=================== 13 failed, 9 passed, 1 skipped in 0.33s ===================\n"
)
GUARD_STDERR = (
    'PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.\n'
    "[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] "
    '{"count":60,"threshold":50,"scope":"turn","targets":['
    '"...\\\\Temp\\\\pytest-of-<user>\\\\garbage-e0bc4f67"]}\n'
)


# ── parse_pytest_summary ───────────────────────────────────────────────────
def test_parse_green_summary():
    assert parse_pytest_summary(GREEN_63) == {"passed": 63}


def test_parse_failed_summary():
    assert parse_pytest_summary(FAILED_13) == {"failed": 13, "passed": 9, "skipped": 1}


def test_parse_truncated_output_returns_none():
    """关键样本：全点但无汇总行，必须老实返回 None（不是"0 失败"）。"""
    assert parse_pytest_summary(TRUNCATED_63) is None


def test_parse_no_tests_ran():
    assert parse_pytest_summary("collected 0 items\n\nno tests ran in 0.01s\n") == {"collected": 0}


def test_parse_empty_output():
    assert parse_pytest_summary("") is None
    assert parse_pytest_summary("   \n\n") is None


def test_parse_plural_aliases():
    """pytest 写 `errors`/`warnings`（复数），内部统一成单数键。"""
    counts = parse_pytest_summary("==== 1 failed, 2 errors, 3 warnings in 1.0s ====")
    assert counts == {"failed": 1, "error": 2, "warning": 3}


def test_parse_single_warning():
    assert parse_pytest_summary("==== 5 passed, 1 warning in 0.2s ====") == {
        "passed": 5, "warning": 1}


def test_parse_ignores_failed_case_lines():
    """`FAILED tests/...` 行不得被当成汇总行（否则会把用例名读成计数）。"""
    text = (
        "FAILED tests/x.py::test_a - assert 1 == 0\n"
        "FAILED tests/x.py::test_b - assert 2 == 0\n"
        "2 failed in 0.5s\n"
    )
    assert parse_pytest_summary(text) == {"failed": 2}


# ── 基线侧 ─────────────────────────────────────────────────────────────────
def test_baseline_green_is_ok():
    ok, msg = judge_baseline(0, GREEN_63)
    assert ok is True
    assert "passed=63" in msg


def test_baseline_real_red_points_at_tests():
    """真红（有失败用例）才允许说"先修关联测试"。"""
    ok, msg = judge_baseline(1, FAILED_13)
    assert ok is False
    assert "13 失败" in msg
    assert "先修关联测试" in msg


def test_baseline_truncated_is_environment_not_tests():
    """假红：必须说"没有汇总行"，且**不得**把人引去改测试。"""
    ok, msg = judge_baseline(1, TRUNCATED_63)
    assert ok is False
    assert "没有 pytest 汇总行" in msg
    assert "先修关联测试" not in msg


def test_baseline_contradictory_zero_failures():
    ok, msg = judge_baseline(1, GREEN_63)
    assert ok is False
    assert "自相矛盾" in msg


def test_baseline_no_tests_collected():
    ok, msg = judge_baseline(5, "no tests ran in 0.01s\n")
    assert ok is False
    assert "一条用例都没收集到" in msg


# ── 变异侧 ─────────────────────────────────────────────────────────────────
def test_mutated_credits_real_failure():
    ok, msg = judge_mutated(1, FAILED_13)
    assert ok is True
    assert "13 个用例失败" in msg


def test_mutated_rejects_rc1_without_failures():
    """rc=1 + 零失败：旧判定会认承重，现在必须拒绝。"""
    ok, msg = judge_mutated(1, GREEN_63)
    assert ok is False
    assert "零失败" in msg


def test_mutated_rejects_rc1_without_summary():
    ok, msg = judge_mutated(1, TRUNCATED_63)
    assert ok is False
    assert "没有 pytest 汇总行" in msg


def test_mutated_still_green_is_not_bearing():
    ok, msg = judge_mutated(0, GREEN_63)
    assert ok is False
    assert "仍绿" in msg


def test_mutated_rc2_is_not_bearing():
    ok, msg = judge_mutated(2, FAILED_13)
    assert ok is False
    assert "2" in msg and "不是「有用例失败」" in msg


def test_mutated_rc5_no_tests_is_not_bearing():
    ok, _ = judge_mutated(5, "no tests ran in 0.01s\n")
    assert ok is False


@pytest.mark.parametrize("rc", [0, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("stdout", ["", TRUNCATED_63, GREEN_63, "63 passed in 0.4s"])
def test_mutated_never_credits_without_failure_evidence(rc, stdout):
    """核心不变量：没有 `N failed`（N≥1）证据，任何退出码都不许判承重。"""
    ok, msg = judge_mutated(rc, stdout)
    assert ok is False, f"rc={rc} 无失败证据却被认承重：{msg}"


@pytest.mark.parametrize("rc", [0, 1, 2, 3, 4, 5])
def test_baseline_never_green_without_rc0(rc):
    if rc == 0:
        return
    ok, _ = judge_baseline(rc, GREEN_63)
    assert ok is False


# ── 环境拦截指纹 ───────────────────────────────────────────────────────────
def test_guard_hint_detects_safe_delete():
    msg = guard_hint(GUARD_STDERR)
    assert msg and "SAFE_DELETE" in msg


def test_guard_hint_ignores_ordinary_warnings():
    plain = "PytestDeprecationWarning: fixture loop scope is unset\n"
    assert guard_hint(plain) == ""


def test_guard_hint_handles_empty():
    assert guard_hint("") == ""


# ── 小工具 ─────────────────────────────────────────────────────────────────
def test_fmt_counts_none():
    assert _fmt_counts(None) == "无汇总行"
    assert _fmt_counts({}) == "无汇总行"


def test_fmt_counts_orders_failed_first():
    assert _fmt_counts({"passed": 9, "failed": 1}) == "failed=1、passed=9"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
