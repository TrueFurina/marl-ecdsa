"""
密钥管理器测试
覆盖：密钥生成/加载、PEM持久化、缓存机制、损坏失败语义、公共接口
"""
import pytest
import sys
import tempfile
import shutil
sys.path.insert(0, '.')

from blockchain.crypto.key_manager import KeyManager


@pytest.fixture
def key_dir():
    """创建临时密钥目录"""
    d = tempfile.mkdtemp(prefix="test_keys_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def key_manager(key_dir):
    return KeyManager(key_dir=key_dir)


class TestKeyGeneration:
    """密钥生成"""

    def test_generate_new_key(self, key_manager):
        priv, pub = key_manager.generate_or_load("test_agent")
        assert priv is not None
        assert pub is not None

    def test_generate_returns_tuple(self, key_manager):
        result = key_manager.generate_or_load("test_agent")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_generate_creates_pem_files(self, key_manager, key_dir):
        from pathlib import Path
        key_manager.generate_or_load("test_agent")
        priv_path = Path(key_dir) / "test_agent_private.pem"
        pub_path = Path(key_dir) / "test_agent_public.pem"
        assert priv_path.exists()
        assert pub_path.exists()

    def test_generate_multiple_agents(self, key_manager):
        for i in range(3):
            priv, pub = key_manager.generate_or_load(f"agent_{i}")
            assert priv is not None


class TestKeyLoading:
    """密钥加载（缓存+磁盘）"""

    def test_load_from_cache(self, key_manager):
        # 第一次生成
        priv1, pub1 = key_manager.generate_or_load("cached_agent")
        # 第二次应从缓存加载
        priv2, pub2 = key_manager.generate_or_load("cached_agent")
        assert priv1 is priv2  # 同一个对象（缓存命中）

    def test_load_from_disk_after_restart(self, key_dir):
        from pathlib import Path
        km1 = KeyManager(key_dir=key_dir)
        km1.generate_or_load("persistent_agent")
        # 创建新实例（模拟重启）
        km2 = KeyManager(key_dir=key_dir)
        priv, pub = km2.generate_or_load("persistent_agent")
        assert priv is not None
        assert pub is not None

    def test_key_persistence_pem_format(self, key_manager, key_dir):
        from pathlib import Path
        key_manager.generate_or_load("format_agent")
        priv_bytes = (Path(key_dir) / "format_agent_private.pem").read_bytes()
        # PEM格式应以 -----BEGIN 开头
        assert b"BEGIN" in priv_bytes


class TestPublicKeyInterface:
    """公共接口"""

    def test_get_public_key(self, key_manager):
        key_manager.generate_or_load("pub_agent")
        pub = key_manager.get_public_key("pub_agent")
        assert pub is not None

    def test_get_public_key_hex(self, key_manager):
        key_manager.generate_or_load("hex_agent")
        hex_str = key_manager.get_public_key_hex("hex_agent")
        assert hex_str is not None
        assert len(hex_str) == 130  # 非压缩公钥: 04 + 64字节

    def test_get_private_key(self, key_manager):
        key_manager.generate_or_load("priv_agent")
        priv = key_manager.get_private_key("priv_agent")
        assert priv is not None

    def test_get_nonexistent_key(self, key_manager):
        assert key_manager.get_public_key("ghost") is None
        assert key_manager.get_public_key_hex("ghost") is None
        assert key_manager.get_private_key("ghost") is None


class TestKeyRemoval:
    """密钥删除"""

    def test_remove_key(self, key_manager, key_dir):
        from pathlib import Path
        key_manager.generate_or_load("removable_agent")
        result = key_manager.remove_key("removable_agent")
        assert result is True
        assert not (Path(key_dir) / "removable_agent_private.pem").exists()

    def test_remove_nonexistent_key(self, key_manager):
        result = key_manager.remove_key("ghost")
        assert result is False


class TestListAgents:
    """智能体列表"""

    def test_list_empty(self, key_manager):
        agents = key_manager.list_agents()
        assert isinstance(agents, list)

    def test_list_after_generation(self, key_manager):
        for i in range(3):
            key_manager.generate_or_load(f"listed_{i}")
        agents = key_manager.list_agents()
        assert len(agents) == 3


class TestCorruptedKeyRecovery:
    """损坏密钥的失败语义（fail-closed，不静默换钥）"""

    def test_corrupted_priv_key_fails_closed(self, key_dir):
        """私钥损坏 → 明确报错，绝不静默重新生成

        原用例名为 `..._regenerates`、docstring 写「新实例应能检测损坏并重新
        生成」，但既没有调用被测方法也没有任何断言——留下的是半成品。

        实测的真实行为（2026-11-04 探针）：抛 `ValueError`，且
          · 损坏的私钥文件不被改写（不留半成品）
          · 公钥文件不被改写（链上身份仍可读）
          · 重复调用仍以同样方式失败（不会第二次「自愈」）

        fail-closed 才是对的：静默重新生成会换掉密钥对，而公钥可能已上链，
        历史签名将全部失配，且用户不会知道自己被换了钥。
        """
        from pathlib import Path
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("corrupt_agent")
        priv_path = Path(key_dir) / "corrupt_agent_private.pem"
        pub_path = Path(key_dir) / "corrupt_agent_public.pem"
        pub_before = pub_path.read_bytes()

        priv_path.write_bytes(b"CORRUPTED_DATA")

        km2 = KeyManager(key_dir=key_dir)
        km2._key_cache.clear()          # 清除缓存强制重新从磁盘加载
        with pytest.raises(ValueError):
            km2.generate_or_load("corrupt_agent")

        # 失败必须干净：损坏的文件原样保留，供人工判断/恢复
        assert priv_path.read_bytes() == b"CORRUPTED_DATA"
        # 公钥不得被牵连改写
        assert pub_path.read_bytes() == pub_before
        assert km2.get_public_key("corrupt_agent") is not None
        # 幂等失败：再来一次还是 ValueError，而不是「第二次自愈」
        km3 = KeyManager(key_dir=key_dir)
        km3._key_cache.clear()
        with pytest.raises(ValueError):
            km3.generate_or_load("corrupt_agent")
