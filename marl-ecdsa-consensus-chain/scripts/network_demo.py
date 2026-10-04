#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MARL-ECDSA Consensus Chain - P2P Network Programming Demo
==========================================================
Demonstrates real TCP network communication + CW-PBFT three-phase consensus

Usage:
    python network_demo.py              # standard demo (3 nodes, 5 rounds)
    python network_demo.py --rounds 10  # custom rounds
    python network_demo.py --nodes 4    # 4-node network
    python network_demo.py --verbose    # verbose debug logs

Network Programming Highlights:
  1. asyncio TCP Server/Client  -- async non-blocking Socket I/O
  2. Custom application protocol -- 4-byte length-prefix + JSON frames
  3. Flood broadcast + SHA256 dedup -- prevents infinite forwarding loops
  4. Heartbeat keepalive + offline detection -- 5s heartbeat, 30s timeout
  5. Full-mesh P2P topology -- every node pair maintains a TCP connection
  6. CW-PBFT 3-phase consensus -- messages travel over real TCP network
"""

import argparse
import hashlib
import logging
import sys
import time
import os
import tempfile

# add project root (parent of scripts/) to path so the script runs both as
#   python scripts/network_demo.py   and   python -m scripts.network_demo
# without requiring PYTHONPATH (fixes ModuleNotFoundError: No module named 'blockchain')
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blockchain.network import P2PConsensusNetwork


# =============================================================================
# Logging setup (Windows-safe: no %f in datefmt)
# =============================================================================

class SimpleFormatter(logging.Formatter):
    def format(self, record):
        ts = time.strftime('%H:%M:%S', time.localtime(record.created))
        ms = int(record.created * 1000) % 1000
        prefix = f"{ts}.{ms:03d}  {record.levelname:<8}  {record.name:<22}"
        return f"{prefix}  {record.getMessage()}"


def setup_logging(verbose: bool = False):
    # P3-5修复: Windows 控制台 UTF-8 编码替换已移至 main() 开头（仅脚本直接运行时）。
    # 原实现（模块顶层/此处）会替换 sys.stdout/stderr，破坏所有导入方
    # （如 pytest 捕获机制、train.py 等），导致"closed file"崩溃。
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SimpleFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


# =============================================================================
# Demo main flow
# =============================================================================

def print_banner():
    print()
    print("=" * 72)
    print("  MARL-ECDSA Consensus Chain -- P2P Network Programming Demo")
    print("  asyncio TCP + CW-PBFT Three-Phase Consensus over Real Network")
    print("=" * 72)
    print()


def print_section(title: str):
    print()
    print(f"  -- {title} " + "-" * max(0, 60 - len(title)))


def _start_network(n_nodes, base_port, key_manager=None, secure: bool = False):
    """Step 1: 启动 P2P 网络"""
    print_section(f"Step 1/4  Start {n_nodes}-node P2P TCP network")
    print(f"  Base port : {base_port}")
    print(f"  Node ports: {list(range(base_port, base_port + n_nodes))}")
    print(f"  Topology  : Full-mesh (every pair builds a TLS TCP connection)\n")
    if secure:
        print(f"  [SECURE]  签名注册 + 签名投票链路已启用（KeyManager 注入，fail-closed）\n")
    else:
        print(f"  [INSECURE] 纯连通性/教学演示模式（无 key_manager，宽松兜底）\n")
    t_start = time.time()
    # 该演示为"无 key_manager 的纯连通性/教学演示"，显式开启 insecure 模式以
    # 兼容旧 fail-open 行为；生产部署必须注入 key_manager 并关闭该开关。
    # TLS 传输加密默认开启（BUG4修复），无需额外参数。
    # --secure 模式（P2-3 补强）：注入 KeyManager、关闭宽松开关，
    # 让 REGISTER 签名注册与 VOTE 签名投票真正走 ECDSA 验签链路。
    net = P2PConsensusNetwork(
        n_nodes=n_nodes, base_port=base_port,
        key_manager=key_manager,
        allow_insecure_register=not secure,
        allow_insecure_vote=not secure,
    )
    net.start()
    print(f"  [OK] Network ready in {int((time.time() - t_start) * 1000)} ms\n")
    print(f"  {'Node ID':<12} {'Port':<8} {'Role'}")
    print(f"  {'-'*12} {'-'*8} {'-'*20}")
    for i, (nid, node) in enumerate(net.nodes.items()):
        print(f"  {nid:<12} {node.port:<8} {'Primary (initial)' if i == 0 else 'Replica'}")
    return net


def _show_protocol():
    """Step 2: 展示消息协议"""
    print_section("Step 2/4  Custom application-layer protocol (4-byte length prefix + JSON)")
    from blockchain.network.message_protocol import MessageProtocol, MessageType
    demo_msg = MessageProtocol.build(
        MessageType.CONSENSUS_PREPREPARE, from_node="agent_0",
        data={"block_hash": "a1b2c3d4e5f6", "voter_id": "agent_0", "weight": 1.27}, nonce=42)
    encoded = MessageProtocol.encode(demo_msg)
    # 显式打印枚举限定名：f"{str枚举}" 的输出随 Python 版本变化
    # （<3.11 只给值，>=3.11 给 ClassName.member），这里固定为跨版本一致。
    _mt = MessageType(demo_msg['header']['msg_type'])
    print(f"  msg_type : MessageType.{_mt.name}")
    print(f"  msg_id   : {demo_msg['header']['msg_id']}  (SHA256[:16] for dedup)")
    print(f"  from     : {demo_msg['header']['from_node']}")
    print(f"  encoded  : {len(encoded)} bytes  (first 4 bytes={encoded[:4].hex()} => length {int.from_bytes(encoded[:4],'big')})")


def _run_consensus_rounds(net, n_nodes, n_rounds, weights_dict):
    """Step 3: 运行 N 轮共识"""
    print_section(f"Step 3/4  {n_rounds} rounds of real P2P CW-PBFT consensus")
    print(f"\n  {'Round':>5}  {'Block hash':>14}  {'Primary':>10}  {'Result':>7}  {'Time':>8}  {'Msgs'}")
    print(f"  {'-'*5}  {'-'*14}  {'-'*10}  {'-'*7}  {'-'*8}  {'-'*6}")
    success_count = 0
    for r in range(n_rounds):
        block_hash = hashlib.sha256(f"block_{r}_ts_{int(time.time())}_marl_state_{r*42}".encode()).hexdigest()
        primary_idx = r % n_nodes
        t0 = time.time()
        ok = net.run_consensus(block_hash, primary_idx=primary_idx)
        elapsed = int((time.time() - t0) * 1000)
        if ok:
            success_count += 1
        stats = net.get_stats()
        print(f"  {r+1:>5}  {block_hash[:14]:>14}  {net.node_ids[primary_idx]:>10}  {'[PASS]' if ok else '[FAIL]':>7}  {elapsed:>6}ms  {stats['total_msg_sent']:>6}")
        for i, nid in enumerate(net.node_ids):
            weights_dict[nid] = round(1.0 + 0.5 * (0.5 + 0.5 * ((r + 1 + i) / n_rounds)), 3)
        net.update_weights(weights_dict)
        time.sleep(0.05)
    return success_count


def _print_stats(net, n_nodes, n_rounds, success_count):
    """Step 4: 打印网络统计"""
    print_section("Step 4/4  Network run statistics")
    stats = net.get_stats()
    print(f"\n  +---------------------------------------------------------------+")
    print(f"  |  P2P Network Run Summary                                      |")
    print(f"  +---------------------------------------------------------------+")
    print(f"  |  Nodes           : {n_nodes} nodes, full-mesh TCP topology")
    print(f"  |  Consensus rounds: {n_rounds}  success={success_count}/{n_rounds}")
    print(f"  |  Success rate    : {success_count/n_rounds*100:.1f}%")
    print(f"  |  Total msgs sent : {stats['total_msg_sent']}")
    print(f"  |  Total msgs recv : {stats['total_msg_received']}")
    print(f"  +---------------------------------------------------------------+")
    print(f"  |  CW-PBFT Contribution Weights (per node)                      |")
    print(f"  +---------------------------------------------------------------+")
    for nid, w in stats["weights"].items():
        ns = stats["nodes"][nid]
        print(f"  |  {nid:<12}  weight={w:.3f}  sent={ns['msg_sent']:>4}  recv={ns['msg_received']:>4}  rounds={ns['consensus_rounds']:>3}")
    print(f"  +---------------------------------------------------------------+")
    net.stop()
    print(f"\n  All nodes stopped. Demo complete.\n")


def demo(n_nodes: int, n_rounds: int, base_port: int = 7001, secure: bool = False,
         key_dir: str = None):
    """Main demo flow"""
    print_banner()
    key_manager = None
    if secure:
        from blockchain.crypto.key_manager import KeyManager
        # 每个节点（agent_i）预生成 ECDSA 密钥对，供 REGISTER/VOTE 签名与验签使用。
        # 默认落临时目录（演示结束即弃），可通过 --key-dir 指定持久化位置。
        key_manager = KeyManager(key_dir=key_dir or tempfile.mkdtemp(prefix="demo_keys_"))
        for i in range(n_nodes):
            key_manager.generate_or_load(f"agent_{i}")
    net = _start_network(n_nodes, base_port, key_manager=key_manager, secure=secure)
    _show_protocol()
    weights_dict = {nid: 1.0 for nid in net.node_ids}
    success_count = _run_consensus_rounds(net, n_nodes, n_rounds, weights_dict)
    _print_stats(net, n_nodes, n_rounds, success_count)
    return {"n_nodes": n_nodes, "n_rounds": n_rounds, "success_count": success_count,
            "total_msg_sent": net.get_stats()["total_msg_sent"],
            "total_msg_received": net.get_stats()["total_msg_received"],
            "weights": net.get_stats()["weights"]}


# =============================================================================
# CLI entry point
# =============================================================================

def main():
    # P3-5修复: Windows 控制台 UTF-8 编码替换仅在脚本直接运行时执行
    # （不污染导入方如 pytest 捕获机制 / train.py）
    if sys.platform == "win32":
        import io
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass  # 无 buffer 或已包装时跳过
    parser = argparse.ArgumentParser(
        description="MARL-ECDSA Consensus Chain P2P Network Demo"
    )
    parser.add_argument("--nodes",   type=int, default=3,    help="number of nodes (default 3)")
    parser.add_argument("--rounds",  type=int, default=5,    help="consensus rounds (default 5)")
    parser.add_argument("--port",    type=int, default=7001,  help="base port (default 7001)")
    parser.add_argument("--verbose", action="store_true",     help="show debug logs")
    parser.add_argument("--secure",  action="store_true",     help="inject KeyManager: signed REGISTER + signed VOTE (ECDSA)")
    parser.add_argument("--key-dir", type=str, default=None,  help="key directory for --secure mode (default: temp dir)")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    result = demo(
        n_nodes=args.nodes,
        n_rounds=args.rounds,
        base_port=args.port,
        secure=args.secure,
        key_dir=args.key_dir,
    )

    sys.exit(0 if result["success_count"] == result["n_rounds"] else 1)


if __name__ == "__main__":
    main()
