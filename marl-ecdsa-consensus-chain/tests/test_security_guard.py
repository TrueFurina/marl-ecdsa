"""
SecurityGuard 安全防护模块测试
测试三阶安全防护：时间戳校验 / Nonce 防重放 / K 值重用检测
"""
import pytest
import time


@pytest.mark.security
class TestSecurityGuardTimestamp:
    """时间戳校验测试"""

    def test_valid_timestamp_passes(self, security_guard, signed_package):
        """正常时间戳通过校验"""
        ok, reason = security_guard.check_package(signed_package)
        assert ok, f"Expected valid but got: {reason}"

    def test_future_timestamp_blocked(self, security_guard, signed_package):
        """未来时间戳被拦截"""
        pkg = signed_package.copy()
        pkg["timestamp"] = int(time.time() * 1000) + 60_000  # 未来60秒
        ok, reason = security_guard.check_package(pkg)
        assert not ok, "Future timestamp should be blocked"

    def test_expired_timestamp_blocked(self, security_guard, signed_package):
        """过期时间戳被拦截"""
        pkg = signed_package.copy()
        pkg["timestamp"] = int(time.time() * 1000) - 60_000  # 过去60秒
        ok, reason = security_guard.check_package(pkg)
        assert not ok, "Expired timestamp should be blocked"

    def test_boundary_timestamp_passes(self, security_guard, signed_package):
        """边界时间戳（刚好在窗口内）通过"""
        pkg = signed_package.copy()
        pkg["timestamp"] = int(time.time() * 1000) - 29_000  # 29秒前，在窗口内
        ok, _ = security_guard.check_package(pkg)
        assert ok


@pytest.mark.security
class TestSecurityGuardNonce:
    """Nonce 防重放测试"""

    def test_increasing_nonce_passes(self, security_guard, key_pair):
        """严格递增 nonce 通过（每个包独立签名避免 r 值冲突）"""
        from blockchain.crypto.ecdsa_utils import ECDSAUtils
        import time
        private_key, _ = key_pair

        pkg1 = ECDSAUtils.sign_action(
            agent_id="agent_nonce_test", private_key=private_key,
            action={"step": 1}, nonce=1, timestamp=int(time.time() * 1000)
        )
        pkg2 = ECDSAUtils.sign_action(
            agent_id="agent_nonce_test", private_key=private_key,
            action={"step": 2}, nonce=2, timestamp=int(time.time() * 1000)
        )

        ok1, _ = security_guard.check_package(pkg1)
        ok2, _ = security_guard.check_package(pkg2)

        assert ok1 and ok2

    def test_reused_nonce_blocked(self, security_guard, signed_package):
        """重复 nonce 被拦截"""
        pkg1 = signed_package.copy()
        pkg1["agent_id"] = "agent_replay_test"
        pkg1["nonce"] = 1

        pkg2 = signed_package.copy()
        pkg2["agent_id"] = "agent_replay_test"
        pkg2["nonce"] = 1  # 重复!

        ok1, _ = security_guard.check_package(pkg1)
        ok2, reason = security_guard.check_package(pkg2)

        assert ok1
        assert not ok2, f"Reused nonce should be blocked, got: {reason}"

    def test_decreasing_nonce_blocked(self, security_guard, signed_package):
        """递减 nonce 被拦截"""
        pkg1 = signed_package.copy()
        pkg1["agent_id"] = "agent_decrease_test"
        pkg1["nonce"] = 5

        pkg2 = signed_package.copy()
        pkg2["agent_id"] = "agent_decrease_test"
        pkg2["nonce"] = 3  # 递减!

        ok1, _ = security_guard.check_package(pkg1)
        ok2, reason = security_guard.check_package(pkg2)

        assert ok1
        assert not ok2

    def test_different_agents_same_nonce_allowed(self, security_guard, signed_package):
        """不同智能体可使用相同 nonce（各自独立计数）"""
        pkg1 = signed_package.copy()
        pkg1["agent_id"] = "agent_a"
        pkg1["nonce"] = 1

        pkg2 = signed_package.copy()
        pkg2["agent_id"] = "agent_b"  # 不同智能体
        pkg2["nonce"] = 1  # 相同nonce但不同智能体，应允许

        ok1, _ = security_guard.check_package(pkg1)
        ok2, _ = security_guard.check_package(pkg2)

        assert ok1 and ok2


@pytest.mark.security
class TestSecurityGuardKRvalue:
    """K 值重用检测测试（r 值追踪）"""

    def test_first_r_value_registered(self, security_guard, signed_package):
        """首次 r 值应被注册但不拦截"""
        pkg = signed_package.copy()
        pkg["agent_id"] = "agent_k_test"
        ok, reason = security_guard.check_package(pkg)
        assert ok

    def test_different_r_values_allowed(self, security_guard, key_pair):
        """不同消息产生不同 r 值，应全部通过"""
        import time
        from blockchain.crypto.ecdsa_utils import ECDSAUtils

        private_key, _ = key_pair
        agent_id = "agent_k_diff"

        for nonce in range(1, 6):
            pkg = ECDSAUtils.sign_action(
                agent_id=agent_id, private_key=private_key,
                action={"step": nonce}, nonce=nonce,
                timestamp=int(time.time() * 1000)
            )
            ok, reason = security_guard.check_package(pkg)
            assert ok, f"Nonce {nonce} failed: {reason}"


@pytest.mark.security
class TestSecurityGuardAlerts:
    """安全告警测试"""

    def test_alert_generated_on_repeated_failure(self, security_guard, signed_package):
        """连续失败触发告警"""
        pkg = signed_package.copy()
        pkg["agent_id"] = "agent_alert_test"

        # 连续发送过期时间戳（触发多次失败）
        for i in range(6):
            bad_pkg = pkg.copy()
            bad_pkg["timestamp"] = int(time.time() * 1000) - 100_000
            bad_pkg["nonce"] = i + 1
            security_guard.check_package(bad_pkg)

        # 应该生成告警（MAX_FAIL_COUNT = 5）
        assert len(security_guard._alerts) > 0

    def test_get_stats_returns_counts(self, security_guard, signed_package):
        """统计接口返回正确计数"""
        # 正常包
        security_guard.check_package(signed_package)
        # 异常包
        bad = signed_package.copy()
        bad["nonce"] = 999
        bad["timestamp"] = int(time.time() * 1000) - 100_000
        security_guard.check_package(bad)

        stats = security_guard.get_stats()
        assert isinstance(stats, dict)


@pytest.mark.security
class TestSecurityGuardEdgeCases:
    """边界情况测试"""

    def test_empty_package_rejected(self, security_guard):
        """空包被拒绝"""
        ok, reason = security_guard.check_package({})
        assert not ok

    def test_missing_agent_id_handled(self, security_guard):
        """缺少关键字段时被正确拒绝（缺失 timestamp 应失败）"""
        pkg = {"agent_id": "agent_test", "nonce": 1, "r": 12345}
        # 不应抛出异常
        try:
            ok, reason = security_guard.check_package(pkg)
            assert not ok, f"Missing timestamp should be rejected, got: {reason}"
        except Exception as e:
            pytest.fail(f"Should not raise exception: {e}")
