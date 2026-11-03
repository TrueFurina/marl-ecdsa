"""
doctor.py --ci 模式契约测试（2026-10-20）

契约焦点：--ci 模式下，仓库外工作区资产必须以 unknown **显式登记**。
背景：scripts/doctor.py --ci 是 CI 第 16 步的「资产齐整性哨兵」。CI clone
天然不含仓库外资产（number_registry / 提交包 / 报告目录 / git 工作区语义）。
若实现退化为「跳过即不记录」，一次误删/改名就表现为全绿——
违反 REA 证据纪律：「没报出来」!= 「没有问题」（unknown 显式输出，
不静默省略）。本文件把该 fail-closed 语义钉死：

  D1 四类仓库外资产在 --ci 下各有登记，且 level=unknown、detail 说明缘由
  D2 --ci 非 strict 退出码为 0（unknown 不误判失败，CI 不因环境差异红）
  D3 --ci --strict 退出码为 1（严格档不放过未确认项）
  D4 仓库内检查（Python 版本 / 门禁脚本齐整）在 --ci 下仍真实执行且 PASS
  D5 JSON 输出的 summary 计数与登记条目自洽（机器可读消费方不错账）

对应 CI 接入：.github/workflows/ci.yml 末步 `python scripts/doctor.py --ci`。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCTOR = REPO / "scripts" / "doctor.py"


def _load_doctor():
    """按路径加载 doctor 模块（importlib，与 test_check_submission_anonymity 同惯例）。"""
    spec = importlib.util.spec_from_file_location("doctor_under_test", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run_ci(monkeypatch, tmp_path, *, strict=False):
    """在「模拟 CI clone」路径环境下跑 doctor --ci，返回 (退出码, 解析后 JSON)。

    模拟手法：把三个仓库外资产路径指到 tmp_path 下**不存在**的位置
    （等价于 CI checkout 里没有这些资产），REPO 保持真实仓库不动。
    """
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REGISTRY", tmp_path / "absent_registry.json")
    monkeypatch.setattr(doctor, "REPORTS", tmp_path / "absent_reports")
    monkeypatch.setattr(doctor, "PKG", tmp_path / "absent_submission_pkg")
    doctor.RESULTS.clear()

    argv = ["doctor.py", "--ci", "--json"] + (["--strict"] if strict else [])
    monkeypatch.setattr(sys, "argv", argv)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = doctor.main()
    return rc, json.loads(buf.getvalue())


# ---------------------------------------------------------------------------
# D1 显式登记契约
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name_fragment,why", [
    ("Git 分支/工作区", "detached HEAD 无工作区语义"),
    ("number_registry.json", "registry 在仓库外工作区"),
    ("verify_numbers 报告新鲜度", "报告目录在仓库外工作区"),
    ("提交包目录", "提交包在仓库外工作区"),
])
def test_d1_external_assets_registered_as_unknown(monkeypatch, tmp_path, name_fragment, why):
    """每个仓库外资产都必须留下 unknown 登记——而不是从结果里消失。"""
    rc, payload = _run_ci(monkeypatch, tmp_path)
    matched = [r for r in payload["results"] if name_fragment in r["name"]]
    assert matched, (
        f"CI 模式下未找到「{name_fragment}」登记——静默省略违反 unknown 显式输出纪律"
    )
    for r in matched:
        assert r["ok"] == "WARN", f"「{r['name']}」在 CI 模式应记 WARN(unknown)，实际 {r['ok']}"
        assert r["level"] == "unknown", f"「{r['name']}」level 应为 unknown，实际 {r['level']}"
        assert r["detail"], f"「{r['name']}」必须说明跳过缘由（{why}）"


def test_d1_unknown_count_is_at_least_four(monkeypatch, tmp_path):
    """数量级守卫：防未来新增仓库外检查时漏加 ci= 分支导致静默省略。"""
    _rc, payload = _run_ci(monkeypatch, tmp_path)
    unknowns = [r for r in payload["results"] if r["level"] == "unknown"]
    assert len(unknowns) >= 4, (
        f"CI 模式 unknown 登记应 >= 4（四类仓库外资产），实际 {len(unknowns)}"
        "——新增仓库外检查时须同步补 ci= 分支"
    )


# ---------------------------------------------------------------------------
# D2/D3 退出码契约
# ---------------------------------------------------------------------------
def test_d2_ci_mode_passes_without_strict(monkeypatch, tmp_path):
    """CI 不因本地环境差异（仓库外资产天然缺失）而红。"""
    rc, payload = _run_ci(monkeypatch, tmp_path, strict=False)
    assert rc == 0, payload
    assert payload["summary"]["fail"] == 0


def test_d3_ci_strict_fails_on_unknown(monkeypatch, tmp_path):
    """严格档不放过未确认项：unknown 计失败。"""
    rc, payload = _run_ci(monkeypatch, tmp_path, strict=True)
    assert rc == 1
    assert payload["summary"]["warn"] >= 4
    # strict_fail = 当前严格度下的有效失败数；机器消费方据此区分
    # 「失败来自 FAIL」与「失败来自 strict 升级的 unknown」，无需反推退出码。
    assert payload["summary"]["fail"] == 0, "仓库外资产缺失不应记 FAIL（那是误判）"
    assert payload["summary"]["strict_fail"] >= 4


# ---------------------------------------------------------------------------
# D4 仓库内检查仍真实执行
# ---------------------------------------------------------------------------
def test_d4_repo_internal_checks_still_run(monkeypatch, tmp_path):
    """--ci 只跳过仓库外资产；仓库内检查不得被顺带跳过。"""
    _rc, payload = _run_ci(monkeypatch, tmp_path)
    names = [r["name"] for r in payload["results"]]
    py_check = [r for r in payload["results"] if r["name"].startswith("Python ")]
    assert py_check and all(r["ok"] == "PASS" for r in py_check), names
    scripts_check = [r for r in payload["results"] if "关键门禁脚本" in r["name"]]
    assert scripts_check and all(r["ok"] == "PASS" for r in scripts_check), (
        f"仓库内门禁脚本齐整性检查应真实执行并 PASS，实际: {names}"
    )


# ---------------------------------------------------------------------------
# D5 JSON 自洽
# ---------------------------------------------------------------------------
def test_d5_json_summary_is_self_consistent(monkeypatch, tmp_path):
    """summary 计数必须与逐条登记一致（机器消费方不错账）。"""
    _rc, payload = _run_ci(monkeypatch, tmp_path)
    results = payload["results"]
    assert payload["summary"]["pass"] == sum(1 for r in results if r["ok"] == "PASS")
    assert payload["summary"]["fail"] == sum(1 for r in results if r["ok"] == "FAIL")
    assert payload["summary"]["warn"] == sum(1 for r in results if r["ok"] == "WARN")
    expected_strict_fail = payload["summary"]["fail"] + (
        payload["summary"]["warn"] if payload["strict"] else 0
    )
    assert payload["summary"]["strict_fail"] == expected_strict_fail
    assert payload["ci"] is True
