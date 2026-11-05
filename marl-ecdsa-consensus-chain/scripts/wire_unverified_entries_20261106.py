#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""wire_unverified_entries_20261106.py —— 把「PASS 但零断言」的登记条目接上真数据。

## 缺陷（2026-11-06 审计实测，非推断）

``scripts/verify_numbers.py::compare()`` 只遍历 ``declared`` 里的键；``declared``
为空时循环体一次都不执行，``ok`` 保持初值 ``True`` ⇒ **判 PASS**。受影响的 7 条：

=====================  ============================================================
ID                     现象
=====================  ============================================================
NR-180 ~ NR-183        ``analysis=none`` + ``sources=[]`` + ``declared={}``，却登记
                       ``status=PASS``。实测：在**完全没有数据**的仓库里跑门禁，
                       这 4 条判 PASS，其余 187 条全是 DATA_MISSING/PENDING/INVALID
NR-120 / 121 / 122     ``analysis=benchmark`` + ``declared={}``。实测：喂进一份与
                       主张**相反**的数据（吞吐 1 pkg/s、拦截 0/999999），NR-121
                       仍判 PASS、``deltas={}``（零次比对）、退出码 0
=====================  ============================================================

于是报告抬头的 ``PASS=184`` 里有 7 条是空断言 —— 「PASS」在那里等于「没检查」。

## 本脚本做什么

1. **NR-180~183 接真数据**：改成 ``analysis=benchmark`` + 显式 ``paths`` 嵌套取数
   （``ml_defender.train_accuracy`` / ``runs.L1_omniscient[].coop_rate#min`` /
   ``runs.L2_adaptive[seed=11].coop_rate``），``declared`` 填入**从这些源文件实测
   出来的值**。这 4 条从「零断言 PASS」变成「真的逐值比对」，且源文件缺失时会
   如实变成 DATA_MISSING，而不是继续 PASS。
2. **NR-120/121/122 降级为 PENDING**：E22/E23/E24 的结果文件（
   ``results/security_replay_20261014/`` 等）不在版本库内，本机测不出 ``declared``。
   **不猜数**、也不把 claim 里的文字数字抄成 ``declared``（那是自证），改为
   PENDING：不阻断常规运行，但 ``--strict`` 下阻断，直到 owner 用真实数据补登。
3. 目标是镜像（含 ``_mirror_of``）时重算 ``_mirror_sha256``，保持
   「镜像记录的指纹 == 镜像自身内容指纹」这一不变式。

## 权威源（只读镜像 ↔ 工作区权威，两边都要跑）

``number_registry.json`` 是只读镜像，权威在 ``<工作区>/deliverables/number_registry.json``
（``assurance_common.REGISTRY_PATH``）。**只在一边跑**会让
``scripts/check_registry_mirror.py --check`` 正确地报「两边不一致」::

    python -X utf8 scripts/wire_unverified_entries_20261106.py --apply
    python -X utf8 scripts/wire_unverified_entries_20261106.py --apply \\
        --registry ../deliverables/number_registry.json
    python -X utf8 scripts/check_registry_mirror.py --check     # 应为 PASS

## 幂等

条目按 **id + 内容** 判定：已是目标态就跳过（不重复追加 note、不覆盖 owner 后续
实测出来的 declared）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402
from check_registry_mirror import entity_fingerprint  # noqa: E402

MIRROR_KEYS = ("_mirror_of", "_mirror_note", "_mirror_sha256", "_mirror_generated_by")

#: 2026-11-06 审计说明，写进被降级条目的 notes 末尾（幂等：已含则不再追加）
_AUDIT_NOTE = (
    "【2026-11-06 审计】本条原登记 status=PASS 但 declared 为空 ⇒ 门禁对它是零断言"
    "通过（compare() 旧实现对空 declared 返回 True）。E22/E23/E24 结果文件不在版本库内，"
    "本机无法实测 declared，故降级为 PENDING：不得在 declared 补齐前标回 PASS。"
    "补齐方式见 scripts/wire_unverified_entries_20261106.py 文件头。"
)

#: 接了真数据的 4 条：源文件都在仓库内，declared 为**实测值**（2026-11-06 复算）
_WIRED: Dict[str, Dict[str, Any]] = {
    "NR-180": {
        "analysis": "benchmark",
        "sources": [{
            "file": "scripts/security/ml_blindspot_result.json",
            "paths": {
                "train_accuracy": "ml_defender.train_accuracy",
                "train_samples": "ml_defender.train_samples",
                "heldout_samples": "ml_defender.heldout_samples",
            },
        }],
        "declared": {
            "train_accuracy": 0.9882,
            "train_samples": 9600,
            "heldout_samples": 2400,
        },
    },
    "NR-181": {
        "analysis": "benchmark",
        "sources": [{
            "file": "scripts/security/ml_blindspot_result.json",
            "paths": {
                "heldout_accuracy": "ml_defender.heldout_accuracy",
                "off_manifold_samples": "ml_defender.benign_diag.off_manifold_samples",
                "total_samples": "ml_defender.benign_diag.total_samples",
            },
        }],
        "declared": {
            "heldout_accuracy": 0.9879,
            "off_manifold_samples": 0,
            "total_samples": 12000,
        },
    },
    "NR-182": {
        "analysis": "benchmark",
        "sources": [{
            "file": "scripts/security/adaptive_attacker_result.json",
            "paths": {
                "L1_coop_mean": "runs.L1_omniscient[].coop_rate",
                "L1_coop_min": "runs.L1_omniscient[].coop_rate#min",
                "L1_coop_max": "runs.L1_omniscient[].coop_rate#max",
                "L1_n_seeds": "runs.L1_omniscient[].coop_rate#n",
            },
        }],
        "declared": {
            "L1_coop_mean": 0.995,
            "L1_coop_min": 0.995,
            "L1_coop_max": 0.995,
            "L1_n_seeds": 5,
        },
    },
    "NR-183": {
        "analysis": "benchmark",
        "sources": [{
            "file": "scripts/security/adaptive_attacker_result.json",
            "paths": {"L2_seed11_coop": "runs.L2_adaptive[seed=11].coop_rate"},
        }],
        "declared": {"L2_seed11_coop": 0.825},
    },
}

#: 无本地数据可复算、只能降级为 PENDING 的条目
_DOWNGRADE = ("NR-120", "NR-121", "NR-122")


def load_registry(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(path: Path, doc: Dict[str, Any]) -> None:
    """按版本库风格落盘：indent=1 / LF / 无尾换行（与既有镜像逐字节风格一致）。"""
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _refresh_mirror_fingerprint(doc: Dict[str, Any]) -> bool:
    """镜像：把 ``_mirror_sha256`` 重算为自身内容指纹（保持自洽）。"""
    if "_mirror_of" not in doc:
        return False
    fp = entity_fingerprint(doc)
    if doc.get("_mirror_sha256") == fp:
        return False
    doc["_mirror_sha256"] = fp
    return True


def plan(doc: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """生成迁移计划：``[(id, action, changes)]``，不改动 doc。"""
    out: List[Tuple[str, str, Dict[str, Any]]] = []
    by_id = {e.get("id"): e for e in doc.get("entries", [])}
    for rid, spec in _WIRED.items():
        entry = by_id.get(rid)
        if entry is None:
            out.append((rid, "MISSING", {}))
            continue
        changes = {}
        if entry.get("analysis") != spec["analysis"]:
            changes["analysis"] = spec["analysis"]
        if entry.get("sources") != spec["sources"]:
            changes["sources"] = spec["sources"]
        if entry.get("declared") != spec["declared"]:
            changes["declared"] = spec["declared"]
        out.append((rid, "WIRE" if changes else "NOOP", changes))
    for rid in _DOWNGRADE:
        entry = by_id.get(rid)
        if entry is None:
            out.append((rid, "MISSING", {}))
            continue
        changes = {}
        if entry.get("status") != "PENDING":
            changes["status"] = "PENDING"
        if _AUDIT_NOTE not in (entry.get("notes") or ""):
            changes["notes"] = ((entry.get("notes") or "").rstrip() + " " + _AUDIT_NOTE).strip()
        out.append((rid, "DOWNGRADE" if changes else "NOOP", changes))
    return out


def apply_plan(doc: Dict[str, Any], steps: List[Tuple[str, str, Dict[str, Any]]]) -> None:
    by_id = {e.get("id"): e for e in doc.get("entries", [])}
    for rid, action, changes in steps:
        if action in ("NOOP", "MISSING"):
            continue
        by_id[rid].update(changes)


def check(doc: Dict[str, Any]) -> List[str]:
    """返回「登记 PASS 但没有可复算值」的条目 id（应为空）。"""
    bad = []
    for e in doc.get("entries", []):
        if e.get("status") == "PASS" and not e.get("declared"):
            bad.append(str(e.get("id")))
    return bad


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把零断言的 PASS 登记条目接上真数据 / 降级")
    ap.add_argument("--registry", default=str(ac.REPO_ROOT / "number_registry.json"),
                    help="登记表路径（默认仓库内镜像；权威源在 deliverables/ 下）")
    ap.add_argument("--apply", action="store_true", help="实际写盘（缺省只打印计划）")
    ap.add_argument("--check", action="store_true",
                    help="只做不变式检查：登记 PASS 的条目必须有非空 declared（违反则退出码 1）")
    args = ap.parse_args(argv)

    path = Path(args.registry)
    if not path.exists():
        print(f"[ERROR] 登记表不存在：{path}")
        return ac.EXIT_USAGE
    doc = load_registry(path)

    if args.check:
        bad = check(doc)
        if bad:
            print(f"[FAIL] {path.name}：{len(bad)} 条登记 PASS 但 declared 为空 —— {', '.join(bad)}")
            return ac.EXIT_FAIL
        print(f"[OK] {path.name}：所有 PASS 条目都有可复算的 declared")
        return ac.EXIT_OK

    steps = plan(doc)
    is_mirror = "_mirror_of" in doc
    for rid, action, changes in steps:
        keys = ", ".join(sorted(changes)) or "-"
        print(f"  {rid:8s} {action:10s} {keys}")
    for rid, action, _ in steps:
        if action == "MISSING":
            print(f"[WARN] 登记表里没有 {rid} —— 该条可能已改名/删除，请人工确认")

    if not args.apply:
        print("\n（dry-run；加 --apply 写盘）")
        return ac.EXIT_OK

    apply_plan(doc, steps)
    fp_changed = _refresh_mirror_fingerprint(doc)
    if any(a not in ("NOOP", "MISSING") for _, a, _ in steps) or fp_changed:
        save_registry(path, doc)
        print(f"\n[WROTE] {path}"
              + ("（已重算 _mirror_sha256）" if fp_changed else ""))
    else:
        print("\n[NOOP] 已是目标态，未写盘")

    remaining = check(doc)
    if remaining:
        print(f"[WARN] 仍有 {len(remaining)} 条 PASS 但 declared 为空：{', '.join(remaining)}")
        return ac.EXIT_FAIL
    print("[OK] 不再有「登记 PASS 但零断言」的条目")

    if is_mirror:
        print("\n下一步（权威源必须一起迁移，否则 check_registry_mirror 会报不一致）：")
        print("  python -X utf8 scripts/wire_unverified_entries_20261106.py --apply \\")
        print("      --registry ../deliverables/number_registry.json")
        print("  python -X utf8 scripts/check_registry_mirror.py --check")
    return ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
