"""
Tier1: CW-PBFT vs Standard PBFT 对比实验（v3 — 引擎原生拜占庭注入）

P0-D 修复（2026-09-01）：
- 改用引擎原生 simulated_consensus(byzantine_nodes) 真实注入拜占庭（省略故障模型），
  不再依赖外部多节点编排，byz_ratio 由共识引擎本身真实消费。
- 保留 5% 诚实节点消息丢失（HONEST_MSG_LOSS），模拟网络不可靠。
- 不使用 fast_consensus fallback，真实统计成功率。

核心差异体现：
- Standard PBFT：需要 2n/3 个节点投票（按节点数），拜占庭/丢包节点不投票 → 难达阈值
- CW-PBFT：需要 2/3 总权重，高贡献诚实节点权重高 → 少数诚实节点即可达阈值

⚠ 假象对照组声明（2026-09-19）：
本脚本的 CW-PBFT 权重是**硬编码**的：拜占庭节点 w=0.2、其余节点 1.0+0.3*(idx%3)。
构造权重时直接读取了 byzantine_ids，即协议事先知道谁是坏节点 —— 真实系统做不到。
因此本脚本报告的 CW 增益属**实验假象**，仅作 artifact control 保留，
**禁止作为创新点申报**；数值不做修改以保持历史可比性。
输出 JSON 中带 is_artifact_control=true 与 warning 字段。
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import json
import time
import random
import hashlib
import logging
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set

sys.path.insert(0, str(Path(__file__).parent))

from blockchain.consensus.cw_pbft import CWPBFTConsensus, ConsensusState, ConsensusVote
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('consensus_compare')

# 结果落到仓库 results/ 下（原为 legacy/experiments/results，与仓库口径不一致）
RESULTS_DIR = _Path(_REPO_ROOT) / 'results' / 'consensus_comparison'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 保护已有实验结果：默认绝不覆盖（--overwrite 显式开启才覆盖）
OVERWRITE = False


def _safe_write_json(obj, target: Path) -> Path:
    """写 JSON 但绝不覆盖已存在文件：存在时改写为 <stem>_<时间戳>.json"""
    target = Path(target)
    if target.exists() and not OVERWRITE:
        alt = target.with_name(f"{target.stem}_{time.strftime('%Y%m%d_%H%M%S')}{target.suffix}")
        logger.warning(f"[保护] {target.name} 已存在，本次报告另存为 {alt.name}")
        target = alt
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return target

NODE_COUNTS = [4, 7, 10, 16]
BYZANTINE_RATIOS = [0.0, 0.1, 0.2, 0.33, 0.4]
N_ROUNDS = 200
HONEST_MSG_LOSS = 0.05  # 5% 消息丢失率（模拟网络不可靠）


def simulate_consensus(
    consensus_class,
    n_nodes: int,
    byzantine_ratio: float,
    n_rounds: int,
    use_weights: bool = True,
) -> Dict:
    """
    单机引擎原生共识模拟（P0-D 修复版）

    - 用共识引擎自身的 simulated_consensus(byzantine_nodes) 真实注入拜占庭；
    - 每轮静默节点 = 拜占庭节点 ∪ 5% 消息丢失的诚实节点；
    - 真实统计共识成功率与延迟。
    """
    node_ids = [f'node_{i}' for i in range(n_nodes)]
    n_byzantine = int(n_nodes * byzantine_ratio)
    byzantine_ids = set(node_ids[:n_byzantine]) if n_byzantine > 0 else set()

    engine = consensus_class(node_id='node_0', consensus_nodes=node_ids)

    # CW-PBFT：设置差异化权重（高贡献节点更高权重）
    #
    # ⚠ 实验假象对照组（2026-09-19 标注）：
    #    下面这段直接读取 byzantine_ids —— 即协议"事先知道谁是坏节点"，
    #    并把坏节点权重手工压到 0.2、诚实节点按 1.0+0.3*(idx%3) 硬编码。
    #    真实系统中坏节点身份不可预知，因此本档的增益属实验假象，
    #    **禁止作为创新点申报**；仅作 artifact control 保留。
    #    数值与逻辑不做修改，以保持与历史 report 的可比性。
    if use_weights and consensus_class == CWPBFTConsensus:
        for nid in node_ids:
            if nid in byzantine_ids:
                engine.update_weight(nid, 0.2)  # 拜占庭节点极低权重
            else:
                idx = int(nid.split('_')[1])
                engine.update_weight(nid, 1.0 + 0.3 * (idx % 3))

    latencies = []
    successes = 0
    failures = 0

    for round_idx in range(n_rounds):
        engine.reset()
        engine._state = ConsensusState.IDLE

        # 本轮静默节点 = 拜占庭节点 + 5% 消息丢失的诚实节点
        silent = set(byzantine_ids)
        for nid in node_ids:
            if nid not in byzantine_ids and random.random() < HONEST_MSG_LOSS:
                silent.add(nid)

        proposer = engine.get_primary(round_idx // 10)
        start_ms = time.time() * 1000
        block_hash = hashlib.sha256(f'block_{round_idx}_{start_ms}'.encode()).hexdigest()
        ok = engine.simulated_consensus(block_hash, proposer, byzantine_nodes=silent)
        latency = time.time() * 1000 - start_ms

        if ok:
            successes += 1
            latencies.append(latency)
        else:
            failures += 1

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    success_rate = successes / n_rounds if n_rounds > 0 else 0.0

    final_weights = {}
    if use_weights and consensus_class == CWPBFTConsensus:
        final_weights = engine.get_weights()

    result = {
        'n_nodes': n_nodes,
        'byzantine_ratio': byzantine_ratio,
        'n_byzantine': n_byzantine,
        'n_rounds': n_rounds,
        'successes': successes,
        'failures': failures,
        'success_rate': success_rate,
        'avg_latency_ms': round(avg_latency, 3),
        'min_latency_ms': round(min(latencies), 3) if latencies else 0.0,
        'max_latency_ms': round(max(latencies), 3) if latencies else 0.0,
        'final_weights': final_weights,
    }
    # 假象对照标记：本脚本的 CW 权重为硬编码且预知坏节点身份 → 输出强制标注
    if use_weights and consensus_class == CWPBFTConsensus:
        result['is_artifact_control'] = True
        result['warning'] = (
            'CW-PBFT 权重为硬编码（拜占庭 w=0.2、诚实 1.0+0.3*(idx%3)），'
            '构造时直接读取拜占庭身份集合，等于协议事先知道谁是坏节点。'
            '该增益是实验假象，仅作对照组，禁止作为创新点申报。'
        )
    return result


def main():
    logger.info(f"=== CW-PBFT vs Standard PBFT v3 (native byzantine) ===")
    logger.info(f"节点数: {NODE_COUNTS}, 拜占庭比例: {BYZANTINE_RATIOS}, 每配置{N_ROUNDS}轮")

    results = {
        'cw_pbft': [], 'standard_pbft': [], 'comparison': [],
        # 全局假象标记：本脚本所有 CW 行的权重均硬编码且预知坏节点身份
        'is_artifact_control': True,
        'artifact_warning': (
            '本报告中 CW-PBFT 的权重为硬编码（拜占庭 w=0.2、诚实 1.0+0.3*(idx%3)），'
            '构造时直接读取拜占庭身份集合，等于协议事先知道谁是坏节点。'
            '相应增益属实验假象，仅作对照组，禁止作为创新点申报。'
        ),
    }
    total_configs = len(NODE_COUNTS) * len(BYZANTINE_RATIOS)
    config_idx = 0

    for n in NODE_COUNTS:
        for byz_ratio in BYZANTINE_RATIOS:
            config_idx += 1
            logger.info(f"[{config_idx}/{total_configs}] n={n}, byzantine={byz_ratio:.0%}")

            cw_result = simulate_consensus(CWPBFTConsensus, n, byz_ratio, N_ROUNDS, use_weights=True)
            cw_result['consensus_type'] = 'cw_pbft'
            results['cw_pbft'].append(cw_result)

            std_result = simulate_consensus(StandardPBFTConsensus, n, byz_ratio, N_ROUNDS, use_weights=False)
            std_result['consensus_type'] = 'standard_pbft'
            results['standard_pbft'].append(std_result)

            latency_improvement = 0.0
            if std_result['avg_latency_ms'] > 0 and cw_result['avg_latency_ms'] > 0:
                latency_improvement = (
                    (std_result['avg_latency_ms'] - cw_result['avg_latency_ms'])
                    / std_result['avg_latency_ms'] * 100
                )

            comparison = {
                'n_nodes': n,
                'byzantine_ratio': byz_ratio,
                'cw_pbft_success_rate': cw_result['success_rate'],
                'std_pbft_success_rate': std_result['success_rate'],
                'cw_pbft_avg_latency': cw_result['avg_latency_ms'],
                'std_pbft_avg_latency': std_result['avg_latency_ms'],
                'latency_improvement_pct': round(latency_improvement, 2),
                'success_rate_diff': cw_result['success_rate'] - std_result['success_rate'],
            }
            results['comparison'].append(comparison)

            logger.info(
                f"  CW: rate={cw_result['success_rate']:.1%}, lat={cw_result['avg_latency_ms']:.3f}ms | "
                f"PBFT: rate={std_result['success_rate']:.1%}, lat={std_result['avg_latency_ms']:.3f}ms | "
                f"diff={comparison['success_rate_diff']:+.1%}"
            )

    report_path = _safe_write_json(results, RESULTS_DIR / 'consensus_comparison_report.json')
    logger.info(f"Report saved: {report_path}")

    # 打印摘要表
    print("\n" + "=" * 95)
    print("CW-PBFT vs Standard PBFT Comparison Results (native byzantine injection)")
    print("=" * 95)
    print(f"{'Nodes':>6} {'Byz%':>6} | {'CW Rate':>8} {'PBFT Rate':>10} | {'CW Lat':>8} {'PBFT Lat':>9} {'Diff':>6}")
    print("-" * 95)
    for c in results['comparison']:
        print(
            f"{c['n_nodes']:>6} {c['byzantine_ratio']:>5.0%} | "
            f"{c['cw_pbft_success_rate']:>7.1%} {c['std_pbft_success_rate']:>9.1%} | "
            f"{c['cw_pbft_avg_latency']:>7.3f}ms {c['std_pbft_avg_latency']:>8.3f}ms "
            f"{c['success_rate_diff']:>+5.1%}"
        )


if __name__ == '__main__':
    import argparse as _ap
    _p = _ap.ArgumentParser(description='CW-PBFT vs Standard PBFT 共识对比')
    _p.add_argument('--out-dir', type=str, default=None)
    _p.add_argument('--n-rounds', type=int, default=None)
    _p.add_argument('--overwrite', action='store_true', default=False)
    _a = _p.parse_args()
    if _a.out_dir is not None:
        RESULTS_DIR = Path(_a.out_dir)
    if _a.n_rounds is not None:
        N_ROUNDS = _a.n_rounds
    OVERWRITE = bool(_a.overwrite)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    main()
