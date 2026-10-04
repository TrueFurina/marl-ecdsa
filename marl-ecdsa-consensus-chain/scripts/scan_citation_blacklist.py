#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_citation_blacklist.py —— 伪引用黑白名单扫描（P0-6 / NFR-5）。

命中两类：

1. 外置 ``citation_blacklist[]``（合成伪文献域，具体域名见外部配置，不入库）；
2. ``citation_markers[]``（如 ``SYNTHETIC_`` 合成标记）。

严重度分级同 ``scan_void_tokens``：对外材料 ``block`` / 历史快照 ``snapshot`` /
内部文档 ``info``；行内含「排除/未使用/黑名单/预警…」等**声明性上下文**降级 ``info``
（那是「声明已排除」，不是「引用」）。

退出码：``0`` 无 blocking；``1`` 存在 blocking；``2`` 用法/配置错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assurance_common as ac  # noqa: E402

logger = ac.get_logger("scan_citation_blacklist")

SCANNER = "scan_citation_blacklist"


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


def scan(root: Path, cfg: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 ``root``，返回报告 dict。"""
    matchers = build_matchers(blacklist)
    mention = blacklist.get("context_markers", {}).get("mention", [])
    text_ext = [e for e in cfg.get("include_ext", []) if e not in (".pptx", ".pdf")]
    hits: List[Dict[str, Any]] = []
    files_scanned = 0

    for path in ac.iter_files([root], text_ext, cfg.get("exclude_dirs", []), cfg.get("exclude_globs", [])):
        files_scanned += 1
        rel = path.relative_to(root).as_posix() if (root == path.parent or root in path.parents) else str(path)
        scope = ac.classify_path_scope(rel, cfg)
        default_sev = ac.scope_severity(scope)
        for lineno, line in ac.scan_text_lines(path):
            for m in matchers:
                for mm in m["regex"].finditer(line):
                    if any(mk in line for mk in mention):
                        sev, context = ac.SEV_INFO, "mention"
                    else:
                        sev, context = default_sev, scope
                    hits.append({
                        "file": rel, "line": lineno, "match": mm.group(0),
                        "rule": m["rule"], "severity": sev, "context": context,
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
            "blocking": counts[ac.SEV_BLOCK],
            "block": counts[ac.SEV_BLOCK], "warn": counts[ac.SEV_WARN],
            "snapshot": counts[ac.SEV_SNAPSHOT], "info": counts[ac.SEV_INFO],
        },
        "hits": hits,
    }


def _resolve_root(root_arg: str, cfg: Dict[str, Any]) -> Path:
    if root_arg:
        p = Path(root_arg)
        return p if p.is_absolute() else (ac.WORKSPACE_ROOT / p)
    return ac.WORKSPACE_ROOT / cfg.get("scan_roots", ["deliverables"])[0]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="伪引用黑白名单扫描器")
    ap.add_argument("--root", default="")
    ap.add_argument("--config", default=str(ac.SCAN_TARGETS_PATH))
    ap.add_argument("--blacklist", default=str(ac.BLACKLIST_PATH))
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "scan_citation_report.json"))
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
    logger.info("引用域命中 %d（blocking=%d, info=%d），报告：%s",
                s["hits"], s["blocking"], s["info"], ac.rel_to_workspace(pj))
    return ac.EXIT_FAIL if s["blocking"] else ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
