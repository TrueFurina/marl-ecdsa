"""
IdentityContract 剩余组合测试（RalphLoop 原子任务 CK）
覆盖：公钥格式与注册联动、状态+活跃性联动、list 摘要字段、边界输入
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.identity_contract import IdentityContract, ContractCaller

logging.basicConfig(level=logging.CRITICAL)

VALID_PK = "04" + "ab" * 64
VALID_PK2 = "02" + "cd" * 32


class TestPubkeyValidationFlow:
    def test_register_uppercase_hex(self):
        """大写 hex 公钥也可注册（格式校验大小写不敏感）"""
        ws = WorldState()
        ic = IdentityContract(ws)
        pk_upper = "04" + "AB" * 64
        assert ic.register("agent_0", pk_upper)["success"] is True
        assert ic.get_public_key("agent_0") == pk_upper

    def test_register_invalid_prefix_rejected(self):
        """非法前缀（非 04/02/03）拒绝"""
        ws = WorldState()
        ic = IdentityContract(ws)
        r = ic.register("agent_0", "FF" + "ab" * 63)
        assert r["success"] is False
        assert "格式" in r["error"]

    def test_register_odd_length_rejected(self):
        """奇数长度 hex 拒绝"""
        ws = WorldState()
        ic = IdentityContract(ws)
        r = ic.register("agent_0", "04" + "abc")
        assert r["success"] is False


class TestStatusActiveFlow:
    def test_status_active_matrix(self):
        """各状态 + 活跃性联动"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        for status, active in [("active", True), ("warning", True),
                               ("demoted", True), ("banned", False)]:
            ic.update_status("agent_0", status, ContractCaller.PENALTY)
            assert ic.is_active("agent_0") is active, f"{status} 活跃性错误"

    def test_status_update_roundtrip(self):
        """状态更新往返一致"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        for status in ["warning", "demoted", "banned", "active"]:
            ic.update_status("agent_0", status, ContractCaller.PENALTY)
            assert ic.get_status("agent_0") == status


class TestListAgentsDetails:
    def test_list_has_all_summary_fields(self):
        """list_agents 摘要含 agent_id/status/consensus_weight"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        agents = ic.list_agents()
        a0 = agents[0]
        for key in ['agent_id', 'status', 'consensus_weight', 'score',
                    'cumulative_contribution', 'betrayal_count']:
            assert key in a0

    def test_list_after_ban_reflects(self):
        """封禁后 list 反映 banned 状态"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        ic.update_status("agent_0", "banned", ContractCaller.PENALTY)
        agents = ic.list_agents()
        assert agents[0]["status"] == "banned"
        assert agents[0]["betrayal_count"] >= 0


class TestEdgeCases:
    def test_register_none_agent_id(self):
        """None agent_id 注册 → 拒绝（不崩溃）"""
        ws = WorldState()
        ic = IdentityContract(ws)
        r = ic.register(None, VALID_PK)
        assert r["success"] is False

    def test_get_status_missing_none(self):
        """未注册 get_status → None"""
        ws = WorldState()
        ic = IdentityContract(ws)
        assert ic.get_status("ghost") is None

    def test_update_status_missing_agent(self):
        """未注册 update_status → 失败"""
        ws = WorldState()
        ic = IdentityContract(ws)
        r = ic.update_status("ghost", "warning", ContractCaller.PENALTY)
        assert r["success"] is False
        assert "不存在" in r["error"]
