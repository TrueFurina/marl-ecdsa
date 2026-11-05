# -*- coding: utf-8 -*-
"""``check_evidence_closure.py`` 的第二层契约：**读不懂 ≠ 没有**。

背景（2026-11-06 实测）
----------------------
门禁第一版自称 fail-closed，但四类"读不懂"都被当成"没有"，于是静默放行：

1. ``n_episodes`` 只认 ``int``：``500.0``（numpy 除法产物）与 ``"500"``
   （配置被序列化成字符串）退化成"没声明"，100/500 的截断以
   ``pass: undeclared`` 出线；
2. 非数值列（字符串 / null）被 ``if arr`` 丢出 ``usable``：函数注释写着
   "宁可 unknown，不猜"，实际是"当作这列不存在"，只要剩一列正常就判
   ``pass: closed``；
3. 空数组同样被丢掉：声明 500 却给 ``[]`` 是 0/500，属**截断**；
4. 顶层不是对象的 JSON 被 ``continue``：既不计入分母也不留记录，
   输出里的"扫描 N 个 JSON"不再等于目录里的文件数。

外加第五处：``--compare`` 的 glob 一条都没匹配到、或匹配到的文件全都没有
种子/口径，输出一张空表然后 exit 0 —— "什么都没比"被报成"比较完成"。

本文件把这五种静默钉成红。**注意**：报告类文件（纯汇总、无回合数组）不能被
这些新判定误伤，所以每条 fail-closed 都配一个"不该报"的对照。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_evidence_closure.py"

sys.path.insert(0, str(GATE.parent))
import check_evidence_closure as cec  # noqa: E402


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
def _run_doc(declared=500, length=500) -> dict:
    """一份形态正常的运行结果（默认声明 500 跑满 500）。"""
    return {
        "config": {"n_episodes": declared, "seed": 1},
        "summary": {"total_episodes": declared},
        "episode_rewards": [float(i % 13) - 40 for i in range(length)],
        "cooperation_rates": [0.001 * (i % 997) for i in range(length)],
    }


def _write(root: Path, name: str, doc) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _gate(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(GATE), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )


# --------------------------------------------------------------------------- #
# 1. 声明的写法不改变它是不是声明
# --------------------------------------------------------------------------- #
def test_float_declared_count_is_not_ignored():
    """``n_episodes: 500.0`` 是声明；当成"没声明"就把截断放行了。"""
    doc = _run_doc()
    doc["config"]["n_episodes"] = 500.0
    doc["summary"]["total_episodes"] = 500.0
    doc["episode_rewards"] = doc["episode_rewards"][:100]
    doc["cooperation_rates"] = doc["cooperation_rates"][:100]
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_TRUNCATED, verdict
    assert verdict["reason_code"] == "length_mismatch"
    assert verdict["declared_episodes"] == 500
    assert verdict["actual"]["episode_rewards"] == 100


def test_numeric_string_declared_count_is_accepted():
    doc = _run_doc()
    doc["config"]["n_episodes"] = "500"
    doc["episode_rewards"] = doc["episode_rewards"][:100]
    doc["cooperation_rates"] = doc["cooperation_rates"][:100]
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_TRUNCATED, verdict
    assert verdict["declared_episodes"] == 500


def test_junk_declaration_is_unknown_not_undeclared():
    """``"abc"`` 读不懂 → unknown；旧实现把它当"没声明"再判 pass。"""
    doc = _run_doc()
    doc["config"]["n_episodes"] = "abc"
    doc.pop("summary")
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_UNKNOWN, verdict
    assert verdict["reason_code"] == "invalid_declaration"
    assert "config.n_episodes" in verdict["detail"]


def test_zero_declaration_is_unknown():
    doc = _run_doc()
    doc["config"]["n_episodes"] = 0
    doc.pop("summary")
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "invalid_declaration"


def test_null_declaration_still_means_absent():
    """``null`` 是"没有值"，不能因为要 fail-closed 就把 null 判成读不懂。"""
    doc = {"config": {"n_episodes": None, "seed": 1},
           "episode_rewards": [float(i) for i in range(120)],
           "cooperation_rates": [0.001 * (i % 97) for i in range(120)]}
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_PASS, verdict
    assert verdict["reason_code"] == "undeclared"


def test_report_with_junk_declaration_stays_not_applicable():
    """纯汇总报告里出现怪值不该把整棵树按死（无数组、无强声明）。"""
    verdict = cec.inspect_document({"title": "r", "n_episodes": "见正文"})
    assert verdict["status"] == cec.STATUS_NA, verdict
    assert verdict["reason_code"] == "not_a_run"


# --------------------------------------------------------------------------- #
# 2. 列在但读不懂 / 列在但是空的
# --------------------------------------------------------------------------- #
def test_numeric_string_column_is_unknown_not_dropped():
    """一列全是 ``"0.5"`` 字符串：读不出数，不许当这列不存在。"""
    doc = _run_doc()
    doc["cooperation_rates"] = ["0.5"] * 500
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_UNKNOWN, verdict
    assert verdict["reason_code"] == "malformed_column"
    assert "cooperation_rates" in verdict["detail"]


def test_null_column_is_unknown_not_dropped():
    doc = _run_doc()
    doc["cooperation_rates"] = [None] * 500
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "malformed_column"


def test_malformed_column_beats_no_evidence():
    """全列都读不懂时，理由必须是"读不懂"，不能退化成"没有证据"。"""
    doc = {"config": {"n_episodes": 500},
           "episode_rewards": "oops",
           "cooperation_rates": {"0": 0.5}}
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_UNKNOWN
    assert verdict["reason_code"] == "malformed_column"


def test_empty_array_is_truncation_not_missing_column():
    """声明 500 给 ``[]`` 是 0/500，属截断。"""
    doc = _run_doc()
    doc["cooperation_rates"] = []
    verdict = cec.inspect_document(doc)
    assert verdict["status"] == cec.STATUS_TRUNCATED, verdict
    assert verdict["actual"] == {"cooperation_rates": 0}


def test_absent_column_is_still_not_an_error():
    """真的没有这列（键不存在）不算问题——只有"键在、读不懂"才拦。"""
    doc = _run_doc()
    doc.pop("cooperation_rates")
    assert cec.inspect_document(doc)["status"] == cec.STATUS_PASS


# --------------------------------------------------------------------------- #
# 3. 顶层不是对象的 JSON 必须留记录
# --------------------------------------------------------------------------- #
def test_scan_root_records_non_object_json(tmp_path: Path):
    _write(tmp_path, "good.json", _run_doc(declared=120, length=120))
    (tmp_path / "list.json").write_text(
        json.dumps([{"episode": i} for i in range(5)]), encoding="utf-8")
    (tmp_path / "scalar.json").write_text("42", encoding="utf-8")

    records = cec.scan_root(tmp_path)
    by_file = {r["file"]: r for r in records}
    assert len(records) == 3, [r["file"] for r in records]
    assert by_file["list.json"]["reason_code"] == "not_an_object"
    assert by_file["scalar.json"]["reason_code"] == "not_an_object"
    assert by_file["good.json"]["status"] == cec.STATUS_PASS


def test_gate_counts_every_json_file(tmp_path: Path):
    """输出里的"扫描 N 个 JSON"必须等于目录里的文件数。"""
    _write(tmp_path, "good.json", _run_doc(declared=120, length=120))
    (tmp_path / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
    proc = _gate("--root", str(tmp_path))
    assert f"扫描 2 个 JSON" in proc.stdout, proc.stdout
    assert "not_an_object" in proc.stdout


# --------------------------------------------------------------------------- #
# 4. 偏序：没比对到东西不许报成功
# --------------------------------------------------------------------------- #
def test_partial_order_reports_skipped_samples(tmp_path: Path):
    doc = _run_doc(declared=20, length=20)
    _write(tmp_path, "arm_seed1.json", doc)
    no_seed = _run_doc(declared=20, length=20)
    no_seed["config"].pop("seed")
    _write(tmp_path, "plain.json", no_seed)

    result = cec.build_partial_order(sorted(tmp_path.glob("*.json")), "config.n_episodes")
    assert result["skipped"]["no_seed"] == 1, result
    assert result["total_score"] is None
    assert result["ranking_emitted"] is False


def test_compare_without_any_match_exits_data_missing(tmp_path: Path):
    _write(tmp_path, "good.json", _run_doc(declared=120, length=120))
    proc = _gate("--root", str(tmp_path), "--compare", "no_such_dir/*.json")
    assert proc.returncode == cec.ac.EXIT_DATA_MISSING, proc.stdout + proc.stderr
    assert "一个文件都没匹配到" in proc.stderr


def test_compare_without_usable_arms_exits_data_missing(tmp_path: Path, monkeypatch):
    """匹配到文件但全无种子 → 实际比对 0 条，不得 exit 0。"""
    root = tmp_path / "scan"
    _write(root, "good.json", _run_doc(declared=120, length=120))
    arena = tmp_path / "arms"
    doc = _run_doc(declared=20, length=20)
    doc["config"].pop("seed")
    _write(arena, "arm_a.json", doc)
    _write(arena, "arm_b.json", doc)

    monkeypatch.setattr(cec.ac, "REPO_ROOT", arena, raising=False)
    code = cec.main(["--root", str(root), "--compare", "arm_*.json"])
    assert code == cec.ac.EXIT_DATA_MISSING
