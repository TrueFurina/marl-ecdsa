"""
更多模块剩余边界测试（RalphLoop 原子任务 DH）
覆盖：cw_pbft 状态/超时/重置、security_guard 检查分支（此前未单点覆盖）
通过标准：新增 ≥6 项测试全过
"""
import logging
import time

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus, ConsensusState
from blockchain.crypto.security_guard import SecurityGuard

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']


@pytest.fixture
def pbft():
    return CWPBFTConsensus('node_0', NODES)


class TestConsensusState:
    def test_initial_state_idle(self, pbft):
        """初始状态 IDLE"""
        assert pbft.get_state() == ConsensusState.IDLE
        assert pbft.is_consensus_reached() is False

    def test_fast_consensus_committed(self, pbft):
        """快速共识后状态 COMMITTED"""
        pbft.fast_consensus('hash_x', 'node_0')
        assert pbft.is_consensus_reached() is True

    def test_reset_returns_idle(self, pbft):
        """reset 后回 IDLE 且投票清空"""
        pbft.fast_consensus('hash_x', 'node_0')
        pbft.reset()
        assert pbft.get_state() == ConsensusState.IDLE
        assert pbft._votes == {'prepare': {}, 'commit': {}}
        assert pbft._current_block_hash is None

    def test_is_timed_out_before_start(self, pbft):
        """未启动共识 → 不超时"""
        assert pbft.is_timed_out() is False


class TestSecurityTimestamp:
    def test_timestamp_valid(self):
        """当前时间戳 → 通过"""
        guard = SecurityGuard()
        ok, _ = guard._check_timestamp({'timestamp': int(time.time() * 1000)})
        assert ok is True

    def test_timestamp_expired(self):
        """过期 60s → 拒绝（±30s 窗口）"""
        guard = SecurityGuard()
        ts = int(time.time() * 1000) - 60000
        ok, reason = guard._check_timestamp({'timestamp': ts})
        assert ok is False
        assert "过期" in reason

    def test_timestamp_missing(self):
        """缺时间戳 → 拒绝"""
        guard = SecurityGuard()
        ok, reason = guard._check_timestamp({})
        assert ok is False
        assert "缺少" in reason


class TestSecurityNonce:
    def test_nonce_monotonic(self):
        """nonce 严格递增通过"""
        guard = SecurityGuard()
        ok, _ = guard._check_nonce({'agent_id': 'a0', 'nonce': 1})
        assert ok is True
        ok, _ = guard._check_nonce({'agent_id': 'a0', 'nonce': 2})
        assert ok is True

    def test_nonce_replay_rejected(self):
        """重复 nonce → 拒绝"""
        guard = SecurityGuard()
        guard._check_nonce({'agent_id': 'a0', 'nonce': 5})
        ok, reason = guard._check_nonce({'agent_id': 'a0', 'nonce': 5})
        assert ok is False
        assert "重放" in reason

    def test_nonce_missing(self):
        """缺 nonce → 拒绝"""
        guard = SecurityGuard()
        ok, reason = guard._check_nonce({'agent_id': 'a0'})
        assert ok is False
        assert "缺少" in reason


class TestSecurityRReuse:
    def test_r_unique_passes(self):
        """不同 r 值 → 通过"""
        guard = SecurityGuard()
        ok, _ = guard._check_r_reuse({'agent_id': 'a0', 'r': 0x1111})
        assert ok is True
        ok, _ = guard._check_r_reuse({'agent_id': 'a0', 'r': 0x2222})
        assert ok is True

    def test_r_reuse_rejected(self):
        """重复 r → 拒绝（k 重用检测）"""
        guard = SecurityGuard()
        guard._check_r_reuse({'agent_id': 'a0', 'r': 0x3333})
        ok, reason = guard._check_r_reuse({'agent_id': 'a0', 'r': 0x3333})
        assert ok is False
        assert "重用" in reason or "k值" in reason.lower()

    def test_r_missing_ok(self):
        """缺 r → 通过（r 可选）"""
        guard = SecurityGuard()
        ok, _ = guard._check_r_reuse({'agent_id': 'a0'})
        assert ok is True
