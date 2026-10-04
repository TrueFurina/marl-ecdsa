"""
experiments/run_experiment 实验模块测试（RalphLoop 原子任务 AT）
覆盖：ExperimentRunner 初始化、结果结构、实验入口、模块完整性
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.run_experiment import ExperimentRunner, run_experiment

logging.basicConfig(level=logging.CRITICAL)


class TestExperimentRunnerInit:
    def test_default_init(self):
        runner = ExperimentRunner()
        assert runner.n_agents == 3
        assert runner.n_episodes == 500

    def test_custom_init(self):
        runner = ExperimentRunner(n_agents=5, n_episodes=200)
        assert runner.n_agents == 5
        assert runner.n_episodes == 200

    def test_results_meta_structure(self):
        runner = ExperimentRunner(n_agents=3, n_episodes=500)
        meta = runner.results['meta']
        assert meta['n_agents'] == 3
        assert meta['n_episodes'] == 500
        assert 'timestamp' in meta

    def test_results_experiments_empty(self):
        runner = ExperimentRunner()
        assert runner.results['experiments'] == []


class TestExperimentEntrypoints:
    def test_run_exp_a_structure(self, monkeypatch):
        """实验A：纯MARL vs BC（monkeypatch trainer 避免实际训练）"""
        class FakeStats:
            def summary(self):
                return {'avg_reward': -30.0, 'avg_env_reward': -28.0,
                        'avg_cooperation_rate': 0.5, 'total_episodes': 10}

        class FakeTrainer:
            def __init__(self, *a, **kw):
                pass

            def train(self):
                return FakeStats()

        import experiments.run_experiment as re_mod
        monkeypatch.setattr(re_mod, 'MARLBlockchainTrainer', FakeTrainer)
        runner = ExperimentRunner(n_agents=3, n_episodes=10)
        result = runner.run_exp_a_pure_vs_bc(seed=42)
        assert 'pure_marl' in result
        assert 'bc_marl' in result
        assert 'comparison' in result
        assert len(runner.results['experiments']) == 1

    def test_run_exp_b_selfish_ratios(self, monkeypatch):
        """实验B：自私比例对照（monkeypatch trainer 避免实际训练）"""
        class FakeStats:
            def summary(self):
                return {'avg_reward': -30.0, 'avg_env_reward': -28.0,
                        'avg_cooperation_rate': 0.5, 'total_episodes': 10}

        class FakeTrainer:
            def __init__(self, *a, **kw):
                self.bridge = None  # run_exp_b 内部访问 trainer.bridge

            def train(self):
                return FakeStats()

        import experiments.run_experiment as re_mod
        monkeypatch.setattr(re_mod, 'MARLBlockchainTrainer', FakeTrainer)
        runner = ExperimentRunner(n_agents=3, n_episodes=10)
        result = runner.run_exp_b_selfish_ratios(ratios=[0.0, 0.2, 0.5], seed=42)
        assert isinstance(result, dict)
        assert len(runner.results['experiments']) == 1


class TestModuleIntegrity:
    def test_run_experiment_callable(self):
        """run_experiment 顶层入口可调用"""
        assert callable(run_experiment)

    def test_import_ok(self):
        """模块导入完整（ExperimentRunner 存在）"""
        assert ExperimentRunner is not None
