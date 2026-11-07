#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``scan_void_tokens.py`` 的「查了等于没查」回归测试（2026-11-07）。

背景
----
这道门禁是 pre-commit 第 3/6 步、也在 CI 的 ``Caliber gate — void tokens`` 里跑。
它此前把「读不懂」「没拿到清单」「路径不存在」一律折叠成「0 命中 ⇒ 通过」：

1. ``read_text(errors="replace")`` 读 UTF-16：``6026`` 被拆成 ``6\\x000\\x002\\x006``，
   数字边界正则再也匹配不上；PDF/PPTX 解析器缺失返回空列表 ⇒ 0 行。
   两种情况下 ``files_scanned`` 都照样 +1，报告写「扫过 1 个文件」。
2. ``_staged_files()`` 的 ``except Exception: return []``：git 失败 ⇒ 「暂存区无文件，
   跳过扫描」+ rc=0，与「本次确实没有暂存文件」不可分。
3. ``--paths`` 里不存在的路径被静默丢弃，全缺失 ⇒ 「跳过扫描」+ rc=0；
   且相对路径只按 WORKSPACE_ROOT（项目父目录）拼，项目内相对路径全部落空。
4. 零文件判通过，不打计数，也没有 strict 模式。
5. hook 第 6 步写死的私有文档不在干净 checkout 里 ⇒ 那道门从未运行。

合成令牌一律**运行时拼接**：本文件也在扫描范围内，写字面量会自锁。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = REPO_ROOT / "scripts" / "scan_void_tokens.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import scan_void_tokens as svt  # noqa: E402


def _token() -> str:
    return "60" + "26"


def _cli(*args: str, report: Path, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [PY, "-X", "utf8", str(SCAN), *args, "--report", str(report), "--overwrite"],
        cwd=str(cwd or REPO_ROOT), capture_output=True,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace") + \
          (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out


def _external(tmp_path: Path, name: str, data: bytes) -> Path:
    """放在名字含 thesis/README 的路径下 ⇒ scope=external ⇒ 默认 severity=block。"""
    d = tmp_path / "thesis"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


# ── 1. 读不懂是状态，不是空列表 ──────────────────────────────────────────

@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-8-sig", "gbk"])
def test_encoded_documents_are_scanned(tmp_path, encoding):
    line = f"吞吐 {_token()} TPS\n"
    p = _external(tmp_path, "README_demo.md", line.encode(encoding))
    code, out = _cli("--paths", str(p), report=tmp_path / "r.json")
    assert code == 1, f"{encoding} 文档里的作废令牌必须检出，实得 {code}\n{out}"
    assert "blocking=1" in out, out


def test_utf16_not_counted_as_empty_scan(tmp_path):
    line = f"吞吐 {_token()} TPS\n"
    p = _external(tmp_path, "README_u16.md", line.encode("utf-16"))
    hits, n, unreadable = svt.scan_paths_detailed(
        [p], {"include_ext": [".md"], "semantic_scan_ext": [], "external_material_markers": ["thesis"]},
        {"void_tokens": [{"token": _token(), "kind": "numeric"}], "context_markers": {}})
    assert n == 1 and len(hits) == 1 and not unreadable, (n, hits, unreadable)


def test_pdf_parse_failure_is_not_counted_as_scanned(tmp_path):
    p = _external(tmp_path, "README_fake.pdf", b"%PDF-1.4\nnot a real pdf\n")
    code, out = _cli("--paths", str(p), report=tmp_path / "r_pdf.json")
    assert code == 2, f"PDF 解析失败必须判「没检查」，实得 {code}\n{out}"
    assert "读不出" in out, out
    rep = json.loads((tmp_path / "r_pdf.json").read_text(encoding="utf-8"))
    assert rep["summary"]["files_scanned"] == 0, rep["summary"]
    assert rep["summary"]["unreadable"] == 1, rep["summary"]
    assert rep["unreadable_files"][0]["status"] == svt.STATUS_PARSE_FAILED


def test_decode_bytes_text_reports_binary():
    text, status, reason = svt.decode_bytes_text(b"\x00\x01binary")
    assert status == svt.STATUS_UNREADABLE and not text, (status, reason)


def test_source_does_not_use_errors_replace_on_read():
    """回归锁：读取层不得再退回 ``open(..., errors='replace')`` 的「读不懂当没有」。"""
    import ast
    src = (REPO_ROOT / "scripts" / "scan_void_tokens.py").read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in {"open", "read_text"}:
            if any(kw.arg == "errors" for kw in node.keywords):
                offenders.append((name, node.lineno))
    assert not offenders, f"读取层不得传 errors=：{offenders}"


# ── 2. 路径：不存在必须留痕，相对路径基准要对 ────────────────────────────

def test_all_missing_paths_fail_closed(tmp_path):
    code, out = _cli("--paths", "no_such_xyz.md", report=tmp_path / "r_missing.json")
    assert code == 2, f"一个都没扫到不得判通过，实得 {code}\n{out}"
    assert "不存在" in out, out


def test_partial_missing_is_recorded_and_strict_fails(tmp_path):
    good = _external(tmp_path, "README_ok.md", b"nothing to report\n")
    r1 = tmp_path / "r1.json"
    code_ok, out_ok = _cli("--paths", str(good), "no_such_xyz.md", report=r1)
    assert code_ok == 0, out_ok
    rep = json.loads(r1.read_text(encoding="utf-8"))
    assert rep["summary"]["missing_paths"] == 1, rep["summary"]
    assert rep["missing_files"] == ["no_such_xyz.md"], rep["missing_files"]

    r2 = tmp_path / "r2.json"
    code_strict, _ = _cli("--paths", str(good), "no_such_xyz.md", "--strict", report=r2)
    assert code_strict == 2, "--strict 下部分路径缺失必须判失败"


def test_resolve_paths_prefers_cwd(tmp_path, monkeypatch):
    rel = tmp_path / "thesis" / "README_rel.md"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text("x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    found, missing = svt.resolve_paths(["thesis/README_rel.md"])
    assert len(found) == 1 and not missing, (found, missing)


def test_resolve_paths_reports_missing():
    found, missing = svt.resolve_paths(["no_such_void_xyz.md"])
    assert not found and missing == ["no_such_void_xyz.md"]


def test_hook_step6_has_fallback_for_absent_private_doc():
    """干净 checkout 上第 6 步写死的私有文档不存在 —— hook 必须有兜底，不能静默跳过。"""
    hook = (REPO_ROOT / "scripts" / "pre-commit" / "pre-commit").read_text(encoding="utf-8")
    assert "改对暂存区严格复扫兜底" in hook, "hook 缺私有文档缺失时的兜底"
    assert "--cached --strict --overwrite" in hook, "兜底必须真的跑一次严格扫描"


def test_staged_files_contract_returns_error_string(tmp_path):
    """``_staged_files()`` 必须返回 (list, error_str)，git 失败时 error 非空。"""
    import os
    old = Path.cwd()
    try:
        os.chdir(tmp_path)
        paths, err = svt._staged_files()
    finally:
        os.chdir(old)
    assert isinstance(paths, list) and isinstance(err, str)
    assert err, "非仓库目录下必须拿到错误说明，而不是空清单"


# ── 3. git 清单与零文件 ──────────────────────────────────────────────────

def test_git_error_is_not_an_empty_staged_list(tmp_path):
    code, out = _cli("--cached", report=tmp_path / "r_git.json", cwd=tmp_path)
    assert code == 2, f"非仓库目录下 --cached 必须判环境错误，实得 {code}\n{out}"
    assert "环境错误" in out, out


def test_strict_zero_files_fails(tmp_path):
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    code, out = _cli("--paths", str(empty), "--strict", report=tmp_path / "r_zero.json")
    assert code == 2, f"--strict 下零文件必须失败，实得 {code}\n{out}"


def test_zero_files_without_strict_passes_but_is_visible(tmp_path):
    empty = tmp_path / "empty_dir2"
    empty.mkdir()
    code, out = _cli("--paths", str(empty), report=tmp_path / "r_zero2.json")
    assert code == 0, out
    assert "扫过 0 个文件" in out, out



# ── 4. 降级证据与旧契约兼容 ──────────────────────────────────────────────

def test_downgrade_records_which_marker_fired(tmp_path):
    line = f"吞吐 {_token()} TPS → 见正文\n"
    p = _external(tmp_path, "README_mention.md", line.encode("utf-8"))
    hits, n, _ = svt.scan_paths_detailed(
        [p], {"include_ext": [".md"], "semantic_scan_ext": [], "external_material_markers": ["thesis"]},
        {"void_tokens": [{"token": _token(), "kind": "numeric"}],
         "context_markers": {"mention": ["→", "应改为"], "code_line_ref": "",
                             "code_line_ref_line": ""}})
    assert n == 1 and len(hits) == 1, (n, hits)
    assert hits[0]["severity"] == "info", hits[0]
    assert hits[0]["downgrade_reason"] == "mention:→", hits[0]


def test_mention_marker_still_a_bool_contract():
    assert svt._is_mention("旧 6026 应改为 71", ["应改为"])
    assert not svt._is_mention("吞吐正常", ["应改为"])
    assert svt.mention_marker("旧口径 → 新口径", ["应改为", "→"]) == "→"


def test_scan_paths_keeps_two_tuple_contract(tmp_path):
    p = _external(tmp_path, "README_tuple.md", b"nothing here\n")
    result = svt.scan_paths([p], {"include_ext": [".md"], "semantic_scan_ext": []},
                            {"void_tokens": [], "context_markers": {}})
    assert isinstance(result, tuple) and len(result) == 2, result


# ── 5. 判定入口与自证 ────────────────────────────────────────────────────

@pytest.mark.parametrize("args,expect", [
    ((0, 0, 3, 0, "", True), 0),
    ((1, 0, 3, 0, "", False), 1),
    ((0, 1, 3, 0, "", False), 2),
    ((0, 0, 0, 0, "fatal: not a git repository", False), 2),
    ((0, 0, 0, 1, "", False), 2),
    ((0, 0, 0, 0, "", True), 2),
    ((0, 0, 0, 0, "", False), 0),
])
def test_decide_exit(args, expect):
    assert svt.decide_exit(*args)[0] == expect


def test_self_test_passes():
    proc = subprocess.run([PY, "-X", "utf8", str(SCAN), "--self-test"],
                          cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
