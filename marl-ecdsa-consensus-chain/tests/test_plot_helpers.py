"""
plot_results 辅助图测试（RalphLoop 原子任务 BS）
覆盖：奖励对比/合作率对比/奖励分布/BC积分趋势/仪表盘图
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import visualization.plot_results as pr

logging.basicConfig(level=logging.CRITICAL)


class TestRewardComparison:
    def test_generates_png(self, tmp_path):
        """奖励对比图生成 PNG"""
        out = tmp_path / 'sub'
        out.mkdir(exist_ok=True)
        pr._plot_reward_comparison(list(range(100)), list(range(50, 150)), 50, str(out))
        assert (out / 'comparison_reward.png').exists()

    def test_short_data_no_crash(self, tmp_path):
        """短数据（不足 window）不崩溃"""
        out = tmp_path / 'sub2'
        out.mkdir(exist_ok=True)
        pr._plot_reward_comparison([1, 2], [3, 4], 50, str(out))
        assert (out / 'comparison_reward.png').exists()


class TestCooperationComparison:
    def test_generates_png(self, tmp_path):
        out = tmp_path / 'sub3'
        out.mkdir(exist_ok=True)
        pr._plot_cooperation_comparison([0.5] * 50, [0.6] * 50, str(out))
        assert (out / 'comparison_coop.png').exists()

    def test_empty_no_crash(self, tmp_path):
        out = tmp_path / 'sub4'
        out.mkdir(exist_ok=True)
        pr._plot_cooperation_comparison([], [], str(out))  # 空数据不崩溃


class TestRewardDistribution:
    def test_generates_png(self, tmp_path):
        out = tmp_path / 'sub5'
        out.mkdir(exist_ok=True)
        pr._plot_reward_distribution(list(range(300)), list(range(100, 400)), str(out))
        assert (out / 'comparison_distribution.png').exists() or any(
            p.name.startswith('comparison') for p in out.glob('*.png'))


class TestBCScoreTrend:
    def test_generates_png(self, tmp_path):
        """BC 积分趋势图：bc 参数需含 bc_scores_history 键（真实契约）"""
        out = tmp_path / 'sub6'
        out.mkdir(exist_ok=True)
        bc = {'bc_scores_history': [{'agent_0': 1.0, 'agent_1': 2.0},
                                    {'agent_0': 2.0, 'agent_1': 3.0}]}
        pr._plot_bc_score_trend(bc, str(out))
        assert (out / 'bc_scores.png').exists()

    def test_empty_history_no_crash(self, tmp_path):
        """空 bc_scores_history → 不生成图（降级返回）"""
        out = tmp_path / 'sub6b'
        out.mkdir(exist_ok=True)
        pr._plot_bc_score_trend({}, str(out))
        assert not (out / 'bc_scores.png').exists()


class TestDashboardOverview:
    def test_generates_png(self, tmp_path):
        """综合仪表盘图：bc_scores_hist 为 list、pure/bc 含 summary 键（真实契约）"""
        out = tmp_path / 'sub7'
        out.mkdir(exist_ok=True)
        pr._plot_dashboard_overview(
            pure_r=list(range(30)), bc_r=list(range(30)),
            pure_c=[0.5] * 30, bc_c=[0.6] * 30,
            pure={'summary': {'avg_reward': -30.0, 'avg_reward_last_50': -28.0}},
            bc={'summary': {'avg_reward': -25.0, 'avg_reward_last_50': -23.0}},
            bc_scores_hist=[{'agent_0': 1.0}, {'agent_0': 2.0}], window=10,
            output_dir=str(out),
        )
        assert (out / 'dashboard_overview.png').exists()

    def test_functions_exist(self):
        """全部辅助图函数可调用"""
        for name in ['_plot_reward_comparison', '_plot_cooperation_comparison',
                     '_plot_reward_distribution', '_plot_bc_score_trend',
                     '_plot_dashboard_overview']:
            assert callable(getattr(pr, name))
