"""
WorldState/Identity 剩余边界测试（RalphLoop 原子任务 CT）
覆盖：积分-状态-摘要深度联动、惩罚链边界、合约组合查询
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState, AgentStatus
from blockchain.contracts.identity_contract import IdentityContract, ContractCaller

logging.basicConfig(level=logging.CRITICAL)

VALID_PK = "04" + "ab" * 64


class TestWorldStateDeepFlow:
    def test_penalty_chain_full(self):
        """完整惩罚链：背叛→扣分→权重降→状态降→摘要一致"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        ws.add_score("agent_0", 50.0)
        for h in range(3):
            ws.record_betrayal("agent_0", h)
        ws.update_consensus_weight("agent_0", 0.3)
        ws.set_agent_status("agent_0", AgentStatus.DEMOTED)
        summary = ws.get_agent_summary("agent_0")
        assert summary["betrayal_count"] == 3
        assert summary["consensus_weight"] == 0.3
        assert summary["status"] == AgentStatus.DEMOTED
        assert summary["score"] == 50.0

    def test_score_negative_contribution(self):
        """负积分不影响累计贡献（仅正增量）"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        ws.add_score("agent_0", 10.0)
        ws.add_score("agent_0", -10.0)
        ws.add_score("agent_0", 5.0)
        assert ws.get_score("agent_0") == 5.0
        assert ws.get_contribution("agent_0") == 15.0  # 10+5

    def test_system_state_multi_update(self):
        """系统状态多次更新累计"""
        ws = WorldState()
        ws.update_system_state(1, 10, 1)
        ws.update_system_state(2, 20, 2)
        ws.update_system_state(3, 30, 3)
        state = ws.get_system_state()
        assert state["total_transactions"] == 60
        assert state["block_height"] == 3
        assert state["online_agents"] == 3


class TestIdentityContractFlow:
    def test_register_status_flow(self):
        """注册→状态流转→摘要联动"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        ic.update_status("agent_0", "banned", ContractCaller.PENALTY)
        assert ic.get_status("agent_0") == "banned"
        assert ic.is_active("agent_0") is False
        agents = ic.list_agents()
        assert agents[0]["status"] == "banned"

    def test_contract_shared_state(self):
        """合约与 WorldState 共享状态（积分互通）"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        ws.add_score("agent_0", 25.0)  # 直接操作 WorldState
        agents = ic.list_agents()
        assert agents[0]["score"] == 25.0  # 合约看到积分

    def test_duplicate_register_same_pk(self):
        """同公钥重复注册仍拒绝（唯一性）"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        r = ic.register("agent_0", VALID_PK)
        assert r["success"] is False
        assert "已注册" in r["error"]


class TestBoundaryValues:
    def test_weight_bounds(self):
        """权重 0 与 1 边界"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        ws.update_consensus_weight("agent_0", 0.0)
        assert ws.get_consensus_weight("agent_0") == 0.0
        ws.update_consensus_weight("agent_0", 1.0)
        assert ws.get_consensus_weight("agent_0") == 1.0

    def test_score_large_negative(self):
        """大负积分（深度惩罚）"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        ws.add_score("agent_0", -1000.0)
        assert ws.get_score("agent_0") == -1000.0

    def test_unregistered_all_safe(self):
        """未注册全查询安全（get_score 抛 KeyError 为 P2-13 契约）"""
        ws = WorldState()
        assert ws.get_public_key("x") is None
        assert ws.get_agent_status("x") is None
        assert ws.is_registered("x") is False
        assert ws.get_contribution("x") == 0.0
        with pytest.raises(KeyError):  # P2-13：未注册获取积分抛 KeyError
            ws.get_score("x")


class TestPenaltyThreshold:
    def test_penalty_levels_by_betrayal_count(self):
        """背叛次数分级：封禁阈值自动封禁"""
        ws = WorldState()
        ws.register_agent("agent_0", "0x" + "ab" * 32)
        # 达到封禁阈值
        from blockchain.contracts.penalty_contract import PenaltyContract
        threshold = PenaltyContract.BAN_THRESHOLD
        for _ in range(threshold):
            ws.record_betrayal("agent_0", 1)
        penalty = PenaltyContract(ws)
        result = penalty.apply_penalty("agent_0")  # 默认 mild，但背叛数达标
        assert result["level"] == "BANNED"
