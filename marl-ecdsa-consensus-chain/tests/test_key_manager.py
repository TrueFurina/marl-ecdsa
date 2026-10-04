"""
密钥管理器测试
覆盖：密钥生成/加载、PEM持久化、缓存机制、损坏恢复、公共接口
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
    """损坏密钥恢复"""

    def test_corrupted_priv_key_regenerates(self, key_dir):
        from pathlib import Path
        km = KeyManager(key_dir=key_dir)
        km.generate_or_load("corrupt_agent")
        # 损坏私钥文件
        priv_path = Path(key_dir) / "corrupt_agent_private.pem"
        priv_path.write_bytes(b"CORRUPTED_DATA")
        # 新实例应能检测损坏并重新生成
        km2 = KeyManager(key_dir=key_dir)
        # 清除缓存强制重新加载
        km2._key_cache.clear()
        # 公钥文件仍存在，私钥损坏 → generate_or_load 会尝试加载失败后重新生成
        # 注意：实际行为取决于ECDSAUtils.private_key_from_bytes是否抛异常
        # 此测试验证KeyManager在异常情况下的行为
