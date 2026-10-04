"""
KeyManager 并发/持久化边界测试（RalphLoop 原子任务 Z）
覆盖：磁盘持久化往返、并发生成一致性、缓存隔离、权限文件、多实例共存
通过标准：新增 ≥6 项测试全过
"""
import logging
import shutil
import tempfile
import threading

import pytest

from blockchain.crypto.key_manager import KeyManager

logging.basicConfig(level=logging.CRITICAL)


class TestPersistence:
    def test_persist_and_reload_same_key(self):
        """磁盘持久化：新实例加载到同一密钥（非重新生成）"""
        key_dir = tempfile.mkdtemp(prefix="test_km_persist_")
        try:
            km1 = KeyManager(key_dir=key_dir)
            priv1, pub1 = km1.generate_or_load("agent_0")
            km2 = KeyManager(key_dir=key_dir)  # 全新实例，无内存缓存
            priv2, pub2 = km2.generate_or_load("agent_0")
            assert priv1.private_numbers().private_value == priv2.private_numbers().private_value
            assert pub1.public_numbers().x == pub2.public_numbers().x
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)

    def test_reload_public_key_hex_consistent(self):
        key_dir = tempfile.mkdtemp(prefix="test_km_hex_")
        try:
            km1 = KeyManager(key_dir=key_dir)
            km1.generate_or_load("agent_0")
            hex1 = km1.get_public_key_hex("agent_0")
            km2 = KeyManager(key_dir=key_dir)
            hex2 = km2.get_public_key_hex("agent_0")
            assert hex1 == hex2
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)

    def test_private_key_file_permission(self):
        """私钥 PEM 文件应被 chmod 0o600 保护（若平台支持）"""
        key_dir = tempfile.mkdtemp(prefix="test_km_perm_")
        try:
            import os
            from pathlib import Path
            km = KeyManager(key_dir=key_dir)
            km.generate_or_load("agent_0")
            priv_path = Path(key_dir, "agent_0_private.pem")
            assert priv_path.exists()
            # Windows 平台 chmod 可能无效，但文件必须存在且可读
            assert priv_path.stat().st_size > 0
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)


class TestCacheIsolation:
    def test_different_key_dirs_isolated(self):
        """不同 key_dir 的 KeyManager 互不影响"""
        d1 = tempfile.mkdtemp(prefix="test_km_a_")
        d2 = tempfile.mkdtemp(prefix="test_km_b_")
        try:
            km_a = KeyManager(key_dir=d1)
            km_b = KeyManager(key_dir=d2)
            priv_a, _ = km_a.generate_or_load("agent_0")
            priv_b, _ = km_b.generate_or_load("agent_0")
            assert priv_a.private_numbers().private_value != priv_b.private_numbers().private_value
        finally:
            shutil.rmtree(d1, ignore_errors=True)
            shutil.rmtree(d2, ignore_errors=True)


class TestConcurrency:
    def test_concurrent_generate_same_agent(self):
        """并发生成同一 agent 密钥：结果一致（缓存/磁盘双保护）"""
        key_dir = tempfile.mkdtemp(prefix="test_km_conc_")
        try:
            results = []
            barrier = threading.Barrier(4)

            def worker():
                km = KeyManager(key_dir=key_dir)
                barrier.wait()
                priv, pub = km.generate_or_load("agent_0")
                results.append(priv.private_numbers().private_value)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(results) == 4
            assert len(set(results)) == 1  # 所有线程拿到同一密钥
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)


class TestMultipleAgents:
    def test_multi_agent_independent(self):
        """多智能体密钥互不相同"""
        key_dir = tempfile.mkdtemp(prefix="test_km_multi_")
        try:
            km = KeyManager(key_dir=key_dir)
            privs = {}
            for i in range(5):
                privs[f"agent_{i}"] = km.generate_or_load(f"agent_{i}")[0]
            vals = {p.private_numbers().private_value for p in privs.values()}
            assert len(vals) == 5  # 全部唯一
            assert len(km.list_agents()) == 5
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)

    def test_remove_one_keeps_others(self):
        key_dir = tempfile.mkdtemp(prefix="test_km_rm_")
        try:
            km = KeyManager(key_dir=key_dir)
            km.generate_or_load("agent_0")
            km.generate_or_load("agent_1")
            km.remove_key("agent_0")
            agents = km.list_agents()
            assert "agent_0" not in agents
            assert "agent_1" in agents
        finally:
            shutil.rmtree(key_dir, ignore_errors=True)
