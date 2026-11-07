#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``pre_submission_gate.py`` 的「陈旧报告被当成新证据」回归测试（2026-11-07）。

背景
----
提交前终检的三项检查（口径扫描 / 引用域 / code_check）都去磁盘读一份报告，
只判 ``report.exists()`` 与 ``blocking == 0``，**既不看工具这次有没有重写报告，
也不看子进程退出码**。实测：把 ``run()`` 换成「返回 rc=2、不写报告」，磁盘上留着
上一次成功的旧报告时：

    check_void()      -> True（PASS），detail 里甚至印着 ``rc=2``
    check_citation()  -> True（PASS）
    check_claim_code_consistency() -> True（PASS）

也就是说，PR #20 刚给 ``scan_void_tokens.py`` 加的「读不出/路径缺失 ⇒ 退出码 2」
到了终检层又被吞掉：信号出现在用户看到的文本里，却没有接到判定上。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "pre_submission_gate.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import pre_submission_gate as psg  # noqa: E402


def _ok_report(path: Path, **summary) -> None:
    base = {"blocking": 0, "files_scanned": 1, "hits": 0, "warn": 0, "info": 0}
    base.update(summary)
    path.write_text(json.dumps({"summary": base}), encoding="utf-8")


def _stale(monkeypatch, tmp_path: Path, rc: int = 2) -> Path:
    """造一份『上一次成功』的旧报告，并让本次扫描器报错、不写报告。"""
    rep = tmp_path / "stale.json"
    _ok_report(rep)
    monkeypatch.setattr(psg, "VOID_REPORT", rep)
    monkeypatch.setattr(psg, "CIT_REPORT", rep)
    monkeypatch.setattr(psg, "run", lambda cmd: (rc, "配置读取错误 / 读不出文件"))
    return rep


# ── 1. 判定入口 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("args,expect", [
    ((0, True, 0, ""), True),
    ((0, False, 0, ""), False),       # 陈旧报告
    ((2, True, 0, "错误"), False),    # 工具报错但报告新鲜
    ((1, True, 2, ""), False),        # blocking
    ((1, True, 0, ""), False),        # rc 与报告矛盾
    ((0, True, None, ""), False),     # 报告不可解析
])
def test_scanner_verdict(args, expect):
    assert psg.scanner_verdict(*args)[0] is expect


def test_verdict_explains_why():
    ok, why = psg.scanner_verdict(2, False, 0, "配置错误")
    assert not ok and "陈旧报告" in why and "退出码 2" in why, why


def test_report_signature_changes_on_rewrite(tmp_path):
    p = tmp_path / "r.json"
    assert psg.report_signature(p) is None
    _ok_report(p)
    before = psg.report_signature(p)
    _ok_report(p, hits=7)
    assert psg.report_signature(p) != before


def test_blocking_of_damaged_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    assert psg.blocking_of(p) is None


def test_run_with_report_detects_no_rewrite(monkeypatch, tmp_path):
    p = tmp_path / "r.json"
    _ok_report(p)
    monkeypatch.setattr(psg, "run", lambda cmd: (2, "err"))
    rc, out, fresh = psg.run_with_report(["fake"], p)
    assert rc == 2 and not fresh


def test_run_with_report_detects_rewrite(monkeypatch, tmp_path):
    p = tmp_path / "r.json"
    _ok_report(p)

    def _write(cmd):
        _ok_report(p, hits=3)
        return 0, "ok"

    monkeypatch.setattr(psg, "run", _write)
    rc, out, fresh = psg.run_with_report(["fake"], p)
    assert rc == 0 and fresh


# ── 2. 三项检查不得把旧报告当新证据 ───────────────────────────────────────

def test_check_void_rejects_stale_report(monkeypatch, tmp_path):
    _stale(monkeypatch, tmp_path)
    ok, detail = psg.check_void()
    assert not ok, detail
    assert "陈旧报告" in detail and "rc=2" in detail, detail


def test_check_citation_rejects_stale_report(monkeypatch, tmp_path):
    _stale(monkeypatch, tmp_path)
    ok, detail = psg.check_citation()
    assert not ok, detail
    assert "陈旧报告" in detail, detail


def test_check_void_rejects_rc2_even_with_fresh_report(monkeypatch, tmp_path):
    rep = tmp_path / "fresh.json"
    _ok_report(rep, unreadable=1)

    def _write_then_fail(cmd):
        _ok_report(rep, hits=1, unreadable=1)
        return 2, "读不出 1 个文件"

    monkeypatch.setattr(psg, "VOID_REPORT", rep)
    monkeypatch.setattr(psg, "run", _write_then_fail)
    ok, detail = psg.check_void()
    assert not ok, detail
    assert "退出码 2" in detail, detail


def test_check_void_accepts_fresh_clean_report(monkeypatch, tmp_path):
    rep = tmp_path / "clean.json"

    def _write(cmd):
        _ok_report(rep, files_scanned=12)
        return 0, "ok"

    monkeypatch.setattr(psg, "VOID_REPORT", rep)
    monkeypatch.setattr(psg, "run", _write)
    ok, detail = psg.check_void()
    assert ok, detail


def test_check_claim_rejects_stale_report(monkeypatch, tmp_path):
    rep = tmp_path / "claim.json"
    rep.write_text(json.dumps({"entries": [], "summary": {"total": 0, "pass": 0, "fail": 0}}),
                   encoding="utf-8")
    monkeypatch.setattr(psg, "CLAIM_REPORT", rep)
    monkeypatch.setattr(psg, "run", lambda cmd: (2, "工具报错"))
    ok, detail = psg.check_claim_code_consistency()
    assert not ok, detail
    assert "本次报告" in detail or "陈旧报告" in detail, detail


def test_check_tests_rejects_stale_junit(monkeypatch, tmp_path):
    junit = tmp_path / "pre_submit_junit.xml"
    junit.write_text("<testsuite tests='3' failures='0' errors='0' skipped='0'/>",
                     encoding="utf-8")
    monkeypatch.setattr(psg, "REPORTS", tmp_path)
    monkeypatch.setattr(psg, "run", lambda cmd: (2, "pytest 被中断"))
    ok, detail = psg.check_tests()
    assert not ok, detail
    assert "本次生成" in detail, detail


# ── 3. 源码契约与自证 ─────────────────────────────────────────────────────

def test_check_void_uses_scanner_verdict():
    """回归锁：判定必须走 scanner_verdict，不能退回只看 blocking 的旧写法。"""
    import ast
    src = (REPO_ROOT / "scripts" / "pre_submission_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "check_void")
    calls = [getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)]
    assert "scanner_verdict" in calls, calls


def test_self_test_passes():
    proc = subprocess.run([PY, "-X", "utf8", str(GATE), "--self-test"],
                          cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
