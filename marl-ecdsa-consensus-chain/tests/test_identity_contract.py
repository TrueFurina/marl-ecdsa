"""
身份注册智能合约测试
覆盖：注册、查询、状态更新、权限控制、公钥校验
"""
import pytest
import sys
sys.path.insert(0, '.')

from blockchain.ledger.world_state import WorldState
from blockchain.contracts.identity_contract import IdentityContract, ContractCaller


@pytest.fixture
def world_state():
    return WorldState()


@pytest.fixture
def identity_contract(world_state):
    return IdentityContract(world_state)

VALID_PK = "04" + "a" * 128  # 非压缩公钥格式
VALID_PK2 = "04" + "b" * 128
COMPRESSED_PK = "02" + "c" * 64  # 压缩公钥格式


class TestRegistration:
    """智能体注册"""

    def test_register_success(self, identity_contract):
        result = identity_contract.register("agent_0", VALID_PK)
        assert result["success"] is True

    def test_register_duplicate_fails(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        result = identity_contract.register("agent_0", VALID_PK2)
        assert result["success"] is False
        assert "已注册" in result["error"]

    def test_register_empty_pk_fails(self, identity_contract):
        result = identity_contract.register("agent_0", None)
        assert result["success"] is False

    def test_register_invalid_pk_format(self, identity_contract):
        result = identity_contract.register("agent_0", "invalid_key")
        assert result["success"] is False
        assert "格式" in result["error"]

    def test_register_compressed_pk(self, identity_contract):
        result = identity_contract.register("agent_0", COMPRESSED_PK)
        assert result["success"] is True

    def test_register_wrong_length_pk(self, identity_contract):
        result = identity_contract.register("agent_0", "04" + "a" * 10)
        assert result["success"] is False


class TestQuery:
    """查询接口"""

    def test_get_public_key(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        pk = identity_contract.get_public_key("agent_0")
        assert pk == VALID_PK

    def test_get_public_key_nonexistent(self, identity_contract):
        pk = identity_contract.get_public_key("unknown")
        assert pk is None

    def test_get_status_normal(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        status = identity_contract.get_status("agent_0")
        assert status == "active"

    def test_get_status_nonexistent(self, identity_contract):
        status = identity_contract.get_status("unknown")
        assert status is None

    def test_list_agents(self, identity_contract):
        for i in range(3):
            identity_contract.register(f"agent_{i}", "04" + chr(97 + i) * 128)
        agents = identity_contract.list_agents()
        assert len(agents) == 3

    def test_is_active(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        assert identity_contract.is_active("agent_0") is True
        assert identity_contract.is_active("unknown") is False


class TestUpdateStatus:
    """状态更新（权限控制）"""

    def test_update_by_penalty_contract(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        result = identity_contract.update_status("agent_0", "warning", ContractCaller.PENALTY)
        assert result["success"] is True

    def test_update_by_admin_caller(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        result = identity_contract.update_status("agent_0", "warning", ContractCaller.ADMIN)
        assert result["success"] is True

    def test_update_by_unauthorized_caller(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        result = identity_contract.update_status("agent_0", "warning", ContractCaller.SYSTEM)
        assert result["success"] is False
        assert "无权限" in result["error"]

    def test_update_nonexistent_agent(self, identity_contract):
        result = identity_contract.update_status("unknown", "warning", ContractCaller.PENALTY)
        assert result["success"] is False

    def test_update_invalid_status(self, identity_contract):
        identity_contract.register("agent_0", VALID_PK)
        result = identity_contract.update_status("agent_0", "invalid_status", ContractCaller.PENALTY)
        assert result["success"] is False
