#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_identity.py —— 身份合规扫描（P0-5 / NFR-4，一票否决）。

命中三类：

1. 外置 ``identity.tokens[]``（真名 / 用户名 / QQ）——**输出中一律脱敏**，
   只显示 ``token#k`` 与长度，明文仅存于外置 config；
2. ``identity.path_markers[]``（沙箱目录标记 / 根级用户名路径 / 私有密钥文件后缀）；
3. **二进制元数据**：PPTX ``docProps/core.xml``（标题/作者/最后修改者）与
   PDF ``/Title`` ``/Author`` 等。

严重度恒为 ``block``（NFR-4 一票否决）。自排除 ``assurance/config/``（敏感表本身，
非交付物），并在报告中显式列出 ``excluded``。

导出闸门复用：``scan_content(text, label, blacklist)`` 为纯函数，供
``export_thesis_drafts.py`` 在落盘前调用（零副作用）。

退出码：``0`` 无 blocking；``1`` 存在 blocking；``2`` 用法/配置错误。
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

logger = ac.get_logger("scan_identity")

SCANNER = "scan_identity"
HINT_TOKEN = "命中身份串（真名/用户名/QQ 类；明文见外置 config）：NFR-4 一票否决，必须改写/删除"
HINT_PATH = "命中敏感路径标记（沙箱目录标记 / 根级用户名路径 / 私有密钥后缀）：NFR-4 一票否决，必须删除或脱敏"


def _mask(token: str, idx: int) -> str:
    """敏感串脱敏：只暴露序号与长度，不暴露任何字符。"""
    return f"‹identity#{idx} len={len(token)}›"


def build_matchers(blacklist: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建 ``(regex, rule, raw, masked, kind)`` 匹配器列表。"""
    matchers: List[Dict[str, Any]] = []
    for i, tok in enumerate(blacklist.get("identity", {}).get("tokens", [])):
        tok = str(tok)
        if not tok:
            continue
        if tok.isdigit():
            rx = re.compile(r"(?<![\d])" + re.escape(tok) + r"(?![\d])")
        else:
            rx = re.compile(re.escape(tok), re.IGNORECASE)
        matchers.append({"regex": rx, "rule": f"identity_token#{i}", "kind": "token",
                         "raw": tok, "masked": _mask(tok, i)})
    for pm in blacklist.get("identity", {}).get("path_markers", []):
        pm = str(pm)
        if not pm:
            continue
        matchers.append({"regex": re.compile(re.escape(pm), re.IGNORECASE), "rule": "path_marker",
                         "kind": "path", "raw": pm, "masked": pm})
    return matchers


def _sanitize(text: str, matchers: List[Dict[str, Any]]) -> str:
    """把片段中的敏感串替换为掩码（token 类）。"""
    out = text
    for m in matchers:
        if m["kind"] == "token":
            out = m["regex"].sub(m["masked"], out)
    return out


def scan_text(text: str, label: str, matchers: List[Dict[str, Any]],
              scope: str = "external") -> List[Dict[str, Any]]:
    """纯函数：扫描一段文本，返回命中列表（敏感串已脱敏）。

    ``scope`` 仅用于标注文件归属（external/snapshot/internal），identity 严重度恒为 block。
    """
    hits: List[Dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in matchers:
            for mm in m["regex"].finditer(line):
                hits.append({
                    "file": label, "line": lineno, "match": m["masked"],
                    "rule": m["rule"], "severity": ac.SEV_BLOCK, "context": scope,
                    "scope": scope,
                    "snippet": _sanitize(ac.snippet(line, mm.start(), mm.end()), matchers),
                    "hint": HINT_TOKEN if m["kind"] == "token" else HINT_PATH,
                })
    return hits


def scan_content(text: str, label: str, blacklist: Dict[str, Any]) -> List[Dict[str, Any]]:
    """便捷封装：供导出闸门使用（内部构建 matchers）。"""
    return scan_text(text, label, build_matchers(blacklist))


def _scan_binary(path: Path, rel: str, matchers: List[Dict[str, Any]],
                 kind: str, scope: str) -> List[Dict[str, Any]]:
    """扫描 PPTX / PDF 元数据与文本。"""
    hits: List[Dict[str, Any]] = []
    if kind == "pptx":
        parts: List[Tuple[str, str]] = ac.extract_pptx_strings(path)
    else:
        parts = [("__pdf_raw__", "\n".join(ac.extract_pdf_strings(path)))]
    for part, text in parts:
        for m in matchers:
            for mm in m["regex"].finditer(text):
                hits.append({
                    "file": rel, "line": 0, "match": m["masked"], "rule": m["rule"],
                    "severity": ac.SEV_BLOCK, "context": f"{kind}:{part}", "scope": scope,
                    "snippet": _sanitize(ac.snippet(text.replace("\n", " "), mm.start(), mm.end()), matchers),
                    "hint": HINT_TOKEN if m["kind"] == "token" else HINT_PATH,
                })
    return hits


def scan(root: Path, cfg: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 ``root``（文本 + PPTX + PDF），返回报告 dict。"""
    matchers = build_matchers(blacklist)
    include_ext = list(cfg.get("include_ext", []))
    self_exclude = {str(Path(p).as_posix()).lower() for p in cfg.get("identity_self_exclude", [])}
    hits: List[Dict[str, Any]] = []
    files_scanned = 0
    excluded: List[str] = []

    for path in ac.iter_files([root], include_ext, cfg.get("exclude_dirs", []), cfg.get("exclude_globs", [])):
        rel = path.relative_to(root).as_posix() if (root == path.parent or root in path.parents) else str(path)
        rel_lower = rel.lower()
        if any(se in rel_lower for se in self_exclude):
            excluded.append(rel)
            continue
        files_scanned += 1
        scope = ac.classify_path_scope(rel, cfg)
        ext = path.suffix.lower()
        if ext == ".pptx":
            hits.extend(_scan_binary(path, rel, matchers, "pptx", scope))
        elif ext == ".pdf":
            hits.extend(_scan_binary(path, rel, matchers, "pdf", scope))
        else:
            hits.extend(scan_text(ac.load_text(path), rel, matchers, scope))

    counts = ac.scanner_severity_counts(hits)
    scope_counts = {"external": 0, "snapshot": 0, "internal": 0}
    for h in hits:
        scope_counts[h.get("scope", "internal")] = scope_counts.get(h.get("scope", "internal"), 0) + 1
    return {
        "scanner": SCANNER,
        "generated_at": ac.now_iso(),
        "root": ac.rel_to_workspace(root),
        "config_ref": ac.rel_to_workspace(ac.BLACKLIST_PATH),
        "excluded": sorted(excluded),
        "summary": {
            "files_scanned": files_scanned, "hits": len(hits),
            "blocking": counts[ac.SEV_BLOCK],
            "block": counts[ac.SEV_BLOCK], "warn": counts[ac.SEV_WARN],
            "snapshot": counts[ac.SEV_SNAPSHOT], "info": counts[ac.SEV_INFO],
            "scope_counts": scope_counts,
        },
        "hits": hits,
    }


def _resolve_root(root_arg: str, cfg: Dict[str, Any]) -> Path:
    if root_arg:
        p = Path(root_arg)
        return p if p.is_absolute() else (ac.WORKSPACE_ROOT / p)
    return ac.WORKSPACE_ROOT / cfg.get("scan_roots", ["deliverables"])[0]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="身份合规扫描器（含 PPTX/PDF 元数据）")
    ap.add_argument("--root", default="")
    ap.add_argument("--config", default=str(ac.SCAN_TARGETS_PATH))
    ap.add_argument("--blacklist", default=str(ac.BLACKLIST_PATH))
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "scan_identity_report.json"))
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = ac.load_scan_targets(args.config)
        blacklist = ac.load_blacklist(args.blacklist)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置读取错误：%s", exc)
        return ac.EXIT_USAGE
    root = _resolve_root(args.root, cfg)
    if not root.exists():
        logger.error("扫描根不存在：%s", root)
        return ac.EXIT_USAGE
    report = scan(root, cfg, blacklist)
    pj = ac.emit_scanner_report(report, args.report, overwrite=args.overwrite)
    s = report["summary"]
    logger.info("身份命中 %d（blocking=%d，排除 %d 个自排除文件），报告：%s",
                s["hits"], s["blocking"], len(report["excluded"]), ac.rel_to_workspace(pj))
    return ac.EXIT_FAIL if s["blocking"] else ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
