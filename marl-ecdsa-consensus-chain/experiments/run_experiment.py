"""
对比实验脚本
系统评估区块链-MARL协同机制的有效性

实验设计：
1. 实验A: 纯MARL vs MARL+区块链（验证区块链激励的增益效果）
2. 实验B: 不同自私比例对照（0% / 20% / 50%）（验证抗背叛能力）
3. 实验C: 不同λ权重对照（0.05 / 0.1 / 0.3）（超参数敏感性分析）

核心指标：
- 平均回合奖励、合作率、背叛率
- 区块链积分分布（基尼系数）
- 训练收敛速度
- 诚实智能体 vs 自私智能体的积分差异
"""
import json
import logging
import time
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger('experiment')

# 导入训练模块
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from train import TrainingConfig, MARLBlockchainTrainer, TrainingStats


class ExperimentRunner:
    """对比实验运行器"""

    def __init__(self, n_agents: int = 3, n_episodes: int = 500, greedy_step: float = 0.5):
        self.n_agents = n_agents
        self.n_episodes = n_episodes
        # greedy 一步贪心的假设步长：0.5=历史默认值；0.05=按环境动力学校准（GREEDY_STEP_CALIBRATED）
        self.greedy_step = greedy_step
        self.results: Dict[str, Any] = {
            'meta': {
                'timestamp': datetime.now().isoformat(),
                'n_agents': n_agents,
                'n_episodes': n_episodes,
                'greedy_step': greedy_step,
            },
            'experiments': [],
        }

    # -------------------------------------------------------------------------
    # 实验A: 纯MARL vs MARL+区块链
    # -------------------------------------------------------------------------

    def run_exp_a_pure_vs_bc(self, seed: int = 42) -> Dict:
        """
        实验A: 纯MARL vs MARL+区块链
        验证区块链激励对MARL训练效果的增益
        """
        logger.info("=" * 60)
        logger.info("实验A: 纯MARL vs MARL+区块链")
        logger.info("=" * 60)

        results_a = {}

        # A1: 纯MARL
        logger.info("\n>>> A1: 纯MARL模式（无区块链激励）")
        config_a1 = TrainingConfig(
            n_agents=self.n_agents, n_episodes=self.n_episodes,
            mode='pure_marl', seed=seed, lambda_weight=0.0,
        )
        trainer_a1 = MARLBlockchainTrainer(config_a1)
        stats_a1 = trainer_a1.train()
        results_a['pure_marl'] = stats_a1.summary()

        # A2: MARL+区块链
        logger.info("\n>>> A2: MARL+区块链模式（双向协同）")
        config_a2 = TrainingConfig(
            n_agents=self.n_agents, n_episodes=self.n_episodes,
            mode='bc_marl', seed=seed, lambda_weight=0.1,
        )
        trainer_a2 = MARLBlockchainTrainer(config_a2)
        stats_a2 = trainer_a2.train()
        results_a['bc_marl'] = stats_a2.summary()

        # 对比分析
        comparison = self._compare_results(results_a)
        results_a['comparison'] = comparison
        logger.info(f"\n实验A结论: {json.dumps(comparison, indent=2)}")

        self.results['experiments'].append({
            'name': 'Experiment A: Pure MARL vs MARL+Blockchain',
            'results': results_a,
        })
        return results_a

    # -------------------------------------------------------------------------
    # 实验B: 不同自私比例对照
    # -------------------------------------------------------------------------

    def run_exp_b_selfish_ratios(self, ratios: List[float] = None, modes: List[str] = None, seed: int = 42) -> Dict:
        """
        实验B: 不同自私比例下区块链激励机制的效果
        测试 0% / 20% / 50% 自私比例 × (random | greedy) 两种背叛模式
        """
        if ratios is None:
            ratios = [0.0, 0.2, 0.5]
        if modes is None:
            modes = ['random', 'greedy']

        logger.info("=" * 60)
        logger.info("实验B: 不同自私比例对照 (random vs greedy)")
        logger.info(f"测试比例: {[f'{r:.0%}' for r in ratios]}")
        logger.info(f"测试模式: {modes}")
        logger.info("=" * 60)

        results_b = {}

        for mode in modes:
            for ratio in ratios:
                label = f"selfish_{int(ratio*100)}pct_{mode}"
                logger.info(f"\n>>> B: 自私比例={ratio:.0%}, 模式={mode}")

                config = TrainingConfig(
                    n_agents=self.n_agents, n_episodes=self.n_episodes,
                    mode='selfish', seed=seed, lambda_weight=0.1,
                    selfish_ratio=ratio,
                    betrayal_mode=mode,
                    greedy_step=self.greedy_step,
                )
                trainer = MARLBlockchainTrainer(config)
                stats = trainer.train()
                results_b[label] = stats.summary()

                # 额外记录：诚实vs自私智能体的积分差异
                if trainer.bridge is not None:
                    bc_scores = trainer.bridge.get_bc_scores()
                    results_b[label]['bc_scores_final'] = dict(bc_scores)
                    results_b[label]['leaderboard'] = [
                        {'agent_id': a, 'score': s}
                        for a, s in trainer.incentive_contract.get_leaderboard()
                    ]

        comparison = self._compare_results(results_b)
        results_b['comparison'] = comparison
        logger.info(f"\n实验B结论: {json.dumps(comparison, indent=2)}")

        self.results['experiments'].append({
            'name': 'Experiment B: Selfish Ratio Comparison',
            'results': results_b,
        })
        return results_b

    # -------------------------------------------------------------------------
    # 实验C: λ权重敏感性分析
    # -------------------------------------------------------------------------

    def run_exp_c_lambda_sensitivity(self, lambdas: List[float] = None, seed: int = 42) -> Dict:
        """
        实验C: 区块链奖励权重 λ 的敏感性分析
        测试 λ = 0.05 / 0.1 / 0.3
        """
        if lambdas is None:
            lambdas = [0.05, 0.1, 0.3]

        logger.info("=" * 60)
        logger.info("实验C: λ权重敏感性分析")
        logger.info(f"测试值: {lambdas}")
        logger.info("=" * 60)

        results_c = {}

        for lam in lambdas:
            label = f"lambda_{lam:.2f}"
            logger.info(f"\n>>> C: λ={lam}")

            config = TrainingConfig(
                n_agents=self.n_agents, n_episodes=self.n_episodes,
                mode='bc_marl', seed=seed, lambda_weight=lam,
                selfish_ratio=0.2,  # 固定20%自私
            )
            trainer = MARLBlockchainTrainer(config)
            stats = trainer.train()
            results_c[label] = stats.summary()

        comparison = self._compare_results(results_c)
        results_c['comparison'] = comparison
        logger.info(f"\n实验C结论: {json.dumps(comparison, indent=2)}")

        self.results['experiments'].append({
            'name': 'Experiment C: Lambda Sensitivity Analysis',
            'results': results_c,
        })
        return results_c

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def _compare_results(self, results: Dict[str, Dict]) -> Dict:
        """比较各组实验结果"""
        comparison = {}
        for key, summary in results.items():
            comparison[key] = {
                'avg_reward': summary.get('avg_reward', 0),
                'avg_cooperation_rate': summary.get('avg_cooperation_rate', 0),
                'avg_betrayal_rate': summary.get('avg_betrayal_rate', 0),
                'elapsed_time': summary.get('elapsed_time', 0),
            }

        # 最佳模式
        if comparison:
            best = max(comparison.items(), key=lambda x: x[1]['avg_reward'])
            comparison['_best_mode'] = best[0]
            comparison['_best_reward'] = best[1]['avg_reward']

        return comparison

    def run_all(self) -> Dict:
        """运行全部对照实验"""
        start = time.time()

        self.run_exp_a_pure_vs_bc()
        self.run_exp_b_selfish_ratios()
        self.run_exp_c_lambda_sensitivity()

        self.results['meta']['total_time'] = time.time() - start

        # 输出综合报告
        self._print_final_report()

        return self.results

    def _print_final_report(self):
        """输出综合实验报告"""
        print("\n")
        print("=" * 70)
        print("  对照实验综合报告")
        print("=" * 70)

        for exp in self.results['experiments']:
            print(f"\n{'─' * 50}")
            print(f"  {exp['name']}")
            print(f"{'─' * 50}")

            for key, summary in exp['results'].items():
                if key == 'comparison':
                    continue
                print(f"  [{key}]")
                print(f"    平均奖励:     {summary.get('avg_reward', 0):.2f}")
                print(f"    合作率:       {summary.get('avg_cooperation_rate', 0):.2%}")
                print(f"    背叛率:       {summary.get('avg_betrayal_rate', 0):.2%}")
                print(f"    耗时:         {summary.get('elapsed_time', 0):.1f}s")

            comp = exp['results'].get('comparison', {})
            best = comp.get('_best_mode', 'N/A')
            best_r = comp.get('_best_reward', 0)
            print(f"  → 最佳配置: {best} (平均奖励={best_r:.2f})")

        print(f"\n{'=' * 70}")
        print(f"  总耗时: {self.results['meta']['total_time']:.1f}s")
        print(f"{'=' * 70}\n")

    def export_results(self, filepath: str = "experiment_results.json"):
        """导出实验结果为JSON"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"实验报告已导出到 {filepath}")


# =============================================================================
# 主入口
# =============================================================================

def run_experiment(n_agents: int = 3, n_episodes: int = 500, dashboard: bool = False):
    """运行对照实验（main.py调用入口）"""
    runner = ExperimentRunner(n_agents=n_agents, n_episodes=n_episodes)
    results = runner.run_all()
    runner.export_results()

    if dashboard:
        try:
            from visualization.dashboard import start_dashboard
            logger.info("启动可视化面板查看实验结果...")
            start_dashboard()
        except Exception as e:
            logger.error(f"Dashboard启动失败: {e}")

    return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='MARL-ECDSA 共识链 — 对照实验')
    parser.add_argument('--n_agents', type=int, default=3, help='智能体数量')
    parser.add_argument('--n_episodes', type=int, default=500, help='训练回合数')
    parser.add_argument('--exp', type=str, default='all',
                        choices=['all', 'a', 'b', 'c'], help='运行哪个实验')
    parser.add_argument('--dashboard', action='store_true', help='启动Dashboard')
    parser.add_argument('--seed', type=int, default=42, help='随机种子')
    parser.add_argument('--greedy_step', type=float, default=0.5,
                        help='greedy 一步贪心假设的每步位移（0.5=历史默认；0.05=按环境动力学校准）')
    parser.add_argument('--save', type=str, default=None,
                        help='结果输出绝对路径（默认写入 CWD 的 experiment_results.json）')
    args = parser.parse_args()

    out_path = args.save or "experiment_results.json"
    runner = ExperimentRunner(
        n_agents=args.n_agents, n_episodes=args.n_episodes, greedy_step=args.greedy_step,
    )

    if args.exp == 'all':
        runner.run_all()
    elif args.exp == 'a':
        runner.run_exp_a_pure_vs_bc(seed=args.seed)
    elif args.exp == 'b':
        runner.run_exp_b_selfish_ratios(seed=args.seed)
    elif args.exp == 'c':
        runner.run_exp_c_lambda_sensitivity(seed=args.seed)

    runner.export_results(out_path)

    if args.dashboard:
        from visualization.dashboard import start_dashboard
        start_dashboard()
