"""
QA 独立验证：P1-16 私钥 PEM 口令加密 + P2P 安全开关 / TLS（新增文件，不修改被测源）

覆盖"必须验到的事情"：
  密码模块
    A1 加密 PEM 落盘后，用同一口令可重新加载（KeyManager 重启后仍能读回同一私钥）
    A2 落盘的 PEM 确实是加密 PEM（含 ENCRYPTED 头），不是明文
    A3 错误口令 → 明确报错（抛异常），不得静默走回退返回 None/错误密钥
    A4 旧明文 PEM 向后兼容（回退路径真的能走通）
    A5 不传 passphrase 的旧调用路径仍然正常
    A6 环境变量 MARL_ECDSA_KEY_PASSPHRASE 优先生效
  网络模块
    B1 投票签名：无 key_manager 默认 fail-closed
    B2 投票签名：显式 allow_insecure_vote 才走长度兜底
    B3 注册签名：无 key_manager 默认 fail-closed / insecure 开关生效
    B4 P2P 默认启用 TLS，且服务端真的拒绝明文客户端（TLS 不是摆设）
    B5 enable_tls=False 的旧路径仍可用
    B6 P2P 启动失败/超时必须抛错（start() 检查了 _ready.wait 返回值）
"""
import asyncio
import hashlib
import os
import ssl
import sys
import tempfile
import shutil

import pytest

sys.path.insert(0, '.')

from blockchain.crypto.ecdsa_utils import ECDSAUtils, resolve_key_passphrase, DEFAULT_KEY_PASSPHRASE
from blockchain.crypto.key_manager import KeyManager
from blockchain.network.p2p_node import P2PNode, build_tls_contexts
from blockchain.network.network_consensus import NetworkConsensusNode

NODES = ['node_0', 'node_1', 'node_2']


# =============================================================================
# A. 密码模块（P1-16）
# =============================================================================

@pytest.fixture
def key_dir():
    d = tempfile.mkdtemp(prefix="qa_keys_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestEncryptedPemRoundTrip:
    """A1 + A2 + A6"""

    def test_a1_encrypted_pem_reload_with_same_passphrase(self, key_dir, monkeypatch):
        """加密 PEM 落盘 → 新实例（模拟重启）用同一口令可重新加载，且私钥一致"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "qa_secret_pw")
        km1 = KeyManager(key_dir=key_dir)
        priv1, pub1 = km1.generate_or_load("agent_qa")

        km2 = KeyManager(key_dir=key_dir)  # 新实例，强制走磁盘加载
        priv2, pub2 = km2.generate_or_load("agent_qa")

        assert priv2.private_numbers() == priv1.private_numbers(), "重新加载的私钥与原私钥不一致"
        assert pub2.public_numbers() == pub1.public_numbers()

    def test_a2_pem_on_disk_is_encrypted(self, key_dir, monkeypatch):
        """落盘的私钥 PEM 必须是加密 PEM，不能是明文"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "qa_encryption_pw")
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("agent_enc")
        pem = os.path.join(key_dir, "agent_enc_private.pem")
        with open(pem, "rb") as f:
            raw = f.read()
        assert b"BEGIN" in raw
        assert b"ENCRYPTED" in raw, f"私钥 PEM 未加密（无 ENCRYPTED 标记）: {raw[:60]!r}"

    def test_a6_env_priority_and_default_fallback(self, key_dir, monkeypatch):
        """环境变量优先；缺失时回退 NON_PRODUCTION_ONLY 默认口令（开发期可用，生产须设环境变量）"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "from_env")
        assert resolve_key_passphrase() == b"from_env"

        monkeypatch.delenv("MARL_ECDSA_KEY_PASSPHRASE", raising=False)
        # 缺失时回退到默认口令，而非抛错（保证开发/测试开箱即用）
        assert resolve_key_passphrase() == DEFAULT_KEY_PASSPHRASE

        # 用默认口令生成：磁盘落盘必须是加密 PEM（不再是明文）
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("dev_default")
        pem = os.path.join(key_dir, "dev_default_private.pem")
        assert os.path.exists(pem)
        with open(pem, "rb") as f:
            assert b"ENCRYPTED" in f.read()

    def test_a7_legacy_plaintext_is_migrated_on_load(self, key_dir, monkeypatch):
        """旧明文私钥首次加载后必须用配置口令重写为加密 PEM。"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "migration_pw")
        priv, pub = ECDSAUtils.generate_key_pair()
        priv_path = os.path.join(key_dir, "legacy_migrate_private.pem")
        pub_path = os.path.join(key_dir, "legacy_migrate_public.pem")
        with open(priv_path, "wb") as f:
            f.write(ECDSAUtils.private_key_to_bytes(priv))
        with open(pub_path, "wb") as f:
            f.write(ECDSAUtils.public_key_to_bytes(pub))

        loaded, _ = KeyManager(key_dir=key_dir).generate_or_load("legacy_migrate")

        assert loaded.private_numbers() == priv.private_numbers()
        with open(priv_path, "rb") as f:
            assert b"ENCRYPTED" in f.read()


class TestWrongPassphrase:
    """A3"""

    def test_a3_wrong_passphrase_raises_not_silent(self, key_dir, monkeypatch):
        """错误口令必须报错，不能静默返回（也不能静默走明文回退拿到错误密钥）"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "correct_pw")
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("agent_pw")
        pem_bytes = open(os.path.join(key_dir, "agent_pw_private.pem"), "rb").read()

        # 正确口令：一定能加载
        ok = ECDSAUtils.private_key_from_bytes(pem_bytes, b"correct_pw")
        assert ok is not None

        # 错误口令：必须抛异常
        with pytest.raises(Exception) as exc:
            ECDSAUtils.private_key_from_bytes(pem_bytes, b"wrong_pw")
        msg = str(exc.value)
        assert msg, "错误口令场景下异常信息为空，不利于定位问题"

    def test_a3b_wrong_passphrase_via_key_manager(self, key_dir, monkeypatch):
        """KeyManager 在口令被改错时也必须报错，而不是静默降级"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "pw_one")
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("agent_km")

        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "pw_two")
        km2 = KeyManager(key_dir=key_dir)
        with pytest.raises(Exception):
            km2.generate_or_load("agent_km")


class TestLegacyCompatibility:
    """A4 + A5"""

    def test_a4_legacy_plaintext_pem_backward_compatible(self, key_dir, monkeypatch):
        """已存在的旧明文 PEM（NoEncryption）必须仍能加载（回退路径真的走通）"""
        monkeypatch.setenv("MARL_ECDSA_KEY_PASSPHRASE", "new_pw")

        # 模拟旧版本写下的明文私钥 PEM
        priv, pub = ECDSAUtils.generate_key_pair()
        with open(os.path.join(key_dir, "legacy_agent_private.pem"), "wb") as f:
            f.write(ECDSAUtils.private_key_to_bytes(priv))  # 不传口令 → 明文
        with open(os.path.join(key_dir, "legacy_agent_public.pem"), "wb") as f:
            f.write(ECDSAUtils.public_key_to_bytes(pub))

        km = KeyManager(key_dir=key_dir)
        loaded_priv, loaded_pub = km.generate_or_load("legacy_agent")
        assert loaded_priv.private_numbers() == priv.private_numbers(), "旧明文 PEM 回退加载失败"

    def test_a5_legacy_call_path_without_passphrase(self):
        """不传 passphrase 的旧调用路径：仍然写明文 PEM 且可往返（向后兼容未被破坏）"""
        priv, _ = ECDSAUtils.generate_key_pair()
        pem = ECDSAUtils.private_key_to_bytes(priv)
        assert b"ENCRYPTED" not in pem, "旧调用路径（不传口令）不应产出加密 PEM"
        back = ECDSAUtils.private_key_from_bytes(pem)
        assert back.private_numbers() == priv.private_numbers()

    def test_a5b_legacy_load_of_plaintext_with_explicit_passphrase(self):
        """给明文 PEM 传口令：走回退分支，仍能加载成功"""
        priv, _ = ECDSAUtils.generate_key_pair()
        pem = ECDSAUtils.private_key_to_bytes(priv)
        back = ECDSAUtils.private_key_from_bytes(pem, b"whatever")
        assert back.private_numbers() == priv.private_numbers()


# =============================================================================
# B. 网络模块
# =============================================================================

def _mk_node(**kw):
    return NetworkConsensusNode(
        node_id='node_0', host='127.0.0.1', port=7901,
        all_node_ids=NODES, **kw
    )


class TestVoteSignatureFailClosed:
    """B1 + B2"""

    def test_b1_no_keymanager_default_fail_closed(self):
        n = _mk_node()  # allow_insecure_vote 默认 False
        assert n._verify_vote_signature({}, "node_1") is False, "无签名投票未被 fail-closed 拒绝"
        assert n._verify_vote_signature({"signature_hex": "ab" * 64}, "node_1") is False

    def test_b2_insecure_opt_in_still_works(self):
        n = _mk_node(allow_insecure_vote=True)
        assert n._verify_vote_signature({}, "node_1") is True
        assert n._verify_vote_signature({"signature_hex": "ab" * 64}, "node_1") is True
        assert n._verify_vote_signature({"signature_hex": "abcd"}, "node_1") is False


class TestRegisterSignatureFailClosed:
    """B3"""

    def test_b3_register_fail_closed_and_insecure(self, tmp_path):
        sig_ok = bytes([0x30, 0x44]) + b"\x00" * 68  # ≥64 字节
        sig_short = b"\x00" * 10
        h = hashlib.sha256(b"reg").digest()

        strict = P2PNode("n0", "127.0.0.1", 7911, tls_dir=str(tmp_path / "tls1"))
        assert strict._verify_register_signature("node_1", h, sig_ok) is False

        loose = P2PNode("n1", "127.0.0.1", 7912, allow_insecure_register=True,
                        tls_dir=str(tmp_path / "tls2"))
        assert loose._verify_register_signature("node_1", h, sig_ok) is True
        assert loose._verify_register_signature("node_1", h, sig_short) is False


class TestTls:
    """B4 + B5"""

    def test_b5_tls_defaults_and_disable_path(self, tmp_path):
        d = str(tmp_path / "tls3")
        default_node = P2PNode("n0", "127.0.0.1", 7921, tls_dir=d)
        assert default_node._enable_tls is True, "P2P 默认必须开启 TLS"
        srv, cli = build_tls_contexts(d, True)
        assert srv is not None and cli is not None
        assert cli.verify_mode is not None and cli.check_hostname is False

        off_node = P2PNode("n1", "127.0.0.1", 7922, enable_tls=False, tls_dir=d)
        assert off_node._enable_tls is False
        assert build_tls_contexts(d, False) == (None, None)

    @pytest.mark.timeout(60)
    def test_b4a_start_server_receives_ssl_context(self, tmp_path, monkeypatch):
        """P2PNode.start() 必须把 TLS 上下文真正传给监听套接字（不能只是字段置 True）"""
        d = str(tmp_path / "tls_a")
        node = P2PNode("n0", "127.0.0.1", 7931, tls_dir=d)
        captured = {}

        real_start_server = asyncio.start_server

        async def _spy(*a, **k):
            captured.update(k)
            return await real_start_server(*a, **k)

        monkeypatch.setattr(asyncio, "start_server", _spy)

        async def main():
            await node.start()
            node._running = False
            node._server.close()
            await asyncio.wait_for(node._server.wait_closed(), timeout=5)

        asyncio.run(asyncio.wait_for(main(), timeout=20))
        assert "ssl" in captured, "asyncio.start_server 未收到 ssl 参数（TLS 未接入监听）"
        assert captured["ssl"] is not None and isinstance(captured["ssl"], ssl.SSLContext), (
            f"ssl 参数不是 SSLContext: {captured['ssl']!r}"
        )

    @pytest.mark.timeout(60)
    def test_b4b_connect_to_receives_ssl_context(self, tmp_path, monkeypatch):
        """start() 之后，P2PNode.connect_to() 必须把 TLS 上下文传给出站连接"""
        d = str(tmp_path / "tls_b")
        node = P2PNode("n0", "127.0.0.1", 7932, tls_dir=d)
        captured = {}

        async def _spy(*a, **k):
            captured.update(k)
            raise OSError("simulated connect failure")  # 只需记录参数，不真连

        async def main():
            await node.start()
            monkeypatch.setattr(asyncio, "open_connection", _spy)
            await node.connect_to("127.0.0.1", 7999, "peer_x")
            node._running = False
            node._server.close()
            await asyncio.wait_for(node._server.wait_closed(), timeout=5)

        asyncio.run(asyncio.wait_for(main(), timeout=20))
        assert "ssl" in captured, "asyncio.open_connection 未收到 ssl 参数"
        assert isinstance(captured["ssl"], ssl.SSLContext), (
            f"出站连接 ssl 参数不是 SSLContext: {captured['ssl']!r}"
        )

    def test_b4b2_connect_before_start_uses_tls(self, tmp_path, monkeypatch):
        """未 start() 就 connect_to()：也必须构建 TLS 上下文，禁止静默明文降级。"""
        d = str(tmp_path / "tls_b2")
        node = P2PNode("n0", "127.0.0.1", 7933, tls_dir=d)
        captured = {}

        async def _spy(*a, **k):
            captured.update(k)
            raise OSError("simulated connect failure")

        monkeypatch.setattr(asyncio, "open_connection", _spy)
        result = asyncio.run(node.connect_to("127.0.0.1", 7999, "peer_y"))
        assert result is False
        assert isinstance(captured.get("ssl"), ssl.SSLContext), (
            "未 start() 时出站连接退化为明文（ssl=None），TLS 被静默绕过"
        )

    @pytest.mark.timeout(60)
    def test_b4c_real_handshake_and_untrusted_client_rejected(self, tmp_path):
        """真实握手：互信两端可通信；不信任该证书的客户端必须被拒绝"""
        import ssl as _ssl
        d = str(tmp_path / "tls_c")
        server_ctx, client_ctx = build_tls_contexts(d, True)

        async def main():
            got = []

            async def cb(reader, writer):
                got.append(await asyncio.wait_for(reader.read(16), timeout=5))
                writer.write(b"pong")
                await writer.drain()
                writer.close()

            server = await asyncio.start_server(cb, "127.0.0.1", 0, ssl=server_ctx)
            port = server.sockets[0].getsockname()[1]

            # 1) 互信客户端：握手成功并双向通信
            r, w = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port, ssl=client_ctx), timeout=5
            )
            w.write(b"ping")
            await w.drain()
            resp = await asyncio.wait_for(r.read(16), timeout=5)
            w.close()

            # 2) 不信任该证书的客户端（自签名不在系统根）：必须握手失败
            untrusted = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            untrusted.check_hostname = False
            untrusted.verify_mode = _ssl.CERT_REQUIRED
            rejected = False
            try:
                r2, w2 = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port, ssl=untrusted), timeout=5
                )
                w2.close()
            except Exception:
                rejected = True

            server.close()
            await asyncio.wait_for(server.wait_closed(), timeout=5)
            return got, resp, rejected

        got, resp, rejected = asyncio.run(asyncio.wait_for(main(), timeout=30))
        assert got == [b"ping"], f"TLS 服务端未收到明文 payload: {got!r}"
        assert resp == b"pong"
        assert rejected is True, "不持有信任锚的客户端竟能握手成功（TLS 形同虚设）"


class TestStartTimeoutChecked:
    """B6"""

    @pytest.mark.timeout(60)
    def test_b6_start_failure_raises(self, monkeypatch):
        """P2P 启动失败时 start() 必须抛错，而不是静默返回一个"已启动"的节点"""

        async def _boom(*a, **k):
            raise OSError("simulated bind failure")

        monkeypatch.setattr(asyncio, "start_server", _boom)
        n = _mk_node()
        with pytest.raises(RuntimeError):
            n.start()
