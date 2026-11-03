"""
E43: CW-PBFT Byzantine 容错阈值扫描（真实共识代码）

两组对比：
  A. 等权基线：所有节点 w=1.0，验证是否匹配 PBFT 理论阈值 f <= (n-1)/3
  B. 加权风险：恶意节点通过贡献积累拿到 w=1.5（最大权重），测阈值是否提前崩塌

指标：
  - liveness：正确块上共识成功率
  - latency_ms：单轮共识耗时
  - 实际调用 CWPBFTConsensus.simulated_consensus(block_hash, proposer, byzantine_nodes)
"""
import os, sys, json, time
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blockchain.consensus.cw_pbft import CWPBFTConsensus


def run_one(n, f, byz_weight=1.0, honest_weight=1.0, n_rounds=10):
    """跑 n_rounds 轮共识，返回指标。"""
    nodes = [f"node_{i}" for i in range(n)]
    byz_nodes = set(nodes[:f])

    successes = 0
    latencies = []
    for r in range(n_rounds):
        c = CWPBFTConsensus("node_0", nodes)
        for i, nid in enumerate(nodes):
            w = byz_weight if nid in byz_nodes else honest_weight
            c.update_weight(nid, w)

        block_hash = f"block_r{r}_n{n}_f{f}"
        t0 = time.perf_counter()
        ok = c.simulated_consensus(block_hash, "node_0", byzantine_nodes=byz_nodes)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        if ok:
            successes += 1

    threshold = (2/3) * sum(
        byz_weight if nid in byz_nodes else honest_weight for nid in nodes
    )
    honest_w = sum(honest_weight for nid in nodes if nid not in byz_nodes)
    byz_w = sum(byz_weight for _ in range(f))

    return {
        'n': n, 'f': f, 'byz_weight': byz_weight,
        'success_rate': successes / n_rounds,
        'avg_latency_ms': mean(latencies),
        'honest_weight_sum': honest_w,
        'byz_weight_sum': byz_w,
        'quorum_threshold': threshold,
        'honest_meets_quorum': honest_w >= threshold,
        'byz_meets_quorum': byz_w >= threshold,
    }


def main():
    print("=" * 80)
    print("E43: CW-PBFT Byzantine 容错阈值扫描")
    print("=" * 80)

    ns = [4, 7, 10, 13, 16]
    all_results = []

    for label, byz_w, honest_w in [
        ("A_等权基线(w=1.0)", 1.0, 1.0),
        ("B_恶意高权重(w=1.5)", 1.5, 1.0),
    ]:
        print(f"\n=== {label} ===")
        print(f"{'n':>4} {'f':>3} {'f/n':>5} {'诚实权':>7} {'恶意权':>7} {'2/3阈值':>8} "
              f"{'成功率':>7} {'活性':>5} {'latency':>9}")
        print("-" * 80)
        for n in ns:
            for f in range(0, n+1):
                r = run_one(n, f, byz_weight=byz_w, honest_weight=honest_w, n_rounds=10)
                r['scenario'] = label
                all_results.append(r)
                liveness = "✓" if r['success_rate'] >= 0.99 else "✗"
                print(f"{n:>4} {f:>3} {f/n:>5.2f} {r['honest_weight_sum']:>7.1f} "
                      f"{r['byz_weight_sum']:>7.1f} {r['quorum_threshold']:>8.2f} "
                      f"{r['success_rate']:>7.2f} {liveness:>5} {r['avg_latency_ms']:>8.2f}ms")
            print("-" * 80)

    # 汇总
    print("\n=== 容错阈值汇总（最大 f 使成功率 >= 99%） ===")
    print(f"{'场景':<25} {'n=4':>6} {'n=7':>6} {'n=10':>6} {'n=13':>6} {'n=16':>6}")
    print("-" * 60)
    for label in ["A_等权基线(w=1.0)", "B_恶意高权重(w=1.5)"]:
        row = [label[:24]]
        for n in ns:
            max_f = 0
            for r in all_results:
                if r['scenario'] == label and r['n'] == n and r['success_rate'] >= 0.99:
                    max_f = r['f']
            row.append(f"{max_f:>6}")
        print(" ".join(row))
    print(f"\n理论阈值（等权）: f <= (n-1)/3 → n=4:1, n=7:2, n=10:3, n=13:4, n=16:5")

    out = "results/delivery_main/e43_byzantine_threshold.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump({'results': all_results}, fh, ensure_ascii=False, indent=2)
    print(f"\n已保存: {out}")


if __name__ == '__main__':
    main()
