"""
SigningService 子组件独立测试
覆盖：ECDSA签名、SecurityGuard校验、nonce管理、验签统计、重置
"""
import pytest
import sys
import time
import tempfile
import shutil

sys.path.insert(0, '.')

from marl.integration.signing_service import SigningService
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.security_guard import SecurityGuard


@pytest.fixture
def signing_setup():
    """构建完整签名组件（含 KeyManager + SecurityGuard）"""
    key_dir = tempfile.mkdtemp(prefix="test_signing_keys_")
    km = KeyManager(key_dir=key_dir)
    sg = SecurityGuard()

    # 注册 3 个智能体密钥
    for i in range(3):
        km.generate_or_load(f"agent_{i}")

    service = SigningService(
        key_manager=km,
        security_guard=sg,
        n_agents=3,
    )

    yield service, km, sg, key_dir

    shutil.rmtree(key_dir, ignore_errors=True)


@pytest.fixture
def signing_no_km():
    """无 KeyManager 的 SigningService（stub 模式）"""
    return SigningService(key_manager=None, security_guard=None, n_agents=3)


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


class TestSigningServiceInit:
    """初始化测试"""

    def test_init_nonce_counters(self, signing_setup):
        """nonce 计数器应初始化为 0"""
        service, _, _, _ = signing_setup
        for i in range(3):
            assert service._nonce_counters[f"agent_{i}"] == 0

    def test_init_stats_zero(self, signing_setup):
        """统计计数器应初始化为 0"""
        service, _, _, _ = signing_setup
        stats = service.get_stats()
        assert stats['ecdsa_sign_count'] == 0
        assert stats['ecdsa_verify_count'] == 0
        assert stats['security_pass_count'] == 0
        assert stats['security_fail_count'] == 0

    def test_init_nonce_baseline_synced(self, signing_setup):
        """初始化时应将 nonce 基线同步到 SecurityGuard"""
        service, _, sg, _ = signing_setup
        # SecurityGuard 应有 nonce 基线记录
        for aid in AGENT_IDS:
            baseline = sg._nonce_registry.get(aid)
            assert baseline is not None, f"{aid} 应有 nonce 基线"

    def test_init_no_key_manager(self, signing_no_km):
        """无 KeyManager 时不应崩溃"""
        assert signing_no_km.key_manager is None
        assert len(signing_no_km._nonce_counters) == 3


class TestSignAndVerify:
    """签名 + 安全校验一体化流程"""

    def test_sign_and_verify_basic(self, signing_setup):
        """基本签名 + 校验流程"""
        service, km, _, _ = signing_setup
        nonce = 1
        ts = int(time.time() * 1000)
        action_data = {"action": 2, "position": [0.5, 0.3]}

        result = service.sign_and_verify("agent_0", action_data, nonce, ts)

        assert result is not None
        assert 'signature_hex' in result
        assert 'message_hex' in result
        assert 'r' in result
        assert 's' in result
        assert result.get('verified') is True  # SecurityGuard 应通过

    def test_sign_and_verify_all_agents(self, signing_setup):
        """3 个智能体均能签名"""
        service, _, _, _ = signing_setup
        ts = int(time.time() * 1000)

        for i, aid in enumerate(AGENT_IDS):
            nonce = i + 1
            result = service.sign_and_verify(aid, {"action": i}, nonce, ts)
            assert result is not None, f"{aid} 签名应成功"
            assert result['verified'] is True, f"{aid} SecurityGuard 应通过"

    def test_sign_count_increments(self, signing_setup):
        """签名次数应正确递增"""
        service, _, _, _ = signing_setup
        ts = int(time.time() * 1000)
        for step in range(3):
            service.sign_and_verify("agent_0", {"action": step}, step + 1, ts)
        assert service._sign_count == 3

    def test_security_pass_count_increments(self, signing_setup):
        """SecurityGuard 通过次数应递增"""
        service, _, _, _ = signing_setup
        ts = int(time.time() * 1000)
        service.sign_and_verify("agent_0", {"action": 0}, 1, ts)
        assert service._security_pass_count == 1

    def test_sign_without_key_manager(self, signing_no_km):
        """无 KeyManager 时签名返回 None"""
        ts = int(time.time() * 1000)
        result = signing_no_km.sign_and_verify("agent_0", {"action": 0}, 1, ts)
        # 无 key_manager → 签名跳过 → signed_package=None → 返回 None
        assert result is None

    def test_sign_invalid_agent(self, signing_setup):
        """不存在密钥的智能体签名返回 None"""
        service, _, _, _ = signing_setup
        ts = int(time.time() * 1000)
        result = service.sign_and_verify("agent_99", {"action": 0}, 1, ts)
        assert result is None

    def test_security_fail_on_nonce_reuse(self, signing_setup):
        """nonce 重用 → SecurityGuard 应拦截"""
        service, _, sg, _ = signing_setup
        ts = int(time.time() * 1000)

        # 正常签名 nonce=1
        service.sign_and_verify("agent_0", {"action": 0}, 1, ts)
        assert service._security_pass_count == 1

        # nonce 重用（nonce=1 再次出现）→ SecurityGuard 拦截
        # 注意：SigningService 不自动管理 nonce，这里模拟重放场景
        sg._nonce_registry["agent_0"] = 1  # 已记录 nonce=1
        result = service.sign_and_verify("agent_0", {"action": 0}, 1, ts)
        # sign_and_verify 内部调用 SecurityGuard.check_package
        # nonce 不递增 → 拦截 → verified=False
        assert result is not None  # 签名本身成功
        assert result.get('verified') is False  # SecurityGuard 拦截
        assert service._security_fail_count >= 1


class TestNonceManagement:
    """nonce 管理"""

    def test_nonce_counters_external_increment(self, signing_setup):
        """外部手动递增 nonce_counters（模拟 Bridge.on_step 行为）"""
        service, _, _, _ = signing_setup
        for step in range(5):
            aid = "agent_0"
            nonce = service._nonce_counters.get(aid, 0) + 1
            service._nonce_counters[aid] = nonce
        assert service._nonce_counters["agent_0"] == 5

    def test_reset_nonce_state(self, signing_setup):
        """reset_nonce_state 应清零 nonce_counters + 同步 SecurityGuard"""
        service, _, sg, _ = signing_setup
        # 先递增
        service._nonce_counters["agent_0"] = 5
        service._nonce_counters["agent_1"] = 3

        service.reset_nonce_state()

        assert service._nonce_counters["agent_0"] == 0
        assert service._nonce_counters["agent_1"] == 0
        # SecurityGuard nonce 也应重置
        assert sg._nonce_registry.get("agent_0") == 0


class TestVerifyEpisodeTransactions:
    """回合验签测试"""

    def test_verify_with_real_blockchain(self, signing_setup):
        """使用真实 Blockchain 验签"""
        service, km, _, _ = signing_setup
        from blockchain.ledger.blockchain import Blockchain
        from blockchain.ledger.block import Transaction

        bc = Blockchain()
        # 创建一个带签名的 Transaction 并加入交易池
        ts = int(time.time() * 1000)
        priv_key = km.get_private_key("agent_0")
        signed_pkg = ECDSAUtils.sign_action("agent_0", priv_key, {"action": 0}, 1, ts)

        tx = Transaction(
            tx_id="", agent_id="agent_0", action={"action": 0},
            action_hash=signed_pkg.get('message_hex', '')[:16],
            timestamp=ts, nonce=1,
            signature_hex=signed_pkg['signature_hex'],
            tx_type="action",
            extra={
                'message_hex': signed_pkg['message_hex'],
                'r': signed_pkg['r'], 's': signed_pkg['s'],
            },
        )
        tx.tx_id = tx.compute_hash()
        bc.add_transaction(tx)

        # 验签
        service.verify_episode_transactions(bc)
        assert service._verify_count >= 1

    def test_verify_no_bc_node(self, signing_setup):
        """bc_node=None 时验签应跳过"""
        service, _, _, _ = signing_setup
        service.verify_episode_transactions(None)
        assert service._verify_count == 0  # 未增加

    def test_verify_no_key_manager(self, signing_no_km):
        """key_manager=None 时验签应跳过"""
        from blockchain.ledger.blockchain import Blockchain
        bc = Blockchain()
        signing_no_km.verify_episode_transactions(bc)
        assert signing_no_km._verify_count == 0


class TestGetStats:
    """统计接口"""

    def test_get_stats_structure(self, signing_setup):
        """get_stats 返回完整结构"""
        service, _, _, _ = signing_setup
        stats = service.get_stats()
        assert 'ecdsa_sign_count' in stats
        assert 'ecdsa_verify_count' in stats
        assert 'security_pass_count' in stats
        assert 'security_fail_count' in stats

    def test_get_stats_after_operations(self, signing_setup):
        """操作后统计应正确反映"""
        service, _, _, _ = signing_setup
        ts = int(time.time() * 1000)
        service.sign_and_verify("agent_0", {"action": 0}, 1, ts)
        service.sign_and_verify("agent_1", {"action": 1}, 1, ts)

        stats = service.get_stats()
        assert stats['ecdsa_sign_count'] == 2
        assert stats['security_pass_count'] == 2
        assert stats['security_fail_count'] == 0
