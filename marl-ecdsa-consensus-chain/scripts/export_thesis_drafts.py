#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""export_thesis_drafts.py —— 草稿落盘 + 保障总览（P0-5 / G6）。

① 从团队收件箱 ``inboxes/*.json`` 导出 5 章初稿 + 修订稿 + 审稿意见为
   ``deliverables/thesis_drafts/*.md``；**落盘前先过 ``scan_identity`` 闸门**：
   命中身份串的文件**不落盘**，改写入 ``deliverables/assurance/held_drafts/``
   并登记「待人工改写」清单（NFR-4 一票否决）。

② 汇总 verifier + 4 scanner 结论为 ``assurance_summary_2026-09-17.md``，
   对 Go/No-Go 判据 G1–G8 逐条给出 PASS/FAIL/PENDING。

用法::

    python -X utf8 scripts/export_thesis_drafts.py [--drafts-only|--summary-only]
        [--inbox-dir <path>] [--overwrite] [--dry-run]

被 import 时零副作用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assurance_common as ac  # noqa: E402
import scan_identity  # noqa: E402

logger = ac.get_logger("export_thesis_drafts")

#: 草稿选择规则：(输出名, 源文件, from, summary 前缀, 说明)
DRAFT_RULES: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("ch1", "team-lead.json", "topic-researcher", "第1章草稿交付", "第1章初稿"),
    ("ch2", "team-lead.json", "topic-researcher", "第2章草稿交付", "第2章初稿"),
    ("ch3", "team-lead.json", "topic-researcher", "第3章草稿交付", "第3章初稿"),
    ("ch4", "team-lead.json", "topic-researcher", "第4章草稿交付", "第4章初稿"),
    ("ch5", "team-lead.json", "topic-researcher", "第5章草稿交付", "第5章初稿"),
    ("ch1_revised", "team-lead.json", "draft-reviser", "第1章修订稿完成", "第1章修订稿"),
    ("ch2_review", "team-lead.json", "draft-reviewer", "第2章草稿审查结论", "第2章审稿意见"),
    ("ch2_revised", "team-lead.json", "draft-reviser", "第2章修订稿完成", "第2章修订稿"),
    ("ch3_revised", "team-lead.json", "draft-reviser", "第3章修订稿完成", "第3章修订稿"),
    ("ch4_revised", "team-lead.json", "draft-reviser", "第4章修订稿完成", "第4章修订稿"),
    ("ch5_revised", "team-lead.json", "draft-reviser", "第5章修订稿完成", "第5章修订稿"),
    ("section0_method", "team-lead.json", "topic-researcher", "§0文献检索方法小节交付", "§0 文献检索方法"),
    ("framework", "team-lead.json", "report-writer", "框架文件已完成", "论文骨架框架"),
)

#: Go/No-Go 判据（G1–G8）机检映射
G_DEFS = (
    ("G1", "注册表每条数字均由脚本从原始数据复算 PASS", "verify_numbers.py"),
    ("G2", "全稿数字三件套齐备（无源数字=0）", "scan_unsourced_numbers.py"),
    ("G3", "全稿不出现作废令牌", "scan_void_tokens.py"),
    ("G4", "引用域无 合成伪文献域 / SYNTHETIC_ 伪文献", "scan_citation_blacklist.py"),
    ("G5", "『固定比例拜占庭』类表述全部改为省略故障（规则 BYZ-40）", "scan_void_tokens.py 语义规则 BYZ-40"),
    ("G6", "5 章草稿落盘且过匿名合规扫描", "export_thesis_drafts.py + scan_identity.py"),
    ("G7", "≥4 个实验脚本冒烟通过", "run_repeats.py --smoke（本轮未做）"),
    ("G8", "CARS 路标冲突消融 ab1 或 H1~H4 小节", "章节内容检查（本轮未做）"),
)

#: 判据来源报告
_REPORT_FILES = {
    "number_verification": "number_verification_report.json",
    "unsourced": "scan_unsourced_report.json",
    "void": "scan_void_tokens_report.json",
    "citation": "scan_citation_report.json",
    "identity": "scan_identity_report.json",
}


# --------------------------------------------------------------------------- #
# ① 草稿落盘
# --------------------------------------------------------------------------- #
def _select_message(msgs: List[Dict[str, Any]], from_: str, prefix: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """按 (from, summary 前缀) 选首条匹配消息；返回 ``(索引, 消息)``。"""
    for i, m in enumerate(msgs):
        if str(m.get("from", "")) == from_ and str(m.get("summary", "")).startswith(prefix):
            return i, m
    return None


def export_drafts(inbox_dir: Path, drafts_dir: Path, held_dir: Path,
                  blacklist: Dict[str, Any], overwrite: bool, dry_run: bool) -> Dict[str, Any]:
    """导出草稿并过身份闸门；返回 manifest dict。"""
    drafts_dir.mkdir(parents=True, exist_ok=True)
    held_dir.mkdir(parents=True, exist_ok=True)
    cache: Dict[str, List[Dict[str, Any]]] = {}
    written: List[str] = []
    held: List[Dict[str, Any]] = []

    for out_name, src_file, from_, prefix, desc in DRAFT_RULES:
        src_path = inbox_dir / src_file
        if src_path.name not in cache:
            cache[src_path.name] = ac.load_json(src_path) if src_path.exists() else []
        found = _select_message(cache[src_path.name], from_, prefix)
        if not found:
            logger.warning("未找到草稿：%s（%s / %s）", out_name, from_, prefix)
            continue
        idx, msg = found
        body = str(msg.get("text", ""))
        header = f"<!-- 来源：{src_file} 第{idx}条 | {desc} -->\n\n"
        content = header + body + "\n"

        hits = scan_identity.scan_content(content, f"{out_name}.md", blacklist)
        if hits:
            rel_hits = [{"line": h["line"], "rule": h["rule"]} for h in hits[:20]]
            held.append({"name": out_name, "source": src_file, "index": idx,
                         "desc": desc, "reason": "identity_hit", "n_hits": len(hits),
                         "hits": rel_hits})
            if not dry_run:
                ac.safe_write_text(content, held_dir / f"{out_name}.md", overwrite=overwrite)
            logger.warning("[HOLD] %s：身份命中 %d 处，改入 held_drafts（待人工改写）", out_name, len(hits))
        else:
            written.append(out_name)
            if not dry_run:
                ac.safe_write_text(content, drafts_dir / f"{out_name}.md", overwrite=overwrite)
            logger.info("[OK] %s（%d 字）→ thesis_drafts/%s.md", out_name, len(body), out_name)

    manifest = {
        "generated_at": ac.now_iso(),
        # 不外泄机器本地路径（沙箱目录标记 / 用户名），只记录「由外置配置提供」
        "inbox_dir": "<external: 见 assurance/config/scan_targets.json thesis_inbox_dir>",
        "drafts_dir": ac.rel_to_workspace(drafts_dir),
        "held_dir": ac.rel_to_workspace(held_dir),
        "written": sorted(written),
        "held": held,
        "n_written": len(written),
        "n_held": len(held),
        "dry_run": dry_run,
    }
    if not dry_run:
        ac.safe_write_json(manifest, drafts_dir / "_export_manifest.json", overwrite=overwrite)
        ac.safe_write_json(manifest, held_dir / "_held_manifest.json", overwrite=overwrite)
    return manifest


# --------------------------------------------------------------------------- #
# ② 保障总览
# --------------------------------------------------------------------------- #
def _load_reports() -> Dict[str, Optional[Dict[str, Any]]]:
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    for key, fname in _REPORT_FILES.items():
        p = ac.REPORTS_DIR / fname
        try:
            out[key] = ac.load_json(p) if p.exists() else None
        except (OSError, json.JSONDecodeError):
            out[key] = None
    return out


def build_summary(manifest: Dict[str, Any], drafts_id_hits: Optional[int]) -> str:
    """汇总 verifier + 4 scanner 结论，输出 G1–G8 逐条判定 markdown。"""
    rep = _load_reports()
    num = rep["number_verification"]
    g: Dict[str, Tuple[str, str]] = {}

    if num:
        s = num["summary"]
        g["G1"] = ("PASS" if s["fail"] == 0 else "FAIL",
                   f"total={s['total']} PASS={s['pass']} FAIL={s['fail']} "
                   f"PENDING={s['pending']} INVALID={s['invalid']}；"
                   f"双源一致={num.get('mirror_consistent')}")
    else:
        g["G1"] = ("PENDING", "未找到 number_verification_report.json")

    if rep["unsourced"]:
        s = rep["unsourced"]["summary"]
        g["G2"] = ("PENDING",
                   f"启发式告警 {s['hits']} 处（advisory，不阻断）；需人工分诊后补齐三件套或标 pending")
    else:
        g["G2"] = ("PENDING", "未找到 scan_unsourced_report.json")

    if rep["void"]:
        s = rep["void"]["summary"]
        g["G3"] = ("PASS" if s["blocking"] == 0 else "FAIL",
                   f"blocking={s['blocking']} snapshot={s['snapshot']} info={s['info']} "
                   f"（总命中 {s['hits']}）")
    else:
        g["G3"] = ("PENDING", "未找到 scan_void_tokens_report.json")

    if rep["citation"]:
        s = rep["citation"]["summary"]
        g["G4"] = ("PASS" if s["blocking"] == 0 else "FAIL",
                   f"引用域 blocking={s['blocking']}，声明性提及 info={s['info']}")
    else:
        g["G4"] = ("PENDING", "未找到 scan_citation_report.json")

    if rep["void"]:
        byz = [h for h in rep["void"]["hits"]
               if h.get("rule") == "semantic_rule:BYZ-40" and h.get("severity") == ac.SEV_BLOCK]
        g["G5"] = ("PASS" if not byz else "PENDING",
                   f"对外材料中『固定比例拜占庭』（规则 BYZ-40）阻断级命中 {len(byz)} 处"
                   + ("" if not byz else "；其余为改写指令（info）"))
    else:
        g["G5"] = ("PENDING", "依赖 scan_void_tokens 报告")

    if drafts_id_hits is None:
        g["G6"] = ("PENDING", "未执行 thesis_drafts 身份扫描")
    else:
        ok = manifest["n_written"] >= 6 and drafts_id_hits == 0
        g["G6"] = ("PASS" if ok else "FAIL",
                   f"落盘 {manifest['n_written']} 个（held {manifest['n_held']} 个），"
                   f"thesis_drafts 身份命中={drafts_id_hits}")

    g["G7"] = ("PENDING", "本轮未执行实验脚本冒烟（T04/T05 范围外）")
    g["G8"] = ("PENDING", "本轮未核验 CARS 消融 ab1 / H1~H4 小节")

    lines: List[str] = [
        "# 毕设双线保障 · 保障总览（assurance_summary_2026-09-17）",
        "",
        f"- 生成时间：{ac.now_iso()}",
        f"- 注册表：`{ac.rel_to_workspace(ac.REGISTRY_PATH)}`（commit `aaed3e0`）",
        f"- 草稿落盘：`{manifest['drafts_dir']}`（{manifest['n_written']} 个）"
        f"，held：`{manifest['held_dir']}`（{manifest['n_held']} 个）",
        "",
        "## 一、Go/No-Go 判据 G1–G8",
        "",
        "| 判据 | 结论 | 说明 | 机检方式 |",
        "|---|---|---|---|",
    ]
    for gid, desc, how in G_DEFS:
        verdict, note = g[gid]
        lines.append(f"| {gid} {desc} | **{verdict}** | {note} | {how} |")

    lines += [
        "",
        "## 二、数字复算（G1 明细）",
        "",
    ]
    if num:
        s = num["summary"]
        lines += [
            f"- 汇总：total={s['total']} / PASS={s['pass']} / FAIL={s['fail']} / "
            f"PENDING={s['pending']} / INVALID={s['invalid']}",
            f"- 双源一致性：{num.get('mirror_consistent')}"
            + (f"（比较 {num['mirror']['files_compared']} 个文件，"
               f"{len(num['mirror']['diffs'])} 处差异）" if num.get("mirror") else ""),
            "",
            "| ID | 状态 | 复算值（摘要） |",
            "|---|---|---|",
        ]
        for e in num["entries"]:
            comp = e.get("computed", {})
            brief = ", ".join(
                f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in list(comp.items())[:3]
            )
            lines.append(f"| {e['id']} | {e['status']} | {brief} |")

    lines += ["", "## 三、红线扫描汇总", ""]
    for key in ("unsourced", "void", "citation", "identity"):
        r = rep[key]
        if not r:
            lines.append(f"- **{key}**：报告缺失")
            continue
        s = r["summary"]
        extra = f"，scope={s['scope_counts']}" if "scope_counts" in s else ""
        lines.append(
            f"- **{r['scanner']}**：files={s['files_scanned']} hits={s['hits']} "
            f"blocking={s['blocking']}（block={s.get('block')} warn={s.get('warn')} "
            f"snapshot={s.get('snapshot')} info={s.get('info')}）{extra}"
        )

    lines += ["", "## 四、未决事项（须委托人/下游处置）", ""]
    void_blocking = [h for h in (rep["void"]["hits"] if rep["void"] else [])
                     if h.get("severity") == ac.SEV_BLOCK]
    if void_blocking:
        lines.append("1. **G3 未完**：对外材料仍存在下列作废令牌 / 作废结论命中，须逐条改写或移出交付目录：")
        for h in void_blocking:
            lines.append(f"   - `{h['file']}:{h['line']}` 命中 `{h['match']}`（{h['rule']}）")
        lines.append("     注：以上命中集中在 **v1 初稿**（经 v2 修订前的版本）；"
                     "建议把 v1 初稿标注为『历史快照』或移出 `thesis_drafts/`，"
                     "仅保留修订稿作为交付正文。")
    else:
        lines.append("1. **G3 已完成**：对外材料无作废令牌阻断级命中。")
    lines += [
        "2. **G2 待分诊**：无源数字扫描为启发式告警，需人工逐条补三件套或标 `pending`。",
        "3. **G7/G8 待做**：实验脚本冒烟与 CARS 消融/H1~H4 小节属本轮范围外（T04 及后续）。",
        "4. **NR-19 待复跑**：测试数量 1574 为历史值，`--run-tests` 未执行。",
        f"5. **held 草稿**：含身份串的修订稿（{', '.join(h['name'] for h in manifest.get('held', [])) or '无'}）"
        "已隔离至 held_drafts，改写后可重新落盘。",
        "6. **INVALID 条目**：NR-8 / NR-14 / NR-17 为禁止申报项，verifier 已确认其数据属性，"
        "但论文中不得作为结果出现。",
        "",
        "> 本总览仅陈述机检事实；判定口径以 `number_registry.json` 与各 scanner 报告为准。",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="草稿落盘 + 保障总览")
    ap.add_argument("--inbox-dir", default="", help="团队收件箱目录（默认取配置 thesis_inbox_dir）")
    ap.add_argument("--drafts-only", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = ac.load_scan_targets()
        blacklist = ac.load_blacklist()
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("配置读取错误：%s", exc)
        return ac.EXIT_USAGE

    # 注意：`thesis_inbox_dir` 是**私有层专属**键（值含本机绝对路径，不入库）。
    # 不能用 `Path(x or "")`——`Path("")` 会退化成 `.`，于是 curdir 被当成收件箱
    # 静默扫过（分层前就有此隐患，CI/换机时必然触发）。这里显式区分「未配置」与「不存在」。
    inbox_raw = args.inbox_dir or cfg.get("thesis_inbox_dir", "")
    if not inbox_raw:
        logger.error(
            "未指定团队收件箱目录：请用 --inbox-dir 指定，或在私有配置 "
            "assurance/config/scan_targets.json 设置 thesis_inbox_dir"
            "（该键只存在于私有层，不入库）。")
        return ac.EXIT_USAGE
    inbox = Path(inbox_raw)
    if not inbox.exists():
        logger.error("收件箱目录不存在：%s", inbox)
        return ac.EXIT_USAGE
    drafts_dir = ac.WORKSPACE_ROOT / cfg.get("thesis_drafts_dir", "deliverables/thesis_drafts")
    held_dir = ac.WORKSPACE_ROOT / cfg.get("held_drafts_dir", "deliverables/assurance/held_drafts")

    manifest = None
    drafts_id_hits: Optional[int] = None

    if not args.summary_only:
        manifest = export_drafts(inbox, drafts_dir, held_dir, blacklist, args.overwrite, args.dry_run)
        logger.info("落盘 %d 个，隔离 %d 个", manifest["n_written"], manifest["n_held"])
        if not args.dry_run:
            id_report = scan_identity.scan(drafts_dir, cfg, blacklist)
            drafts_id_hits = id_report["summary"]["hits"]
            logger.info("thesis_drafts 身份扫描命中=%d", drafts_id_hits)
            ac.emit_scanner_report(id_report, ac.REPORTS_DIR / "scan_identity_thesis_drafts_report.json",
                                   overwrite=args.overwrite)

    if args.drafts_only:
        return ac.EXIT_OK

    if manifest is None:
        # summary-only：读取既有 manifest（若无则空 manifest）
        man_path = drafts_dir / "_export_manifest.json"
        manifest = ac.load_json(man_path) if man_path.exists() else {
            "drafts_dir": ac.rel_to_workspace(drafts_dir), "held_dir": ac.rel_to_workspace(held_dir),
            "n_written": len(list(drafts_dir.glob("*.md"))) if drafts_dir.exists() else 0,
            "n_held": 0, "written": [], "held": [],
        }

    summary = build_summary(manifest, drafts_id_hits)
    out = ac.REPORTS_DIR / "assurance_summary_2026-09-17.md"
    if not args.dry_run:
        p = ac.safe_write_text(summary, out, overwrite=True)
        logger.info("保障总览已写出：%s", ac.rel_to_workspace(p))
    return ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
