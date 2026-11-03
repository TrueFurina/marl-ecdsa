#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E45: ECDSA sign/verify microbenchmark"""
import time, json, os, sys
sys.path.insert(0, '.')
from blockchain.crypto.ecdsa_utils import ECDSAUtils

def bench(n=2000):
    t0 = time.perf_counter()
    for _ in range(n):
        priv, pub = ECDSAUtils.generate_key_pair()
    keygen_ms = (time.perf_counter() - t0) / n * 1000

    priv, pub = ECDSAUtils.generate_key_pair()
    msg = b"delivery_proof_order_12345"

    t0 = time.perf_counter()
    sigs = [ECDSAUtils.sign(priv, msg) for _ in range(n)]
    sign_us = (time.perf_counter() - t0) / n * 1e6

    t0 = time.perf_counter()
    for s in sigs:
        ECDSAUtils.verify(pub, msg, s)
    verify_us = (time.perf_counter() - t0) / n * 1e6

    t0 = time.perf_counter()
    for _ in range(n):
        s = ECDSAUtils.sign(priv, msg)
        ECDSAUtils.verify(pub, msg, s)
    combined_us = (time.perf_counter() - t0) / n * 1e6

    return {
        'n_iterations': n,
        'keygen_ms_per_key': round(keygen_ms, 3),
        'sign_us': round(sign_us, 1),
        'verify_us': round(verify_us, 1),
        'sign_plus_verify_us': round(combined_us, 1),
        'sign_per_second': round(1e6/sign_us, 0),
        'verify_per_second': round(1e6/verify_us, 0),
    }

if __name__ == '__main__':
    r = bench(2000)
    print("=== ECDSA Microbenchmark ===")
    for k, v in r.items():
        print(f"  {k}: {v}")
    os.makedirs('results/delivery_main', exist_ok=True)
    with open('results/delivery_main/e45_ecdsa_microbench.json', 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'E45_ecdsa_microbenchmark', **r}, f, ensure_ascii=False, indent=2)
    print("Saved.")
