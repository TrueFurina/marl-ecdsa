#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_unsourced_numbers.py —— 无源数字扫描（P0-2 / NFR-1，数字三件套铁律）。

判定规则：正文中的小数 / 百分数若**缺少「文件路径 + 字段 + 统计检验」三件套**
（即命中行及其紧邻上文均无 ``results/``、``.json``、``字段``、``p=``、``n=``、
``Welch``、``Cohen``、``NR-``、``±`` 等来源标记），即判为无源数字。

严重度：默认 ``warn``（可推导线/无脚注），**不阻断**；跨配置混比的强命中由
``scan_void_tokens`` 负责 blocking。故本扫描器退出码恒为 ``0``（除非用法错误）。
被 import 时零副作用。
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

logger = ac.get_logger("scan_unsourced_numbers")

SCANNER = "scan_unsourced_numbers"
MAX_STORED_HITS = 500

#: 数字 token：小数（≥1 位小数）或百分数
_NUM_RE = re.compile(r"(?<![\w.])(\d+\.\d+|\d+(?:\.\d+)?%)")

#: 「三件套 / 来源」标记（命中行或紧邻上文出现任一即视为有源）
_SOURCE_MARKERS = (
    "results/", "backup/", ".json", "字段", "field:", "field =",
    "p=", "p =", "p<", "p>", "n=", "n =", "N=", "welch", "cohen",
    "d=", "d =", "ci", "95%", "@", "nr-", "commit", "sd", "±",
    "seed", "seeds", "aaed3e0", "delta", "Δ", "η", "λ",
)


def _is_sourced(lineno: int, lines: List[str]) -> bool:
    """检查命中行与其前 2 个非空行是否含来源标记。"""
    idxs = [lineno - 1]
    j = lineno - 2
    while j >= 0 and len(idxs) < 3:
        if lines[j].strip():
            idxs.append(j)
        j -= 1
    for i in idxs:
        low = lines[i].lower()
        if any(mk.lower() in low for mk in _SOURCE_MARKERS):
            return True
    return False


def scan(root: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 ``root`` 中的文本文件，返回报告 dict。"""
    text_ext = [e for e in cfg.get("include_ext", []) if e not in (".pptx", ".pdf", ".csv")]
    hits: List[Dict[str, Any]] = []
    files_scanned = 0
    total_unsourced = 0

    for path in ac.iter_files([root], text_ext, cfg.get("exclude_dirs", []), cfg.get("exclude_globs", [])):
        files_scanned += 1
        rel = path.relative_to(root).as_posix() if (root == path.parent or root in path.parents) else str(path)
        scope = ac.classify_path_scope(rel, cfg)
        lines = ac.load_text(path).splitlines()
        in_fence = False
        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for mm in _NUM_RE.finditer(line):
                start = mm.start()
                # 跳过 `path:123` 形式的行号引用与紧贴变量名的数字
                prefix = line[max(0, start - 1):start]
                if prefix == ":" and re.search(r"[\w./\\-]\.(py|md|json|txt|yml)", line[max(0, start - 40):start]):
                    continue
                if _is_sourced(lineno, lines):
                    continue
                total_unsourced += 1
                if len(hits) < MAX_STORED_HITS:
                    hits.append({
                        "file": rel, "line": lineno, "match": mm.group(0),
                        "rule": "unsourced_number", "severity": ac.SEV_WARN, "context": scope,
                        "snippet": ac.snippet(line, mm.start(), mm.end()),
                        "hint": "缺少三件套（文件路径+字段+检验）；补来源或标 pending",
                    })

    counts = ac.scanner_severity_counts(hits)
    return {
        "scanner": SCANNER,
        "generated_at": ac.now_iso(),
        "root": ac.rel_to_workspace(root),
        "config_ref": ac.rel_to_workspace(ac.SCAN_TARGETS_PATH),
        "summary": {
            "files_scanned": files_scanned,
            "hits": total_unsourced,
            "stored_hits": len(hits),
            "blocking": counts[ac.SEV_BLOCK],
            "block": counts[ac.SEV_BLOCK], "warn": counts[ac.SEV_WARN],
            "snapshot": counts[ac.SEV_SNAPSHOT], "info": counts[ac.SEV_INFO],
            "truncated": total_unsourced > len(hits),
        },
        "hits": hits,
    }


def _resolve_root(root_arg: str, cfg: Dict[str, Any]) -> Path:
    if root_arg:
        p = Path(root_arg)
        return p if p.is_absolute() else (ac.WORKSPACE_ROOT / p)
    return ac.WORKSPACE_ROOT / cfg.get("scan_roots", ["deliverables"])[0]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="无源数字扫描器（三件套铁律）")
    ap.add_argument("--root", default="")
    ap.add_argument("--config", default=str(ac.SCAN_TARGETS_PATH))
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "scan_unsourced_report.json"))
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = ac.load_scan_targets(args.config)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置读取错误：%s", exc)
        return ac.EXIT_USAGE
    root = _resolve_root(args.root, cfg)
    if not root.exists():
        logger.error("扫描根不存在：%s", root)
        return ac.EXIT_USAGE
    report = scan(root, cfg)
    pj = ac.emit_scanner_report(report, args.report, overwrite=args.overwrite)
    s = report["summary"]
    logger.info("无源数字 %d（存储 %d%s），报告：%s",
                s["hits"], s["stored_hits"], "，已截断" if s["truncated"] else "", ac.rel_to_workspace(pj))
    return ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
