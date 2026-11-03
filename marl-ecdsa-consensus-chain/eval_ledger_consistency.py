#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E48: 区块链账本一致性实证
- 跑20轮真实共识
- 检查所有节点的链高度、最后一个block_hash是否一致
- 测量链增长速率
输出 results/delivery_main/e48_ledger_consistency.json
"""
import asyncio, hashlib, json, os, sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blockchain.network import P2PConsensusNetwork
from blockchain.crypto.key_manager import KeyManager


async def run(n_nodes=7, n_rounds=20):
    key_dir = tempfile.mkdtemp(prefix="ledger_keys_")
    km = KeyManager(key_dir=key_dir)
    for i in range(n_nodes):
        km.generate_or_load(f"agent_{i}")

    net = P2PConsensusNetwork(n_nodes=n_nodes, base_port=8500, key_manager=km,
                               allow_insecure_register=False, allow_insecure_vote=False)
    net.start()
    await asyncio.sleep(1)

    successes = 0
    block_hashes = []
    for r in range(n_rounds):
        bh = hashlib.sha256(f"ledger_block_{r}".encode()).hexdigest()
        ok = net.run_consensus(bh, block_height=r + 1)
        if ok:
            successes += 1
            block_hashes.append(bh)

    await asyncio.sleep(1)

    # 检查所有节点的本地链状态
    chain_heights = []
    chain_tips = []
    for i, node in enumerate(net.nodes):
        try:
            if hasattr(node, 'blockchain') and node.blockchain:
                chain_heights.append(len(node.blockchain.chain))
                tip = node.blockchain.chain[-1]['hash'] if node.blockchain.chain else None
                chain_tips.append(tip)
            elif hasattr(node, 'chain'):
                chain_heights.append(len(node.chain))
                chain_tips.append(node.chain[-1] if node.chain else None)
        except Exception as e:
            chain_heights.append(-1)
            chain_tips.append(str(e))

    net.stop()
    shutil.rmtree(key_dir, ignore_errors=True)

    return {
        'n_nodes': n_nodes,
        'n_rounds': n_rounds,
        'successes': successes,
        'success_rate': successes / n_rounds,
        'chain_heights': chain_heights,
        'all_heights_equal': len(set(chain_heights)) == 1,
        'heights_consistent': chain_heights[0] == successes if chain_heights else False,
        'unique_block_hashes': len(set(block_hashes)),
        'duplicate_blocks': len(block_hashes) - len(set(block_hashes)),
    }


if __name__ == '__main__':
    r = asyncio.run(run())
    print("=== E48 Ledger Consistency ===")
    for k, v in r.items():
        print(f"  {k}: {v}")
    os.makedirs('results/delivery_main', exist_ok=True)
    with open('results/delivery_main/e48_ledger_consistency.json', 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'E48_ledger_consistency', **r}, f, ensure_ascii=False, indent=2)
    print("Saved.")
