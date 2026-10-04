"""
plot_results 图表生成测试（RalphLoop 原子任务 BQ）
覆盖：图表输出、空数据降级、实验对比、排行榜、全部图表
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import visualization.plot_results as pr

logging.basicConfig(level=logging.CRITICAL)


class TestPlotTrainingCurve:
    def test_empty_data_no_output(self, tmp_path):
        """空数据 → 不生成文件（降级返回）"""
        out = tmp_path / 'curve.png'
        pr.plot_training_curve({}, str(out))
        assert not out.exists()  # 空数据不落盘

    def test_generates_png(self, tmp_path):
        """有数据 → 生成 PNG 文件"""
        out = tmp_path / 'curve.png'
        pr.plot_training_curve({'episode_rewards': list(range(30))}, str(out))
        assert out.exists()
        assert out.stat().st_size > 0


class TestPlotCooperationRate:
    def test_empty_rates_no_output(self, tmp_path):
        out = tmp_path / 'coop.png'
        pr.plot_cooperation_rate({}, str(out))
        assert not out.exists()

    def test_generates_png(self, tmp_path):
        out = tmp_path / 'coop.png'
        pr.plot_cooperation_rate({'cooperation_rates': [0.5] * 30}, str(out))
        assert out.exists()
        assert out.stat().st_size > 0


class TestPlotExperimentComparison:
    def test_empty_experiments_creates_dir(self, tmp_path):
        """空实验 → 创建输出目录（不崩溃）"""
        pr.plot_experiment_comparison({}, str(tmp_path / 'exp'))
        assert (tmp_path / 'exp').exists()

    def test_generates_plots(self, tmp_path):
        """有实验数据 → 生成对比图"""
        exp_results = {
            'experiments': [{
                'name': 'test',
                'results': {
                    'pure_marl': {'avg_env_reward': -30.0, 'avg_cooperation_rate': 0.5},
                    'bc_marl': {'avg_env_reward': -25.0, 'avg_cooperation_rate': 0.6},
                },
            }]
        }
        out_dir = tmp_path / 'exp'
        pr.plot_experiment_comparison(exp_results, str(out_dir))
        files = list(out_dir.glob('*.png'))
        assert len(files) >= 1


class TestPlotLeaderboard:
    def test_empty_leaderboard_no_crash(self, tmp_path):
        out = tmp_path / 'lb.png'
        pr.plot_leaderboard({}, str(out))  # 空数据不崩溃


class TestGenerateAllPlots:
    def test_missing_results_file(self, tmp_path):
        """缺失结果文件 → 不崩溃（返回 None）"""
        result = pr.generate_all_plots(
            str(tmp_path / 'nonexistent.json'), str(tmp_path / 'plots'))
        assert result is None

    def test_functions_exist(self):
        """全部图表函数可调用"""
        for name in ['plot_training_curve', 'plot_cooperation_rate',
                     'plot_experiment_comparison', 'plot_leaderboard',
                     'generate_all_plots']:
            assert callable(getattr(pr, name))
