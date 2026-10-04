"""
IdentityContract 边界测试（RalphLoop 原子任务 O）
覆盖：注册校验（空/格式/重复）、状态更新权限、公钥查询、活跃检查
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.identity_contract import IdentityContract, ContractCaller

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def ws():
    return WorldState()


@pytest.fixture
def contract(ws):
    return IdentityContract(ws)


VALID_PK = "04" + "ab" * 64  # 130 字符非压缩公钥
VALID_PK2 = "02" + "cd" * 32  # 66 字符压缩公钥


class TestRegister:
    def test_register_valid_pk(self, contract):
        result = contract.register("agent_0", VALID_PK)
        assert result["success"] is True

    def test_register_none_pk_rejected(self, contract):
        result = contract.register("agent_0", None)
        assert result["success"] is False
        assert "不能为空" in result["error"]

    def test_register_malformed_pk_rejected(self, contract):
        result = contract.register("agent_0", "not_a_hex_key")
        assert result["success"] is False
        assert "格式不合法" in result["error"]

    def test_register_duplicate_rejected(self, contract):
        contract.register("agent_0", VALID_PK)
        result = contract.register("agent_0", VALID_PK2)
        assert result["success"] is False
        assert "已注册" in result["error"]

    def test_register_compressed_pk_valid(self, contract):
        """压缩公钥（66 字符）也接受"""
        result = contract.register("agent_1", VALID_PK2)
        assert result["success"] is True


class TestPublicKeyQuery:
    def test_get_public_key_after_register(self, contract):
        contract.register("agent_0", VALID_PK)
        assert contract.get_public_key("agent_0") == VALID_PK

    def test_get_public_key_missing_returns_none(self, contract):
        assert contract.get_public_key("ghost") is None


class TestUpdateStatus:
    def test_update_status_valid(self, contract):
        contract.register("agent_0", VALID_PK)
        result = contract.update_status("agent_0", "warning", ContractCaller.PENALTY)
        assert result["success"] is True

    def test_update_status_unauthorized_caller(self, contract):
        """非授权调用方（SYSTEM 不在 PENALTY/ADMIN 白名单）→ 拒绝"""
        contract.register("agent_0", VALID_PK)
        result = contract.update_status("agent_0", "warning", ContractCaller.SYSTEM)
        assert result["success"] is False
        assert "无权限" in result["error"]

    def test_update_status_invalid_value(self, contract):
        contract.register("agent_0", VALID_PK)
        result = contract.update_status("agent_0", "not_a_status", ContractCaller.PENALTY)
        assert result["success"] is False
        assert "无效状态" in result["error"]

    def test_update_status_unregistered(self, contract):
        result = contract.update_status("ghost", "warning", ContractCaller.PENALTY)
        assert result["success"] is False


class TestActiveCheck:
    def test_is_active_after_register(self, contract):
        contract.register("agent_0", VALID_PK)
        assert contract.is_active("agent_0") is True

    def test_is_active_unregistered(self, contract):
        assert contract.is_active("ghost") is False
