"""
KeyManager 边界测试（RalphLoop 原子任务 I）
覆盖：生成/加载、缓存、查询缺失、删除、列出、私钥隔离
通过标准：新增 ≥6 项测试全过
"""
import logging
import shutil
import tempfile

import pytest

from blockchain.crypto.key_manager import KeyManager

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def key_manager():
    key_dir = tempfile.mkdtemp(prefix="test_km_")
    km = KeyManager(key_dir=key_dir)
    yield km, key_dir
    shutil.rmtree(key_dir, ignore_errors=True)


class TestGenerateLoad:
    def test_generate_returns_pair(self, key_manager):
        km, _ = key_manager
        priv, pub = km.generate_or_load("agent_0")
        assert priv is not None
        assert pub is not None

    def test_generate_creates_pem_files(self, key_manager):
        km, key_dir = key_manager
        km.generate_or_load("agent_0")
        from pathlib import Path
        assert Path(key_dir, "agent_0_private.pem").exists()
        assert Path(key_dir, "agent_0_public.pem").exists()

    def test_load_existing_roundtrip(self, key_manager):
        km, _ = key_manager
        priv1, pub1 = km.generate_or_load("agent_0")
        # 新实例加载同一目录（缓存清空）→ 应加载而非重新生成
        km2 = KeyManager(key_dir=km.key_dir)
        priv2, pub2 = km2.generate_or_load("agent_0")
        assert priv1.private_numbers().private_value == priv2.private_numbers().private_value


class TestCache:
    def test_cache_hit_returns_same(self, key_manager):
        km, _ = key_manager
        km.generate_or_load("agent_0")
        priv, pub = km.generate_or_load("agent_0")
        assert km._key_cache["agent_0"][0] is priv  # 命中缓存，同一对象


class TestQueries:
    def test_get_public_key_hex(self, key_manager):
        km, _ = key_manager
        km.generate_or_load("agent_0")
        hex_str = km.get_public_key_hex("agent_0")
        assert hex_str is not None
        assert len(hex_str) > 0

    def test_get_public_key_missing_returns_none(self, key_manager):
        km, _ = key_manager
        assert km.get_public_key("ghost_agent") is None
        assert km.get_public_key_hex("ghost_agent") is None

    def test_get_private_key_missing_returns_none(self, key_manager):
        km, _ = key_manager
        assert km.get_private_key("ghost_agent") is None

    def test_get_private_key_after_generate(self, key_manager):
        km, _ = key_manager
        km.generate_or_load("agent_1")
        priv = km.get_private_key("agent_1")
        assert priv is not None


class TestRemoveAndList:
    def test_remove_key_existing(self, key_manager):
        km, key_dir = key_manager
        km.generate_or_load("agent_0")
        assert km.remove_key("agent_0") is True
        from pathlib import Path
        assert not Path(key_dir, "agent_0_private.pem").exists()

    def test_remove_key_missing_returns_false(self, key_manager):
        km, _ = key_manager
        assert km.remove_key("ghost_agent") is False

    def test_list_agents(self, key_manager):
        km, _ = key_manager
        km.generate_or_load("agent_0")
        km.generate_or_load("agent_1")
        agents = km.list_agents()
        assert "agent_0" in agents
        assert "agent_1" in agents

    def test_list_agents_empty_dir(self):
        key_dir = tempfile.mkdtemp(prefix="test_km_empty_")
        try:
            km = KeyManager(key_dir=key_dir)
            assert km.list_agents() == []
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)
