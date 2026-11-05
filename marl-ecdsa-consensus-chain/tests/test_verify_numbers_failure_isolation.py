#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""复算器的「失败隔离」与「双源校验真能跑」守卫（2026-11-06 审计）。

## 三处缺陷（全部实测，非推断）

### 1. 一条坏数据 = 全部 191 条失去校验

``main()`` 原只接
``except (FileNotFoundError, NotADirectoryError, PermissionError, OSError)``，
而 ``recompute`` 家族还会抛别的：``extract_field`` 的 ``KeyError``、
``float(None)`` 的 ``TypeError``、``load_json`` 的 ``JSONDecodeError``。

实测：把 NR-1 的一份数据文件写成
``{"summary": {"avg_env_reward_last_50": null}}``（很常见——某次跑挂了），
整跑输出

    TypeError: float() argument must be a string or a real number, not 'NoneType'

后退出，``--report`` 指定的文件**根本没生成**。报告在循环之后才写，所以一条
坏数据就把「191 条的体检表」变成「一段 traceback」：门禁从「有一条红」退化成
「没有门禁」，而读者拿到的信息量是零。

### 2. 登记缺陷被误诊成「数据缺失」（退出码 3，非阻断）

``_sources_present`` 只读 ``src.get("glob")``，而注册表里 ``globs`` 有 135 处、
``file`` 有 31 处。于是用 ``globs`` 登记的条目在复算提前返回（``files == 0``）时
**永远被判成「没有数据」**：实测把 NR-1 的 ``role=b`` 删掉（登记缺陷），报告写
「数据源缺失：本数据包不含该条目所需的任何结果文件」——数据明明都在盘上。
本模块的 docstring 反复警告「把门禁失败伪装成数据缺失」，这次伪装的是登记错误。

### 3. ``--check-mirror`` 自加入起从未跑通

``check_mirror`` 里 ``g = src["glob"]``：

* ``globs`` 条目 → ``KeyError: 'glob'``；
* ``file`` 条目 → ``KeyError: 'glob'``；
* NR-19 的字符串 sources（junit ``path#attr`` 引用）→
  ``TypeError: string indices must be integers``。

对真实注册表跑 ``--check-mirror``，第一条 NR-1 就崩；崩溃在写报告之前，所以
这项「repo↔backup 双源一致」承诺的产物是一段 traceback。它还只在单个 ``glob``
上比，``globs`` 的多批次并集只比了前半截；而零比较（镜像根不存在）时
``diffs == 0`` ⇒ ``consistent = True``，报告抬头写「双源一致：是（比较 0 个
文件）」——与 ``declared`` 为空的 fail-open 是同一个病。

## 本文件守护的不变式

1. 单条复算抛异常 ⇒ **该条** FAIL（带异常类型与出错位置），报告照写，其余条目照查；
2. 数据文件在盘上却读不出（坏值 / 半截 JSON）⇒ FAIL，不退化成 DATA_MISSING；
3. 「有数据」的判据与取数用同一套模式解析（``globs`` / ``glob`` / ``file``）；
4. ``check_mirror`` 对每种 source 形态都不抛异常，且结论三态
   （一致 / 有差异 / **未判定**），零比较绝不报「一致」；
5. ``--self-test`` 本身可用（CI 直接跑），且真能抓到上面每一条的回归。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
PY = sys.executable

import verify_numbers as vn  # noqa: E402  (conftest 已注入 scripts/**)

FIELD = vn._ST_FIELD


# --------------------------------------------------------------------------
# 夹具：合成注册表 / 数据 / 镜像（绝不碰仓库里的注册表与 results）
# --------------------------------------------------------------------------
def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _arm(root: Path, prefix: str, arm: str, values: List[Any]) -> None:
    for i, v in enumerate(values):
        _write_json(root / prefix / f"{arm}_seed{i}.json",
                    {"summary": {"avg_env_reward_last_50": v}})


def _two_sample(eid: str, prefix: str, declared: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": eid, "analysis": "two_sample", "status": "PASS",
        "sources": [
            {"globs": [f"{prefix}/a_seed*.json"], "field": FIELD, "role": "a"},
            {"globs": [f"{prefix}/b_seed*.json"], "field": FIELD, "role": "b"},
        ],
        "declared": declared, "tolerance": {"abs": 0.01},
    }


def _ok_declared() -> Dict[str, Any]:
    """配 ``a=[-7.0,-7.1,-6.9]`` / ``b=[-9.0,-9.1,-8.9]``（均值恰为 -7.0 / -9.0）。"""
    return {"mean_a": -7.0, "mean_b": -9.0, "n_a": 3, "n_b": 3}


def _run(tmp: Path, entries: List[Dict[str, Any]],
         extra: Optional[List[str]] = None) -> Tuple[int, Dict[str, Any], Path]:
    data = tmp / "data"
    data.mkdir(parents=True, exist_ok=True)
    regp = tmp / "registry.json"
    _write_json(regp, {"version": 1, "commit": "test", "entries": entries})
    rep = tmp / "report.json"
    rc = vn.main(["--registry", str(regp), "--data-root", str(data),
                  "--report", str(rep), "--overwrite"] + list(extra or []))
    doc = json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else {}
    return rc, doc, data


def _by_id(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {e["id"]: e for e in doc.get("entries") or []}


def _two_arm_data(data: Path, prefix: str = "p") -> None:
    _arm(data, prefix, "a", [-7.0, -7.1, -6.9])
    _arm(data, prefix, "b", [-9.0, -9.1, -8.9])


# --------------------------------------------------------------------------
# 1. 崩溃隔离
# --------------------------------------------------------------------------
def test_bad_value_no_longer_kills_the_whole_report(tmp_path):
    """坏值（null）曾让整跑 traceback 退出、一份报告都不留。"""
    bad = _two_sample("NR-T1", "bad", _ok_declared())
    good = _two_sample("NR-T2", "ok", _ok_declared())
    data = tmp_path / "data"
    data.mkdir(parents=True)
    _arm(data, "bad", "a", [None, -7.0, -7.0])
    _arm(data, "bad", "b", [-9.0, -9.0, -9.0])
    _two_arm_data(data, "ok")
    regp = tmp_path / "registry.json"
    _write_json(regp, {"version": 1, "commit": "test", "entries": [bad, good]})
    rep = tmp_path / "report.json"

    rc = vn.main(["--registry", str(regp), "--data-root", str(data),
                  "--report", str(rep), "--overwrite"])

    assert rep.exists(), "报告没产出：一条坏数据又把这整份体检表带崩了"
    doc = json.loads(rep.read_text(encoding="utf-8"))
    by = _by_id(doc)
    assert rc == vn.ac.EXIT_FAIL
    assert by["NR-T1"]["status"] == "FAIL", by["NR-T1"]["status"]
    assert by["NR-T1"]["crashed"] is True, "崩溃标记丢失，读者无法区分算错与崩了"
    assert doc["summary"]["crashed"] == 1, doc["summary"]


def test_crash_reason_names_the_exception_and_location(tmp_path):
    """FAIL 理由必须能定位：异常类型 + 出错文件:行号，而不是「见 traceback」。"""
    entry = _two_sample("NR-T3", "p", _ok_declared())
    data = tmp_path / "data"
    data.mkdir(parents=True)
    _arm(data, "p", "a", [None, -7.0, -7.0])
    _arm(data, "p", "b", [-9.0, -9.0, -9.0])
    _rc, doc, _ = _run(tmp_path, [entry])
    reason = _by_id(doc)["NR-T3"]["reason"]
    assert "复算抛异常" in reason, reason
    assert "SourceReadError" in reason, reason
    assert "verify_numbers.py:" in reason, reason
    assert "a_seed0.json" in reason, "没指出是哪份文件坏：{}".format(reason)


def test_crash_does_not_take_down_sibling_entries(tmp_path):
    """同批的正常条目必须照常判 PASS —— 隔离的意义就在这里。"""
    bad = _two_sample("NR-T4", "bad", _ok_declared())
    good = _two_sample("NR-T5", "ok", _ok_declared())
    data = tmp_path / "data"
    data.mkdir(parents=True)
    _arm(data, "bad", "a", [None, None, None])
    _arm(data, "bad", "b", [-9.0, -9.0, -9.0])
    _two_arm_data(data, "ok")
    regp = tmp_path / "registry.json"
    _write_json(regp, {"version": 1, "commit": "test", "entries": [bad, good]})
    rc = vn.main(["--registry", str(regp), "--data-root", str(data),
                  "--report", str(tmp_path / "r.json"), "--overwrite"])
    doc = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert _by_id(doc)["NR-T5"]["status"] == "PASS", _by_id(doc)["NR-T5"]
    assert rc == vn.ac.EXIT_FAIL, "有 FAIL 时退出码必须为 1"


def test_truncated_json_is_fail_not_data_missing(tmp_path):
    """半截 JSON（写盘时被打断）是坏数据，不是「本数据包没有这份结果」。"""
    entry = _two_sample("NR-T6", "p", _ok_declared())
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "p").mkdir()
    for i in range(3):
        (data / "p" / f"a_seed{i}.json").write_text('{"summary": {"avg_env', encoding="utf-8")
    _arm(data, "p", "b", [-9.0, -9.1, -8.9])
    rc, doc, _ = _run(tmp_path, [entry])
    status = _by_id(doc)["NR-T6"]["status"]
    assert status == "FAIL", f"半截 JSON 被报成 {status}"
    assert rc == vn.ac.EXIT_FAIL, f"退出码 {rc}（3 = 被误诊成数据缺失）"


def test_crashed_entry_without_declared_is_fail_not_pending(tmp_path):
    """崩溃优先于「declared 待补登」：PENDING 不阻断，不能把崩溃降级放过。"""
    entry = _two_sample("NR-T9", "p", {})
    entry["status"] = "PENDING"          # 登记还在补，但复算已经崩了
    data = tmp_path / "data"
    data.mkdir(parents=True)
    _arm(data, "p", "a", [None, -7.0, -7.0])
    _arm(data, "p", "b", [-9.0, -9.0, -9.0])
    rc, doc, _ = _run(tmp_path, [entry])
    got = _by_id(doc)["NR-T9"]
    assert got["status"] == "FAIL", f"崩溃被降级成 {got['status']}（PENDING 不阻断）"
    assert "复算抛异常" in got["reason"], got["reason"]
    assert rc == vn.ac.EXIT_FAIL, rc


def test_unreadable_existing_file_is_fail_not_data_missing(tmp_path, monkeypatch):
    """「文件在，但读不出」（权限/被占用）不是缺数据 —— 不许退化成退出码 3。"""
    entry = {"id": "NR-TU", "analysis": "consensus_row", "status": "PASS",
             "consensus_file": "curve.json",
             "match": {"n_nodes": 4, "byzantine_ratio": 0.25, "key": "k"},
             "declared": {"cw_success_rate": 1.0}}
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "curve.json").write_text("{}", encoding="utf-8")   # 文件确实在
    real = vn.ac.load_json

    def fake(path):
        if Path(path).name == "curve.json":
            raise PermissionError("被另一个进程占用")
        return real(path)

    monkeypatch.setattr(vn.ac, "load_json", fake)
    rc, doc, _ = _run(tmp_path, [entry])
    got = _by_id(doc)["NR-TU"]
    assert got["status"] == "FAIL", f"读不出被报成 {got['status']}"
    assert "读取失败" in got["reason"], got["reason"]
    assert rc == vn.ac.EXIT_FAIL, rc


def test_missing_file_still_data_missing_not_fail(tmp_path):
    """反向守卫：文件根本不存在时仍是 DATA_MISSING（本机 174/191 条属于此列）。"""
    entry = {"id": "NR-TV", "analysis": "consensus_row", "status": "PASS",
             "consensus_file": "nope.json",
             "match": {"n_nodes": 4, "byzantine_ratio": 0.25, "key": "k"},
             "declared": {"cw_success_rate": 1.0}}
    rc, doc, _ = _run(tmp_path, [entry])
    got = _by_id(doc)["NR-TV"]
    assert got["status"] == "DATA_MISSING", got["status"]
    assert rc == vn.ac.EXIT_DATA_MISSING, rc


def test_collect_source_raises_with_file_and_field_context(tmp_path):
    """取值失败必须带上「哪份文件、哪个字段」，否则 191 条里没法找。"""
    root = tmp_path / "d"
    root.mkdir()
    _write_json(root / "x_seed0.json", {"summary": {}})      # 字段缺失
    src = {"globs": ["x_seed*.json"], "field": "summary.avg_env_reward_last_50",
           "role": "a"}
    with pytest.raises(vn.SourceReadError) as ei:
        vn._collect_source(root, src)
    assert "x_seed0.json" in str(ei.value)
    assert "avg_env_reward_last_50" in str(ei.value)


def test_collect_source_rejects_non_numeric_value(tmp_path):
    root = tmp_path / "d"
    root.mkdir()
    _write_json(root / "x_seed0.json", {"summary": {"avg_env_reward_last_50": "n/a"}})
    src = {"globs": ["x_seed*.json"], "field": FIELD, "role": "a"}
    with pytest.raises(vn.SourceReadError) as ei:
        vn._collect_source(root, src)
    assert "不是数值" in str(ei.value)


# --------------------------------------------------------------------------
# 2. 登记缺陷 ≠ 数据缺失
# --------------------------------------------------------------------------
def test_missing_role_is_fail_not_data_missing(tmp_path):
    """登记缺 role=b 是登记缺陷，数据都在盘上 —— 曾报成「数据缺失」退出码 3。"""
    entry = _two_sample("NR-T7", "p", _ok_declared())
    entry["sources"] = [s for s in entry["sources"] if s["role"] == "a"]
    data = tmp_path / "data"
    data.mkdir(parents=True)
    _two_arm_data(data, "p")
    rc, doc, _ = _run(tmp_path, [entry])
    got = _by_id(doc)["NR-T7"]
    assert got["status"] == "FAIL", f"登记缺陷被报成 {got['status']}"
    assert "缺 role=b" in got["reason"], got["reason"]
    assert rc == vn.ac.EXIT_FAIL, f"退出码 {rc}（3 = 伪装成数据缺失，不阻断）"


def test_sources_present_uses_globs(tmp_path):
    """``globs`` 是当前注册表最主流的写法（135 处）——「有没有数据」必须认它。"""
    data = tmp_path / "d"
    _arm(data, "p", "a", [-7.0])
    entry = {"id": "X", "sources": [
        {"globs": ["p/a_seed*.json"], "field": FIELD, "role": "a"}]}
    assert vn._sources_present(entry, data) is True


def test_sources_present_uses_file_key(tmp_path):
    data = tmp_path / "d"
    data.mkdir(parents=True)
    _write_json(data / "flat.json", {"sign_ms": 1.5})
    entry = {"id": "X", "sources": [{"file": "flat.json", "field": "sign_ms"}]}
    assert vn._sources_present(entry, data) is True


def test_sources_present_false_when_truly_absent(tmp_path):
    data = tmp_path / "d"
    data.mkdir(parents=True)
    entry = {"id": "X", "sources": [
        {"globs": ["nothing/*.json"], "field": FIELD, "role": "a"}]}
    assert vn._sources_present(entry, data) is False


def test_genuinely_missing_data_still_data_missing(tmp_path):
    """修完误诊不能走到反面：真没有数据时仍须是 DATA_MISSING（退出码 3）。"""
    rc, doc, _ = _run(tmp_path, [_two_sample("NR-T8", "nowhere", _ok_declared())])
    got = _by_id(doc)["NR-T8"]
    assert got["status"] == "DATA_MISSING", got["status"]
    assert rc == vn.ac.EXIT_DATA_MISSING, rc


# --------------------------------------------------------------------------
# 3. 双源一致性：三态 + 全 source 形态
# --------------------------------------------------------------------------
def _mirror_registry(sources: List[Any], eid: str = "NR-M") -> Dict[str, Any]:
    return {"version": 1, "entries": [{"id": eid, "sources": sources}]}


def test_check_mirror_handles_globs_sources(tmp_path):
    """旧实现第一行就 ``KeyError: 'glob'`` —— 对 globs 条目从未工作过。"""
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    _arm(repo, "p", "a", [-7.0, -7.1, -6.9])
    _arm(mir, "p", "a", [-7.0, -7.1, -6.9])
    reg = _mirror_registry([{"globs": ["p/a_seed*.json"], "field": FIELD, "role": "a"}])
    info = vn.check_mirror(reg, repo, mir)
    assert info["files_compared"] == 3, info
    assert info["consistent"] is True, info


def test_check_mirror_handles_file_sources(tmp_path):
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    _write_json(repo / "flat.json", {"sign_ms": 1.5})
    _write_json(mir / "flat.json", {"sign_ms": 1.5})
    reg = _mirror_registry([{"file": "flat.json", "field": "sign_ms"}])
    info = vn.check_mirror(reg, repo, mir)
    assert info["files_compared"] == 1, info
    assert info["consistent"] is True, info


def test_check_mirror_records_static_refs_instead_of_crashing(tmp_path):
    """NR-19 的 sources 是 junit 的 ``path#attr`` 字符串 —— 旧实现 TypeError。"""
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    repo.mkdir(parents=True)
    mir.mkdir(parents=True)
    reg = _mirror_registry(["reports/junit.xml#testsuite@tests"])
    info = vn.check_mirror(reg, repo, mir)
    assert any(s["reason"] == "static_ref" for s in info["skipped"]), info
    assert info["consistent"] is None, "没有可比项时说「一致」就是假话"


def test_check_mirror_absent_root_is_undetermined(tmp_path):
    """镜像根不存在 ⇒ 未判定。旧实现 ``diffs==0`` ⇒ 「一致（比较 0 个文件）」。"""
    repo = tmp_path / "repo"
    _arm(repo, "p", "a", [-7.0])
    reg = _mirror_registry([{"globs": ["p/a_seed*.json"], "field": FIELD, "role": "a"}])
    info = vn.check_mirror(reg, repo, tmp_path / "no_such_mirror")
    assert info["consistent"] is None, info
    assert "不存在" in info["reason"], info["reason"]


def test_check_mirror_zero_comparison_is_undetermined(tmp_path):
    """文件名对得上但字段不可机读（描述性 field）⇒ 读不懂，未判定。"""
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    _arm(repo, "p", "a", [-7.0])
    _arm(mir, "p", "a", [-7.0])
    reg = _mirror_registry([{"globs": ["p/a_seed*.json"],
                             "field": "签名长度常量 / 说明文字", "role": "a"}])
    info = vn.check_mirror(reg, repo, mir)
    assert info["files_compared"] == 0, info
    assert info["consistent"] is None, info
    assert info["skipped"], "不可机读的字段必须留痕，不能静默略过"


def test_check_mirror_detects_value_drift(tmp_path):
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    _arm(repo, "p", "a", [-7.0, -7.1, -6.9])
    _arm(mir, "p", "a", [-7.0, -7.2, -6.9])
    reg = _mirror_registry([{"globs": ["p/a_seed*.json"], "field": FIELD, "role": "a"}])
    info = vn.check_mirror(reg, repo, mir)
    assert info["consistent"] is False, info
    assert len(info["diffs"]) == 1, info["diffs"]


def test_check_mirror_detects_name_set_drift(tmp_path):
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    _arm(repo, "p", "a", [-7.0, -7.1])
    _arm(mir, "p", "a", [-7.0])
    mir.mkdir(parents=True, exist_ok=True)
    reg = _mirror_registry([{"globs": ["p/a_seed*.json"], "field": FIELD, "role": "a"}])
    info = vn.check_mirror(reg, repo, mir)
    assert info["consistent"] is False, info
    assert info["diffs"][0]["only_repo"] == ["a_seed1.json"], info["diffs"]


def test_check_mirror_skips_sources_outside_data_root(tmp_path):
    """``deliverables/`` 类源不在双源镜像范围：既不能报差异，也不能当一致。"""
    repo = tmp_path / "data"
    mir = tmp_path / "mirror"
    mir.mkdir(parents=True)
    _write_json(repo / "flat.json", {"sign_ms": 1.5})
    reg = _mirror_registry([{"file": "deliverables/x.json", "field": "sign_ms"}])
    info = vn.check_mirror(reg, repo, mir)
    assert info["consistent"] is None, info
    assert any(s["reason"] == "outside_data_root" for s in info["skipped"]), info["skipped"]


def test_check_mirror_only_filters_entries(tmp_path):
    repo, mir = tmp_path / "repo", tmp_path / "mirror"
    _arm(repo, "p", "a", [-7.0])
    _arm(repo, "q", "a", [-7.0])
    _arm(mir, "p", "a", [-7.0])
    reg = {"version": 1, "entries": [
        {"id": "NR-A", "sources": [{"globs": ["p/a_seed*.json"], "field": FIELD, "role": "a"}]},
        {"id": "NR-B", "sources": [{"globs": ["q/a_seed*.json"], "field": FIELD, "role": "a"}]},
    ]}
    info = vn.check_mirror(reg, repo, mir, only={"NR-A"})
    assert info["files_compared"] == 1, info
    assert info["consistent"] is True, "未选中的 NR-B 不该把一致性带红"


def test_render_mirror_line_distinguishes_four_states():
    """「未检查 / 未判定 / 是 / 否」四种状态在报告抬头必须一眼可分。"""
    not_run = vn._render_mirror_line({"mirror": None, "mirror_consistent": None})
    undetermined = vn._render_mirror_line({
        "mirror": {"files_compared": 0, "diffs": [], "reason": "零次比较"},
        "mirror_consistent": None})
    ok = vn._render_mirror_line({
        "mirror": {"files_compared": 3, "diffs": []}, "mirror_consistent": True})
    bad = vn._render_mirror_line({
        "mirror": {"files_compared": 3, "diffs": [{"file": "x"}]},
        "mirror_consistent": False})
    assert "未检查" in not_run and "未判定" not in not_run
    assert "未判定" in undetermined and "零次比较" in undetermined
    assert "是" in ok and "3" in ok
    assert "否" in bad and "1" in bad
    assert len({not_run, undetermined, ok, bad}) == 4, "四态出现混淆"


# --------------------------------------------------------------------------
# 4. 自证可用（CI 直接跑的入口）
# --------------------------------------------------------------------------
def test_self_test_passes_in_process():
    assert vn._self_test() == vn.ac.EXIT_OK


def test_cli_self_test_exit_zero():
    proc = subprocess.run([PY, "-X", "utf8", str(SCRIPTS / "verify_numbers.py"),
                           "--self-test"], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "自证通过" in proc.stdout, proc.stdout


def test_self_test_does_not_read_repository_data():
    """自证必须在临时目录里成形：不许依赖仓库的注册表 / results 是否存在。"""
    src = (SCRIPTS / "verify_numbers.py").read_text(encoding="utf-8")
    body = src.split("def _self_test()", 1)[1].split("def _resolve(", 1)[0]
    assert "ac.REGISTRY_PATH" not in body, "自证读了权威注册表 —— 换机即不可复现"
    assert "ac.RESULTS_DIR" not in body, "自证读了仓库 results —— 换机即不可复现"
