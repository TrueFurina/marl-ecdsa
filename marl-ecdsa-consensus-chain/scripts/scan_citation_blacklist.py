#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_citation_blacklist.py —— 伪引用黑白名单扫描（P0-6 / NFR-5）。

命中两类：

1. 外置 ``citation_blacklist[]``（合成伪文献域，具体域名见外部配置，不入库）；
2. ``citation_markers[]``（如 ``SYNTHETIC_`` 合成标记）。

严重度分级同 ``scan_void_tokens``：对外材料 ``block`` / 历史快照 ``snapshot`` /
内部文档 ``info``；行内含「排除/未使用/黑名单/预警…」等**声明性上下文**降级 ``info``
（那是「声明已排除」，不是「引用」）。这是既定策略，本轮不改判定，只把触发降级的
marker 写进每条命中（``downgrade_reason``），让放宽可被核对。

退出码：``0`` 无 blocking；``1`` 存在 blocking；``2`` 用法/配置/环境错误。

2026-11-08 修的「查了等于没查」（全部实测复现，见 CHANGELOG）：
  1. ``ac.scan_text_lines()`` 用 ``errors="replace"``：UTF-16 文档里的
     ``freederia.com`` 被拆成 ``f\\x00r\\x00e\\x00...``，正则永不命中；
     实测 UTF-8 版 ``blocking=1 / rc=1``，UTF-16 版 ``hits=0`` 却照样
     ``files_scanned=1 / rc=0``。
  2. ``files_scanned += 1`` 发生在读取**之前**：读不出的文件也算「已扫」。
  3. 零文件（空目录 / 目录内全是 .pdf）判通过，不打计数、无 strict。
  4. ``--root`` 相对路径只按 WORKSPACE_ROOT（项目父目录）拼，项目内相对路径全部落空。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assurance_common as ac  # noqa: E402

logger = ac.get_logger("scan_citation_blacklist")

SCANNER = "scan_citation_blacklist"

STATUS_TEXT = "text"
STATUS_UNREADABLE = "unreadable"


def build_matchers(blacklist: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建 ``(regex, rule, hint)`` 匹配器列表。"""
    matchers: List[Dict[str, Any]] = []
    for domain in blacklist.get("citation_blacklist", []):
        matchers.append({
            "regex": re.compile(re.escape(str(domain)), re.IGNORECASE),
            "rule": "citation_blacklist",
            "hint": f"禁止引用 {domain}（NFR-5 伪文献污点）；若为『已排除』声明请确认措辞",
        })
    for marker in blacklist.get("citation_markers", []):
        matchers.append({
            "regex": re.compile(re.escape(str(marker))),
            "rule": "synthetic_marker",
            "hint": f"含合成标记 {marker} 的来源禁止引用",
        })
    return matchers


def decode_bytes_text(raw: bytes) -> Tuple[str, str, str]:
    """把原始字节解成文本，返回 ``(text, status, reason)``。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", "replace"), STATUS_TEXT, ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace"), STATUS_TEXT, ""
    if b"\x00" in raw[:4096]:
        return "", STATUS_UNREADABLE, "含 NUL 且无 BOM（按二进制处理）"
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc), STATUS_TEXT, ""
        except UnicodeDecodeError:
            continue
    return "", STATUS_UNREADABLE, "utf-8 与 gbk 均解不开"


def read_lines(path: Path) -> Tuple[List[Tuple[int, str]], str, str]:
    """返回 ``(行列表, status, reason)``；只有 status==text 才计入 files_scanned。

    HTML 先经 ``strip_html_markup()`` 屏蔽标签内部（保行号），与 F6 口径一致。
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [], STATUS_UNREADABLE, f"读不出（{exc.__class__.__name__}: {exc}）"
    text, status, reason = decode_bytes_text(raw)
    if status != STATUS_TEXT:
        return [], status, reason
    if path.suffix.lower() in (".html", ".htm"):
        text = ac.strip_html_markup(text)
    return [(i, ln.rstrip("\n")) for i, ln in enumerate(text.splitlines(), 1)], STATUS_TEXT, ""


def mention_marker(line: str, markers: List[str]) -> Optional[str]:
    """返回触发降级的那个 marker（而不是一个无从核对的 bool）。"""
    for mk in markers:
        if mk and mk in line:
            return mk
    return None


def scan(root: Path, cfg: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 ``root``，返回报告 dict；读不出的文件不计入 files_scanned。"""
    matchers = build_matchers(blacklist)
    mention = blacklist.get("context_markers", {}).get("mention", [])
    # .pptx/.pdf 明确不在本扫描器的文本范围内（容器类由别的门禁处理）
    text_ext = [e for e in cfg.get("include_ext", []) if e not in (".pptx", ".pdf")]
    hits: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, str]] = []
    files_scanned = 0

    for path in ac.iter_files([root], text_ext, cfg.get("exclude_dirs", []),
                              cfg.get("exclude_globs", [])):
        rel = path.relative_to(root).as_posix() if (root == path.parent or root in path.parents) else str(path)
        lines, status, reason = read_lines(path)
        if status != STATUS_TEXT:
            unreadable.append({"file": rel, "status": status, "reason": reason})
            continue
        files_scanned += 1
        scope = ac.classify_path_scope(rel, cfg)
        default_sev = ac.scope_severity(scope)
        for lineno, line in lines:
            marker = mention_marker(line, mention)
            for m in matchers:
                for mm in m["regex"].finditer(line):
                    if marker is not None:
                        sev, context, why = ac.SEV_INFO, "mention", f"mention:{marker}"
                    else:
                        sev, context, why = default_sev, scope, ""
                    hits.append({
                        "file": rel, "line": lineno, "match": mm.group(0),
                        "rule": m["rule"], "severity": sev, "context": context,
                        "downgrade_reason": why,
                        "snippet": ac.snippet(line, mm.start(), mm.end()),
                        "hint": m["hint"],
                    })

    counts = ac.scanner_severity_counts(hits)
    return {
        "scanner": SCANNER,
        "generated_at": ac.now_iso(),
        "root": ac.rel_to_workspace(root),
        "config_ref": ac.rel_to_workspace(ac.BLACKLIST_PATH),
        "summary": {
            "files_scanned": files_scanned, "hits": len(hits),
            "unreadable": len(unreadable),
            "blocking": counts[ac.SEV_BLOCK],
            "block": counts[ac.SEV_BLOCK], "warn": counts[ac.SEV_WARN],
            "snapshot": counts[ac.SEV_SNAPSHOT], "info": counts[ac.SEV_INFO],
        },
        "unreadable_files": unreadable,
        "hits": hits,
    }


def resolve_root(root_arg: str, cfg: Dict[str, Any]) -> Path:
    """相对路径先按 cwd 找，找不到再按 WORKSPACE_ROOT 找。

    旧实现只按 WORKSPACE_ROOT（项目父目录）拼，项目内相对路径全部落空。
    """
    if not root_arg:
        name = cfg.get("scan_roots", ["deliverables"])[0]
        return Path.cwd() / name if (Path.cwd() / name).exists() else ac.WORKSPACE_ROOT / name
    p = Path(root_arg)
    if p.is_absolute():
        return p
    cand = Path.cwd() / p
    return cand if cand.exists() else ac.WORKSPACE_ROOT / p


def decide_exit(blocking: int, unreadable: int, files_scanned: int,
                strict: bool) -> Tuple[int, str]:
    """唯一的判定入口（纯函数，便于自证与变异测试）。"""
    if unreadable:
        return ac.EXIT_USAGE, f"{unreadable} 个文件读不出 —— 没检查不等于没有伪引用"
    if blocking:
        return ac.EXIT_FAIL, f"{blocking} 条 blocking 命中"
    if files_scanned == 0:
        if strict:
            return ac.EXIT_USAGE, "零个文件被扫描 —— 什么都没扫不等于干净（--strict）"
        return ac.EXIT_OK, "零个文件被扫描（未启用 --strict）"
    return ac.EXIT_OK, ""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="伪引用黑白名单扫描器")
    ap.add_argument("--root", default="")
    ap.add_argument("--config", default=str(ac.SCAN_TARGETS_PATH))
    ap.add_argument("--blacklist", default=str(ac.BLACKLIST_PATH))
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "scan_citation_report.json"))
    ap.add_argument("--strict", action="store_true",
                    help="零个文件被扫描时判失败（退出码 2）")
    ap.add_argument("--self-test", action="store_true", help="内置夹具自证")
    return ap


# --------------------------------------------------------------------------- #
# 自证：临时目录现造样本，不依赖仓库状态
# --------------------------------------------------------------------------- #
def run_self_test(verbose: bool = True) -> int:
    import tempfile

    failures: List[str] = []
    passed = 0

    def ck(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<30} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<30} → FAIL {detail}")

    cfg = {"include_ext": [".md", ".txt", ".html"], "exclude_dirs": [],
           "exclude_globs": [], "external_material_markers": ["README", "thesis"]}
    bl = {"citation_blacklist": ["freederia.com"], "citation_markers": ["SYNTHETIC_"],
          "context_markers": {"mention": ["已排除", "黑名单"]}}
    # 运行时拼接，避免本文件被自家门禁扫到自锁
    domain = "freederia" + ".com"
    line = f"参考文献见 {domain} 请核对" + chr(10)

    with tempfile.TemporaryDirectory(prefix="citation_selftest_") as td:
        root = Path(td)
        (root / "d8").mkdir()
        f8 = root / "d8" / "README_u8.md"
        f8.write_text(line, encoding="utf-8")
        rep = scan(root / "d8", cfg, bl)
        ck("utf8_detected", rep["summary"]["hits"] == 1 and rep["summary"]["blocking"] == 1,
           str(rep["summary"]))

        (root / "d16").mkdir()
        f16 = root / "d16" / "README_u16.md"
        f16.write_bytes(line.encode("utf-16"))
        rep16 = scan(root / "d16", cfg, bl)
        ck("utf16_is_decoded",
           rep16["summary"]["hits"] == 1 and rep16["summary"]["files_scanned"] == 1,
           str(rep16["summary"]))

        (root / "dgbk").mkdir()
        fg = root / "dgbk" / "README_gbk.md"
        fg.write_bytes(line.encode("gbk"))
        repg = scan(root / "dgbk", cfg, bl)
        ck("gbk_is_decoded", repg["summary"]["hits"] == 1, str(repg["summary"]))

        (root / "dbin").mkdir()
        fb = root / "dbin" / "README_bin.md"
        fb.write_bytes(b"\x00\x01binary\x00")
        repb = scan(root / "dbin", cfg, bl)
        ck("binary_not_counted_as_scanned",
           repb["summary"]["files_scanned"] == 0 and repb["summary"]["unreadable"] == 1,
           str(repb["summary"]))

        (root / "dmention").mkdir()
        fm = root / "dmention" / "README_mention.md"
        fm.write_text(f"该域名已排除：{domain}\n", encoding="utf-8")
        repm = scan(root / "dmention", cfg, bl)
        ck("downgrade_has_reason",
           bool(repm["hits"]) and repm["hits"][0]["context"] == "mention"
           and repm["hits"][0]["downgrade_reason"] == "mention:已排除",
           repm["hits"][0]["downgrade_reason"] if repm["hits"] else "no hit")

        (root / "empty").mkdir()
        repe = scan(root / "empty", cfg, bl)
        ck("empty_dir_zero_scanned", repe["summary"]["files_scanned"] == 0,
           str(repe["summary"]))

        import os
        old = Path.cwd()
        try:
            os.chdir(root)
            p = resolve_root("d8", cfg)
            ck("cwd_relative_root", p == (root / "d8"), str(p))
        finally:
            os.chdir(old)

    ck("unreadable_blocks", decide_exit(0, 1, 1, False)[0] == ac.EXIT_USAGE)
    ck("blocking_fails", decide_exit(1, 0, 1, False)[0] == ac.EXIT_FAIL)
    ck("strict_zero_blocks", decide_exit(0, 0, 0, True)[0] == ac.EXIT_USAGE)
    ck("zero_nonstrict_passes", decide_exit(0, 0, 0, False)[0] == ac.EXIT_OK)
    ck("clean_passes", decide_exit(0, 0, 3, True)[0] == ac.EXIT_OK)

    total = passed + len(failures)
    if failures:
        for item in failures:
            print(f"❌ [自证失败] {item}")
        print(f"❌ 自证失败 {len(failures)}/{total} 项")
        return 1
    print(f"✅ 自证通过 {passed}/{total}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    try:
        cfg = ac.load_scan_targets(args.config)
        blacklist = ac.load_blacklist(args.blacklist)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置读取错误：%s", exc)
        return ac.EXIT_USAGE
    root = resolve_root(args.root, cfg)
    if not root.exists():
        logger.error("扫描根不存在：%s", root)
        return ac.EXIT_USAGE
    report = scan(root, cfg, blacklist)
    pj = ac.emit_scanner_report(report, args.report, overwrite=args.overwrite)
    s = report["summary"]
    logger.info("扫过 %d 个文件：命中 %d（blocking=%d, warn=%d, snapshot=%d, info=%d）；"
                "读不出 %d；报告：%s",
                s["files_scanned"], s["hits"], s["blocking"], s["warn"],
                s["snapshot"], s["info"], s["unreadable"], ac.rel_to_workspace(pj))
    for item in report["unreadable_files"]:
        logger.error("  未检查：%s [%s] %s", item["file"], item["status"], item["reason"])

    code, msg = decide_exit(s["blocking"], s["unreadable"], s["files_scanned"], args.strict)
    if code == ac.EXIT_USAGE:
        logger.error("❌ %s", msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
