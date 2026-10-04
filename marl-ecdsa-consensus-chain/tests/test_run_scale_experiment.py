"""
run_scale_experiment 规模实验测试（RalphLoop 原子任务 AQ）
覆盖：BC 提升计算、结果收集结构、输出文件、模块完整性
通过标准：新增 ≥6 项测试全过
"""
import json
import logging
import sys
from pathlib import Path

import pytest

import run_scale_experiment as rse

logging.basicConfig(level=logging.CRITICAL)

ROOT = Path(__file__).resolve().parent.parent


class TestBCImprovements:
    def test_compute_improvement_pct(self):
        """BC 提升百分比：均值差/基线绝对值*100"""
        results = {
            'pure_marl_n3': {'env_reward_mean': 10.0, 'coop_rate_mean': 0.5},
            'bc_marl_n3': {'env_reward_mean': 12.0, 'coop_rate_mean': 0.6},
        }
        rse._compute_bc_improvements(results, [3])
        imp = results['bc_improvement_n3']
        assert imp['improvement_pct'] == pytest.approx(20.0)  # (12-10)/10*100
        assert imp['pure_env_reward'] == 10.0
        assert imp['bc_env_reward'] == 12.0

    def test_compute_improvement_missing_key_skips(self):
        """缺 key 时不崩溃、不生成提升记录"""
        results = {'pure_marl_n3': {'env_reward_mean': 10.0, 'coop_rate_mean': 0.5}}
        rse._compute_bc_improvements(results, [3])  # bc_marl_n3 缺失
        assert 'bc_improvement_n3' not in results

    def test_compute_improvement_zero_baseline(self):
        """基线为 0 → 不除零崩溃（用 max(0.001, abs) 保护）"""
        results = {
            'pure_marl_n3': {'env_reward_mean': 0.0, 'coop_rate_mean': 0.5},
            'bc_marl_n3': {'env_reward_mean': 1.0, 'coop_rate_mean': 0.6},
        }
        rse._compute_bc_improvements(results, [3])
        assert 'bc_improvement_n3' in results  # 不崩溃


class TestCollectResults:
    def test_collect_structure(self, monkeypatch):
        """_collect_results 产出标准结构（monkeypatch run_single 避免实际训练）"""
        fake_summary = {
            'avg_env_reward': -30.0, 'avg_reward': -25.0,
            'avg_cooperation_rate': 0.5,
        }
        monkeypatch.setattr(rse, 'run_single', lambda *a, **kw: fake_summary)
        results = rse._collect_results([3], 10, 2, 0.1, [42, 123])
        assert 'pure_marl_n3' in results
        assert 'bc_marl_n3' in results
        for key in ('env_reward_mean', 'env_reward_std', 'coop_rate_mean',
                    'avg_time_sec', 'n_agents', 'mode'):
            assert key in results['pure_marl_n3']


class TestRunScaleExperiment:
    def test_run_scale_writes_json(self, monkeypatch, tmp_path):
        """run_scale_experiment 输出 JSON 文件（monkeypatch 避免实际训练）"""
        fake_summary = {
            'avg_env_reward': -30.0, 'avg_reward': -25.0,
            'avg_cooperation_rate': 0.5,
        }
        monkeypatch.setattr(rse, 'run_single', lambda *a, **kw: fake_summary)
        out = tmp_path / "scale_out.json"

        class Args:
            agents = [3]
            episodes = 10
            seeds = 2
            seed_list = [42, 123]
            lambda_weight = 0.1
            output = str(out)

        rse.run_scale_experiment(Args)
        assert out.exists()
        data = json.loads(out.read_text(encoding='utf-8'))
        assert 'bc_improvement_n3' in data  # BC 提升已计算
        assert 'pure_marl_n3' in data


class TestModuleIntegrity:
    def test_functions_exist(self):
        """规模实验核心函数可导入"""
        assert callable(rse.run_single)
        assert callable(rse._collect_results)
        assert callable(rse._compute_bc_improvements)
        assert callable(rse.run_scale_experiment)

    def test_import_ok(self):
        """模块导入完整"""
        assert (ROOT / 'train.py').exists()
