#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``check_evidence_closure.py`` 门禁契约测试（fail-closed 不被误修击穿）。

背景
----
2026-10-18 对账发现：仓库已有 ``verify_numbers.py``（声明值 vs 复算值）与
``check_registry_mirror.py``（权威源 vs 镜像），但**没有一道门禁管"没跑完的
算不算通过"**。``verify_numbers`` 假定结果文件完整——某臂只跑 100/500 回合，
复算依旧自洽，于是截断可以一路绿灯。

本测试钉死门禁的契约：

1. **截断必拦**：声明 500、数组 100 → ``truncated``，退出码 1；
2. **零填充必拦**：``avg_x=0`` 而底层数组缺失 → ``fail``，退出码 1；
3. **退化记 unknown**：整列恒定 → ``unknown``，``--strict`` 下退出码 4；
4. **不适用不计分母**：汇总报告不得被算成"没跑完"（否则 3592 个报告文件淹没信号）；
5. **结构性恒列必须放过**：``selfish_ratio=0`` 的 betrayal、``lambda_weight=0``
   的 λ 恒 0 属实验设计，误判会让门禁失去可信度；
6. **聚合 fail-closed**：存在任一 unknown，``complete`` 必须为 False；
7. **偏序不输出总分**：``total_score`` 恒 None、``ranking_emitted`` 恒 False；
8. **自证非空洞**：``--self-test`` 的夹具必须 7/7 命中。

第 5、8 条来自实测教训：第一版门禁把 2194 个结构性恒列判成"指标未接"，
若不修就会被当成噪声门禁而弃用。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_evidence_closure.py"

sys.path.insert(0, str(GATE.parent))
import check_evidence_closure as cec  # noqa: E402


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
def _run_doc(episodes: int = 500, *, arrays: bool = True,
             cooperation: str = "normal", betrayal: str = "normal",
             selfish_ratio: float = 0.0, mode: str = "bc_marl",
             lambda_weight: float = 0.1) -> dict:
    """造一份形态逼真的训练结果文档。"""
    doc: dict = {
        "config": {"n_episodes": episodes, "seed": 1, "mode": mode,
                   "selfish_ratio": selfish_ratio, "lambda_weight": lambda_weight},
        "summary": {"total_episodes": episodes,
                    "avg_env_reward_last_50": -20.0},
    }
    if not arrays:
        return doc

    def series(kind: str) -> list:
        if kind == "zeros":
            return [0.0] * episodes
        if kind == "thirds":
            return [1.0 / 3.0] * episodes
        if kind == "constant":
            return [0.1] * episodes
        return [0.001 * (i % 997) for i in range(episodes)]

    doc["episode_rewards"] = [float(i % 13) - 40 for i in range(episodes)]
    doc["env_rewards"] = [float(i % 7) - 45 for i in range(episodes)]
    doc["cooperation_rates"] = series(cooperation)
    doc["betrayal_rates"] = series(betrayal)
    # λ 列：bc_marl 且 λ 权重非 0 时应逐回合变化（真实自适应行为）。
    if mode == "bc_marl" and lambda_weight:
        doc["lambda_history"] = [0.1 + 0.0001 * (i % 50) for i in range(episodes)]
    else:
        doc["lambda_history"] = [0.0 if not lambda_weight else 0.1] * episodes
    return doc


def _write(tmp_path: Path, name: str, doc: dict) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _gate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(GATE), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )


# --------------------------------------------------------------------------- #
# 1. 逐条判定（直接调纯函数，快）
# --------------------------------------------------------------------------- #
def test_clean_run_passes():
    verdict = cec.inspect_document(_run_doc())
    assert verdict["status"] == cec.STATUS_PASS
    assert verdict["reason_code"] == "closed"


def test_truncated_is_not_pass():
    doc = _run_doc(episodes=500)
    doc["episode_rewards"] = doc["episode_rewards"][:100]
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_TRUNCATED
    assert verdict["reason_code"] == "length_mismatch"
    assert verdict["actual"]["episode_rewards"] == 100


def test_zero_filled_summary_is_fail():
    doc = _run_doc(episodes=800)
    doc["summary"]["avg_cooperation_rate"] = 0.0
    doc.pop("cooperation_rates")
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_FAIL
    assert verdict["reason_code"] == "zero_filled"


def test_degenerate_series_is_unknown_not_pass():
    verdict = cec.inspect_document(_run_doc(cooperation="zeros"))
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "degenerate"


def test_missing_arrays_is_unknown():
    verdict = cec.inspect_document(_run_doc(arrays=False))
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "no_evidence"


# --------------------------------------------------------------------------- #
# 2. 不适用 / 结构性恒列（防误伤）
# --------------------------------------------------------------------------- #
def test_report_file_is_not_applicable():
    """汇总报告只有根级回合数，绝不能算成"没跑完"。"""
    verdict = cec.inspect_document({"title": "r", "n_episodes": 50, "n_seeds": 3})
    assert verdict["status"] == cec.STATUS_NA
    assert verdict["reason_code"] == "not_a_run"


def test_report_file_becomes_unknown_under_require_trace():
    verdict = cec.inspect_document({"title": "r", "n_episodes": 50}, require_trace=True)
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "summary_only"


def test_betrayal_zero_is_structural_when_selfish_ratio_zero():
    verdict = cec.inspect_document(_run_doc(betrayal="zeros", selfish_ratio=0.0))
    assert verdict["status"] == cec.STATUS_PASS
    assert "结构性" in verdict["detail"]


def test_betrayal_constant_with_selfish_agents_is_flagged():
    """selfish_ratio=0.3 却整列恒为 1/3 —— 这是"合成值"，必须报出来。"""
    verdict = cec.inspect_document(_run_doc(betrayal="thirds", selfish_ratio=0.3))
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "degenerate"


def test_lambda_zero_is_structural_when_lambda_weight_zero():
    doc = _run_doc(episodes=300, lambda_weight=0.0)
    doc["lambda_history"] = [0.0] * 300
    assert cec.inspect_document(doc)["status"] == cec.STATUS_PASS


def test_lambda_constant_is_structural_for_non_bc_marl():
    doc = _run_doc(episodes=300, mode="pure_marl")
    assert cec.inspect_document(doc)["status"] == cec.STATUS_PASS


# --------------------------------------------------------------------------- #
# 3. 聚合 fail-closed
# --------------------------------------------------------------------------- #
def test_unknown_blocks_complete():
    agg = cec.summarize([
        {"status": cec.STATUS_PASS, "reason_code": "closed"},
        {"status": cec.STATUS_UNKNOWN, "reason_code": "degenerate"},
    ])
    assert agg["complete"] is False


def test_not_applicable_excluded_from_denominator():
    agg = cec.summarize([
        {"status": cec.STATUS_PASS, "reason_code": "closed"},
        {"status": cec.STATUS_NA, "reason_code": "not_a_run"},
    ])
    assert agg["complete"] is True
    assert agg["applicable"] == 1
    assert agg["summary"][cec.STATUS_NA] == 1


def test_nothing_applicable_is_not_complete():
    agg = cec.summarize([{"status": cec.STATUS_NA, "reason_code": "not_a_run"}])
    assert agg["complete"] is False


# --------------------------------------------------------------------------- #
# 4. 偏序不输出总分
# --------------------------------------------------------------------------- #
def test_partial_order_never_emits_total_score(tmp_path: Path):
    arms = {"baseline": [1, 2, 3], "variant": [1, 2]}
    files = []
    for arm, seeds in arms.items():
        for seed in seeds:
            doc = _run_doc(episodes=20)
            doc["config"]["seed"] = seed
            doc["summary"]["avg_env_reward_last_50"] = -10.0 if arm == "variant" else -20.0
            files.append(_write(tmp_path, f"{arm}_seed{seed}.json", doc))

    result = cec.build_partial_order(sorted(files), "summary.avg_env_reward_last_50")
    assert result["total_score"] is None
    assert result["ranking_emitted"] is False
    pair = result["pairs"][0]
    assert pair["shared_seeds"] == 2
    assert pair["seeds_only_left"] == [3]
    assert "variant" in pair["relation"]


def test_partial_order_marks_insufficient_overlap_incomparable(tmp_path: Path):
    files = []
    for arm, seeds in {"a": [1], "b": [2, 3]}.items():
        for seed in seeds:
            doc = _run_doc(episodes=20)
            doc["config"]["seed"] = seed
            files.append(_write(tmp_path, f"{arm}_seed{seed}.json", doc))
    result = cec.build_partial_order(sorted(files), "summary.avg_env_reward_last_50")
    assert result["pairs"][0]["relation"] == "incomparable"
    assert result["pairs"][0]["comparable"] is False


# --------------------------------------------------------------------------- #
# 5. 退出码（端到端）
# --------------------------------------------------------------------------- #
def test_exit_ok_on_clean_tree(tmp_path: Path):
    _write(tmp_path, "clean.json", _run_doc(episodes=120))
    proc = _gate("--root", str(tmp_path))
    assert proc.returncode == cec.ac.EXIT_OK, proc.stdout + proc.stderr


def test_exit_fail_on_truncated(tmp_path: Path):
    doc = _run_doc(episodes=500)
    doc["episode_rewards"] = doc["episode_rewards"][:10]
    _write(tmp_path, "bad.json", doc)
    proc = _gate("--root", str(tmp_path))
    assert proc.returncode == cec.ac.EXIT_FAIL


def test_exit_fail_on_zero_filled(tmp_path: Path):
    doc = _run_doc(episodes=100)
    doc["summary"]["avg_betrayal_rate"] = 0.0
    doc.pop("betrayal_rates")
    _write(tmp_path, "zf.json", doc)
    assert _gate("--root", str(tmp_path)).returncode == cec.ac.EXIT_FAIL


def test_strict_turns_unknown_into_exit_code_4(tmp_path: Path):
    _write(tmp_path, "deg.json", _run_doc(episodes=200, cooperation="zeros"))
    assert _gate("--root", str(tmp_path)).returncode == cec.ac.EXIT_OK
    assert _gate("--root", str(tmp_path), "--strict").returncode == cec.ac.EXIT_STRICT_PENDING


def test_missing_root_returns_data_missing(tmp_path: Path):
    assert _gate("--root", str(tmp_path / "nope")).returncode == cec.ac.EXIT_DATA_MISSING


def test_self_test_fixtures_all_caught():
    """门禁自证：坏夹具少抓一个，门禁就是空的。"""
    proc = _gate("--self-test")
    assert proc.returncode == cec.ac.EXIT_OK, proc.stdout + proc.stderr
    assert f"{len(cec.SELF_TEST_CASES)}/{len(cec.SELF_TEST_CASES)}" in proc.stderr + proc.stdout


# --------------------------------------------------------------------------- #
# 6. 契约常量自检：新增回合数组必须同步进 EPISODE_ARRAYS
# --------------------------------------------------------------------------- #
def test_summary_bindings_reference_known_arrays():
    for metric, arrays in cec.SUMMARY_BINDINGS.items():
        for name in arrays:
            assert name in cec.EPISODE_ARRAYS, f"{metric} 绑定了未登记数组 {name}"
