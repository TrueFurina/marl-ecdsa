#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
register_e41_longrun.py — E41 长跑一致性程序化登记（2026-10-16）
===============================================================
纪律：数字全部程序化取自 results/e41_ledger_consistency/e41_ledger_consistency.json
的 summary，不手抄；declared 只放标量（divergences 是 list，禁入 declared，
一致性结论用 n_divergence_checks == 0 表达 —— 见 tests/test_verify_numbers_e41.py）。

登记 NR-174（analysis: e41_longrun，由 scripts/verify_numbers.py 的新分支复算）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

REG = _REPO_ROOT.parent / "deliverables" / "number_registry.json"
DATA = _REPO_ROOT / "results" / "e41_ledger_consistency" / "e41_ledger_consistency.json"
NR = "NR-179"
GLOB_REL = "e41_ledger_consistency/e41_ledger_consistency.json"


def main() -> int:
    if not DATA.exists():
        raise SystemExit(f"[FATAL] E41 报告不存在：{DATA}")
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    s = doc["summary"]
    lat = s["latency_ms"]
    meta = doc["meta"]

    allowed = (
        f"端到端长跑一致性：{meta['n_nodes']} 节点真实 TCP P2P（secure 模式，"
        f"ECDSA 签名 REGISTER/VOTE）连续 {s['n_rounds']} 轮共识，"
        f"成功 {s['success_count']}/{s['n_rounds']}（{s['success_rate'] * 100:.2f}%），"
        f"周期一致性校验 {s['n_checks']} 次、不一致 {s['n_divergence_checks']} 次；"
        f"平均 {lat['mean']:.1f}ms/轮（max {lat['max']:.1f}ms），"
        f"全网消息 {s['total_msg_sent']} 条。"
        "一致性判据：轮次连续无跳号 + 协调器/本地双视角交叉验证 + block_hash 唯一"
        "（无重复提议）+ 权重视图全等 + 主持次数符合轮换。"
        "口径限定：单机多进程回环 TCP（与 NR-94 同限定）、不注入任何故障、"
        "延迟含调度开销不作性能结论。"
    )

    entry = {
        "id": NR,
        "claim": (f"E41 端到端长跑一致性：{meta['n_nodes']} 节点真实 TCP P2P "
                  f"连续 {s['n_rounds']} 轮共识无漂移/分叉/失同步"),
        "allowed_wording": allowed,
        "analysis": "e41_longrun",
        "sources": [{"file": GLOB_REL}],
        "n_expected": 1,
        "statistic": ["success_count", "n_rounds", "success_rate", "n_checks",
                      "n_divergence_checks", "latency_ms_mean", "latency_ms_max",
                      "total_msg_sent"],
        "declared": {
            "success_count": s["success_count"],
            "n_rounds": s["n_rounds"],
            "success_rate": s["success_rate"],
            "n_checks": s["n_checks"],
            "n_divergence_checks": s["n_divergence_checks"],
            "latency_ms_mean": lat["mean"],
            "latency_ms_max": lat["max"],
            "total_msg_sent": s["total_msg_sent"],
        },
        "tolerance": {"abs": 0.001, "p_abs": 0.001},
        "status": "PENDING",
        "pre_registered": False,
        "requires": [],
        "notes": (
            "E41（2026-10-16，服务器 <HOST-B> 实测）。"
            "divergences 是 list，按契约**不进 declared**（verify 对 "
            "「declared 是 list 而 computed 无对应 key」直接判 FAIL），"
            "一致性结论由 n_divergence_checks == 0 表达。"
            "实验执行与登记同日，按铁律显式标 pre_registered=false。"
        ),
        "evidence_kind": "experiment",
    }

    reg = json.loads(REG.read_text(encoding="utf-8"))
    have = {e["id"] for e in reg["entries"]}

    # 🔴 并发写防护（2026-10-16 踩坑）：本项目有多个并行会话同时往 registry
    # 追加条目，硬编码编号会**静默覆盖他人的条目**（本次就把他人 NR-174
    # 覆盖掉、又与他人 NR-176 撞号导致重复 ID）。故：编号已被占用时直接
    # FAIL，由人确认后改号，绝不覆盖。
    if NR in have:
        occupant = next(e for e in reg["entries"] if e["id"] == NR)
        raise SystemExit(
            f"[FATAL] {NR} 已被占用（analysis={occupant.get('analysis')}, "
            f"claim={occupant.get('claim', '')[:60]}）。\n"
            f"        并行会话可能已追加新条目——请改用一个未占用编号后重跑，"
            f"**不要覆盖他人条目**。")

    reg["entries"].append(entry)
    action = "新增"

    bak = _REPO_ROOT.parent / "backup"
    bak.mkdir(parents=True, exist_ok=True)
    bak_fp = bak / "number_registry_pre_e41_20261016.json"
    bak_fp.write_text(REG.read_text(encoding="utf-8"), encoding="utf-8")
    assert bak_fp.stat().st_size > 0, "备份写入失败"

    REG.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[登记] {action} {NR}（registry {len(reg['entries'])} 条）")
    print(f"[备份] {bak_fp}")
    print(f"[declared] {json.dumps(entry['declared'], ensure_ascii=False)}")
    print("\n⚠ 下一步：check_registry_mirror.py --sync  →  verify_numbers.py --strict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
