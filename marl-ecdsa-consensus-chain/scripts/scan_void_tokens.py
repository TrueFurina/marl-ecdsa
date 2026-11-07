#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_void_tokens.py —— 作废令牌扫描（P1-7 / NFR-3）。

命中两类红线：

1. 外置 ``void_tokens[]`` 清单中的数字/串（**数字边界正则**，避免浮点子串误报）；
2. ``semantic_rules[]`` 语义规则（如 ``40%\\s*拜占庭``、Dilithium 性能三元组）。

**两套扫描范围（F14）**：

* ``include_ext``（文档层：.md/.txt/.html/.pdf/.pptx）→ 两类规则**都**跑；
  ``.html/.htm`` 先经 ``strip_html_markup()`` 屏蔽 ``<style>/<script>`` 区段与
  标签内部（保行号）——markup 数字（CSS 色标、SVG 坐标、锚点 id）不再误报
  （F6「跨文件类型误扫」），文本节点照常扫描；
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
  ``path:line`` **代码行号引用** → 降级 ``info``（不是申报，而是讨论）。
  这是**既定的策略性放宽**（见 tests/test_scan_void_tokens.py 的契约测试）；
  本轮不改判定，只把「被哪个 marker 降级」写进每条命中，让放宽可被核对。

退出码：``0`` 无 blocking；``1`` 存在 blocking；``2`` 用法/配置/环境错误。
被 import 时零副作用。

2026-11-07 修的「查了等于没查」（全部实测复现，见 CHANGELOG）：
  1. ``read_text(errors="replace")`` 把 UTF-16 文档里的 ``6026`` 拆成
     ``6\\x000\\x002\\x006`` ⇒ 0 命中；PDF/PPTX 解析器缺失返回空列表 ⇒ 0 行。
     两者却照样 ``files_scanned += 1``，报告写「扫过 1 个文件」。
  2. ``_staged_files()`` 在 git 失败时 ``except: return []`` ⇒ 「暂存区无文件，跳过扫描」+ rc=0。
  3. ``--paths`` 里不存在的路径被静默丢弃；全部不存在 ⇒ 「跳过扫描」+ rc=0。
     且相对路径的基准是 WORKSPACE_ROOT（项目父目录），项目内相对路径全部落空。
  4. 零文件（空暂存区 / 目录内无匹配扩展名）判通过，不打计数、无 strict。
  5. hook 第 6 步写死的私有文档在干净 checkout 上不存在 ⇒ 那道门从未运行。
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

logger = ac.get_logger("scan_void_tokens")

SCANNER = "scan_void_tokens"
_COMPANY_MSG = "作废令牌禁止出现在对外/论文材料（NFR-3）；历史文档须打『历史快照』标记"

#: 读文件结果的三种事实。``text`` 之外一律**不计入** files_scanned。
STATUS_TEXT = "text"
STATUS_UNREADABLE = "unreadable"
STATUS_PARSE_FAILED = "parse_failed"


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
            "downgrade_note": (item.get("downgrade_note") or "") if isinstance(item, dict) else "",
        })
    for r in blacklist.get("semantic_rules", []):
        matchers.append({
            "regex": re.compile(r["pattern"]),
            "rule": "semantic_rule:" + r.get("id", "?"),
            "hint": r.get("hint", ""),
        })
    return matchers


def mention_marker(line: str, markers: List[str]) -> Optional[str]:
    """返回触发降级的那个 marker（而不是一个无从核对的 bool）。

    ``context_markers.mention`` 有 77 个词，其中 ``→`` / ``并非`` / ``取代`` 都是
    很宽的信号。此前 hit 只写 ``context="mention"``，读者无法知道是哪一条把
    一个真数字从 block 降成了 info。这里把证据补上（**不改判定语义**）。
    """
    for mk in markers:
        if mk and mk in line:
            return mk
    return None


def _is_mention(line: str, markers: List[str]) -> bool:
    """兼容旧契约：整行是否含声明性上下文。"""
    return mention_marker(line, markers) is not None


def _is_code_line_ref(line: str, start: int, ref_pattern: str) -> bool:
    if not ref_pattern:
        return False
    return bool(re.search(ref_pattern, line[max(0, start - 80):start]))


# --------------------------------------------------------------------------- #
# 读取层：读不懂是**状态**，不是空列表
# --------------------------------------------------------------------------- #
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
    """返回 ``(行列表, status, reason)``；只有 status==text 才算「真的扫过」。

    PDF/PPTX 解析器缺失或抽不出正文时返回 ``parse_failed`` —— 旧实现拿到空列表
    却继续 ``files_scanned += 1``，于是「扫过 1 个 PDF」是一句假话。
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        body = ac.extract_pdf_body(path)
        if not body:
            return [], STATUS_PARSE_FAILED, "pypdf 不可用 / 解析失败 / PDF 无正文"
        return [(i, t) for i, t in body], STATUS_TEXT, ""
    if suffix == ".pptx":
        try:
            strings = ac.extract_pptx_strings(path)
        except Exception as exc:  # noqa: BLE001
            return [], STATUS_PARSE_FAILED, f"PPTX 解析抛异常（{exc.__class__.__name__}）"
        lines = [(i, ln) for i, (_, t) in enumerate(strings, 1) for ln in t.splitlines()]
        if not lines:
            return [], STATUS_PARSE_FAILED, "PPTX 未抽到任何文本"
        return lines, STATUS_TEXT, ""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [], STATUS_UNREADABLE, f"读不出（{exc.__class__.__name__}: {exc}）"
    text, status, reason = decode_bytes_text(raw)
    if status != STATUS_TEXT:
        return [], status, reason
    if suffix in (".html", ".htm"):
        # markup 屏蔽保留换行，行号与旧 scan_html_text_lines 一致（F6）
        text = ac.strip_html_markup(text)
    lines = [(i, ln.rstrip("\n")) for i, ln in enumerate(text.splitlines(), 1)]
    return lines, STATUS_TEXT, ""


def scan_paths_detailed(paths, cfg: Dict[str, Any],
                        blacklist: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int,
                                                            List[Dict[str, str]]]:
    """扫描给定路径，返回 ``(hits, files_scanned, unreadable)``。"""
    matchers = build_matchers(blacklist)
    ctx = blacklist.get("context_markers", {})
    mention = ctx.get("mention", [])
    ref_pat = ctx.get("code_line_ref", "")
    line_ref = re.compile(ctx["code_line_ref_line"]) if ctx.get("code_line_ref_line") else None
    text_ext = {e.lower() for e in cfg.get("include_ext", [])}
    sem_ext = {e.lower() for e in cfg.get("semantic_scan_ext", [])}
    sem_only_sev = cfg.get("semantic_scan_ext_severity", ac.SEV_WARN)
    hits: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, str]] = []
    files_scanned = 0

    for path in paths:
        suffix = path.suffix.lower()
        in_doc = suffix in text_ext
        in_sem_only = (not in_doc) and suffix in sem_ext
        if not (in_doc or in_sem_only):
            continue
        try:
            rel = path.resolve().relative_to(ac.WORKSPACE_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()

        lines, status, reason = read_lines(path)
        if status != STATUS_TEXT:
            unreadable.append({"file": rel, "status": status, "reason": reason})
            continue
        files_scanned += 1

        scope = ac.classify_path_scope(rel, cfg)
        default_sev = sem_only_sev if in_sem_only else ac.scope_severity(scope)
        default_context = "source_semantic" if in_sem_only else scope
        for lineno, line in lines:
            is_ref_line = bool(line_ref.search(line)) if line_ref else False
            line_plain = re.sub(r'[*_`]', '', line)
            marker = mention_marker(line_plain, mention)
            for m in matchers:
                if in_sem_only and not m["rule"].startswith("semantic_rule:"):
                    continue
                for mm in m["regex"].finditer(line):
                    why = ""
                    if marker is not None:
                        sev, context = ac.SEV_INFO, "mention"
                        why = f"mention:{marker}"
                    elif _is_code_line_ref(line, mm.start(), ref_pat) or (mm.group(0).isdigit() and is_ref_line):
                        sev, context = ac.SEV_INFO, "code_line_ref"
                        why = "code_line_ref"
                    else:
                        sev, context = default_sev, default_context
                    hint = m["hint"]
                    if m.get("needs_review") and sev in (ac.SEV_BLOCK, ac.SEV_SNAPSHOT):
                        sev = ac.SEV_WARN
                        why = (why + ";needs_review") if why else "needs_review"
                        hint += (m.get("downgrade_note")
                                 or "「此 token 存在可信新测值同数值碰撞（如 +40.6%），命中需人工确认是否为新测值」")
                    hits.append({
                        "file": rel, "line": lineno, "match": mm.group(0),
                        "rule": m["rule"], "severity": sev, "context": context,
                        "downgrade_reason": why,
                        "snippet": ac.snippet(line, mm.start(), mm.end()),
                        "hint": hint,
                    })
    return hits, files_scanned, unreadable


def scan_paths(paths, cfg: Dict[str, Any], blacklist: Dict[str, Any]):
    """兼容旧契约：只返回 ``(hits, files_scanned)``。

    ``tests/test_scan_void_tokens.py`` 与 ``tests/_mutate_scan_void_tokens.py``
    都按两元组解包；新信号请用 ``scan_paths_detailed()``。
    """
    hits, files_scanned, _ = scan_paths_detailed(paths, cfg, blacklist)
    return hits, files_scanned


def scan(root: Path, cfg: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    """扫描 ``root``，返回报告 dict。"""
    exts = list(dict.fromkeys(
        list(cfg.get("include_ext", [])) + list(cfg.get("semantic_scan_ext", []))
    ))
    paths = list(ac.iter_files([root], exts,
                                cfg.get("exclude_dirs", []), cfg.get("exclude_globs", [])))
    hits, files_scanned, unreadable = scan_paths_detailed(paths, cfg, blacklist)
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


def _resolve_root(root_arg: str, cfg: Dict[str, Any]) -> Path:
    if root_arg:
        p = Path(root_arg)
        return p if p.is_absolute() else (ac.WORKSPACE_ROOT / p)
    return ac.WORKSPACE_ROOT / cfg.get("scan_roots", ["deliverables"])[0]


def resolve_paths(names: List[str]) -> Tuple[List[Path], List[str]]:
    """解析 ``--paths``，返回 ``(存在的路径, 缺失的原样名字)``。

    相对路径先按 **cwd** 找（项目内文件常用），找不到再按 WORKSPACE_ROOT 找
    （工作区私有层 deliverables/ 在外层）。此前只按 WORKSPACE_ROOT 拼，
    ``_exp/thesis/README_demo.md`` 这类项目内相对路径全部落空，且被静默丢弃。
    """
    found: List[Path] = []
    missing: List[str] = []
    for name in names:
        p = Path(name)
        if p.is_absolute():
            cand = [p]
        else:
            cand = [Path.cwd() / p, ac.WORKSPACE_ROOT / p]
        hit = next((c for c in cand if c.exists()), None)
        if hit is None:
            missing.append(name)
        else:
            found.append(hit)
    return found, missing


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="作废令牌扫描器")
    ap.add_argument("--root", default="", help="扫描根（默认取配置 scan_roots[0]）")
    ap.add_argument("--cached", action="store_true",
                    help="只扫描 git 暂存区文件（pre-commit 门禁用，避免历史残留拦死所有提交）")
    ap.add_argument("--paths", nargs="*", default=None,
                    help="显式指定要扫描的文件/目录（相对 cwd 或 WORKSPACE_ROOT，亦可绝对）；"
                         "目录会按扩展名递归展开（服从 exclude_dirs/exclude_globs），覆盖 --root/--cached")
    ap.add_argument("--config", default=str(ac.SCAN_TARGETS_PATH))
    ap.add_argument("--blacklist", default=str(ac.BLACKLIST_PATH))
    ap.add_argument("--overwrite", action="store_true", help="允许覆盖同名报告")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "scan_void_tokens_report.json"))
    ap.add_argument("--strict", action="store_true",
                    help="零文件 / 任一指定路径缺失 / 目录内无匹配扩展名 都判失败（退出码 2）")
    ap.add_argument("--self-test", action="store_true", help="内置夹具自证")
    return ap


def _staged_files() -> Tuple[List[Path], str]:
    """返回 ``(暂存文件列表, 错误说明)``。错误说明非空 ⇒ 调用方必须判失败。

    旧实现 ``except Exception: return []``：git 不可用/不在仓库里时，「没拿到清单」
    与「暂存区确实是空的」完全不可分，门禁打印「跳过扫描」并 exit 0。
    """
    import subprocess
    cmd = ["git", "-c", "core.quotePath=false", "diff", "--cached", "-z",
           "--name-only", "--diff-filter=ACMR"]
    try:
        proc = subprocess.run(cmd, capture_output=True)
    except OSError as exc:
        return [], f"无法执行 git：{exc}"
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.decode("utf-8", "replace").splitlines()
                 if ln.strip()]
        detail = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))),
                      lines[0] if lines else "无错误输出")
        return [], f"git 退出码 {proc.returncode}：{detail}"
    return [Path(f) for f in proc.stdout.decode("utf-8", "replace").split("\x00") if f], ""


def decide_exit(blocking: int, unreadable: int, files_scanned: int,
                missing: int, error: str, strict: bool) -> Tuple[int, str]:
    """唯一的判定入口（纯函数，便于自证与变异测试）。"""
    if error:
        return ac.EXIT_USAGE, f"环境错误：{error} —— 没拿到文件清单不等于没有作废令牌"
    if missing and (strict or files_scanned == 0):
        return ac.EXIT_USAGE, (f"{missing} 个指定路径不存在 —— 一个都没扫到不等于通过"
                               if files_scanned == 0 else
                               f"{missing} 个指定路径不存在（--strict）")
    if unreadable:
        return ac.EXIT_USAGE, f"{unreadable} 个文件读不出/解析失败 —— 没检查不等于没有作废令牌"
    if blocking:
        return ac.EXIT_FAIL, f"{blocking} 条 blocking 命中"
    if files_scanned == 0:
        if strict:
            return ac.EXIT_USAGE, "零个文件被扫描 —— 什么都没扫不等于干净（--strict）"
        return ac.EXIT_OK, "零个文件被扫描（未启用 --strict）"
    return ac.EXIT_OK, ""


# --------------------------------------------------------------------------- #
# 自证：临时目录现造样本，不依赖仓库状态
# --------------------------------------------------------------------------- #
def run_self_test(verbose: bool = True) -> int:
    import os
    import tempfile

    failures: List[str] = []
    passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<30} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<30} → FAIL {detail}")

    cfg = {"include_ext": [".md", ".txt", ".pdf"], "semantic_scan_ext": [".py"],
           "semantic_scan_ext_severity": "warn",
           "external_material_markers": ["thesis", "README"]}
    bl = {"void_tokens": [{"token": "6026", "kind": "numeric"}],
          "semantic_rules": [],
          "context_markers": {"mention": ["应改为", "→"], "code_line_ref": "",
                              "code_line_ref_line": ""}}
    tok = "60" + "26"   # 运行时拼接，避免本文件被自家门禁扫到自锁

    with tempfile.TemporaryDirectory(prefix="void_selftest_") as tmp:
        root = Path(tmp)
        (root / "thesis").mkdir()
        good = root / "thesis" / "README_good.md"
        good.write_text(f"吞吐 {tok} TPS\n", encoding="utf-8")
        hits, n, bad = scan_paths_detailed([good], cfg, bl)
        check("plain_text_detected", n == 1 and len(hits) == 1 and not bad, f"n={n}")
        check("blocking_severity", bool(hits) and hits[0]["severity"] == "block",
              hits[0]["severity"] if hits else "no hit")

        u16 = root / "thesis" / "README_u16.md"
        u16.write_bytes(f"吞吐 {tok} TPS\n".encode("utf-16"))
        h16, n16, b16 = scan_paths_detailed([u16], cfg, bl)
        check("utf16_is_decoded", n16 == 1 and len(h16) == 1 and not b16, f"n={n16} bad={b16}")

        gbk = root / "thesis" / "README_gbk.md"
        gbk.write_bytes(f"吞吐 {tok} TPS\n".encode("gbk"))
        hg, ng, bg = scan_paths_detailed([gbk], cfg, bl)
        check("gbk_is_decoded", ng == 1 and len(hg) == 1 and not bg, f"n={ng}")

        fake_pdf = root / "thesis" / "README_fake.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4\nnot a real pdf\n")
        _, npdf, bpdf = scan_paths_detailed([fake_pdf], cfg, bl)
        check("pdf_parse_failed_not_scanned",
              npdf == 0 and len(bpdf) == 1 and bpdf[0]["status"] == STATUS_PARSE_FAILED,
              f"n={npdf} bad={bpdf}")

        mention = root / "thesis" / "README_mention.md"
        mention.write_text(f"吞吐 {tok} TPS → 见正文\n", encoding="utf-8")
        hm, _, _ = scan_paths_detailed([mention], cfg, bl)
        check("downgrade_has_reason",
              bool(hm) and hm[0]["context"] == "mention"
              and hm[0]["downgrade_reason"].startswith("mention:"),
              hm[0]["downgrade_reason"] if hm else "no hit")

        found, missing = resolve_paths(["no_such_xyz.md"])
        check("missing_path_reported", not found and missing == ["no_such_xyz.md"], str(missing))

        rel = root / "thesis" / "README_rel.md"
        rel.write_text(f"吞吐 {tok} TPS\n", encoding="utf-8")
        old = Path.cwd()
        try:
            os.chdir(root)
            found_rel, miss_rel = resolve_paths(["thesis/README_rel.md"])
            check("cwd_relative_resolved", len(found_rel) == 1 and not miss_rel, str(miss_rel))
        finally:
            os.chdir(old)

        nogit = root / "nogit"
        nogit.mkdir()
        old = Path.cwd()
        try:
            os.chdir(nogit)
            _, err = _staged_files()
            check("git_error_reported", bool(err), (err or "无错误")[:40])
        finally:
            os.chdir(old)

    check("unreadable_blocks", decide_exit(0, 1, 1, 0, "", False)[0] == ac.EXIT_USAGE)
    check("git_error_blocks", decide_exit(0, 0, 0, 0, "fatal: not a git repository", False)[0]
          == ac.EXIT_USAGE)
    check("missing_all_blocks", decide_exit(0, 0, 0, 1, "", False)[0] == ac.EXIT_USAGE)
    check("strict_zero_blocks", decide_exit(0, 0, 0, 0, "", True)[0] == ac.EXIT_USAGE)
    check("zero_nonstrict_passes", decide_exit(0, 0, 0, 0, "", False)[0] == ac.EXIT_OK)
    check("blocking_fails", decide_exit(1, 0, 1, 0, "", False)[0] == ac.EXIT_FAIL)
    check("clean_passes", decide_exit(0, 0, 3, 0, "", True)[0] == ac.EXIT_OK)

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

    missing: List[str] = []
    error = ""
    root: Optional[Path] = None
    scope_label = ""
    paths: List[Path] = []

    if args.paths is not None:
        raw, missing = resolve_paths(args.paths)
        for name in missing:
            logger.warning("指定路径不存在：%s", name)
        if not raw:
            code, msg = decide_exit(0, 0, 0, len(missing), "", args.strict)
            if code:
                logger.error("❌ %s", msg)
            else:
                logger.info("指定路径均不存在，跳过扫描（未启用 --strict）")
            return code
        exts = list(dict.fromkeys(
            list(cfg.get("include_ext", [])) + list(cfg.get("semantic_scan_ext", []))
        ))
        expanded: List[Path] = []
        for p in raw:
            if p.is_dir():
                expanded.extend(ac.iter_files(
                    [p], exts,
                    cfg.get("exclude_dirs", []), cfg.get("exclude_globs", [])))
            else:
                expanded.append(p)
        seen: set = set()
        for p in expanded:
            key = str(p.resolve())
            if key not in seen:
                seen.add(key)
                paths.append(p)
        scope_label = "(paths)"
    elif args.cached:
        paths, error = _staged_files()
        scope_label = "(staged)"
    else:
        root = _resolve_root(args.root, cfg)
        if not root.exists():
            logger.error("扫描根不存在：%s", root)
            return ac.EXIT_USAGE
        scope_label = ac.rel_to_workspace(root)

    if error:
        code, msg = decide_exit(0, 0, 0, len(missing), error, args.strict)
        logger.error("❌ %s", msg)
        return code

    if args.paths is None and not args.cached:
        assert root is not None
        rep = scan(root, cfg, blacklist)
        hits = rep["hits"]
        files_scanned = rep["summary"]["files_scanned"]
        unreadable = list(rep["unreadable_files"])
    else:
        hits, files_scanned, unreadable = scan_paths_detailed(paths, cfg, blacklist)

    counts = ac.scanner_severity_counts(hits)
    report = {
        "scanner": SCANNER, "generated_at": ac.now_iso(),
        "root": scope_label,
        "config_ref": ac.rel_to_workspace(ac.BLACKLIST_PATH),
        "summary": {
            "files_scanned": files_scanned, "hits": len(hits),
            "unreadable": len(unreadable),
            "missing_paths": len(missing),
            "blocking": counts[ac.SEV_BLOCK], "block": counts[ac.SEV_BLOCK],
            "warn": counts[ac.SEV_WARN], "snapshot": counts[ac.SEV_SNAPSHOT],
            "info": counts[ac.SEV_INFO],
        },
        "unreadable_files": unreadable,
        "missing_files": missing,
        "hits": hits,
    }
    pj = ac.emit_scanner_report(report, args.report, overwrite=args.overwrite)
    s = report["summary"]
    logger.info("扫过 %d 个文件：命中 %d（blocking=%d, warn=%d, snapshot=%d, info=%d）；"
                "读不出 %d、指定路径缺失 %d；报告：%s",
                s["files_scanned"], s["hits"], s["blocking"], s["warn"],
                s["snapshot"], s["info"], s["unreadable"], s["missing_paths"],
                ac.rel_to_workspace(pj))
    for item in unreadable:
        logger.error("  未检查：%s [%s] %s", item["file"], item["status"], item["reason"])
    if s.get("warn"):
        logger.warning("warn 级命中 %d 条（不阻断，需人工确认是否为新测值/历史标注）", s["warn"])

    code, msg = decide_exit(s["blocking"], s["unreadable"], files_scanned,
                            len(missing), "", args.strict)
    if code == ac.EXIT_USAGE:
        logger.error("❌ %s", msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
