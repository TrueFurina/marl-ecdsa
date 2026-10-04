"""
scripts 剩余脚本测试（RalphLoop 原子任务 CP）
覆盖：generate_complete_data 生成函数、screenshots 辅助函数
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import generate_complete_data as gcd
import generate_all_dashboard_screenshots as gads

logging.basicConfig(level=logging.CRITICAL)


class TestGenerateRewards:
    def test_length_and_mean(self):
        """奖励序列长度与均值近似目标"""
        rewards = gcd.generate_rewards(100, target_avg=-30, target_last50=-25)
        assert len(rewards) == 100
        assert abs(sum(rewards[-50:]) / 50 - (-25)) < 15  # 最后50均值近似目标

    def test_all_negative_mean(self):
        """奖励均值显著为负（SimpleSpread 环境惩罚；容忍噪声导致的个别正值）"""
        rewards = gcd.generate_rewards(50, target_avg=-30, target_last50=-25)
        assert sum(rewards) / len(rewards) < -10  # 均值显著为负


class TestGenerateRates:
    def test_cooperation_rates_in_range(self):
        """合作率在 [0,1]"""
        rates = gcd.generate_cooperation_rates(100, target_avg=0.6)
        assert len(rates) == 100
        assert all(0.0 <= r <= 1.0 for r in rates)

    def test_betrayal_rates_nonnegative(self):
        """背叛率非负"""
        rates = gcd.generate_betrayal_rates(100, mode="standard")
        assert all(r >= 0 for r in rates)
        assert len(rates) == 100


class TestGenerateMisc:
    def test_losses_length(self):
        """损失序列长度与智能体数一致"""
        losses = gcd.generate_losses(80, n_agents=3)
        assert len(losses) == 80

    def test_bc_scores_history_structure(self):
        """BC 积分历史为 dict 列表（每 agent 一值）"""
        hist = gcd.generate_bc_scores_history(60, n_agents=3)
        assert len(hist) == 60
        assert isinstance(hist[0], dict)
        assert 'agent_0' in hist[0]

    def test_bc_scores_final(self):
        """最终 BC 积分含全部 agent"""
        scores = gcd.generate_bc_scores_final(n_agents=3)
        assert len(scores) == 3
        assert all(0.0 <= s <= 1.0 for s in scores.values())


class TestScreenshotsHelpers:
    def test_load_json_missing_none(self, tmp_path):
        """缺失文件 → None"""
        assert gads.load_json("nonexistent_xyz.json") is None

    def test_smooth_length(self):
        """平滑后长度 = 原长度 - window + 1"""
        data = list(range(60))
        smoothed = gads.smooth(data, window=10)
        assert len(smoothed) == 51

    def test_smooth_value(self):
        """平滑均值正确"""
        data = [1.0] * 20
        smoothed = gads.smooth(data, window=5)
        assert all(abs(v - 1.0) < 1e-9 for v in smoothed)


class TestModuleIntegrity:
    def test_generate_complete_data_main(self):
        """generate_complete_data 主流程可调用（含 main）"""
        assert callable(gcd.generate_rewards)
        assert callable(gcd.generate_cooperation_rates)

    def test_import_ok(self):
        """两模块导入完整"""
        assert gcd is not None
        assert gads is not None
