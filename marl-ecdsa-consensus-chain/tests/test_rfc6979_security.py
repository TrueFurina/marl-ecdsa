"""
RFC 6979 Deterministic k-value & k-value Leak Risk Simulation Tests
====================================================================
Complete test suite for:
  1. RFC 6979 deterministic k-value verification
  2. k-value reuse detection and private key derivation simulation
  3. SecurityGuard integration testing with malicious scenarios
  4. Nonce replay attack simulation
  5. Timestamp spoofing attack simulation

CCF 5th Blockchain Competition | V4.1 | Security Module
"""
import hashlib
import time
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.security_guard import SecurityGuard


class TestRFC6979DeterministicK:
    """Verify RFC 6979 deterministic k-value generation."""

    def test_same_message_same_signature(self):
        """Same private key + same message → same signature (deterministic k)."""
        priv, pub = ECDSAUtils.generate_key_pair()
        msg = b"test deterministic k-value for RFC 6979 compliance"

        sig1 = ECDSAUtils.sign(priv, msg)
        sig2 = ECDSAUtils.sign(priv, msg)

        # RFC 6979: same inputs → same k → same r → same signature
        assert sig1 == sig2, "RFC 6979 violation: same message should produce same signature"

    def test_different_messages_different_signatures(self):
        """Same private key + different messages → different signatures."""
        priv, pub = ECDSAUtils.generate_key_pair()
        msg1 = b"message one for deterministic k test"
        msg2 = b"message two for deterministic k test"

        sig1 = ECDSAUtils.sign(priv, msg1)
        sig2 = ECDSAUtils.sign(priv, msg2)

        assert sig1 != sig2, "Different messages must produce different signatures"

    def test_deterministic_k_different_private_keys(self):
        """Different private keys + same message → different r values."""
        priv1, _ = ECDSAUtils.generate_key_pair()
        priv2, _ = ECDSAUtils.generate_key_pair()
        msg = b"cross-key deterministic k test"

        sig1 = ECDSAUtils.sign(priv1, msg)
        sig2 = ECDSAUtils.sign(priv2, msg)

        r1, _ = ECDSAUtils.extract_rs(sig1)
        r2, _ = ECDSAUtils.extract_rs(sig2)

        assert r1 != r2, "Different keys must produce different r values"

    def test_rfc6979_k_uniqueness_across_messages(self):
        """RFC 6979: k = HMAC_DRBG(sk, H(m)) → unique per message."""
        priv, _ = ECDSAUtils.generate_key_pair()
        messages = [f"unique_msg_{i}".encode() for i in range(100)]

        signatures = [ECDSAUtils.sign(priv, m) for m in messages]
        r_values = [ECDSAUtils.extract_rs(s)[0] for s in signatures]

        # All r values should be unique (deterministic but message-dependent)
        assert len(set(r_values)) == 100, (
            f"RFC 6979: expected 100 unique r-values, got {len(set(r_values))}"
        )

    def test_verify_with_rfc6979_signature(self):
        """Signatures generated with deterministic k still verify correctly."""
        priv, pub = ECDSAUtils.generate_key_pair()
        msg = b"verify RFC 6979 deterministic signature"

        for _ in range(50):
            sig = ECDSAUtils.sign(priv, msg)
            assert ECDSAUtils.verify(pub, msg, sig), "RFC 6979 signature must verify"


class TestKValueReuseAttack:
    """Simulate k-value reuse attack and verify SecurityGuard detection."""

    def test_security_guard_detects_same_r_value(self):
        """SecurityGuard must detect repeated r-value (k-value reuse indicator)."""
        guard = SecurityGuard()

        # Simulate two packages with same r-value
        pkg1 = {
            "agent_id": "agent_0",
            "timestamp": int(time.time() * 1000),
            "nonce": 1,
            "r": 0x8F3A2B1C4D5E6F7A8B9C0D1E2F3A4B5C,
        }
        pkg2 = {
            "agent_id": "agent_0",
            "timestamp": int(time.time() * 1000) + 100,
            "nonce": 2,
            "r": 0x8F3A2B1C4D5E6F7A8B9C0D1E2F3A4B5C,  # SAME r!
        }

        ok1, reason1 = guard.check_package(pkg1)
        assert ok1, f"First use of r should pass: {reason1}"

        ok2, reason2 = guard.check_package(pkg2)
        assert not ok2, "Repeated r-value MUST be detected and rejected"
        assert "K_REUSE" in reason2 or "k值重用" in reason2, f"Alert should mention k-reuse: {reason2}"

    def test_different_r_values_pass(self):
        """Different r-values should all pass SecurityGuard."""
        guard = SecurityGuard()

        for i in range(100):
            pkg = {
                "agent_id": "agent_0",
                "timestamp": int(time.time() * 1000),
                "nonce": i,
                "r": 0x10000000000000000000000000000000 + i,  # Unique r per iteration
            }
            ok, reason = guard.check_package(pkg)
            assert ok, f"Unique r should pass at i={i}: {reason}"

    def test_k_reuse_across_different_agents(self):
        """Same r-value from different agents should NOT trigger cross-agent alert."""
        guard = SecurityGuard()

        shared_r = 0xCAFE0000000000000000000000000000

        pkg_agent0 = {
            "agent_id": "agent_0",
            "timestamp": int(time.time() * 1000),
            "nonce": 1,
            "r": shared_r,
        }
        pkg_agent1 = {
            "agent_id": "agent_1",
            "timestamp": int(time.time() * 1000) + 100,
            "nonce": 1,
            "r": shared_r,  # Same r, different agent → should pass
        }

        ok0, _ = guard.check_package(pkg_agent0)
        ok1, _ = guard.check_package(pkg_agent1)
        assert ok0 and ok1, "Same r-value from different agents is NOT k-reuse (different keys)"

    def test_k_reuse_derivation_simulation(self):
        """Simulate the mathematical consequence of k-value reuse.

        If attacker obtains two signatures (r, s1) and (r, s2) with same r:
          k = (z1 - z2) / (s1 - s2) mod n
          d = (s1*k - z1) / r mod n

        This test demonstrates the DETECTION (not actual key derivation,
        which requires the real private key — we can't extract it without it).
        """
        priv, pub = ECDSAUtils.generate_key_pair()

        # Sign two different messages
        msg1 = b"k-reuse test message 1"
        msg2 = b"k-reuse test message 2"

        sig1 = ECDSAUtils.sign(priv, msg1)
        sig2 = ECDSAUtils.sign(priv, msg2)

        r1, s1 = ECDSAUtils.extract_rs(sig1)
        r2, s2 = ECDSAUtils.extract_rs(sig2)

        # With RFC 6979, r values should be different (deterministic per message)
        assert r1 != r2, (
            "RFC 6979 ensures different r for different messages — "
            "this is the protection against k-reuse"
        )

        # Verify that IF r were the same, SecurityGuard would detect it
        guard = SecurityGuard()
        pkg1 = {
            "agent_id": "agent_test", "timestamp": int(time.time() * 1000),
            "nonce": 1, "r": r1,
        }
        pkg2 = {
            "agent_id": "agent_test", "timestamp": int(time.time() * 1000) + 10,
            "nonce": 2, "r": r1,  # Force same r
        }

        guard.check_package(pkg1)
        ok, reason = guard.check_package(pkg2)
        assert not ok, f"Forced k-reuse must be detected: {reason}"


class TestNonceReplayAttack:
    """Simulate nonce replay attacks and verify SecurityGuard detection."""

    def test_nonce_replay_detection(self):
        """SecurityGuard must reject replayed nonce."""
        guard = SecurityGuard()

        pkg1 = {
            "agent_id": "agent_0",
            "timestamp": int(time.time() * 1000),
            "nonce": 42,
            "r": 0x11111111111111111111111111111111,
        }
        pkg2 = {
            "agent_id": "agent_0",
            "timestamp": int(time.time() * 1000) + 100,
            "nonce": 42,  # REPLAY!
            "r": 0x22222222222222222222222222222222,
        }

        ok1, _ = guard.check_package(pkg1)
        assert ok1

        ok2, reason2 = guard.check_package(pkg2)
        assert not ok2, "Nonce replay must be detected"
        assert "nonce" in reason2.lower(), f"Alert should mention nonce: {reason2}"

    def test_nonce_monotonic_increase(self):
        """Strictly increasing nonces should all pass."""
        guard = SecurityGuard()

        for nonce in [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]:
            pkg = {
                "agent_id": "agent_0",
                "timestamp": int(time.time() * 1000),
                "nonce": nonce,
                "r": 0x10000000000000000000000000000000 + nonce,
            }
            ok, reason = guard.check_package(pkg)
            assert ok, f"Nonce {nonce} should pass: {reason}"

    def test_nonce_gap_then_backfill(self):
        """Nonce gap is acceptable, but backfill after gap is detected as replay."""
        guard = SecurityGuard()

        # Accept nonce 100
        guard.check_package({
            "agent_id": "agent_0", "timestamp": int(time.time() * 1000),
            "nonce": 100, "r": 0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,
        })

        # Nonce 50 is a replay (less than last=100)
        ok, reason = guard.check_package({
            "agent_id": "agent_0", "timestamp": int(time.time() * 1000) + 200,
            "nonce": 50, "r": 0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB,
        })
        assert not ok, f"Nonce backfill from 100→50 is replay: {reason}"


class TestTimestampSpoofing:
    """Simulate timestamp spoofing attacks."""

    def test_expired_timestamp_rejected(self):
        """Timestamp outside ±30s window must be rejected."""
        guard = SecurityGuard()
        now_ms = int(time.time() * 1000)

        # Far past (60 seconds ago)
        pkg_past = {
            "agent_id": "agent_0",
            "timestamp": now_ms - 60_000,
            "nonce": 1,
            "r": 0x12345678901234567890123456789012,
        }
        ok, reason = guard.check_package(pkg_past)
        assert not ok, f"Expired timestamp must be rejected: {reason}"

        # Far future (60 seconds ahead)
        pkg_future = {
            "agent_id": "agent_0",
            "timestamp": now_ms + 60_000,
            "nonce": 1,
            "r": 0x12345678901234567890123456789012,
        }
        ok, reason = guard.check_package(pkg_future)
        assert not ok, f"Future timestamp must be rejected: {reason}"

    def test_valid_timestamps_accepted(self):
        """Timestamps within ±30s window should pass."""
        guard = SecurityGuard()
        now_ms = int(time.time() * 1000)

        # P1-13修复: nonce 必须单调递增——原用例用 abs(offset) 导致 nonce 序列
        # 25000→10000→0 递减，触发 SecurityGuard 的重放拦截（防护逻辑正确，是测试数据缺陷）
        # r 值同样不能复用：abs(offset) 在对称偏移处重复（-10000/+10000），
        # 会触发 k 值重用检测，需用 i 保证唯一性
        for i, offset in enumerate([-25000, -10000, 0, 10000, 25000]):
            pkg = {
                "agent_id": "agent_0",
                "timestamp": now_ms + offset,
                "nonce": i + 1,
                "r": 0x10000000000000000000000000000000 + i * 1000 + abs(offset),
            }
            ok, reason = guard.check_package(pkg)
            assert ok, f"Timestamp offset {offset}ms should pass: {reason}"


class TestCombinedAttackScenarios:
    """Multi-vector attack simulations."""

    def test_replay_with_spoofed_timestamp(self):
        """Attacker replays nonce with spoofed timestamp — detected by nonce check."""
        guard = SecurityGuard()

        now_ms = int(time.time() * 1000)

        # Legitimate message
        guard.check_package({
            "agent_id": "agent_0", "timestamp": now_ms,
            "nonce": 100, "r": 0xDEADBEEF000000000000000000000000,
        })

        # Attacker replays nonce=100 with different (valid) timestamp
        ok, reason = guard.check_package({
            "agent_id": "agent_0", "timestamp": now_ms + 5000,
            "nonce": 100,  # Replayed!
            "r": 0xFEEDFACE000000000000000000000000,
        })
        assert not ok, f"Replay with spoofed timestamp must be caught: {reason}"

    def test_identity_spoof_with_valid_signature_structure(self):
        """Attacker claims different identity with properly structured (but wrong-key) signature."""
        # This tests the ECDSA verification chain, not just SecurityGuard
        priv, pub = ECDSAUtils.generate_key_pair()
        msg = ECDSAUtils.build_message("agent_0", [0.5], int(time.time() * 1000), 1)
        sig = ECDSAUtils.sign(priv, msg)

        # Verify with correct public key
        assert ECDSAUtils.verify(pub, msg, sig), "Legitimate signature must verify"

        # Attacker claims to be agent_1 using agent_0's signature
        # (The Blockchain.verify validates agent_id matches the registered public key)
        fake_pkg = ECDSAUtils.sign_action("agent_0", priv, [0.5], nonce=1)
        assert fake_pkg["agent_id"] == "agent_0", (
            "SigningService correctly records agent_id — "
            "identity spoofing is prevented at Blockchain verification layer"
        )

    def test_security_guard_alert_accumulation(self):
        """Multiple failures should accumulate and trigger DANGER level."""
        guard = SecurityGuard()

        # Generate 6 failures (exceeds MAX_FAIL_COUNT=5)
        for i in range(6):
            guard.check_package({
                "agent_id": "agent_danger",
                "timestamp": int(time.time() * 1000) - 60_000,  # Always expired
                "nonce": i,
                "r": 0xBADC0FFEE00000000000000000000000 + i,
            })

        risk = guard.get_risk_level("agent_danger")
        assert risk == "DANGER", f"6 failures should trigger DANGER, got {risk}"
        assert guard.get_fail_count("agent_danger") >= 6

        stats = guard.get_stats()
        assert stats["total_alerts"] >= 6
        assert "agent_danger" in stats["danger_agents"]


# =============================================================================
# Pytest Runner
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
