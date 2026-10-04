#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MARL-ECDSA Consensus Chain — 跨物理主机分布式 P2P 共识部署演示（D3）
========================================================================
与 network_demo.py（单机多进程回环）不同，本脚本支持把不同节点分布到
多台物理主机：每台主机各跑一个进程，只启动"属于自己"的节点，通过
真实跨主机 TCP（默认 TLS 加密）建立全连接拓扑并完成 CW-PBFT 三阶段共识。

用法（每台主机各执行一条，地址表必须全网一致）：

  主节点所在主机（假设 agent_0 / agent_1 在本机 172.27.4.71）：
    python scripts/network_demo_distributed.py \
      --node-ids agent_0,agent_1 \
      --addrs agent_0=172.27.4.71:17001,agent_1=172.27.4.71:17002,agent_2=172.16.222.99:17003,agent_3=172.16.222.99:17004 \
      --rounds 10

  其余主机（agent_2 / agent_3 在服务器 172.16.222.99）：
    python scripts/network_demo_distributed.py \
      --node-ids agent_2,agent_3 \
      --addrs agent_0=172.27.4.71:17001,agent_1=172.27.4.71:17002,agent_2=172.16.222.99:17003,agent_3=172.16.222.99:17004 \
      --rounds 10

要点：
  - --addrs 为全网节点地址表（node_id=host:port），各主机必须一字不差。
  - 只有主节点（默认 agent_0）所在进程发起共识；其余进程启动后等待接收。
  - TLS 传输加密默认开启（enable_tls=True，自签名 ECDSA P-256 证书）。
  - --secure 需全网共享同一 key_dir（密钥跨主机预分发），默认不启用。
"""
import argparse
import hashlib
import logging
import os
import sys
import time
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blockchain.network import P2PConsensusNetwork


class SimpleFormatter(logging.Formatter):
    def format(self, record):
        ts = time.strftime('%H:%M:%S', time.localtime(record.created))
        ms = int(record.created * 1000) % 1000
        prefix = f"{ts}.{ms:03d}  {record.levelname:<8}  {record.name:<22}"
        return f"{prefix}  {record.getMessage()}"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SimpleFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def parse_addrs(s: str):
    """解析 "agent_0=host:port,agent_1=host:port,..." -> {node_id: (host, port)}"""
    addrs = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        node_id, addr = part.split("=", 1)
        host, port = addr.rsplit(":", 1)
        addrs[node_id.strip()] = (host.strip(), int(port))
    return addrs


def _sort_key(nid: str) -> int:
    return int(nid.split("_")[1])


def main():
    if sys.platform == "win32":
        import io
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="跨物理主机分布式 P2P 共识部署演示（D3）"
    )
    parser.add_argument("--node-ids", required=True,
                        help="本进程启动的节点 ID，逗号分隔，如 agent_0 或 agent_1,agent_2")
    parser.add_argument("--addrs", required=True,
                        help="全网地址表 node_id=host:port,...（各主机一致）")
    parser.add_argument("--rounds", type=int, default=5, help="共识轮数（默认 5）")
    parser.add_argument("--primary-id", default="agent_0", help="主节点 ID（默认 agent_0）")
    parser.add_argument("--secure", action="store_true",
                        help="签名注册+签名投票（需全网共享 key_dir，默认不启用）")
    parser.add_argument("--key-dir", type=str, default=None,
                        help="--secure 模式密钥目录（跨主机须预分发同一目录）")
    parser.add_argument("--hold", type=int, default=20,
                        help="非主节点进程保持时长(秒)，等待主节点发起共识")
    parser.add_argument("--verbose", action="store_true", help="debug 日志")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    node_addrs = parse_addrs(args.addrs)
    all_ids = sorted(node_addrs.keys(), key=_sort_key)
    local_ids = [x.strip() for x in args.node_ids.split(",") if x.strip()]

    for nid in local_ids:
        if nid not in all_ids:
            print(f"[FATAL] 本进程节点 {nid} 不在全网地址表 {all_ids} 中")
            return 2

    print()
    print("=" * 74)
    print("  MARL-ECDSA 共识链 — 跨物理主机分布式 P2P 共识部署（D3）")
    print("=" * 74)
    print(f"  全网节点 : {len(all_ids)} 个  {all_ids}")
    print(f"  本机节点 : {local_ids}")
    print(f"  地址表   :")
    for nid in all_ids:
        host, port = node_addrs[nid]
        tag = "  <-- 本进程" if nid in local_ids else ""
        print(f"      {nid:<10} {host}:{port}{tag}")
    print(f"  主节点   : {args.primary_id}")
    print(f"  模式     : {'[SECURE] 签名注册+签名投票' if args.secure else '[INSECURE] 纯连通性（TLS 传输加密默认开启）'}")
    print()

    key_manager = None
    if args.secure:
        from blockchain.crypto.key_manager import KeyManager
        key_manager = KeyManager(key_dir=args.key_dir or tempfile.mkdtemp(prefix="dist_keys_"))
        for nid in all_ids:
            key_manager.generate_or_load(nid)

    net = P2PConsensusNetwork(
        n_nodes=len(all_ids),
        node_addrs=node_addrs,
        local_node_ids=local_ids,
        key_manager=key_manager,
        allow_insecure_register=not args.secure,
        allow_insecure_vote=not args.secure,
    )
    net.start()

    is_primary_host = args.primary_id in local_ids
    if is_primary_host:
        primary_idx = all_ids.index(args.primary_id)
        print(f"  -- 本进程含主节点 {args.primary_id}，发起 {args.rounds} 轮共识 --\n")
        print(f"  {'Round':>5}  {'Block hash':>14}  {'Primary':>10}  {'Result':>7}  {'Time':>8}")
        print(f"  {'-'*5}  {'-'*14}  {'-'*10}  {'-'*7}  {'-'*8}")
        success = 0
        for r in range(args.rounds):
            block_hash = hashlib.sha256(
                f"dist_block_{r}_ts_{int(time.time())}".encode()
            ).hexdigest()
            t0 = time.time()
            ok = net.run_consensus(block_hash, primary_idx=primary_idx)
            elapsed = int((time.time() - t0) * 1000)
            if ok:
                success += 1
            print(f"  {r + 1:>5}  {block_hash[:14]:>14}  {args.primary_id:>10}  "
                  f"{'[PASS]' if ok else '[FAIL]':>7}  {elapsed:>6}ms")
        stats = net.get_stats()
        print()
        print(f"  [SUMMARY] 跨主机共识 {success}/{args.rounds} 成功 "
              f"({success / args.rounds * 100:.1f}%) | "
              f"全网消息 发{stats['total_msg_sent']}/收{stats['total_msg_received']}")
        net.stop()
        print("\n  主节点进程退出。\n")
        return 0 if success == args.rounds else 1
    else:
        print(f"  -- 本进程不含主节点，等待 {args.primary_id} 发起共识（最多 {args.hold}s）--\n")
        time.sleep(args.hold)
        stats = net.get_stats()
        print("  本进程节点统计（跨主机消息接收证据）：")
        for nid in local_ids:
            ns = stats["nodes"].get(nid)
            if ns:
                print(f"      {nid:<10} sent={ns['msg_sent']:>4}  recv={ns['msg_received']:>4}")
        total_recv = sum(stats["nodes"][nid]["msg_received"] for nid in local_ids if nid in stats["nodes"])
        print(f"  本进程合计收到 {total_recv} 条跨主机共识消息")
        net.stop()
        print("\n  非主节点进程退出。\n")
        return 0 if total_recv > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
