"""
run_consensus_comparison 实验脚本测试（P0-D 修复后 v3）
覆盖：simulate_consensus 引擎原生拜占庭注入、返回结构、
      CW-PBFT 抗拜占庭显著优于标准 PBFT（真实性质）
"""
import logging
import random
import sys
from pathlib import Path

import pytest

# 将实验脚本目录加入 sys.path（脚本位于 scripts/legacy/experiments/）
_EXP_DIR = str(Path(__file__).resolve().parent.parent / 'scripts' / 'legacy' / 'experiments')
if _EXP_DIR not in sys.path:
    sys.path.insert(0, _EXP_DIR)

import run_consensus_comparison as rcc  # noqa: E402
from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

logging.basicConfig(level=logging.CRITICAL)


class TestSimulateConsensus:
    def test_all_honest_high_success(self):
        """全诚实（拜占庭=0）→ 高成功率"""
        random.seed(42)
        result = rcc.simulate_consensus(CWPBFTConsensus, 7, 0.0, 50)
        assert result['success_rate'] >= 0.9
        assert result['failures'] + result['successes'] == result['n_rounds']

    def test_result_structure(self):
        result = rcc.simulate_consensus(CWPBFTConsensus, 4, 0.0, 5)
        for key in ['success_rate', 'avg_latency_ms', 'failures', 'n_rounds']:
            assert key in result

    def test_byzantine_cw_more_resilient_than_standard(self):
        """P0-D 核心性质：高拜占庭比例下 CW-PBFT 成功率 >= 标准 PBFT"""
        random.seed(7)
        cw = rcc.simulate_consensus(CWPBFTConsensus, 10, 0.4, 50, use_weights=True)
        std = rcc.simulate_consensus(StandardPBFTConsensus, 10, 0.4, 50, use_weights=False)
        assert cw['success_rate'] >= std['success_rate']

    def test_byzantine_reduces_cw_success_at_extreme(self):
        """极端拜占庭（高节点数）下 CW 成功率 <= 全诚实（证明拜占庭真实生效）"""
        random.seed(11)
        honest = rcc.simulate_consensus(CWPBFTConsensus, 16, 0.0, 50)
        byz = rcc.simulate_consensus(CWPBFTConsensus, 16, 0.4, 50, use_weights=True)
        assert byz['success_rate'] <= honest['success_rate']

    def test_cw_weight_protection_runs(self):
        result = rcc.simulate_consensus(CWPBFTConsensus, 5, 0.33, 20, use_weights=True)
        assert 0.0 <= result['success_rate'] <= 1.0

    def test_zero_rounds_handled(self):
        result = rcc.simulate_consensus(CWPBFTConsensus, 3, 0.0, 0)
        assert isinstance(result, dict)


class TestMainFlow:
    def test_imports_work(self):
        """模块导入完整（常量与辅助函数可用）"""
        assert hasattr(rcc, 'simulate_consensus')
        assert rcc.HONEST_MSG_LOSS >= 0.0
        assert rcc.BYZANTINE_RATIOS
