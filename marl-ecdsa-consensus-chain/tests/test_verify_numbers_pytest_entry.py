"""
verify_numbers 的 pytest 类条目（NR-19）诊断契约测试（2026-10-17）
====================================================================
守护当日修复：pytest 子进程失败曾被通用「数据源缺失」分支吞成
DATA_MISSING（exit 3）——把**门禁失败**伪装成**数据缺失**，是最危险的
误诊形态（PATH 上的 python 3.13 无 pytest，子进程秒败，真实原因全灭）。

修复后契约：
  1) ``_data_missing_applies``：pytest 类条目**永不**适用数据缺失判定；
     其余条目维持原判据（有错误 + 零文件扫过 + sources 不在）。
  2) CLI 级：``--run-tests`` 下 pytest 子进程失败 ⇒ FAIL（exit 1）且
     reason 带真实错误；不加 ``--run-tests`` ⇒ 按设计 deferred PENDING
     （exit 0，不伪绿也不阻断）；``--strict`` 下 deferred ⇒ exit 4。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import verify_numbers as vn  # noqa: E402  (conftest 已注入 scripts/**)


def _registry(tmp_path: Path) -> Path:
    """最小 registry：单条 pytest 类条目（sources 用 NR-19 同形态的
    file#fragment 引用——无 glob 键，_sources_present 恒 False）。"""
    reg = {"entries": [{
        "id": "NR-19",
        "claim": "测试计数（下限式）",
        "analysis": "pytest",
        "evidence_kind": "test_count",
        "sources": ["deliverables/assurance/reports/pytest_junit_x.xml#testsuite@tests"],
        "statistic": ["passed", "collected", "failed"],
        "declared": {"passed": 1711, "collected": 1719, "failed": 0},
        "tolerance": {"abs": 0, "p_abs": 0},
        "status": "PASS",
    }]}
    fp = tmp_path / "registry.json"
    fp.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    return fp


class TestDataMissingApplies:
    @pytest.mark.parametrize("analysis,errors,files,sources,expected", [
        # 🔴 核心修复：pytest 类条目任何失败都不吞成数据缺失
        ("pytest", ["boom"], 0, False, False),
        ("pytest", ["boom"], 0, True, False),
        ("pytest", [], 0, False, False),
        # 常规条目维持原判据
        ("two_sample", ["boom"], 0, False, True),
        ("two_sample", ["boom"], 0, True, False),
        ("two_sample", ["boom"], 3, False, False),   # 有文件扫过 ⇒ 非数据缺失
        ("two_sample", [], 0, False, False),         # 无错误 ⇒ 不适用
        ("code_check", ["boom"], 0, False, True),
    ])
    def test_matrix(self, analysis, errors, files, sources, expected):
        got = vn._data_missing_applies(analysis, errors, files, sources)
        assert got is expected


class TestTestCountCompareSemantics:
    """test_count 类条目（NR-19）的键级语义（2026-10-17 补 skipped 信息键）。

    踩坑：declared skipped=8 vs 实测 2——skipped 是环境相关构建产物特性
    （缺依赖跳用例），精确比对使 NR-19 无故 FAIL，与「测试数不应触发全链
    更新」的设计动因矛盾。修复：skipped 为信息键，不计判定。
    """

    def _entry(self, declared):
        return {"id": "NR-19", "analysis": "pytest", "evidence_kind": "test_count",
                "declared": declared, "tolerance": {"abs": 0, "p_abs": 0}}

    def test_skipped_drift_does_not_fail(self):
        """skipped 8→2（或 2→9）都不影响判定；passed/collected 下限仍生效。"""
        ok, deltas = vn.compare(
            self._entry({"passed": 1711, "collected": 1719, "skipped": 8, "failed": 0}),
            {"passed": 2018, "collected": 2020, "skipped": 2, "failed": 0})
        assert ok is True
        assert "信息键" in deltas["skipped"]

    def test_failed_still_exact_zero(self):
        """failed 仍精确比对：出现失败必须 FAIL（回归照旧被抓）。"""
        ok, _ = vn.compare(
            self._entry({"passed": 1711, "collected": 1719, "skipped": 8, "failed": 0}),
            {"passed": 2018, "collected": 2020, "skipped": 2, "failed": 3})
        assert ok is False

    def test_passed_below_floor_fails(self):
        """passed 低于下限必须 FAIL（防止"测试数缩水"被下限语义放行）。"""
        ok, _ = vn.compare(
            self._entry({"passed": 1711, "collected": 1719, "skipped": 8, "failed": 0}),
            {"passed": 1600, "collected": 1700, "skipped": 2, "failed": 0})
        assert ok is False

    def test_skipped_not_informational_for_regular_entries(self):
        """非 test_count 条目不享受信息键语义（精确比对维持）。"""
        entry = {"id": "NR-X", "analysis": "two_sample", "declared": {"skipped": 8},
                 "tolerance": {"abs": 0, "p_abs": 0}}
        ok, _ = vn.compare(entry, {"skipped": 2})
        assert ok is False


class TestPytestEntryCli:
    def test_subprocess_failure_is_fail_not_data_missing(self, tmp_path, monkeypatch):
        """--run-tests 下 pytest 子进程失败 ⇒ FAIL(1) 且带真实原因。"""
        reg = _registry(tmp_path)
        report = tmp_path / "report_fail.json"

        def _fail(entry, data_root, errors):
            errors.append(
                "pytest 未产出 junit xml（退出码 1）；stderr 末行: No module named pytest")
            return {}, 0

        monkeypatch.setattr(vn, "_recompute_pytest", _fail)
        monkeypatch.setattr(vn, "_sources_present", lambda entry, data_root: False)

        rc = vn.main(["--registry", str(reg), "--data-root", str(tmp_path),
                      "--run-tests", "--report", str(report), "--overwrite"])
        assert rc == vn.ac.EXIT_FAIL, "pytest 子进程失败必须是 FAIL，不是 DATA_MISSING(3)"
        doc = json.loads(report.read_text(encoding="utf-8"))
        e = doc["entries"][0]
        assert e["status"] == "FAIL"
        assert "No module named pytest" in e["reason"], "真实原因不得被吞"

    def test_without_run_tests_stays_deferred_pending(self, tmp_path, monkeypatch):
        """未加 --run-tests ⇒ 根本不复跑，deferred PENDING（exit 0）。"""
        reg = _registry(tmp_path)
        report = tmp_path / "report_pending.json"

        def _boom(entry, data_root, errors):  # pragma: no cover - 被调用即失败
            raise AssertionError("未加 --run-tests 不应复跑 pytest")

        monkeypatch.setattr(vn, "_recompute_pytest", _boom)
        rc = vn.main(["--registry", str(reg), "--data-root", str(tmp_path),
                      "--report", str(report), "--overwrite"])
        assert rc == vn.ac.EXIT_OK
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["entries"][0]["status"] == "PENDING"
        assert "须 --run-tests" in doc["entries"][0]["reason"]

    def test_strict_with_deferred_pending_exits_4(self, tmp_path):
        """--strict 下存在 deferred PENDING ⇒ exit 4（既有设计不改）。"""
        reg = _registry(tmp_path)
        report = tmp_path / "report_strict.json"
        rc = vn.main(["--registry", str(reg), "--data-root", str(tmp_path),
                      "--report", str(report), "--overwrite", "--strict"])
        assert rc == vn.ac.EXIT_STRICT_PENDING
