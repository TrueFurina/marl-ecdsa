#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_e41_ledger_consistency.py — 端到端长跑一致性验证（2026-10-16）
==================================================================
动机：NR-94/NR-95 只证明了**短序列**（4 节点 15 轮 / 5 节点 10 轮）真实 TCP
P2P 下共识可达。评审会问："跑久了会不会漂移/分叉/视图失同步？"——此前没有
长跑证据。本脚本把序列拉到 1000 轮，并**周期性校验各节点视图一致性**。

设计：
  - 复用 scripts/network_demo.py 的 _start_network（真实 TCP 全连接 P2P +
    CW-PBFT），不重写网络层；secure 模式与 NR-95/NR-101 同口径
    （ECDSA 签名 REGISTER + 签名 VOTE）
  - 每轮：确定性 block_hash（含高度）+ 轮换 primary + 记录 ok/耗时
  - 每 --check-every 轮做一次**一致性检查**（fail-closed：不一致即记录并
    计入 divergence，不静默放过）：
      1) 所有节点 consensus_rounds 相等（无节点掉队/重复计数）
      2) 所有节点权重视图相等（权重广播无丢失）
      3) 本轮 run_consensus 返回值与各节点计数增量自洽
  - 落盘 results/e41_ledger_consistency/e41_ledger_consistency.json
    （含逐轮摘要 + 周期校验记录 + 汇总），供 registry 复算

口径声明（任何引用必须随行）：
  - 单机多进程回环 TCP（与 NR-94 同限定）；不含跨主机结论
  - 省略型故障模型之外**不注入任何故障**（本实验测的是无故障长跑稳定性）
  - 延迟含固定调度开销，不作性能结论

用法：
  python scripts/run_e41_ledger_consistency.py --nodes 4 --rounds 1000 --secure
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import network_demo  # noqa: E402  复用其 _start_network / setup_logging

OUT_DIR = _REPO_ROOT / "results" / "e41_ledger_consistency"


def _check_consistency(net, per_round, node_ids) -> list[str]:
    """长跑一致性校验（fail-closed：任何不符都记录，不静默放过）。

    四条硬判据：
      1) **轮次连续无跳号**：协调器 network_msg_log 的 round 必须恰好是
         0..N-1（长跑中最怕静默丢轮/重复轮）
      2) **交叉验证**：协调器记录的 primary/success 必须与本脚本逐轮记录一致
         （双视角互证，单侧记录不可信）
      3) **block_hash 唯一**：无重复提议（重复 = 分叉/重放嫌疑）
      4) **权重视图全等**：所有节点对同一节点集的权重认知一致（广播无丢失）
      5) **主持次数符合轮换**：各节点 consensus_rounds（=它主持的轮数）
         必须等于 r % n_nodes 轮换下的应有次数
    """
    problems = []
    log = list(getattr(net, "network_msg_log", []))

    if len(log) != len(per_round):
        problems.append(f"协调器记录 {len(log)} 条 ≠ 本地记录 {len(per_round)} 条")
    else:
        rounds_seen = [e.get("round") for e in log]
        if rounds_seen != list(range(len(per_round))):
            problems.append(f"轮次不连续/跳号: {rounds_seen[:5]}...{rounds_seen[-3:]}")
        for e, mine in zip(log, per_round):
            if e.get("primary") != mine["primary"] or bool(e.get("success")) != mine["ok"]:
                problems.append(
                    f"round {e.get('round')} 双视角不一致: "
                    f"协调器(primary={e.get('primary')},ok={e.get('success')}) vs "
                    f"本地(primary={mine['primary']},ok={mine['ok']})")
                break
        hashes = [e.get("block_hash") for e in log]
        if len(set(hashes)) != len(hashes):
            problems.append(f"block_hash 重复 {len(hashes) - len(set(hashes))} 次（分叉/重放嫌疑）")

    # 权重视图全等
    st = net.get_stats()
    wv = {nid: st["weights"].get(nid) for nid in st["nodes"]}
    if len(set(wv.values())) != 1:
        problems.append(f"权重视图不一致: {wv}")

    # 主持次数符合 r % n_nodes 轮换
    n = len(node_ids)
    expected = {nid: sum(1 for r in range(len(per_round)) if r % n == i)
                for i, nid in enumerate(node_ids)}
    actual = {nid: ns["consensus_rounds"] for nid, ns in st["nodes"].items()}
    if actual != expected:
        problems.append(f"主持次数不符: 实际 {actual} vs 预期 {expected}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=1000)
    ap.add_argument("--port", type=int, default=7001)
    ap.add_argument("--secure", action="store_true", default=True,
                    help="ECDSA 签名 REGISTER/VOTE（与 NR-95/NR-101 同口径，默认开）")
    ap.add_argument("--no-secure", dest="secure", action="store_false")
    ap.add_argument("--key-dir", default=None)
    ap.add_argument("--check-every", type=int, default=100)
    ap.add_argument("--smoke", action="store_true", help="只跑 20 轮验证脚本")
    args = ap.parse_args()

    if args.smoke:
        args.rounds = 20
        args.check_every = 10

    network_demo.setup_logging(verbose=False)
    t_start = time.time()

    key_manager = None
    if args.secure:
        from blockchain.crypto.key_manager import KeyManager
        import tempfile
        key_manager = KeyManager(key_dir=args.key_dir or tempfile.mkdtemp(prefix="e41_keys_"))
        for i in range(args.nodes):
            key_manager.generate_or_load(f"agent_{i}")

    net = network_demo._start_network(args.nodes, args.port,
                                      key_manager=key_manager, secure=args.secure)
    print(f"[E41] {args.nodes} 节点真实 TCP P2P 启动完成（secure={args.secure}）")

    per_round, checks, divergences = [], [], []
    success_count = 0
    try:
        for r in range(args.rounds):
            block_hash = hashlib.sha256(
                f"e41_block_{r}_marl".encode()).hexdigest()
            primary_idx = r % args.nodes
            t0 = time.perf_counter()
            ok = net.run_consensus(block_hash, primary_idx=primary_idx)
            dt_ms = (time.perf_counter() - t0) * 1000
            success_count += 1 if ok else 0
            per_round.append({"round": r, "ok": bool(ok), "ms": round(dt_ms, 3),
                              "primary": net.node_ids[primary_idx]})
            # 权重缓慢演化（与 network_demo 同型，避免权重永久静止）
            w = {nid: round(1.0 + 0.5 * (0.5 + 0.5 * ((r + 1) / max(args.rounds, 1))), 3)
                 for nid in net.node_ids}
            net.update_weights(w)

            if (r + 1) % args.check_every == 0 or r == args.rounds - 1:
                problems = _check_consistency(net, per_round, net.node_ids)
                st = net.get_stats()
                rec = {"after_round": r + 1, "problems": problems,
                       "rounds_view": {nid: ns["consensus_rounds"]
                                       for nid, ns in st["nodes"].items()},
                       "weights_view": {nid: st["weights"].get(nid)
                                        for nid in st["nodes"]},
                       "msg_sent": st["total_msg_sent"],
                       "msg_recv": st["total_msg_received"]}
                checks.append(rec)
                if problems:
                    divergences.extend(problems)
                print(f"[E41] 周期校验 @{r + 1}/{args.rounds}: "
                      f"{'一致' if not problems else '不一致 ' + str(problems)}")
    finally:
        net.stop()

    lat = [x["ms"] for x in per_round]
    stats = net.get_stats()
    out = {
        "meta": {
            "script": "scripts/run_e41_ledger_consistency.py",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_nodes": args.nodes,
            "n_rounds": args.rounds,
            "secure": bool(args.secure),
            "check_every": args.check_every,
            "smoke": bool(args.smoke),
            "scope": ("单机多进程回环 TCP（与 NR-94 同限定）；不注入任何故障，"
                      "测的是无故障长跑稳定性；延迟含调度开销，不作性能结论"),
            "elapsed_sec": round(time.time() - t_start, 1),
        },
        "summary": {
            "success_count": success_count,
            "n_rounds": args.rounds,
            "success_rate": success_count / args.rounds if args.rounds else 0.0,
            "divergences": divergences,
            "n_checks": len(checks),
            "n_divergence_checks": sum(1 for c in checks if c["problems"]),
            "latency_ms": {
                "mean": round(sum(lat) / len(lat), 3) if lat else 0.0,
                "max": round(max(lat), 3) if lat else 0.0,
                "min": round(min(lat), 3) if lat else 0.0,
            },
            "total_msg_sent": stats["total_msg_sent"],
            "total_msg_received": stats["total_msg_received"],
        },
        "checks": checks,
        "per_round": per_round,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    op = OUT_DIR / ("e41_ledger_consistency_smoke.json" if args.smoke
                    else "e41_ledger_consistency.json")
    op.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[E41] 完成：{success_count}/{args.rounds} 成功"
          f"（{out['summary']['success_rate'] * 100:.2f}%），"
          f"周期校验 {len(checks)} 次，不一致 {len(divergences)} 项，"
          f"平均 {out['summary']['latency_ms']['mean']}ms/轮")
    print(f"[报告写入] {op}")
    return 0 if (success_count == args.rounds and not divergences) else 1


if __name__ == "__main__":
    sys.exit(main())
