"""
端到端权重展宽实验（引擎级，路线C合入主引擎后的正式实验）

与 PoC（scripts/legacy/experiments/run_weight_broadening_poc.py）的区别：
- 走真实 CWPBFTConsensus 引擎：每轮共识后执行贡献度 NEW_WEIGHT 更新（R≈1.01 口径）
- 动态组开启 end_of_round_epoch_update（纪元50轮 + PARTICIPATION_FLOOR=0.25 + MAX_WEIGHT钳制）
- 对照组为标准 PBFT（节点计数法定人数）

矩阵：{n=10,25,40} × {省略率 0.1/0.2/0.3/0.4/0.5} × 5 种子 × 300 轮
输出：results/weight_broadening_engine/results.json（落盘判成功）

用法：
    python scripts/run_weight_broadening_engine.py                # 全量（服务器）
    python scripts/run_weight_broadening_engine.py --quick        # 冒烟（本地）
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

logging.basicConfig(level=logging.CRITICAL)

SEEDS = [42, 123, 456, 789, 2026]
ROUNDS = 300
NODE_SIZES = [10, 25, 40]
BYZ_RATIOS = [0.1, 0.2, 0.3, 0.4, 0.5]
FLOOR_RATIO = 0.4  # 超过此省略率跳过 n=10（诚实方不足法定人数属预期失效区）


def run_dynamic(n_nodes, byz_ratio, n_rounds, seed, broadening=True):
    """CW-PBFT 引擎 + 贡献度权重 + （可选）纪元展宽

    贡献度记账与 bc_integration._update_consensus_weights 同式：
    w = 1.0 + 0.5 * weighted_score（诚实协作 1.0 / 省略 0），自包含无合约依赖。
    """
    import random
    rng = random.Random(seed)
    nodes = [f'node_{i}' for i in range(n_nodes)]
    byz = set(rng.sample(nodes, int(n_nodes * byz_ratio)))
    eng = CWPBFTConsensus(nodes[0], nodes)
    scores = {nid: 0.0 for nid in nodes}
    success = epoch_summaries = 0
    for r in range(n_rounds):
        eng.reset()
        proposer = nodes[r % n_nodes]
        ok = eng.simulated_consensus(f'blk{r:04d}', proposer, byzantine_nodes=byz)
        # 贡献度记账（与 bc_integration._update_consensus_weights 语义一致）：
        # 只有产生贡献分数的节点才有 update_weight 事件；省略者无分数条目、
        # 权重不被重置，仅由纪末参与率展宽衰减（修复：此前对所有节点调
        # update_weight(1.0) 把省略者权重每轮重置回基线，导致 69.23% 假象）
        for nid in nodes:
            if nid not in byz:
                scores[nid] += 1.0
                eng.update_weight(nid, 1.0 + 0.5 * min(scores[nid] / (r + 1), 1.0))
        if ok:
            success += 1
            if broadening and eng.end_of_round_epoch_update() is not None:
                epoch_summaries += 1
    weights = eng.get_weights()
    honest_share = sum(w for n, w in weights.items() if n not in byz) / sum(weights.values())
    return success, epoch_summaries, honest_share


def run_std(n_nodes, byz_ratio, n_rounds, seed):
    """标准 PBFT 对照（节点计数法定人数）"""
    import random
    rng = random.Random(seed)
    nodes = [f'node_{i}' for i in range(n_nodes)]
    byz = set(rng.sample(nodes, int(n_nodes * byz_ratio)))
    eng = StandardPBFTConsensus(nodes[0], nodes)
    success = 0
    for r in range(n_rounds):
        proposer = nodes[r % n_nodes]
        if eng.simulated_consensus(f'blk{r:04d}', proposer, byzantine_nodes=byz):
            success += 1
    return success


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true', help='冒烟：n=10 单配置 1 种子 50 轮')
    args = ap.parse_args()

    if args.quick:
        nonlocal_scope = [(10, 0.4)]
        rounds, seeds = 50, [42]
    else:
        nonlocal_scope = [(n, b) for n in NODE_SIZES for b in BYZ_RATIOS]
        rounds, seeds = ROUNDS, SEEDS

    out_dir = Path('results/weight_broadening_engine')
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    t0 = time.time()
    for n_nodes, byz_ratio in nonlocal_scope:
        if n_nodes == 10 and byz_ratio > FLOOR_RATIO and not args.quick:
            continue  # 预期失效区（诚实方<法定人数），已在 PoC 定论
        dyn, dyn_ep, shares, std = [], [], [], []
        for s in seeds:
            succ, n_ep, hs = run_dynamic(n_nodes, byz_ratio, rounds, s, broadening=True)
            dyn.append(succ / rounds)
            dyn_ep.append(n_ep)
            shares.append(hs)
            std.append(run_std(n_nodes, byz_ratio, rounds, s) / rounds)
        row = {
            'n_nodes': n_nodes, 'byz_ratio': byz_ratio, 'n_seeds': len(seeds),
            'rounds': rounds,
            'cw_dynamic_success_rate': round(sum(dyn) / len(dyn), 4),
            'std_pbft_success_rate': round(sum(std) / len(std), 4),
            'honest_weight_share': round(sum(shares) / len(shares), 4),
            'epochs_triggered': int(sum(dyn_ep) / len(dyn_ep)),
        }
        results.append(row)
        print(f"[{time.time()-t0:6.0f}s] n={n_nodes} byz={byz_ratio} "
              f"CW={row['cw_dynamic_success_rate']:.2%} STD={row['std_pbft_success_rate']:.2%} "
              f"honest_share={row['honest_weight_share']:.2%}")

    out = {'results': results, 'meta': {
        'rounds': rounds, 'seeds': seeds, 'engine': 'CWPBFTConsensus(engine-level)',
        'broadening': 'epoch=50 floor=0.25 max=1.5', 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    }}
    out_path = out_dir / 'results.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"落盘: {out_path} ({len(results)} 组)")
    # 落盘判成功
    assert out_path.exists() and out_path.stat().st_size > 100, '结果文件异常'


if __name__ == '__main__':
    main()
