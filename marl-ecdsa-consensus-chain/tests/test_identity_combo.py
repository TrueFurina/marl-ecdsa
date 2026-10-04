"""
IdentityContract 剩余边界测试（RalphLoop 原子任务 CF）
覆盖：注册+状态+摘要联动、多实例共享、公钥注册联动、list 反映状态
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.identity_contract import IdentityContract, ContractCaller

logging.basicConfig(level=logging.CRITICAL)

VALID_PK = "04" + "ab" * 64
VALID_PK2 = "02" + "cd" * 32


class TestIntegratedFlow:
    def test_register_status_summary_flow(self):
        """注册+状态+摘要联动"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        ic.update_status("agent_0", "demoted", ContractCaller.PENALTY)
        agents = ic.list_agents()
        a0 = next(a for a in agents if a.get("agent_id") == "agent_0")
        assert a0["status"] == "demoted"  # 状态已反映
        assert ic.is_active("agent_0") is True  # demoted 仍活跃

    def test_full_flow_ban(self):
        """完整流程：注册→封禁→非活跃"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        ic.update_status("agent_0", "banned", ContractCaller.PENALTY)
        assert ic.is_active("agent_0") is False
        assert ic.get_status("agent_0") == "banned"


class TestMultiInstance:
    def test_two_contracts_share_ws(self):
        """两个 IdentityContract 共享同一 WorldState"""
        ws = WorldState()
        ic1 = IdentityContract(ws)
        ic2 = IdentityContract(ws)
        ic1.register("agent_0", VALID_PK)
        # ic2 能看到 ic1 注册的智能体
        assert ic2.get_public_key("agent_0") == VALID_PK
        assert ic2.is_active("agent_0") is True

    def test_update_via_one_seen_by_other(self):
        """状态更新经 ic1 后 ic2 可见"""
        ws = WorldState()
        ic1 = IdentityContract(ws)
        ic2 = IdentityContract(ws)
        ic1.register("agent_0", VALID_PK)
        ic1.update_status("agent_0", "warning", ContractCaller.PENALTY)
        assert ic2.get_status("agent_0") == "warning"


class TestRegistrationFlow:
    def test_register_then_query_pubkey(self):
        """注册后公钥可查"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        assert ic.get_public_key("agent_0") == VALID_PK

    def test_register_compressed_then_query(self):
        """压缩公钥注册后可查"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_1", VALID_PK2)
        assert ic.get_public_key("agent_1") == VALID_PK2

    def test_register_duplicate_rejected(self):
        """重复注册拒绝（组合流程）"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        r = ic.register("agent_0", VALID_PK2)  # 换公钥也拒绝（id 已存在）
        assert r["success"] is False


class TestStatusAndList:
    def test_list_reflects_status_changes(self):
        """list_agents 反映状态变化"""
        ws = WorldState()
        ic = IdentityContract(ws)
        ic.register("agent_0", VALID_PK)
        ic.update_status("agent_0", "banned", ContractCaller.PENALTY)
        agents = ic.list_agents()
        a0 = next(a for a in agents if a.get("agent_id") == "agent_0")
        assert a0["status"] == "banned"

    def test_unregistered_is_active_false(self):
        ws = WorldState()
        ic = IdentityContract(ws)
        assert ic.is_active("ghost") is False
        assert ic.get_status("ghost") is None
