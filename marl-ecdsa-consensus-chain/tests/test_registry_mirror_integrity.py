#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``check_registry_mirror.py`` 的「CI 上唯一生效的校验只查键不查内容」回归测试（2026-11-08）。

背景
----
权威登记表 ``deliverables/number_registry.json`` **不入库**，所以 CI 里这道门禁
必然走「权威缺失」分支，唯一生效的检查是 ``structural_check()`` —— 它只看
「有没有 id / declared / analysis / sources 这些键」。实测（修前）以下五种镜像
全部打印「[ok] 结构校验通过」并 ``exit 0``：

  ``{"entries": []}`` / 3 条键齐但内容全假的条目 / 真实镜像改一个数字 /
  删掉一条 / 删掉 ``_mirror_sha256``

另外损坏 JSON 与 UTF-16 镜像会直接抛 traceback（无诊断）。

修法核心：``_mirror_sha256`` 是 ``--sync`` 时按权威**实体内容**算出的，而镜像实体
是权威的字节级副本，故 ``entity_fingerprint(strip_mirror(镜像))`` 必须等于它 ——
这个判据不需要权威源在场，却能抓住任何对镜像实体的手改。
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_registry_mirror.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_registry_mirror as crm  # noqa: E402


def _legal_doc() -> dict:
    d = {"entries": [{"id": f"NR-{i}", "declared": {"value": i},
                      "analysis": "pytest", "sources": []} for i in range(3)]}
    d["_mirror_sha256"] = crm.entity_fingerprint(d)
    return d


def _cli(mir: Path, extra: tuple[str, ...] = ()) -> tuple[int, str]:
    proc = subprocess.run(
        [PY, "-X", "utf8", str(GATE),
         "--registry", str(mir.parent / "NO_SUCH_AUTHORITY.json"),
         "--mirror", str(mir), *extra],
        cwd=REPO_ROOT, capture_output=True,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace") + \
          (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out


# ── 1. 读取层：读不懂是错误，不是 traceback ──────────────────────────────

def test_load_broken_json_reports_error(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json", encoding="utf-8")
    doc, err = crm.load_json_document(p)
    assert doc is None and "JSON 解析失败" in err, err


def test_load_non_object_reports_error(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2]", encoding="utf-8")
    doc, err = crm.load_json_document(p)
    assert doc is None and "顶层不是对象" in err, err


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-8-sig", "gbk"])
def test_load_encoded_documents(tmp_path, encoding):
    p = tmp_path / "doc.json"
    p.write_bytes(json.dumps(_legal_doc(), ensure_ascii=False).encode(encoding))
    doc, err = crm.load_json_document(p)
    assert not err and isinstance(doc, dict) and len(doc["entries"]) == 3, err


def test_load_missing_file_reports_error(tmp_path):
    doc, err = crm.load_json_document(tmp_path / "none.json")
    assert doc is None and "读不出" in err, err


def test_cli_broken_json_exits_2(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json", encoding="utf-8")
    code, out = _cli(p)
    assert code == crm.EXIT_DATA_ERROR, out
    assert "镜像读不出" in out and "Traceback" not in out, out


# ── 2. 自洽指纹：任何手改都要被抓住 ──────────────────────────────────────

def test_legal_mirror_is_clean():
    assert crm.self_consistent_problems(_legal_doc()) == []
    assert crm.structural_check(_legal_doc(), "夹具", quiet=True) == []


def test_empty_entries_blocked():
    d = {"entries": []}
    d["_mirror_sha256"] = crm.entity_fingerprint(d)
    assert any("entries 为空" in p for p in crm.self_consistent_problems(d))


def test_tampered_value_blocked():
    d = copy.deepcopy(_legal_doc())
    d["entries"][0]["declared"] = {"value": 999999}
    assert any("指纹与 _mirror_sha256 不符" in p for p in crm.self_consistent_problems(d))


def test_removed_entry_blocked():
    d = copy.deepcopy(_legal_doc())
    d["entries"].pop(0)
    assert any("指纹与 _mirror_sha256 不符" in p for p in crm.self_consistent_problems(d))


def test_missing_meta_blocked():
    d = copy.deepcopy(_legal_doc())
    d.pop("_mirror_sha256")
    assert any("缺少 _mirror_sha256" in p for p in crm.self_consistent_problems(d))


def test_bad_meta_format_blocked():
    d = copy.deepcopy(_legal_doc())
    d["_mirror_sha256"] = "not-a-fingerprint"
    assert any("格式非法" in p for p in crm.self_consistent_problems(d))


def test_structural_check_still_passes_fake_entries():
    """旧校验对「键齐但内容全假」的表本来就是通过的 —— 这正是缺口。"""
    fake = {"entries": [{"id": "NR-X", "declared": {}, "analysis": "pytest", "sources": []}]}
    assert crm.structural_check(fake, "夹具", quiet=True) == []
    assert crm.integrity_check(fake, "夹具"), "完整性校验必须拦住它"


def test_entity_fingerprint_ignores_key_order():
    d = _legal_doc()
    shuffled = {"_mirror_sha256": d["_mirror_sha256"], "entries": d["entries"]}
    assert crm.entity_fingerprint(shuffled) == d["_mirror_sha256"]


# ── 3. 端到端：CI 常态（权威缺失）────────────────────────────────────────

def test_cli_legal_mirror_passes(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps(_legal_doc(), ensure_ascii=False, indent=1), encoding="utf-8")
    code, out = _cli(p)
    assert code == crm.EXIT_OK, out
    assert "指纹自洽" in out, out


@pytest.mark.parametrize("mutate", ["tamper", "remove", "empty", "no_meta"])
def test_cli_tampered_mirror_fails(tmp_path, mutate):
    d = _legal_doc()
    if mutate == "tamper":
        d["entries"][0]["declared"] = {"value": 999999}
    elif mutate == "remove":
        d["entries"].pop(0)
    elif mutate == "empty":
        d = {"entries": []}
        d["_mirror_sha256"] = crm.entity_fingerprint(d)
    else:
        d.pop("_mirror_sha256")
    p = tmp_path / (mutate + ".json")
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    code, out = _cli(p)
    assert code == crm.EXIT_FAIL, out
    assert "完整性校验未通过" in out, out


def test_repo_mirror_itself_is_self_consistent():
    """当前入库镜像必须仍然通过（改动不能把 CI 变红）。"""
    doc, err = crm.load_json_document(REPO_ROOT / "number_registry.json")
    assert not err, err
    assert not crm.self_consistent_problems(doc), crm.self_consistent_problems(doc)
    assert not crm.structural_check(doc, "仓库镜像", quiet=True)


# ── 4. sync 与自证 ───────────────────────────────────────────────────────

def test_sync_rejects_single_line_authority(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps(_legal_doc(), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    mir = tmp_path / "mir.json"
    mir.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="单行 JSON"):
        crm.sync_mirror(mir, auth, crm.entity_fingerprint(_legal_doc()))


def test_skip_branch_uses_integrity_check():
    """回归锁：权威缺失分支必须走 integrity_check，不能退回只看结构。"""
    import ast
    src = (REPO_ROOT / "scripts" / "check_registry_mirror.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)]
    assert "integrity_check" in calls, calls


def test_self_test_passes():
    proc = subprocess.run([PY, "-X", "utf8", str(GATE), "--self-test"],
                          cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
