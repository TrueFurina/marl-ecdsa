"""SecurityGuard 类型混淆回归测试（2026-11-02）。

两个实测洞：

1. **r 直接当 dict 键**：`123` 与 `"123"` 是两个不同的键。攻击者只要把同一个 r
   换成字符串形式重发，就能绕过 k 重用检测——而 k 重用可直接推导私钥。
2. **时间戳/nonce 非整数时比较抛 TypeError**：`timestamp="x"` 会把守卫打成
   未捕获异常（DoS），而不是"拒绝这个包"。

修复口径：三个字段统一归一为整数，非整数一律 fail-closed。
"""
import time

import pytest

from blockchain.crypto.security_guard import SecurityGuard


def _pkg(nonce, r, ts=None, agent="agent-x"):
    return {
        "agent_id": agent,
        "timestamp": int(time.time() * 1000) if ts is None else ts,
        "nonce": nonce,
        "r": r,
        "signature_hex": "deadbeef",
    }


@pytest.mark.security
class TestRTypeConfusion:
    def test_string_r_detected_as_reuse(self):
        """同一个 r 的字符串形式必须仍被判定为 k 重用。"""
        g = SecurityGuard()
        assert g.check_package(_pkg(1, 123))[0] is True
        ok, reason = g.check_package(_pkg(2, "123"))
        assert ok is False, f"字符串形式绕过了 k 重用检测：{reason}"

    def test_float_r_rejected(self):
        """浮点数不是合法 r，应拒绝而不是截断成整数。"""
        g = SecurityGuard()
        assert g.check_package(_pkg(1, 123))[0] is True
        ok, _ = g.check_package(_pkg(2, 123.5))
        assert ok is False

    def test_bool_r_rejected(self):
        """bool 是 int 的子类，但不能当成合法 r。"""
        g = SecurityGuard()
        ok, _ = g.check_package(_pkg(1, True))
        assert ok is False


@pytest.mark.security
class TestMalformedFieldsFailClosed:
    def test_non_int_timestamp_rejected_not_crash(self):
        """非整数时间戳应被拒绝，而不是抛 TypeError 打崩守卫。"""
        g = SecurityGuard()
        ok, reason = g.check_package(_pkg(1, 1, ts="not-a-number"))
        assert ok is False and "时间戳" in reason

    def test_numeric_string_timestamp_accepted(self):
        """数字字符串形式的时间戳应被归一接受（不误伤合法包）。"""
        g = SecurityGuard()
        ok, reason = g.check_package(_pkg(1, 1, ts=str(int(time.time() * 1000))))
        assert ok is True, reason

    def test_non_int_nonce_rejected_not_crash(self):
        g = SecurityGuard()
        ok, reason = g.check_package(_pkg("abc", 1))
        assert ok is False and "nonce" in reason

    def test_string_nonce_detected_as_replay(self):
        """nonce 的数字字符串形式仍要参与单调性判断。"""
        g = SecurityGuard()
        assert g.check_package(_pkg(1, 1))[0] is True
        ok, reason = g.check_package(_pkg("1", 2))
        assert ok is False and "nonce" in reason
