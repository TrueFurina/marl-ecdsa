#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""「登记 PASS 但零断言」必须 fail-closed（2026-11-06 审计守卫）。

## 缺陷（实测，非推断）

``scripts/verify_numbers.py::compare()`` 只遍历 ``declared`` 的键：

    ok, deltas = True, {}
    for key, dec in entry.get("declared", {}).items():   # declared 为空 → 一次都不进
        ...

``declared`` 为空时循环体不执行，``ok`` 保持初值 ``True`` ⇒ **判 PASS**，
``deltas={}``（零次比对），退出码 0。两条独立实测：

1. **无数据也 PASS**：清空 ``results/`` 后跑全量 191 条，NR-180~183
   （``analysis=none`` + ``sources=[]`` + ``declared={}``）判 PASS，
   其余 187 条是 DATA_MISSING/PENDING/INVALID —— 只有它们「不需要数据就能过」。
2. **数据相反也 PASS**：把 NR-121 的 source 指向一份「吞吐 1 pkg/s、拦截
   0/999999」的 JSON（主张是 344,279 pkg/s、100% 拦截），仍旧 PASS、
   ``deltas={}``、退出码 0。

于是报告抬头 ``PASS=184`` 里有 7 条（NR-120/121/122/180/181/182/183）是空断言。

## 修法（本文件守护的四条不变式）

1. ``compare()`` 对空 / 缺失的 ``declared`` 直接返回失败（不再靠循环体碰巧不进）；
2. ``main()`` 把「登记 PASS 但无可复算值」判为 **UNVERIFIED**（阻断，退出码 1），
   「登记 PENDING 且无可复算值」保持 PENDING（不阻断，``--strict`` 才阻断）；
3. NR-180~183 接真数据（``analysis=benchmark`` + 嵌套 ``paths``），源文件缺失时
   退化成 DATA_MISSING 而不是继续 PASS；
4. 仓库镜像登记表里**不允许**存在「status=PASS 且 declared 为空」的条目 ——
   这条独立于代码，能抓住「有人用旧权威源 ``--sync`` 把迁移覆盖回去」。

第 4 条是持久守卫：``check_registry_mirror.py --sync`` 会用权威源整份覆盖镜像，
若权威源仍是被审计前的旧内容，本文件的第 4 条会立刻变红。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIRROR_REGISTRY = REPO_ROOT / "number_registry.json"
SCRIPTS = REPO_ROOT / "scripts"
PY = sys.executable

import verify_numbers as vn  # noqa: E402  (conftest 已注入 scripts/**)


# --------------------------------------------------------------------------
# 1. 比对器：空 declared 必须 fail-closed
# --------------------------------------------------------------------------

def test_compare_rejects_empty_declared():
    """declared={} 时旧实现返回 True（零比对即 PASS）—— 现在必须 False。"""
    ok, deltas = vn.compare(
        {"id": "NR-X", "declared": {}, "tolerance": {"abs": 0.01}},
        {"throughput_pkg_s": 1, "blocked": 0})
    assert not ok, "空 declared 被当成「全部通过」—— PASS 会退化成「没检查」"
    assert "__declared__" in deltas, "必须给出可诊断的原因键，不能只返回 False"


def test_compare_rejects_missing_declared_key():
    """完全没有 declared 键（比空 dict 更早的形态）同样必须失败。"""
    ok, deltas = vn.compare({"id": "NR-Y", "tolerance": {"abs": 0.01}}, {"x": 1.0})
    assert not ok, "缺 declared 键被放过 —— 该条在报告里会算进 PASS"
    assert "__declared__" in deltas


def test_compare_keeps_exact_semantics_when_declared_present():
    """空 declared 的收紧不得改变有值条目的判据（漂移照样要红）。"""
    entry = {"id": "NR-Z", "declared": {"coop": 0.825}, "tolerance": {"abs": 0.01}}
    assert vn.compare(entry, {"coop": 0.825})[0]
    ok, deltas = vn.compare(entry, {"coop": 0.5})
    assert not ok and deltas["coop"] == pytest.approx(0.325)


# --------------------------------------------------------------------------
# 2. 门禁状态机：UNVERIFIED / PENDING / INVALID 的分工
# --------------------------------------------------------------------------

def _run_gate(tmp_path: Path, entries, extra_args=()):
    """用一份最小登记表跑 main()，返回 (exit_code, report_dict)。"""
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    report = tmp_path / "report.json"
    rc = vn.main(["--registry", str(reg), "--data-root", str(data),
                  "--report", str(report), "--overwrite", *extra_args])
    doc = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    return rc, doc


def test_pass_without_declared_becomes_unverified_and_blocks(tmp_path):
    """登记 status=PASS 但没有任何可复算值 → UNVERIFIED（退出码 1、不计 PASS）。"""
    rc, doc = _run_gate(tmp_path, [
        {"id": "NR-901", "analysis": "none", "status": "PASS",
         "sources": [], "declared": {}, "tolerance": {"abs": 0.01}},
    ])
    assert rc == vn.ac.EXIT_FAIL, "零断言的 PASS 未被阻断"
    assert doc["entries"][0]["status"] == "UNVERIFIED"
    assert doc["summary"]["pass"] == 0, "UNVERIFIED 不得计入 PASS"
    assert doc["summary"]["unverified"] == 1


def test_pending_without_declared_stays_pending(tmp_path):
    """登记 PENDING（待补登）时保持 PENDING：不阻断，但出现在汇总里。"""
    rc, doc = _run_gate(tmp_path, [
        {"id": "NR-902", "analysis": "none", "status": "PENDING",
         "sources": [], "declared": {}, "tolerance": {"abs": 0.01}},
    ])
    assert rc == vn.ac.EXIT_OK
    assert doc["entries"][0]["status"] == "PENDING"
    assert doc["summary"]["pending"] == 1


def test_pending_without_declared_blocks_under_strict(tmp_path):
    """--strict 下「待补登」必须阻断（交稿前不许有未核验条目）。"""
    rc, _ = _run_gate(tmp_path, [
        {"id": "NR-903", "analysis": "none", "status": "PENDING",
         "sources": [], "declared": {}, "tolerance": {"abs": 0.01}},
    ], extra_args=("--strict",))
    assert rc == vn.ac.EXIT_STRICT_PENDING


def test_invalid_entry_is_not_reclassified(tmp_path):
    """已声明 INVALID（已撤回的主张）不应被改判成 UNVERIFIED —— 两者语义不同。"""
    rc, doc = _run_gate(tmp_path, [
        {"id": "NR-904", "analysis": "none", "status": "INVALID",
         "sources": [], "declared": {}, "tolerance": {"abs": 0.01}},
    ])
    assert rc == vn.ac.EXIT_OK
    assert doc["entries"][0]["status"] == "INVALID"


# --------------------------------------------------------------------------
# 3. 嵌套取数：NR-180~183 接的真数据
# --------------------------------------------------------------------------

_DOC = {
    "ml_defender": {"train_accuracy": 0.9882, "heldout_accuracy": 0.9879},
    "runs": {
        "L1": [{"seed": 11, "coop_rate": 0.995}, {"seed": 23, "coop_rate": 0.995}],
        "L2": [{"seed": 11, "coop_rate": 0.825}, {"seed": 23, "coop_rate": 0.845}],
    },
}


def test_json_path_nested_field():
    assert vn._json_path_value(_DOC, "ml_defender.train_accuracy")[0] == pytest.approx(0.9882)


def test_json_path_list_aggregations():
    assert vn._json_path_value(_DOC, "runs.L1[].coop_rate")[0] == pytest.approx(0.995)
    assert vn._json_path_value(_DOC, "runs.L2[].coop_rate#min")[0] == pytest.approx(0.825)
    assert vn._json_path_value(_DOC, "runs.L2[].coop_rate#max")[0] == pytest.approx(0.845)
    assert vn._json_path_value(_DOC, "runs.L2[].coop_rate#n")[0] == 2
    assert vn._json_path_value(_DOC, "runs.L2[].coop_rate#sum")[0] == pytest.approx(1.67)


def test_json_path_selector():
    assert vn._json_path_value(_DOC, "runs.L2[seed=11].coop_rate")[0] == pytest.approx(0.825)


@pytest.mark.parametrize("path", [
    "ml_defender.nope",                  # 缺字段
    "runs.L2[seed=99].coop_rate",        # 选择器命中 0 项
    "runs.L1[].coop_rate#median",        # 未知聚合
])
def test_json_path_errors_are_reported_not_zero(path):
    """取不到数必须给 err —— 静默返回 0 会让空断言换个形式复活。"""
    val, err = vn._json_path_value(_DOC, path)
    assert val is None and err, f"{path} 应当报错，实际 value={val!r} err={err!r}"


def test_wired_ml_entries_pass_against_repo_sources(tmp_path):
    """迁移后的 NR-180~183 必须真能复算通过（computed 非空、status=PASS）。"""
    if not MIRROR_REGISTRY.exists():
        pytest.skip("仓库内无登记表镜像")
    doc = json.loads(MIRROR_REGISTRY.read_text(encoding="utf-8"))
    ids = {"NR-180", "NR-181", "NR-182", "NR-183"}
    entries = [e for e in doc["entries"] if e.get("id") in ids]
    if len(entries) != 4:
        pytest.skip("登记表中缺少 NR-180~183")
    for e in entries:
        assert e.get("analysis") == "benchmark", \
            f"{e['id']} 又退回 analysis=none（零断言形态）"
        assert e.get("declared"), f"{e['id']} declared 为空"

    out = tmp_path / "_pytest_nr180.json"
    rc = vn.main(["--registry", str(MIRROR_REGISTRY),
                  "--data-root", str(vn.ac.RESULTS_DIR),
                  "--report", str(out), "--overwrite",
                  "--only", ",".join(sorted(ids))])
    assert rc == vn.ac.EXIT_OK, "接真数据后仍不通过（源文件或 paths 口径有问题）"
    rep = json.loads(out.read_text(encoding="utf-8"))
    for e in rep["entries"]:
        assert e["status"] == "PASS", f"{e['id']} status={e['status']} reason={e['reason']}"
        assert e["computed"], f"{e['id']} computed 为空 —— 仍是零比对"


def test_wired_entry_catches_drift(tmp_path):
    """源数据漂移必须被抓到（迁移前同一条是 PASS 且 deltas={}）。"""
    data = tmp_path / "attacker.json"
    data.write_text(json.dumps({
        "runs": {"L2_adaptive": [{"seed": 11, "coop_rate": 0.5}]},
    }), encoding="utf-8")
    rc, doc = _run_gate(tmp_path, [{
        "id": "NR-905", "analysis": "benchmark", "status": "PASS",
        "sources": [{"file": str(data),
                     "paths": {"L2_seed11_coop": "runs.L2_adaptive[seed=11].coop_rate"}}],
        "declared": {"L2_seed11_coop": 0.825},
        "tolerance": {"abs": 0.01},
    }])
    assert rc == vn.ac.EXIT_FAIL
    assert doc["entries"][0]["status"] == "FAIL"
    assert doc["entries"][0]["deltas"]["L2_seed11_coop"] == pytest.approx(0.325)


def test_wired_entry_reports_missing_source_not_pass(tmp_path):
    """源文件缺失 → DATA_MISSING（可诊断），绝不能继续 PASS。"""
    rc, doc = _run_gate(tmp_path, [{
        "id": "NR-906", "analysis": "benchmark", "status": "PASS",
        "sources": [{"file": str(tmp_path / "gone.json"),
                     "paths": {"x": "a.b"}}],
        "declared": {"x": 1.0}, "tolerance": {"abs": 0.01},
    }])
    assert doc["entries"][0]["status"] == "DATA_MISSING"
    assert rc == vn.ac.EXIT_DATA_MISSING


# --------------------------------------------------------------------------
# 4. 登记表不变式（独立于代码，抓「旧权威源 --sync 覆盖回来」）
# --------------------------------------------------------------------------

def test_registry_has_no_pass_entry_without_declared():
    if not MIRROR_REGISTRY.exists():
        pytest.skip("仓库内无登记表镜像")
    doc = json.loads(MIRROR_REGISTRY.read_text(encoding="utf-8"))
    bad = [e["id"] for e in doc["entries"]
           if e.get("status") == "PASS" and not e.get("declared")]
    assert not bad, (
        "以下条目登记 PASS 但 declared 为空（PASS 无断言支撑）：%s\n"
        "若刚跑过 check_registry_mirror.py --sync，说明权威源还是被审计前的旧内容，"
        "先跑 scripts/wire_unverified_entries_20261106.py --apply --registry <权威源>"
        % ", ".join(bad))


def test_mirror_fingerprint_matches_own_content():
    """镜像记录的 _mirror_sha256 必须等于镜像自身内容指纹。

    迁移改内容时必须同步重算指纹（wire_unverified_entries_20261106.py 会做），
    否则「镜像自洽」这条不变式失守，check_registry_mirror 的判定会失真。
    """
    if not MIRROR_REGISTRY.exists():
        pytest.skip("仓库内无登记表镜像")
    sys.path.insert(0, str(SCRIPTS))
    import check_registry_mirror as crm  # noqa: E402
    doc = json.loads(MIRROR_REGISTRY.read_text(encoding="utf-8"))
    assert doc.get("_mirror_sha256") == crm.entity_fingerprint(doc), (
        "镜像指纹与自身内容不符：迁移后忘了重算 _mirror_sha256")


def test_migration_script_is_idempotent(tmp_path):
    """迁移脚本重复执行不得二次改写（不追加第二条 note、不覆盖已有 declared）。"""
    if not MIRROR_REGISTRY.exists():
        pytest.skip("仓库内无登记表镜像")
    work = tmp_path / "reg.json"
    shutil.copyfile(MIRROR_REGISTRY, work)
    cmd = [PY, "-X", "utf8", str(SCRIPTS / "wire_unverified_entries_20261106.py"),
           "--registry", str(work), "--apply"]
    first = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    assert first.returncode == 0, first.stdout + first.stderr
    after_first = work.read_bytes()
    second = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert second.returncode == 0, second.stdout + second.stderr
    assert work.read_bytes() == after_first, "迁移脚本不幂等：第二次执行又改了内容"
    assert "[NOOP]" in second.stdout or "未写盘" in second.stdout
