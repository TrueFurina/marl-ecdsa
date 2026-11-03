#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flip_status_after_verify_20261017.py — 登记簿 status 除尘（2026-10-17）
====================================================================
背景：2026-10-15 登记 E39 容错活性谱（NR-147~173，27 条）与 10-16 登记 E41
（NR-179）时，register 脚本按惯例写 status=PENDING；当日全量复算其实已通过
（E39 各条 declared 与 canonical 复算一致），但文件态一直挂 PENDING 未翻。

本次依据：2026-10-17 09:06 全量复算实测（verify_numbers --registry
../deliverables/number_registry.json --data-root results，total=172
PASS=166 FAIL=0 PENDING=1(NR-19 测试计数，设计使然须 --run-tests)
INVALID=5 DATA_MISSING=0，exit 0）——NR-147~173 与 NR-179 运行时状态均为
PASS。本脚本把**文件态**更正为与实测一致，并追加带日期的 provenance 注记。

纪律（沿用 register_* 系列）：
- 先备份再写；编号/条目集合写死前断言现状（PENDING 才动，已 PASS 跳过，
  非 PENDING 直接 FAIL——防并行会话并发改写被静默覆盖）；
- 只允许改 status 与 notes 两个字段，其余字段逐条断言不变；
- 写完自证：条目总数不变、目标集外条目零改动、目标集 status 全 PASS。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
REG = _REPO_ROOT.parent / "deliverables" / "number_registry.json"

TARGETS = [f"NR-{n}" for n in range(147, 174)] + ["NR-179"]
NOTE_SUFFIX = (
    " | 2026-10-17 全量复算实测 PASS（verify_numbers total=172 PASS=166 "
    "FAIL=0，exit 0），文件态 status 由 PENDING 更正为 PASS——登记当日即已验证，"
    "仅补翻文件态。"
)


def main() -> int:
    text_before = REG.read_text(encoding="utf-8")
    reg = json.loads(text_before)
    entries = reg["entries"]
    by_id = {e["id"]: e for e in entries}
    n_before = len(entries)

    # ── 现状断言（并发写防护 + 幂等）──
    missing = [t for t in TARGETS if t not in by_id]
    if missing:
        raise SystemExit(f"[FATAL] 目标条目不存在: {missing}——并行会话可能重构过 registry，停手待人确认。")
    wrong = [t for t in TARGETS if by_id[t].get("status") not in ("PENDING", "PASS")]
    if wrong:
        raise SystemExit(
            f"[FATAL] 目标条目状态异常（非 PENDING/PASS）: {[(t, by_id[t].get('status')) for t in wrong]}"
            "——停手待人确认。")
    already = [t for t in TARGETS if by_id[t].get("status") == "PASS"]
    todo = [t for t in TARGETS if by_id[t].get("status") == "PENDING"]
    if not todo:
        print(f"[跳过] {len(already)} 条均已 PASS，无需更改（幂等）")
        return 0

    # ── 备份 ──
    bak = _REPO_ROOT.parent / "backup"
    bak.mkdir(parents=True, exist_ok=True)
    bak_fp = bak / "number_registry_pre_statusflip_20261017.json"
    bak_fp.write_text(text_before, encoding="utf-8")
    assert bak_fp.stat().st_size > 0, "备份写入失败"

    # ── 只改 status + notes ──
    snapshot = {e["id"]: json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries}
    for t in todo:
        e = by_id[t]
        e["status"] = "PASS"
        e["notes"] = (e.get("notes", "") + NOTE_SUFFIX) if e.get("notes") else NOTE_SUFFIX.lstrip(" |")

    # ── 写后自证 ──
    assert len(entries) == n_before, "条目总数被改变"
    for eid, snap in snapshot.items():
        if eid in todo:
            continue
        assert json.dumps(by_id[eid], ensure_ascii=False, sort_keys=True) == snap, \
            f"非目标条目 {eid} 被意外修改"
    for t in todo:
        assert by_id[t]["status"] == "PASS", f"{t} 翻状态失败"

    REG.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[更正] {len(todo)} 条 PENDING→PASS: {todo[0]}..{todo[-1]}")
    print(f"[备份] {bak_fp}")
    print(f"[条目总数] {n_before}（不变）｜目标集外零改动 ✓")
    print("\n⚠ 下一步：check_registry_mirror.py --sync  →  verify_numbers.py --strict --run-tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
