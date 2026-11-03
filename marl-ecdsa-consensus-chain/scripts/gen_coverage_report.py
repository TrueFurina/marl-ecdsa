#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_coverage_report.py — 覆盖率报告生成（2026-10-15）
=====================================================
数据源：pytest-cov 产出的 coverage JSON（由
  python -m pytest tests/ --cov=blockchain --cov-report=json:.coverage_core.json
生成）。**数字不手抄**，全部程序化读取。

产出：deliverables/覆盖率报告_YYYYMMDD.md（人读）+ 控制台摘要。

用法：
  python scripts/gen_coverage_report.py [--json .coverage_core.json] [--out <md>]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELIV = ROOT.parent / "deliverables"

# 核心模块分组（用于"核心链路覆盖率"这一对外表述，须与阈值检查一致）
CORE_GROUPS = {
    "共识层": ("blockchain/consensus/", "blockchain\\consensus\\"),
    "密码层": ("blockchain/crypto/", "blockchain\\crypto\\"),
    "账本层": ("blockchain/ledger/", "blockchain\\ledger\\"),
    "合约层": ("blockchain/contracts/", "blockchain\\contracts\\"),
}


def norm(p: str) -> str:
    return p.replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=".coverage_core.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-core", type=float, default=90.0,
                    help="核心模块（共识/密码/账本/合约）覆盖率下限，低于即非零退出")
    args = ap.parse_args()

    fp = ROOT / args.json
    if not fp.exists():
        print(f"[FATAL] 覆盖率 JSON 不存在：{fp}", file=sys.stderr)
        return 2
    d = json.loads(fp.read_text(encoding="utf-8"))
    files = d["files"]
    tot = d["totals"]

    rows = []
    for name, info in files.items():
        s = info["summary"]
        rows.append({
            "path": norm(name),
            "stmts": s["num_statements"],
            "miss": s["missing_lines"],
            "cover": s["percent_covered"],
        })
    rows.sort(key=lambda r: r["cover"])

    # 分组汇总（按语句数加权）
    groups = {}
    for g, prefixes in CORE_GROUPS.items():
        sel = [r for r in rows if r["path"].startswith(tuple(norm(p) for p in prefixes))]
        st = sum(r["stmts"] for r in sel)
        cv = sum(r["stmts"] - r["miss"] for r in sel)
        groups[g] = (st, cv, (cv / st * 100 if st else 0.0), len(sel))
    core_st = sum(v[0] for v in groups.values())
    core_cv = sum(v[1] for v in groups.values())
    core_pct = core_cv / core_st * 100 if core_st else 0.0

    today = date.today().strftime("%Y%m%d")
    if args.out:
        out = Path(args.out)
    elif DELIV.is_dir():
        out = DELIV / f"覆盖率报告_{today}.md"
    else:
        # CI 环境：仓库之外没有 deliverables/ ⇒ 回落到仓库内，避免在 CI 工作区
        # 之外建目录（既有踩坑：下游脚本硬编码仓库外路径在 CI 静默失败）
        out = ROOT / f"coverage_report_{today}.md"

    lines = [
        f"# 测试覆盖率报告（{date.today().isoformat()}）",
        "",
        "> 工具：pytest-cov；命令：`python -m pytest tests/ --cov=blockchain "
        "--cov-report=json:.coverage_core.json`",
        "> ⚠ 本报告数字**程序化取自** coverage JSON，不手抄；命令与数据文件同时留档。",
        "",
        "## 一、总览",
        "",
        f"- 语句总数：**{tot['num_statements']}**",
        f"- 已覆盖：**{tot['covered_lines']}**",
        f"- 未覆盖：**{tot['missing_lines']}**",
        f"- **总覆盖率：{tot['percent_covered']:.1f}%**",
        f"- **核心链路（共识/密码/账本/合约）覆盖率：{core_pct:.1f}%**"
        f"（{core_cv}/{core_st} 语句）",
        "",
        "## 二、分层覆盖率",
        "",
        "| 层次 | 语句数 | 已覆盖 | 覆盖率 | 文件数 |",
        "|---|---|---|---|---|",
    ]
    for g, (st, cv, pc, n) in sorted(groups.items(), key=lambda kv: -kv[1][2]):
        lines.append(f"| {g} | {st} | {cv} | **{pc:.1f}%** | {n} |")
    lines += [
        "",
        "## 三、逐文件明细（按覆盖率升序，便于定位薄弱点）",
        "",
        "| 文件 | 语句数 | 未覆盖 | 覆盖率 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['path']}` | {r['stmts']} | {r['miss']} | {r['cover']:.0f}% |")

    lines += [
        "",
        "## 四、薄弱点与说明",
        "",
        "按覆盖率升序取最薄的 5 个文件（数字由 coverage JSON 现算，非写死）：",
        "",
        "| 文件 | 覆盖率 | 未覆盖 | 说明 |",
        "|---|---|---|---|",
    ]
    # 针对性说明（按 basename 查表；查不到用通用说明，避免写死数字后失真）
    NOTES = {
        "gossip_discovery.py": "shuffle 主路径已由 test_gossip_discovery 覆盖（54%→74%）；"
                               "剩余为真实 P2P 发现/网络异常分支，依赖真实网络环境，"
                               "集成证据见 NR-94/NR-101",
        "cw_pbft_failover.py": "等价检测/视图更换/裁剪路径已覆盖（70%→83%）；"
                               "剩余为 failover「标记驱动模拟」的少量分支",
        "p2p_node.py": "真实 TCP 收发依赖网络环境，单测覆盖受限；"
                       "集成证据见 NR-94/NR-101",
        "dilithium_adapter.py": "后量子后端为 opt-in 混合签名，部分分支仅在启用时可达",
        "standard_pbft.py": "标准 PBFT 为对照基线，部分异常分支由 CW-PBFT 侧等价覆盖",
        "factory.py": "工厂分支，各引擎类型由对应测试文件覆盖",
    }
    for r in rows[:5]:
        note = NOTES.get(r["path"].split("/")[-1], "异常/边界分支，优先级低")
        lines.append(f"| `{r['path']}` | {r['cover']:.0f}% | {r['miss']} | {note} |")
    lines += [
        "",
        "⛔ 对外表述边界：不得只报「核心 9x%」而不报总体覆盖率；"
        "引用时必须同时给出语句基数与命令。",
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[产出] {out}")
    print(f"[总覆盖率] {tot['percent_covered']:.1f}%  "
          f"[核心链路] {core_pct:.1f}% ({core_cv}/{core_st})")
    for g, (st, cv, pc, n) in sorted(groups.items(), key=lambda kv: -kv[1][2]):
        print(f"   {g}: {pc:.1f}% ({cv}/{st})")

    if core_pct < args.min_core:
        print(f"[FAIL] 核心链路覆盖率 {core_pct:.1f}% < 门限 {args.min_core:.1f}%",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
