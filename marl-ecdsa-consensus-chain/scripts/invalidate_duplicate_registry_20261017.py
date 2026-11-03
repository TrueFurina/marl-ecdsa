#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invalidate_duplicate_registry_20261017.py — 处置重复登记（2026-10-17）
====================================================================
背景：收尾审计（2026-10-17 §19 发现1）确认 NR-132/133 与 NR-175/176 同源同值：
- NR-132 ≡ NR-175：sources glob 逐字节相同（delivery_main/e33_iql_*），declared 同值，
  175 为全精度版（mean_a 18.047717570804487…），132 为 4 位四舍五入快照。
- NR-133 ≡ NR-176：同上（qmix 对）。
两个编号指向同一实验同一批数据，属"同实验重复编号"。按 NR-8 先例须保留全精度版
（175/176）、将 rounded 快照版（132/133）标 INVALID/ superseded，并交叉 notes。

非测量失败、非口径变更——纯数据完整性收口。处置前已核验：
- 权威全量复算（verify_numbers --strict --run-tests，2026-10-17 10:07）total=172
  PASS=167 FAIL=0 PENDING=0 INVALID=5 DATA_MISSING=0，exit 0——132/133 当时亦 PASS（值正确）；
- 材料引用面排查：docx/pptx（解包 XML）+ 全文 grep 双重核验，**无任何材料以 NR-132/133
  作为登记号引用**（二进制扫描命中的 "13[23]" 全部是 p=0.132 消融 p 值误抓）。
  ⇒ 作废 132/133 不牵动材料更新。

纪律（沿用 flip_status_after_verify_20261017.py）：
- 先备份再写；编号写死前断言现状（INVAL 目标须 PASS，否则 FATAL——防并发覆盖）；
- 幂等：INVAL 目标已是 INVALID 则跳过；
- 只改 status（2 条）+ notes（4 条：2 条作废 + 2 条反向交叉引用）；
- 写完自证：条目总数不变、INVAL/CROSSREF 集外条目零改动、目标 status 落位。

⚠ 本脚本不删条目、不删源数据（results/ 不受影响），仅改 status+notes，可逆。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
REG = _REPO_ROOT.parent / "deliverables" / "number_registry.json"

# 作废目标（rounded 快照版）→ 被谁取代
INVAL_TARGETS = {
    "NR-132": "NR-175",
    "NR-133": "NR-176",
}
# 反向交叉引用目标（全精度版，须保留）→ 它取代了谁
CROSS_REF = {
    "NR-175": "NR-132",
    "NR-176": "NR-133",
}

_INVAL_SUFFIX = (
    " | 2026-10-17 标 INVALID（数据完整性收口，非测量失败）：与 {sup} 同源同值"
    "（sources glob 逐字节相同、declared 同值），本条目为 4 位四舍五入快照、{sup}"
    "为全精度版；按 NR-8 先例保留 {sup} 作废本快照。材料引用面已双重核验零引用，"
    "作废不牵动材料。"
)
_CROSS_SUFFIX = (
    " | 2026-10-17 反向交叉引用：本条目为全精度版，取代同源同值的 {dup}"
    "（rounded 快照，已标 INVALID）。"
)


def main() -> int:
    text_before = REG.read_text(encoding="utf-8")
    reg = json.loads(text_before)
    entries = reg["entries"]
    by_id = {e["id"]: e for e in entries}
    n_before = len(entries)

    all_touched = set(INVAL_TARGETS) | set(CROSS_REF)
    missing = [t for t in all_touched if t not in by_id]
    if missing:
        raise SystemExit(f"[FATAL] 条目不存在: {missing}——并行会话可能重构过 registry，停手待人确认。")

    # 并发守卫：INVAL 目标须 PASS（否则可能已被并发改写）
    wrong = [t for t in INVAL_TARGETS if by_id[t].get("status") not in ("PASS", "INVALID")]
    if wrong:
        raise SystemExit(
            f"[FATAL] INVAL 目标状态异常（非 PASS/INVALID）: "
            f"{[(t, by_id[t].get('status')) for t in wrong]}——停手待人确认。")
    # CROSS_REF 目标须 PASS（它们保留）
    wrong_c = [t for t in CROSS_REF if by_id[t].get("status") != "PASS"]
    if wrong_c:
        raise SystemExit(
            f"[FATAL] CROSS_REF 目标状态异常（非 PASS）: "
            f"{[(t, by_id[t].get('status')) for t in wrong_c]}——停手待人确认。")

    already = [t for t in INVAL_TARGETS if by_id[t].get("status") == "INVALID"]
    todo = [t for t in INVAL_TARGETS if by_id[t].get("status") == "PASS"]
    if not todo:
        print(f"[跳过] {len(already)} 条均已 INVALID，无需更改（幂等）")
        return 0

    # 备份
    bak = _REPO_ROOT.parent / "backup"
    bak.mkdir(parents=True, exist_ok=True)
    bak_fp = bak / "number_registry_pre_dup_invalidate_20261017.json"
    bak_fp.write_text(text_before, encoding="utf-8")
    assert bak_fp.stat().st_size > 0, "备份写入失败"

    # 快照（用于结构自断言：非 touched 条目零改动）
    snapshot = {e["id"]: json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries}

    # 1) INVAL 目标：status→INVALID + 作废注记
    for t in todo:
        e = by_id[t]
        e["status"] = "INVALID"
        e["notes"] = (e.get("notes", "") + _INVAL_SUFFIX.format(sup=INVAL_TARGETS[t])) \
            if e.get("notes") else _INVAL_SUFFIX.format(sup=INVAL_TARGETS[t]).lstrip(" |")

    # 2) CROSS_REF 目标：追加反向交叉引用（status 不变）
    for t in CROSS_REF:
        e = by_id[t]
        e["notes"] = (e.get("notes", "") + _CROSS_SUFFIX.format(dup=CROSS_REF[t])) \
            if e.get("notes") else _CROSS_SUFFIX.format(dup=CROSS_REF[t]).lstrip(" |")

    # 写后自证
    assert len(entries) == n_before, "条目总数被改变"
    for eid, snap in snapshot.items():
        if eid in all_touched:
            continue
        assert json.dumps(by_id[eid], ensure_ascii=False, sort_keys=True) == snap, \
            f"非 touched 条目 {eid} 被意外修改"
    for t in todo:
        assert by_id[t]["status"] == "INVALID", f"{t} 作废失败"
    for t in CROSS_REF:
        assert by_id[t]["status"] == "PASS", f"{t} 应保持 PASS"

    REG.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[作废] {len(todo)} 条 PASS→INVALID: {', '.join(todo)}")
    print(f"[交叉] 反向引用已追加至: {', '.join(CROSS_REF)}")
    print(f"[备份] {bak_fp}")
    print(f"[条目总数] {n_before}（不变）｜touched 集外零改动 ✓")
    print("\n⚠ 下一步：check_registry_mirror.py --sync  →  verify_numbers.py --strict --run-tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
