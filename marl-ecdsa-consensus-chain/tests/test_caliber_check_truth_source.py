# -*- coding: utf-8 -*-
"""口径门禁的「真值可用性」与「格式取文」契约（2026-11-06）。

背景：``caliber_check.py --strict`` 此前只在**扫到漂移**时 exit 1，于是
「读不到真值」与「没有问题」在退出码上是同一件事。四条实测路径全部 rc=0 且
末行写着「✅ 口径体检通过」：

1. 登记簿被删 / 改名；
2. 登记簿 JSON 坏了（``load_registry`` 里 ``except: continue``）；
3. 登记簿在，但抽不出任何样本量真值（``if not uni: continue`` 让整族跳过）；
4. NR-19 缺失 → ``tests_floor is None`` → 测试数族整族跳过。

外加一条同一性质的"宣称覆盖"：``DOC_EXT`` 一直含 ``.docx/.pdf/.pptx``，
但读取是 ``read_text(encoding="utf-8", errors="ignore")`` —— 二进制容器读出来
是压缩流乱码，**一个数字也匹配不到**。同一份含 ``n=999 种子/组`` 的 docx，
旧实现在 ``--strict`` 下判 ✅（实测）。

本文件钉死两件事：
* 无真值 / 真值残缺 → ``--strict`` 必须 exit 1，且状态码可区分（不是一句告警）；
* 读不出文字的文件 → 计入 ``unparsed`` 并 fail-closed；docx/pptx 必须真能抽出正文。

不加 ``--strict`` 时保持"只告警不阻断"——pre-commit 交互场景不能被拦死。
"""

from __future__ import annotations

import io
import contextlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))

import caliber_check as cc  # noqa: E402

#: 合法集合外的样本量（不在任何登记簿取值集合、也不是作废令牌黑名单）
BAD_N = 999


# ── 夹具 ────────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """把两个候选位置都指到 tmp 里，避免读到仓库真登记簿。

    返回 ``write(doc)``：写登记簿（``None`` = 两个候选都不存在）。
    """
    primary = tmp_path / "deliverables" / "number_registry.json"
    mirror = tmp_path / "repo" / "number_registry.json"
    primary.parent.mkdir(parents=True, exist_ok=True)
    mirror.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cc, "REGISTRY_CANDIDATES", [primary, mirror])

    def write(doc, raw: str | None = None, target: Path | None = None) -> Path:
        path = target or primary
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
        else:
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    return write


def _run(args: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cc.main(args)
    return code, buf.getvalue()


def _md(tmp_path: Path, name: str = "doc.md", text: str = "本文档无任何样本量表述。\n") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _docx(path: Path, paragraphs: list[str]) -> Path:
    """造一个最小合法 docx（正文在 ``word/document.xml``）。"""
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml)
    return path


def _pptx(path: Path, slides: list[list[str]]) -> Path:
    """造一个最小合法 pptx（每页 ``ppt/slides/slideN.xml``）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, texts in enumerate(slides, 1):
            body = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts)
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f"<p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{idx}.xml", xml)
        zf.writestr("[Content_Types].xml", "<Types/>")
    return path


GOOD_REGISTRY = {
    "entries": [
        {"id": "NR-1", "n_expected": 71},
        {"id": "NR-19", "claim": "2183+ 项自动化测试全部通过", "declared": {"passed": 2183}},
    ]
}


# ── 真值可用性：纯函数 ──────────────────────────────────────────────────────

def test_truth_blockers_clean_registry():
    facts = cc.authoritative_facts(GOOD_REGISTRY)
    assert cc.truth_blockers(facts, {"source": "x", "error": ""}) == []


def test_truth_blockers_no_registry():
    facts = cc.authoritative_facts({})
    codes = [c for c, _ in cc.truth_blockers(facts, {"source": None, "error": ""})]
    assert codes == [cc.TRUTH_NO_REGISTRY], codes


def test_truth_blockers_registry_unreadable():
    facts = cc.authoritative_facts({})
    codes = [c for c, _ in cc.truth_blockers(
        facts, {"source": None, "error": "number_registry.json: JSONDecodeError"})]
    assert codes == [cc.TRUTH_REGISTRY_UNREADABLE], codes


def test_truth_blockers_no_sample_truth():
    facts = cc.authoritative_facts({"entries": [{"id": "NR-19", "claim": "2183+ 全部通过"}]})
    codes = [c for c, _ in cc.truth_blockers(facts, {})]
    assert codes == [cc.TRUTH_NO_SAMPLE], codes


def test_truth_blockers_no_tests_truth():
    facts = cc.authoritative_facts({"entries": [{"id": "NR-1", "n_expected": 71}]})
    codes = [c for c, _ in cc.truth_blockers(facts, {})]
    assert codes == [cc.TRUTH_NO_TESTS], codes


def test_truth_blockers_reports_both_missing_families():
    facts = cc.authoritative_facts({"entries": [{"id": "NR-1", "claim": "只有文字"}]})
    codes = [c for c, _ in cc.truth_blockers(facts, {})]
    assert codes == [cc.TRUTH_NO_SAMPLE, cc.TRUTH_NO_TESTS], codes


# ── load_registry：缺失 / 损坏 / 优先级 ─────────────────────────────────────

def test_load_registry_missing_reports_no_source(isolated_registry):
    reg, info = cc.load_registry()
    assert reg == {} and info["source"] is None and info["error"] == ""


def test_load_registry_corrupted_reports_error(isolated_registry):
    isolated_registry(None, raw='{"entries": [ broken')
    reg, info = cc.load_registry()
    assert reg == {}
    assert info["source"] is None
    assert "JSONDecodeError" in info["error"], info


def test_load_registry_prefers_primary_over_mirror(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    mirror = tmp_path / "repo" / "number_registry.json"
    isolated_registry({"entries": [{"id": "MIRROR"}]}, target=mirror)
    reg, info = cc.load_registry()
    assert info["source"] and info["source"].endswith("number_registry.json")
    assert any(e.get("id") == "NR-19" for e in reg["entries"]), "权威源应优先于镜像"


def test_load_registry_falls_back_to_mirror_when_primary_broken(isolated_registry, tmp_path):
    isolated_registry(None, raw="{ broken")
    isolated_registry(GOOD_REGISTRY, target=tmp_path / "repo" / "number_registry.json")
    reg, info = cc.load_registry()
    assert info["source"] and "repo" in info["source"]
    assert reg["entries"], reg


# ── main：--strict 下的 fail-closed ────────────────────────────────────────

def test_strict_without_registry_exits_1(isolated_registry, tmp_path):
    code, out = _run(["--strict", str(_md(tmp_path))])
    assert code == 1, out
    assert cc.TRUTH_NO_REGISTRY in out
    assert "无真值 ≠ 无漂移" in out


def test_without_strict_missing_registry_only_warns(isolated_registry, tmp_path):
    code, out = _run([str(_md(tmp_path))])
    assert code == 0, out
    assert cc.TRUTH_NO_REGISTRY in out
    assert "仅告警" in out


def test_strict_with_corrupted_registry_exits_1(isolated_registry, tmp_path):
    isolated_registry(None, raw='{"entries": [')
    code, out = _run(["--strict", str(_md(tmp_path))])
    assert code == 1, out
    assert cc.TRUTH_REGISTRY_UNREADABLE in out


def test_strict_with_empty_sample_truth_exits_1(isolated_registry, tmp_path):
    isolated_registry({"entries": [{"id": "NR-19", "claim": "2183+ 全部通过"}]})
    code, out = _run(["--strict", str(_md(tmp_path, text=f"n={BAD_N} 种子/组\n"))])
    assert code == 1, out
    assert cc.TRUTH_NO_SAMPLE in out
    assert "[漂移]" not in out, "无真值时不该假装判过漂移"


def test_strict_without_tests_floor_exits_1(isolated_registry, tmp_path):
    isolated_registry({"entries": [{"id": "NR-1", "n_expected": 71}]})
    code, out = _run(["--strict", str(_md(tmp_path))])
    assert code == 1, out
    assert cc.TRUTH_NO_TESTS in out


def test_shipped_registry_is_unblocked():
    """仓库自带登记簿必须零阻塞项——这是 CI 里 ``--strict`` 能绿的**前提**。

    没有这条，上面所有 fail-closed 都可以靠"真值一直缺"而永真。
    """
    reg, info = cc.load_registry()
    facts = cc.authoritative_facts(reg)
    assert cc.truth_blockers(facts, info) == [], info
    assert facts["n_universe"], "样本量真值集合为空"
    assert isinstance(facts["tests_floor"], int)


# ── 格式取文：docx / pptx / pdf 与解码失败 ─────────────────────────────────

def test_docx_body_is_read_and_drift_detected(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    doc = _docx(tmp_path / "old.docx", ["主实验口径为 n=999 种子/组", "补充说明"])
    code, out = _run(["--strict", str(doc)])
    assert code == 1, out
    assert f"sample_size={BAD_N}" in out and "漂移" in out
    assert "未解析 0 篇" in out


def test_pptx_slides_are_read_and_drift_detected(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    deck = _pptx(tmp_path / "deck.pptx", [["实验结果"], ["本轮 n=999 种子 配对"]])
    code, out = _run(["--strict", str(deck)])
    assert code == 1, out
    assert f"sample_size={BAD_N}" in out and "漂移" in out


def test_docx_exempt_marker_still_applies(isolated_registry, tmp_path):
    """取文改了，豁免口径不能跟着变：带「作废」的段落在 docx 里同样豁免。"""
    isolated_registry(GOOD_REGISTRY)
    doc = _docx(tmp_path / "old.docx", ["旧口径 n=999 种子/组 已作废"])
    code, out = _run(["--strict", str(doc)])
    assert code == 0, out
    assert "[豁免]" in out


def test_corrupted_docx_is_unparsed_not_silently_skipped(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    bad = tmp_path / "broken.docx"
    bad.write_bytes(b"not a zip at all")
    # 同时给一篇能读的文档：这样"扫描数 != 0"，单靠空扫描兜不住未解析
    ok = _md(tmp_path)
    code, out = _run(["--strict", str(ok), str(bad)])
    assert code == 1, out
    assert "[未解析]" in out and "docx_unreadable" in out


def test_pdf_without_parser_fails_closed(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    ok = _md(tmp_path)
    code, out = _run(["--strict", str(ok), str(pdf)])
    # 装了 pypdf 的环境里这份"PDF"会解析失败 → 仍是 1；没装 → pdf_no_parser → 1。
    assert code == 1, out
    assert "[未解析]" in out
    assert "扫描 1 篇文档" in out and "未解析 1 篇" in out


def test_pdf_unparsed_only_warns_without_strict(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    code, out = _run([str(pdf)])
    assert code == 0, out
    assert "[未解析]" in out and "默认不阻断" in out


def test_non_utf8_text_reported_as_decode_failed(isolated_registry, tmp_path):
    """GBK/UTF-16 文档按 UTF-8 读是乱码，等于没读——必须明说，不许算通过。"""
    isolated_registry(GOOD_REGISTRY)
    p = tmp_path / "gbk.md"
    p.write_bytes("n=999 种子/组".encode("gbk"))
    code, out = _run(["--strict", str(p)])
    assert code == 1, out
    assert "decode_failed" in out


def test_strict_zero_documents_fails(isolated_registry, monkeypatch):
    """全仓模式下一篇都没扫到 = 选择器坏了，不是"没问题"。"""
    isolated_registry(GOOD_REGISTRY)
    monkeypatch.setattr(cc, "gather_files", lambda _args: [])
    code, out = _run(["--strict"])
    assert code == 1, out
    assert "一篇文档都没扫到" in out


def test_summary_reports_scanned_count(isolated_registry, tmp_path):
    isolated_registry(GOOD_REGISTRY)
    code, out = _run(["--strict", str(_md(tmp_path))])
    assert code == 0, out
    assert "扫描 1 篇文档" in out
