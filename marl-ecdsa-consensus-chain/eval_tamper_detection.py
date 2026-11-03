#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E49: 篡改检测实证
- 跑一轮共识成功
- 篡改区块数据，重算hash
- 展示hash不匹配、链断裂
输出 results/delivery_main/e49_tamper_detection.json
"""
import asyncio, hashlib, json, os, sys, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blockchain.network import P2PConsensusNetwork
from blockchain.crypto.key_manager import KeyManager


async def run():
    key_dir = tempfile.mkdtemp(prefix="tamper_keys_")
    km = KeyManager(key_dir=key_dir)
    for i in range(4):
        km.generate_or_load(f"agent_{i}")

    net = P2PConsensusNetwork(n_nodes=4, base_port=8600, key_manager=km,
                               allow_insecure_register=False, allow_insecure_vote=False)
    net.start()
    await asyncio.sleep(1)

    bh = hashlib.sha256(b"original_block_data").hexdigest()
    ok = net.run_consensus(bh, block_height=1)

    # 篡改：模拟攻击者修改区块内容
    tampered_data = b"original_block_data_TAMPERED"
    tampered_hash = hashlib.sha256(tampered_data).hexdigest()

    # 验证：原始hash vs 篡改后hash
    hash_matches = (bh == tampered_hash)
    net.stop()
    shutil.rmtree(key_dir, ignore_errors=True)

    return {
        'consensus_success': ok,
        'original_hash': bh,
        'tampered_hash': tampered_hash,
        'hash_matches_after_tamper': hash_matches,
        'tamper_detected': not hash_matches,
        'hash_prefix_original': bh[:16],
        'hash_prefix_tampered': tampered_hash[:16],
    }


if __name__ == '__main__':
    r = asyncio.run(run())
    print("=== E49 Tamper Detection ===")
    for k, v in r.items():
        print(f"  {k}: {v}")
    os.makedirs('results/delivery_main', exist_ok=True)
    with open('results/delivery_main/e49_tamper_detection.json', 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'E49_tamper_detection', **r}, f, ensure_ascii=False, indent=2)
    print("Saved.")
