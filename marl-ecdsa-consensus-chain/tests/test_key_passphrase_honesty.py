"""09-28 新增（全检 #4）：私钥口令解析的诚实性 + 密钥卫生分级的正确性

背景（务必读）：
- ``DEFAULT_KEY_PASSPHRASE`` 是**随源码公开的常量**。用它加密的私钥，任何
  拿到仓库的人都能解开（实测 keys/ 下 5 个"已加密"私钥全部可原样解出）。
  因此"加密形态"存在 ≠ "保密性"存在。
- 旧实现环境变量缺失时**静默**回退该公开默认，且 key_manager 日志照样打印
  "私钥已加密存储" → 虚假安全感。现在缺省回退会打 WARNING，并新增严格模式
  开关 MARL_ECDSA_REQUIRE_KEY_PASSPHRASE 供演示/生产 fail-closed。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from blockchain.crypto.ecdsa_utils import (
    DEFAULT_KEY_PASSPHRASE,
    REQUIRE_PASSPHRASE_ENV,
    ECDSAUtils,
    KeyPassphraseError,
    resolve_key_passphrase,
)

ROOT = Path(__file__).resolve().parent.parent
_AUDIT = ROOT / "scripts" / "audit_key_hygiene.py"


@pytest.fixture(scope="module")
def audit_mod():
    """按路径加载 scripts/audit_key_hygiene.py（scripts 不是包）。"""
    spec = importlib.util.spec_from_file_location("audit_key_hygiene", _AUDIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_key_hygiene"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("MARL_ECDSA_KEY_PASSPHRASE", REQUIRE_PASSPHRASE_ENV):
        monkeypatch.delenv(k, raising=False)


class TestResolveKeyPassphrase:
    def test_env_takes_priority(self, monkeypatch):
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "from_env")
        assert resolve_key_passphrase() == b"from_env"

    def test_default_fallback_emits_warning_not_silence(self, caplog):
        """核心：回退到公开默认时**必须**有告警，杜绝静默造成的虚假安全感"""
        with caplog.at_level("WARNING"):
            pw = resolve_key_passphrase()
        assert pw == DEFAULT_KEY_PASSPHRASE
        joined = caplog.text
        assert "MARL_ECDSA_KEY_PASSPHRASE" in joined
        # 告警必须点明"公开默认口令不具备保密性"
        assert ("公开" in joined) or ("不具备任何保密性" in joined)

    def test_strict_mode_raises_when_env_missing(self, monkeypatch):
        monkeypatch.setenv(REQUIRE_PASSPHRASE_ENV, "1")
        with pytest.raises(KeyPassphraseError) as ei:
            resolve_key_passphrase()
        assert "MARL_ECDSA_KEY_PASSPHRASE" in str(ei.value)

    def test_strict_mode_ok_when_env_present(self, monkeypatch):
        monkeypatch.setenv(REQUIRE_PASSPHRASE_ENV, "1")
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "strong")
        assert resolve_key_passphrase() == b"strong"

    @pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
    def test_strict_flag_aliases(self, monkeypatch, flag):
        monkeypatch.setenv(REQUIRE_PASSPHRASE_ENV, flag)
        with pytest.raises(KeyPassphraseError):
            resolve_key_passphrase()


class TestKeyHygieneClassification:
    def _key_pair(self):
        priv, pub = ECDSAUtils.generate_key_pair()
        return priv, ECDSAUtils.private_key_to_bytes(priv, None)

    def test_plaintext_pem_is_classified_plaintext(self, audit_mod):
        _, plain_pem = self._key_pair()
        assert b"ENCRYPTED PRIVATE KEY" not in plain_pem
        assert audit_mod.classify(plain_pem) == "PLAINTEXT"

    def test_default_passphrase_encryption_is_not_protected(self, audit_mod):
        """最关键的一条：用公开默认口令加密，**不得**被判为 PROTECTED

        这是全检 #4 的核心事实 —— 若这条断言失效，审计脚本就会重新变回
        那个"把加密形态当成保密性"的假水位来源。
        """
        priv, _ = self._key_pair()
        pem = ECDSAUtils.private_key_to_bytes(priv, DEFAULT_KEY_PASSPHRASE)
        assert b"ENCRYPTED PRIVATE KEY" in pem, "前提：形态上确实是加密 PEM"
        # 自证：默认口令确实能解开（这正是它不构成保密性的原因）
        ECDSAUtils.private_key_from_bytes(pem, DEFAULT_KEY_PASSPHRASE)
        assert audit_mod.classify(pem) == "DEFAULT_PASSPHRASE"
        assert audit_mod.classify(pem) != "PROTECTED"

    def test_env_passphrase_encryption_is_protected(self, audit_mod):
        priv, _ = self._key_pair()
        pem = ECDSAUtils.private_key_to_bytes(priv, b"a-real-secret-not-in-repo")
        assert audit_mod.classify(pem) == "PROTECTED"

    def test_default_cannot_decrypt_protected_key(self, audit_mod):
        priv, _ = self._key_pair()
        pem = ECDSAUtils.private_key_to_bytes(priv, b"a-real-secret-not-in-repo")
        with pytest.raises(Exception):
            ECDSAUtils.private_key_from_bytes(pem, DEFAULT_KEY_PASSPHRASE)
