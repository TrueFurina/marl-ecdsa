#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E51: 权重演化追踪
- 10轮共识，每轮记录每个节点的贡献权重
- 展示激励机制如何动态调整权重
输出 results/delivery_main/e51_weight_evolution.json
"""
import asyncio, hashlib, json, os, sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blockchain.network import P2PConsensusNetwork
from blockchain.crypto.key_manager import KeyManager


async def run(n_nodes=7, n_rounds=10):
    key_dir = tempfile.mkdtemp(prefix="weight_keys_")
    km = KeyManager(key_dir=key_dir)
    for i in range(n_nodes):
        km.generate_or_load(f"agent_{i}")

    net = P2PConsensusNetwork(n_nodes=n_nodes, base_port=8700, key_manager=km,
                               allow_insecure_register=False, allow_insecure_vote=False)
    net.start()
    await asyncio.sleep(1)

    weight_history = []
    for r in range(n_rounds):
        bh = hashlib.sha256(f"weight_block_{r}".encode()).hexdigest()
        ok = net.run_consensus(bh, block_height=r + 1)
        # 记录当前权重
        weights = {}
        for i, node in enumerate(net.nodes):
            try:
                if hasattr(node, 'consensus') and node.consensus:
                    w = node.consensus.get_weights()
                    weights[f'agent_{i}'] = {k: round(v, 3) for k, v in w.items()}
            except Exception:
                pass
        weight_history.append({'round': r, 'success': ok, 'weights': weights})

    net.stop()
    shutil.rmtree(key_dir, ignore_errors=True)
    return {'n_nodes': n_nodes, 'n_rounds': n_rounds, 'history': weight_history}


if __name__ == '__main__':
    r = asyncio.run(run())
    print(f"=== E51 Weight Evolution ({r['n_nodes']} nodes, {r['n_rounds']} rounds) ===")
    for h in r['history']:
        print(f"  Round {h['round']}: success={h['success']}")
    os.makedirs('results/delivery_main', exist_ok=True)
    with open('results/delivery_main/e51_weight_evolution.json', 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'E51_weight_evolution', **r}, f, ensure_ascii=False, indent=2)
    print("Saved.")
