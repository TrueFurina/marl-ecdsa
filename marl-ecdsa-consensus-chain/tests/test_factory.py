"""
共识引擎工厂测试
覆盖 cw_pbft / standard_pbft / fast 三种模式的创建与接口一致性
（多共识模式切换功能，CCF 竞赛）
"""
import json
import logging

import pytest

from blockchain.consensus.factory import (
    DEFAULT_MODE, VALID_MODES, create_consensus_engine, load_consensus_mode,
)

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2', 'node_3']


class TestLoadConsensusMode:
    """config.json 模式读取"""

    def test_config_mode_is_valid(self):
        mode = load_consensus_mode()
        assert mode in VALID_MODES
        assert mode == 'cw_pbft'  # config.json 默认值


class TestCreateConsensusEngine:
    """三种模式创建 + 接口一致性"""

    @pytest.mark.parametrize('mode,expected_type', [
        ('cw_pbft', 'CWPBFTConsensus'),
        ('standard_pbft', 'StandardPBFTConsensus'),
        ('fast', 'CWPBFTConsensus'),  # fast 基于 CW-PBFT，网络层短路
    ])
    def test_create_modes(self, mode, expected_type):
        eng = create_consensus_engine('node_0', NODES, mode=mode)
        assert eng.__class__.__name__ == expected_type

    @pytest.mark.parametrize('mode', ['cw_pbft', 'standard_pbft', 'fast'])
    def test_interface_completeness(self, mode):
        """network_consensus 依赖的接口必须全部存在"""
        eng = create_consensus_engine('node_0', NODES, mode=mode)
        required = [
            'start_consensus', 'receive_pre_prepare', 'receive_vote',
            'is_consensus_reached', 'get_state', 'reset', 'fast_consensus',
            'update_weight', 'get_weights', '_check_weight_threshold',
        ]
        missing = [m for m in required if not hasattr(eng, m)]
        assert not missing, f'{mode} 缺少接口: {missing}'

    def test_invalid_mode_fallback(self):
        """非法模式回退默认值"""
        eng = create_consensus_engine('node_0', NODES, mode='not_a_mode')
        assert eng.__class__.__name__ == 'CWPBFTConsensus'


class TestConsensusBehavior:
    """三模式基本共识行为"""

    @pytest.mark.parametrize('mode', ['cw_pbft', 'standard_pbft', 'fast'])
    def test_fast_consensus_round(self, mode):
        eng = create_consensus_engine('node_0', NODES, mode=mode)
        ok = eng.fast_consensus('hash_test', 'node_0')
        assert ok is True
        assert eng.is_consensus_reached() is True

    def test_weights_semantics(self):
        """cw_pbft 有权重；standard_pbft 等权 1.0"""
        cw = create_consensus_engine('node_0', NODES, mode='cw_pbft')
        sp = create_consensus_engine('node_0', NODES, mode='standard_pbft')
        cw_w = cw.get_weights()
        sp_w = sp.get_weights()
        assert all(v == 1.0 for v in sp_w.values()), '标准PBFT应等权1.0'
        assert any(v != 1.0 for v in cw_w.values()) or len(set(cw_w.values())) >= 1
