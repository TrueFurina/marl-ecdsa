"""
IdentityContract 状态流转边界测试（RalphLoop 原子任务 BO）
覆盖：状态字符串流转、list_agents 摘要、ADMIN 权限、公钥格式边界
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.identity_contract import IdentityContract, ContractCaller

logging.basicConfig(level=logging.CRITICAL)

VALID_PK = "04" + "ab" * 64
VALID_PK2 = "02" + "cd" * 32


@pytest.fixture
def contract():
    ws = WorldState()
    ic = IdentityContract(ws)
    ic.register("agent_0", VALID_PK)
    ic.register("agent_1", VALID_PK2)
    return ic


class TestStatusFlow:
    def test_initial_status_active(self, contract):
        assert contract.get_status("agent_0") == "active"

    def test_status_transitions(self, contract):
        """各状态字符串流转（PENALTY 权限）"""
        for status in ["warning", "demoted", "banned"]:
            assert contract.update_status("agent_0", status, ContractCaller.PENALTY)["success"] is True
            assert contract.get_status("agent_0") == status

    def test_admin_can_update(self, contract):
        """ADMIN 权限可更新状态"""
        r = contract.update_status("agent_1", "demoted", ContractCaller.ADMIN)
        assert r["success"] is True
        assert contract.get_status("agent_1") == "demoted"

    def test_system_cannot_update(self, contract):
        """SYSTEM 权限被拒绝"""
        r = contract.update_status("agent_1", "warning", ContractCaller.SYSTEM)
        assert r["success"] is False
        assert "无权限" in r["error"]


class TestListAgents:
    def test_list_agents_summary(self, contract):
        """list_agents 返回注册智能体摘要"""
        agents = contract.list_agents()
        assert len(agents) == 2
        ids = {a.get("agent_id") for a in agents}
        assert ids == {"agent_0", "agent_1"}

    def test_list_agents_has_status(self, contract):
        agents = contract.list_agents()
        assert all("status" in a for a in agents)


class TestPublicKeyValidation:
    def test_validate_130_hex(self):
        """130 字符非压缩公钥合法"""
        assert IdentityContract._validate_public_key("04" + "ab" * 64) is True

    def test_validate_66_hex(self):
        """66 字符压缩公钥合法"""
        assert IdentityContract._validate_public_key("02" + "cd" * 32) is True

    def test_validate_bad_length(self):
        """非法长度拒绝"""
        assert IdentityContract._validate_public_key("04" + "ab" * 10) is False

    def test_validate_non_hex(self):
        """非 hex 字符拒绝"""
        assert IdentityContract._validate_public_key("zz" + "ab" * 64) is False

    def test_validate_empty(self):
        assert IdentityContract._validate_public_key("") is False
        assert IdentityContract._validate_public_key(None) is False


class TestQueries:
    def test_get_status_unregistered_none(self, contract):
        assert contract.get_status("ghost") is None

    def test_is_active_after_ban(self, contract):
        contract.update_status("agent_0", "banned", ContractCaller.PENALTY)
        assert contract.is_active("agent_0") is False
