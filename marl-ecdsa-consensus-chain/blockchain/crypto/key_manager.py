"""
密钥管理器
负责智能体本地密钥对的生成、持久化存储、加载
私钥仅存储于本地，绝不上链传输
"""
import os
import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Tuple

from cryptography.hazmat.primitives.asymmetric import ec

from .ecdsa_utils import ECDSAUtils, resolve_key_passphrase

logger = logging.getLogger(__name__)


class KeyManager:
    """
    智能体密钥管理器
    - 本地生成并安全存储密钥对
    - 按 agent_id 索引，支持多智能体
    - 仅暴露公钥用于链上注册，私钥绝不离开本地
    """

    # P3-2修复: 类级锁保护 generate_or_load 的"检查-生成-缓存"临界区。
    # 多实例/多线程并发生成同一 agent 密钥时，若不加锁会各自 miss 缓存、
    # 各自生成新密钥并写文件竞态（最后写入者赢），导致不同调用方拿到不同密钥。
    _init_lock = threading.Lock()

    def __init__(self, key_dir: str = "./keys"):
        self.key_dir = Path(key_dir)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self._key_cache: Dict[str, Tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]] = {}

    # -------------------------------------------------------------------------
    # 核心接口
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_and_migrate_private_key(
        priv_path: Path,
    ) -> ec.EllipticCurvePrivateKey:
        """加载私钥，并将旧明文 PEM 原地迁移为口令加密 PEM。"""
        passphrase = resolve_key_passphrase()
        pem_bytes = priv_path.read_bytes()
        private_key = ECDSAUtils.private_key_from_bytes(pem_bytes, passphrase)
        if b"ENCRYPTED PRIVATE KEY" not in pem_bytes:
            priv_path.write_bytes(
                ECDSAUtils.private_key_to_bytes(private_key, passphrase)
            )
            try:
                os.chmod(str(priv_path), 0o600)
            except (OSError, AttributeError):
                logger.debug(
                    "[KeyManager] os.chmod(0o600) 在当前平台不可用或失败，跳过"
                )
            logger.warning(
                f"[KeyManager] 已将 {priv_path.name} 从旧明文 PEM 迁移为加密 PEM"
            )
        return private_key

    def generate_or_load(self, agent_id: str) -> Tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
        """
        为指定智能体生成或加载密钥对
        如果本地已有密钥文件则加载，否则生成新密钥对并保存
        线程安全：P3-2 类级锁保证并发调用同一 agent 得到一致密钥
        """
        with KeyManager._init_lock:
            return self._generate_or_load_locked(agent_id)

    def _generate_or_load_locked(self, agent_id: str) -> Tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
        """加锁后的实现（供 generate_or_load 调用）"""
        if agent_id in self._key_cache:
            return self._key_cache[agent_id]

        priv_path = self.key_dir / f"{agent_id}_private.pem"
        pub_path = self.key_dir / f"{agent_id}_public.pem"

        if priv_path.exists() and pub_path.exists():
            # 从磁盘加载；旧明文 PEM 在口令校验成功后立即迁移为加密 PEM。
            private_key = self._load_and_migrate_private_key(priv_path)
            public_key = ECDSAUtils.public_key_from_bytes(pub_path.read_bytes())
            logger.info(f"[KeyManager] 已加载 {agent_id} 的密钥对")
        else:
            # 生成新密钥对并保存。
            # 09-28 修正（全检 #4）：旧注释写"口令缺失时 resolve_key_passphrase
            # 会 fail-closed" —— 与该函数的实际行为不符，它当时是**静默回退**到
            # 随源码公开的 DEFAULT_KEY_PASSPHRASE。现 resolve_key_passphrase 在
            # MARL_ECDSA_REQUIRE_KEY_PASSPHRASE=1 时才真正 fail-closed；
            # 缺省仍回退并打印 WARNING（详见 ecdsa_utils.resolve_key_passphrase）。
            private_key, public_key = ECDSAUtils.generate_key_pair()
            priv_path.write_bytes(
                ECDSAUtils.private_key_to_bytes(private_key, resolve_key_passphrase())
            )
            # P0-2: 私钥文件权限保护 — 仅 owner 可读写，防止其他用户读取私钥
            # Windows 平台 os.chmod 对文件权限的支持有限，但至少尝试执行
            try:
                os.chmod(str(priv_path), 0o600)
            except (OSError, AttributeError):
                logger.debug(f"[KeyManager] os.chmod(0o600) 在当前平台不可用或失败，跳过")
            pub_path.write_bytes(ECDSAUtils.public_key_to_bytes(public_key))
            # 09-28 修正（全检 #4）：旧文案"私钥已加密存储"未交代口令来源，
            # 而缺省用的是随源码公开的 DEFAULT_KEY_PASSPHRASE —— 加密了，
            # 但对任何拿到仓库的人都是裸奔（实测 5 个"已加密"私钥均可用默认
            # 口令解开）。这里改为如实标注口令来源。
            # 严谨模式下走到这里说明环境变量缺失会先行抛错，故只剩两种来源。
            _pw_src = (
                "环境变量 MARL_ECDSA_KEY_PASSPHRASE"
                if os.environ.get("MARL_ECDSA_KEY_PASSPHRASE")
                else "公开的 DEFAULT_KEY_PASSPHRASE（无保密性）"
            )
            logger.info(f"[KeyManager] 已为 {agent_id} 生成新密钥对（私钥口令来源: {_pw_src}）")

        self._key_cache[agent_id] = (private_key, public_key)
        return private_key, public_key

    def get_public_key(self, agent_id: str) -> Optional[ec.EllipticCurvePublicKey]:
        """获取指定智能体的公钥（不暴露私钥）"""
        pair = self._key_cache.get(agent_id)
        if pair:
            return pair[1]
        pub_path = self.key_dir / f"{agent_id}_public.pem"
        if pub_path.exists():
            pub_key = ECDSAUtils.public_key_from_bytes(pub_path.read_bytes())
            return pub_key
        return None

    def get_public_key_hex(self, agent_id: str) -> Optional[str]:
        """获取公钥的十六进制字符串表示（用于链上注册）"""
        pub_key = self.get_public_key(agent_id)
        if pub_key:
            return ECDSAUtils.public_key_to_hex(pub_key)
        return None

    def get_private_key(self, agent_id: str) -> Optional[ec.EllipticCurvePrivateKey]:
        """获取私钥（仅限本地使用）"""
        pair = self._key_cache.get(agent_id)
        if pair:
            return pair[0]
        priv_path = self.key_dir / f"{agent_id}_private.pem"
        if priv_path.exists():
            return self._load_and_migrate_private_key(priv_path)
        return None

    def remove_key(self, agent_id: str) -> bool:
        """删除智能体密钥（谨慎使用）"""
        self._key_cache.pop(agent_id, None)
        priv_path = self.key_dir / f"{agent_id}_private.pem"
        pub_path = self.key_dir / f"{agent_id}_public.pem"
        removed = False
        if priv_path.exists():
            priv_path.unlink()
            removed = True
        if pub_path.exists():
            pub_path.unlink()
            removed = True
        return removed

    def list_agents(self) -> list:
        """列出所有已注册密钥的智能体ID"""
        agents = set()
        for f in self.key_dir.glob("*_private.pem"):
            agent_id = f.stem.replace("_private", "")
            agents.add(agent_id)
        return list(agents)
