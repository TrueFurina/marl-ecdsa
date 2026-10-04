#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_void_tokens.py —— 作废令牌扫描（P1-7 / NFR-3）。

命中两类红线：

1. 外置 ``void_tokens[]`` 清单中的数字/串（**数字边界正则**，避免浮点子串误报）；
2. ``semantic_rules[]`` 语义规则（如 ``40%\\s*拜占庭``、Dilithium 性能三元组）。

**两套扫描范围（F14）**：

* ``include_ext``（文档层：.md/.txt/.html/.pdf/.pptx）→ 两类规则**都**跑；
* ``semantic_scan_ext``（源码层，默认 ``['.py']``）→ **只跑 semantic_rules**。
  源码会随交付包发出（``03_源代码``），注释里的撤回表述同样是风险；但数字令牌
  （``void_tokens``）**不能**扫源码 —— 数字在代码里遍地，会产生数千条误报、
  诱发 ``--no-verify``，反而废掉门禁。源码层严重度由
  ``semantic_scan_ext_severity`` 单独控制（默认 ``warn``；要阻断改为 ``block``）。

严重度分级（架构 §4.3）：

* 对外材料（thesis_drafts / 毕设深度研究 / README / PPT）→ ``block``
* 历史快照（archive / backup / 赛前 / 审计 / 核验…）→ ``snapshot``（打标不改写）
* 内部文档（PRD / 架构 / 审计底稿）→ ``info``
* 行内含「排除/应改为/所谓/未使用…」等**声明性上下文**，或命中处前面是
  ``path:line`` **代码行号引用** → 降级 ``info``（不是申报，而是讨论）

退出码：``0`` 无 blocking；``1`` 存在 blocking；``2`` 用法/配置错误。
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

logger = ac.get_logger("scan_void_tokens")

SCANNER = "scan_void_tokens"
_COMPANY_MSG = "作废令牌禁止出现在对外/论文材料（NFR-3）；历史文档须打『历史快照』标记"


def _compile_numeric(tok: str) -> re.Pattern:
    """数字边界正则：``(?<![\\w.])<tok>(?![\\w.])``。

    两侧对称排除 ``\\w`` 与 ``.``，避免 ``6026.5`` / ``v6026x`` / ``x6026`` /
    ``6026.`` 等被误报；负号兼容 ASCII ``-`` 与 Unicode 减号 ``−``（U+2212）。
    """
    if tok.startswith("-"):
        body = tok[1:]
        return re.compile(r"(?<![\w.])(?:-|\u2212)?" + re.escape(body) + r"(?![\w.])")
    return re.compile(r"(?<![\w.])" + re.escape(tok) + r"(?![\w.])")


def build_matchers(blacklist: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建 ``(regex, rule, hint)`` 匹配器列表。"""
    matchers: List[Dict[str, Any]] = []
    for item in blacklist.get("void_tokens", []):
        if isinstance(item, dict):
            tok, kind = item.get("token", ""), item.get("kind", "literal")
        else:
            tok, kind = str(item), "literal"
        if not tok:
            continue
        rx = _compile_numeric(tok) if kind in ("numeric", "percent") else re.compile(re.escape(tok))
        matchers.append({
            "regex": rx, "rule": "void_token", "hint": f"作废令牌 {tok}：{_COMPANY_MSG}",
            "needs_review": bool(item.get("needs_review")) if isinstance(item, dict) else False,
            # 可选的降级说明：命中 needs_review 令牌被降为 warn 时追加的提示语。
            # 不填则回退到历史默认文案（+40.6% 同数值碰撞），以免影响既有令牌行为。
            "downgrade_note": (item.get("downgrade_note") or "") if isinstance(item, dict) else "",
        })
    for r in blacklist.get("semantic_rules", []):
        matchers.append({
            "regex": re.compile(r["pattern"]),
            "rule": "semantic_rule:" + r.get("id", "?"),
            "hint": r.get("hint", ""),
        })
    return matchers


def _is_mention(line: str, markers: List[str]) -> bool:
    return any(mk in line for mk in markers)


def _is_code_line_ref(line: str, start: int, ref_pattern: str) -> bool:
    if not ref_pattern:
        return False
    return bool(re.search(ref_pattern, line[max(0, start - 80):start]))


def scan_paths(paths, cfg: Dict[str, Any], blacklist: Dict[str, Any]):
    """扫描给定路径列表，返回 ``(hits, files_scanned)``。

    rel 统一相对 ``WORKSPACE_ROOT`` 以便 scope 分类；支持 .pdf 正文 / .pptx 正文 / 文本三类。
    """
    matchers = build_matchers(blacklist)
    ctx = blacklist.get("context_markers", {})
    mention = ctx.get("mention", [])
    ref_pat = ctx.get("code_line_ref", "")
    line_ref = re.compile(ctx["code_line_ref_line"]) if ctx.get("code_line_ref_line") else None
    text_ext = {e.lower() for e in cfg.get("include_ext", [])}
    # F14：源码注释层的**短语级**语义扫描范围（默认 ['.py']，见 scan_targets 的
    # ``semantic_scan_ext``）。这里刻意**只放 semantic_rules 进来**，`void_tokens`
    # 绝不扫源码 —— 那些是数字令牌，而源码里数字遍地（版本号、阈值、形状参数…），
    # 会瞬间产生数千条误报，进而诱发 `--no-verify`，反而把门禁整体废掉。
    sem_ext = {e.lower() for e in cfg.get("semantic_scan_ext", [])}
    #: 仅由 ``semantic_scan_ext`` 命中的文件（源码）使用的默认严重度。
    #: 源码随交付包发出、注释里的撤回表述确有风险，但它不像论文那样是对外表态，
    #: 故默认 ``warn``（可见、不阻断）。要把源码也纳入阻断，把配置改为 ``block``。
    sem_only_sev = cfg.get("semantic_scan_ext_severity", ac.SEV_WARN)
    hits: List[Dict[str, Any]] = []
    files_scanned = 0

    for path in paths:
        suffix = path.suffix.lower()
        in_doc = suffix in text_ext                                   # 文档层：全套规则
        in_sem_only = (not in_doc) and suffix in sem_ext              # 源码层：仅语义规则
        if not (in_doc or in_sem_only):
            continue
        files_scanned += 1
        try:
            rel = path.resolve().relative_to(ac.WORKSPACE_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        scope = ac.classify_path_scope(rel, cfg)
        default_sev = sem_only_sev if in_sem_only else ac.scope_severity(scope)
        default_context = "source_semantic" if in_sem_only else scope
        if suffix == ".pdf":
            lines = ac.extract_pdf_body(path)
        elif suffix == ".pptx":
            lines = [(i, ln) for i, (_, t) in enumerate(ac.extract_pptx_strings(path), 1)
                     for ln in t.splitlines()]
        else:
            lines = list(ac.scan_text_lines(path))
        for lineno, line in lines:
            # 整行是否为代码引用行（含 path.py:123）：整数令牌在此行判为行号引用，非申报
            is_ref_line = bool(line_ref.search(line)) if line_ref else False
            # 去 markdown 强调（**不能**据此推断 → 不能据此推断）后再判 mention，
            # 否则行内 ** 会把「不能据此推断」拆断，合规否定句被误判为 block。
            line_plain = re.sub(r'[*_`]', '', line)
            for m in matchers:
                # 源码层只跑短语级语义规则（void_tokens 是数字令牌，不进源码，理由见上）
                if in_sem_only and not m["rule"].startswith("semantic_rule:"):
                    continue
                for mm in m["regex"].finditer(line):
                    if _is_mention(line_plain, mention):
                        sev, context = ac.SEV_INFO, "mention"
                    elif _is_code_line_ref(line, mm.start(), ref_pat) or (mm.group(0).isdigit() and is_ref_line):
                        sev, context = ac.SEV_INFO, "code_line_ref"
                    else:
                        sev, context = default_sev, default_context
                    hint = m["hint"]
                    # needs_review 令牌（如 40.6）存在可信新测值同数值碰撞：命中需人工确认，
                    # 从 block/snapshot 降级为 warn，且 warn 不影响退出码（仅 block 才 exit 1）。
                    if m.get("needs_review") and sev in (ac.SEV_BLOCK, ac.SEV_SNAPSHOT):
                        sev = ac.SEV_WARN
                        hint += (m.get("downgrade_note")
                                 or "「此 token 存在可信新测值同数值碰撞（如 +40.6%），命中需人工确认是否为新测值」")
                    hits.append({
                        "file": rel, "line": lineno, "match": mm.group(0),
                        "rule": m["rule"], "severity": sev, "context": context,
                        "snippet": ac.snippet(line, mm.start(), mm.end()),
                        "hint": hint,
                    })
    return hits, files_scanned


def scan(root: Path, cfg: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 ``root``，返回报告 dict。"""
    # 遍历时要把「文档扩展名」与「源码语义扩展名」取**并集**，
    # 否则 .py 根本不会被走到，源码层扫描形同虚设。
    exts = list(dict.fromkeys(
        list(cfg.get("include_ext", [])) + list(cfg.get("semantic_scan_ext", []))
    ))
    paths = list(ac.iter_files([root], exts,
                                cfg.get("exclude_dirs", []), cfg.get("exclude_globs", [])))
    hits, files_scanned = scan_paths(paths, cfg, blacklist)
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
    ap = argparse.ArgumentParser(description="作废令牌扫描器")
    ap.add_argument("--root", default="", help="扫描根（默认取配置 scan_roots[0]）")
    ap.add_argument("--cached", action="store_true",
                    help="只扫描 git 暂存区文件（pre-commit 门禁用，避免历史残留拦死所有提交）")
    ap.add_argument("--paths", nargs="*", default=None,
                    help="显式指定要扫描的文件/目录（相对 WORKSPACE_ROOT 或绝对），覆盖 --root/--cached；任一不存在则跳过")
    ap.add_argument("--config", default=str(ac.SCAN_TARGETS_PATH))
    ap.add_argument("--blacklist", default=str(ac.BLACKLIST_PATH))
    ap.add_argument("--overwrite", action="store_true", help="允许覆盖同名报告")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "scan_void_tokens_report.json"))
    return ap


def _staged_files() -> List[Path]:
    """返回 git 暂存区（待提交）文件列表。

    用 ``-z`` 取 NUL 分隔的原始路径——否则中文路径会被 git quote 成
    octal 转义串（``"thesis/\\350\\256..."``），``Path()`` 无法解析，门禁会静默放行。
    """
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "-z", "--name-only", "--diff-filter=ACM"],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    return [Path(f) for f in out.decode("utf-8", "replace").split("\x00") if f]


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = ac.load_scan_targets(args.config)
        blacklist = ac.load_blacklist(args.blacklist)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置读取错误：%s", exc)
        return ac.EXIT_USAGE
    if args.paths is not None:
        paths = [Path(p) if Path(p).is_absolute() else (ac.WORKSPACE_ROOT / p) for p in args.paths]
        paths = [p for p in paths if p.exists()]
        if not paths:
            logger.info("指定路径均不存在，跳过扫描")
            return ac.EXIT_OK
        hits, files_scanned = scan_paths(paths, cfg, blacklist)
    elif args.cached:
        paths = _staged_files()
        if not paths:
            logger.info("暂存区无文件，跳过扫描")
            return ac.EXIT_OK
        hits, files_scanned = scan_paths(paths, cfg, blacklist)
    else:
        root = _resolve_root(args.root, cfg)
        if not root.exists():
            logger.error("扫描根不存在：%s", root)
            return ac.EXIT_USAGE
        report = scan(root, cfg, blacklist)
        hits, files_scanned = report["hits"], report["summary"]["files_scanned"]
    counts = ac.scanner_severity_counts(hits)
    report = {
        "scanner": SCANNER, "generated_at": ac.now_iso(),
        "root": "(paths)" if args.paths is not None else ("(staged)" if args.cached else ac.rel_to_workspace(root)),
        "config_ref": ac.rel_to_workspace(ac.BLACKLIST_PATH),
        "summary": {
            "files_scanned": files_scanned, "hits": len(hits),
            "blocking": counts[ac.SEV_BLOCK], "block": counts[ac.SEV_BLOCK],
            "warn": counts[ac.SEV_WARN], "snapshot": counts[ac.SEV_SNAPSHOT], "info": counts[ac.SEV_INFO],
        },
        "hits": hits,
    }
    pj = ac.emit_scanner_report(report, args.report, overwrite=args.overwrite)
    s = report["summary"]
    logger.info("命中 %d（blocking=%d, warn=%d, snapshot=%d, info=%d），报告：%s",
                s["hits"], s["blocking"], s["warn"], s["snapshot"], s["info"],
                ac.rel_to_workspace(pj))
    # warn 级命中（needs_review 令牌，如已作废的 n=22 口径）不阻断，但必须**可见**：
    # 否则"登记了作废口径"这件事在 CI 日志里完全看不出来，守卫名存实亡。
    if s.get("warn"):
        logger.warning("warn 级命中 %d 条（不阻断，需人工确认是否为新测值/历史标注）", s["warn"])
    return ac.EXIT_FAIL if s["blocking"] else ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
