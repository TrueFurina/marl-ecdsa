#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E44: 真实 P2P TCP 共识性能压测
- n_nodes ∈ {4,7,10,13,16}
- secure=False (无签名) vs secure=True (ECDSA 签名投票)
- 每配置 20 轮共识，测：单轮延迟、成功率、消息数、throughput
- 输出 results/delivery_main/e44_p2p_benchmark.json
"""
import argparse, hashlib, json, os, shutil, sys, time, tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))

from blockchain.network import P2PConsensusNetwork


def run_config(n_nodes, n_rounds, secure, base_port):
    key_dir = None
    if secure:
        from blockchain.crypto.key_manager import KeyManager
        key_dir = tempfile.mkdtemp(prefix="bench_keys_")
        km = KeyManager(key_dir=key_dir)
        for i in range(n_nodes):
            km.generate_or_load(f"agent_{i}")
    else:
        km = None

    net = P2PConsensusNetwork(
        n_nodes=n_nodes, base_port=base_port,
        key_manager=km,
        allow_insecure_register=not secure,
        allow_insecure_vote=not secure,
    )
    try:
        t_start = time.time()
        net.start()
        boot_ms = (time.time() - t_start) * 1000

        latencies = []
        success = 0
        for r in range(n_rounds):
            bh = hashlib.sha256(f"bench_{n_nodes}_{secure}_{r}_{time.time_ns()}".encode()).hexdigest()
            primary_idx = r % n_nodes
            t0 = time.perf_counter()
            ok = net.run_consensus(bh, primary_idx=primary_idx)
            dt = (time.perf_counter() - t0) * 1000
            latencies.append(dt)
            if ok:
                success += 1

        stats = net.get_stats()
    finally:
        net.stop()
        if key_dir:
            shutil.rmtree(key_dir, ignore_errors=True)

    lat_sorted = sorted(latencies)
    p50 = lat_sorted[len(lat_sorted)//2]
    p95 = lat_sorted[int(len(lat_sorted)*0.95)] if len(lat_sorted) > 1 else lat_sorted[0]
    return {
        'n_nodes': n_nodes,
        'secure': secure,
        'n_rounds': n_rounds,
        'boot_ms': round(boot_ms, 1),
        'success': success,
        'success_rate': success / n_rounds,
        'latency_mean_ms': round(sum(latencies)/len(latencies), 2),
        'latency_p50_ms': round(p50, 2),
        'latency_p95_ms': round(p95, 2),
        'latency_min_ms': round(min(latencies), 2),
        'latency_max_ms': round(max(latencies), 2),
        'msg_sent': stats.get('total_msg_sent', 0),
        'msg_recv': stats.get('total_msg_received', 0),
        'rounds_per_sec': round(n_rounds / (sum(latencies)/1000), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rounds', type=int, default=20)
    ap.add_argument('--out', type=str, default='results/delivery_main/e44_p2p_benchmark.json')
    args = ap.parse_args()

    results = []
    for n in [4, 7, 10, 13, 16]:
        for secure in [False, True]:
            port = 8100 + n * 10 + (1 if secure else 0)
            print(f"\n=== n={n} secure={secure} port={port} ===", flush=True)
            r = run_config(n, args.rounds, secure, port)
            results.append(r)
            print(f"  success={r['success_rate']*100:.0f}%  "
                  f"lat_mean={r['latency_mean_ms']}ms  "
                  f"p95={r['latency_p95_ms']}ms  "
                  f"throughput={r['rounds_per_sec']} r/s  "
                  f"msgs={r['msg_sent']}", flush=True)
            time.sleep(1)

    # ECDSA overhead comparison
    print("\n=== ECDSA 开销对比 ===")
    print(f"{'n':>4} {'无签名均值ms':>12} {'签名均值ms':>12} {'开销ms':>10} {'开销%':>8}")
    for n in [4, 7, 10, 13, 16]:
        ins = next(r for r in results if r['n_nodes']==n and not r['secure'])
        sec = next(r for r in results if r['n_nodes']==n and r['secure'])
        overhead = sec['latency_mean_ms'] - ins['latency_mean_ms']
        pct = overhead / ins['latency_mean_ms'] * 100 if ins['latency_mean_ms'] > 0 else 0
        print(f"{n:>4} {ins['latency_mean_ms']:>12.2f} {sec['latency_mean_ms']:>12.2f} "
              f"{overhead:>10.2f} {pct:>7.1f}%")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'E44_p2p_tcp_benchmark', 'results': results}, f, ensure_ascii=False, indent=2)
    print(f"\n已保存: {args.out}")


if __name__ == '__main__':
    main()
