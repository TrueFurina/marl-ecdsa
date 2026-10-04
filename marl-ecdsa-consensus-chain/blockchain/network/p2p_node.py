"""
P2P节点
基于 asyncio TCP Socket 构建无中心P2P网络节点
支持：节点发现、心跳保活、消息广播（泛洪+去重）、区块同步
P1-9修复：节点注册需携带ECDSA签名验证身份，防止Eclipse攻击
BUG4修复：P2P 传输层默认启用 TLS，避免共识消息（含签名投票）明文传输
"""
import asyncio
import datetime
import hashlib
import ipaddress
import json
import logging
import os
import ssl
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Awaitable, Tuple

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .message_protocol import MessageProtocol, MessageType

logger = logging.getLogger(__name__)


# =============================================================================
# BUG4: P2P 传输 TLS 上下文工具
# 节点同时充当 TLS 服务端（监听）与 TLS 客户端（主动连接），因此各维护一份上下文。
# 自签名证书存于 tls_dir（默认 keys/tls/，已被 .gitignore 覆盖），已存在则复用。
# 客户端以该自签名证书为信任锚(CERT_REQUIRED)，确保两端均持有同一证书，
# 防止第三方用任意证书发起 MITM；演示证书不校验主机名(check_hostname=False)。
# =============================================================================

def _ensure_tls_cert(tls_dir: str) -> Tuple[Path, Path]:
    """生成（若不存在）自签名证书，返回 (cert_path, key_path)。"""
    tls_path = Path(tls_dir)
    tls_path.mkdir(parents=True, exist_ok=True)
    cert_path = tls_path / "tls_cert.pem"
    key_path = tls_path / "tls_key.pem"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MARL-ECDSA-P2P"),
    ])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(str(key_path), 0o600)
    except (OSError, AttributeError):
        pass
    logger.info(f"[P2PNode] 已生成自签名 TLS 证书: {cert_path}")
    return cert_path, key_path


def build_tls_contexts(tls_dir: str, enable_tls: bool):
    """构建 (server_ctx, client_ctx)；未启用 TLS 时返回 (None, None)。"""
    if not enable_tls:
        return None, None
    cert_path, key_path = _ensure_tls_cert(tls_dir)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.load_verify_locations(cafile=str(cert_path))
    client_ctx.verify_mode = ssl.CERT_REQUIRED
    # 演示用自签名证书：以共享证书为信任锚即可，跳过主机名校验
    client_ctx.check_hostname = False
    return server_ctx, client_ctx


class NodeInfo:
    """节点信息"""
    def __init__(self, node_id: str, host: str, port: int):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.last_heartbeat = time.time()
        self.is_online = True

    def __repr__(self):
        return f"NodeInfo({self.node_id}@{self.host}:{self.port})"


class P2PNode:
    """
    P2P网络节点
    混合架构：
    - 共识全节点：维护完整账本，参与共识投票
    - 智能体轻节点：仅提交行为交易，查询链上数据

    通信机制：
    - asyncio TCP Server（服务端）+ TCP Client（客户端）
    - 消息格式：带4字节长度前缀的JSON
    - 心跳周期：5秒
    - 节点下线判定：30秒无心跳
    - 广播去重：msg_id缓存，避免循环广播
    """

    HEARTBEAT_INTERVAL = 5      # 心跳周期（秒）
    NODE_TIMEOUT = 30           # 节点下线判定（秒）
    MAX_MSG_CACHE = 10_000      # 消息ID去重缓存上限

    def __init__(
        self,
        node_id: str,
        host: str,
        port: int,
        is_consensus_node: bool = False,
        key_manager=None,  # P1-9修复：注入KeyManager用于签名验证
        allow_insecure_register: bool = False,  # BUG1: 仅连通性测试显式开启注册宽松兜底
        enable_tls: bool = True,  # BUG4: P2P 传输 TLS 加密，默认开启
        tls_dir: str = "keys/tls",  # BUG4: 自签名证书存储目录（已被 .gitignore 覆盖）
    ):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.is_consensus_node = is_consensus_node
        self._key_manager = key_manager  # P1-9修复：密钥管理器引用

        # BUG1 修复：注册签名默认 fail-closed（生产必须配 key_manager）。
        # 仅当此开关为 True 且 key_manager 为 None 时，才允许走长度兜底（非生产安全）。
        self._allow_insecure_register = allow_insecure_register

        # BUG4: TLS 传输加密（默认开启）
        self._enable_tls = enable_tls
        self._tls_dir = tls_dir
        self._tls_server_ctx = None
        self._tls_client_ctx = None

        # 节点表：{node_id: NodeInfo}
        self._peers: Dict[str, NodeInfo] = {}
        # 活跃连接：{node_id: (reader, writer)}
        self._connections: Dict[str, tuple] = {}
        # 消息ID去重缓存（P2-12: 新增 _msg_order 配合 FIFO trim）
        self._seen_msg_ids: Set[str] = set()
        self._msg_order: dict = {}  # 使用dict保存消息序号（Python 3.7+ dict保持插入序，等效OrderedDict）
        # 消息类型处理器：{msg_type: handler_coroutine}
        self._handlers: Dict[str, Callable] = {}
        # 本地消息计数（nonce）
        self._nonce = 0

        # 运行状态
        self._server = None
        self._running = False

        # 注册默认处理器
        self._register_default_handlers()

    # -------------------------------------------------------------------------
    # 启动与停止
    # -------------------------------------------------------------------------

    async def start(self):
        """启动P2P节点服务"""
        self._running = True
        # BUG4: 构建 TLS 上下文（默认开启），包裹 asyncio server
        self._tls_server_ctx, self._tls_client_ctx = build_tls_contexts(
            self._tls_dir, self._enable_tls
        )
        self._server = await asyncio.start_server(
            self._handle_incoming,
            self.host,
            self.port,
            ssl=self._tls_server_ctx,
        )
        tls_tag = "TLS" if self._enable_tls else "明文(已禁用)"
        logger.info(f"[P2PNode] {self.node_id} 启动，监听 {self.host}:{self.port} [{tls_tag}]")

        # 启动心跳任务
        asyncio.create_task(self._heartbeat_loop())
        # 启动节点健康检查
        asyncio.create_task(self._health_check_loop())

    async def stop(self):
        """停止P2P节点"""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        # 关闭所有连接
        for node_id, (_, writer) in self._connections.items():
            writer.close()
        self._connections.clear()
        logger.info(f"[P2PNode] {self.node_id} 已停止")

    # -------------------------------------------------------------------------
    # 节点管理
    # -------------------------------------------------------------------------

    async def connect_to(self, host: str, port: int, node_id: str) -> bool:
        """主动连接到另一个节点，成功返回 True，失败返回 False。"""
        try:
            # TLS 默认开启。即使调用方尚未 start()，也必须先构建客户端上下文，
            # 禁止把未初始化的 None 传给 asyncio 而静默降级为明文连接。
            if self._enable_tls:
                if self._tls_client_ctx is None:
                    _, self._tls_client_ctx = build_tls_contexts(
                        self._tls_dir, self._enable_tls
                    )
                if self._tls_client_ctx is None:
                    raise RuntimeError("TLS 已启用但客户端上下文初始化失败")
            reader, writer = await asyncio.open_connection(
                host, port, ssl=self._tls_client_ctx
            )
            self._connections[node_id] = (reader, writer)
            self._peers[node_id] = NodeInfo(node_id, host, port)
            logger.info(f"[P2PNode] 已连接到节点 {node_id}@{host}:{port}")

            # 发送注册消息（P1-9修复：附带ECDSA签名）
            reg_data = {
                'node_id': self.node_id,
                'host': self.host,
                'port': self.port,
                'is_consensus': self.is_consensus_node,
            }
            signature_hex = None
            if self._key_manager is not None:
                priv_key = self._key_manager.get_private_key(self.node_id)
                if priv_key is not None:
                    from ..crypto.ecdsa_utils import ECDSAUtils
                    message_bytes = json.dumps(reg_data, sort_keys=True).encode('utf-8')
                    message_hash = hashlib.sha256(message_bytes).digest()
                    sig = ECDSAUtils.sign(priv_key, message_hash)
                    signature_hex = sig.hex()
            registered = await self.send_to(
                node_id, MessageType.REGISTER, reg_data, signature=signature_hex
            )
            if not registered:
                logger.warning(
                    f"[P2PNode] 连接 {node_id}@{host}:{port} 后发送注册消息失败"
                )
                return False

            # 启动读取循环
            asyncio.create_task(self._read_loop(node_id, reader, writer))
            return True
        except Exception as e:
            logger.warning(f"[P2PNode] 连接 {node_id}@{host}:{port} 失败: {e}")
            return False

    def get_online_peers(self) -> List[NodeInfo]:
        """获取在线节点列表"""
        return [p for p in self._peers.values() if p.is_online]

    def get_consensus_peers(self) -> List[NodeInfo]:
        """获取在线的共识全节点"""
        return [p for p in self.get_online_peers()]  # 按需扩展过滤逻辑

    # -------------------------------------------------------------------------
    # 消息发送
    # -------------------------------------------------------------------------

    async def send_to(self, node_id: str, msg_type: MessageType, data: dict, signature: str = None):
        """向指定节点发送消息"""
        self._nonce += 1
        msg = MessageProtocol.build(msg_type, self.node_id, data, self._nonce, signature)
        encoded = MessageProtocol.encode(msg)

        if node_id not in self._connections:
            logger.warning(f"[P2PNode] 节点 {node_id} 未连接，无法发送")
            return False

        _, writer = self._connections[node_id]
        try:
            writer.write(encoded)
            await writer.drain()
            return True
        except Exception as e:
            logger.error(f"[P2PNode] 发送消息到 {node_id} 失败: {e}")
            self._mark_offline(node_id)
            return False

    async def broadcast(self, msg_type: MessageType, data: dict, signature: str = None, exclude: str = None):
        """
        广播消息到所有在线节点（泛洪+去重）
        :param exclude: 排除的节点ID（通常是消息来源，避免回传）
        """
        self._nonce += 1
        msg = MessageProtocol.build(msg_type, self.node_id, data, self._nonce, signature)
        msg_id = MessageProtocol.get_msg_id(msg)

        # 防止重复广播
        if msg_id in self._seen_msg_ids:
            return
        self._seen_msg_ids.add(msg_id)
        self._msg_order[msg_id] = True  # P2-12: 记录插入顺序用于 FIFO trim
        self._trim_msg_cache()

        encoded = MessageProtocol.encode(msg)
        tasks = []
        for node_id, (_, writer) in self._connections.items():
            if node_id == exclude:
                continue
            tasks.append(self._write_to_writer(writer, encoded, node_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _write_to_writer(self, writer, encoded: bytes, node_id: str):
        """安全写入（内部方法）"""
        try:
            writer.write(encoded)
            await writer.drain()
        except Exception as e:
            logger.error(f"[P2PNode] 广播到 {node_id} 失败: {e}")

    # -------------------------------------------------------------------------
    # 接收与处理
    # -------------------------------------------------------------------------

    async def _handle_incoming(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """接受新的入站连接"""
        peer_addr = writer.get_extra_info('peername')
        logger.debug(f"[P2PNode] 新连接来自 {peer_addr}")
        node_id = f"unknown_{peer_addr}"
        self._connections[node_id] = (reader, writer)
        await self._read_loop(node_id, reader, writer)

    async def _read_loop(self, node_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """持续读取并处理来自节点的消息"""
        try:
            while self._running:
                # 先读4字节长度头
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, 'big')
                if length > 10 * 1024 * 1024:  # 限制10MB
                    logger.warning(f"[P2PNode] 消息过大 {length} bytes，丢弃")
                    continue

                payload = await reader.readexactly(length)
                msg = json.loads(payload.decode('utf-8'))

                await self._dispatch(msg, from_node=node_id)
        except asyncio.IncompleteReadError:
            logger.info(f"[P2PNode] 节点 {node_id} 断开连接")
            self._mark_offline(node_id)
        except Exception as e:
            logger.error(f"[P2PNode] 读取 {node_id} 消息异常: {e}")
            self._mark_offline(node_id)

    async def _dispatch(self, msg: Dict, from_node: str):
        """消息分发到对应处理器"""
        msg_id = MessageProtocol.get_msg_id(msg)
        msg_type = MessageProtocol.get_msg_type(msg)

        # 去重
        if msg_id in self._seen_msg_ids:
            return
        self._seen_msg_ids.add(msg_id)
        self._msg_order[msg_id] = True  # P2-12: 记录插入顺序用于 FIFO trim
        self._trim_msg_cache()

        # 更新来源节点ID
        real_from = MessageProtocol.get_from_node(msg)
        if real_from and real_from != from_node:
            # 如果有更规范的node_id则更新
            if from_node in self._connections:
                conn = self._connections.pop(from_node)
                self._connections[real_from] = conn

        # 调用处理器
        handler = self._handlers.get(msg_type)
        if handler:
            try:
                await handler(msg, from_node=real_from or from_node)
            except Exception as e:
                logger.error(f"[P2PNode] 处理 {msg_type} 消息时出错: {e}")
        else:
            logger.debug(f"[P2PNode] 无处理器: msg_type={msg_type}")

    # -------------------------------------------------------------------------
    # 默认消息处理器
    # -------------------------------------------------------------------------

    def _register_default_handlers(self):
        """注册内置处理器"""
        self._handlers[MessageType.REGISTER] = self._on_register
        self._handlers[MessageType.HEARTBEAT] = self._on_heartbeat

    async def _on_register(self, msg: Dict, from_node: str):
        """
        处理节点注册消息（P1-9修复：增加身份验证）

        安全检查：
        1. REGISTER消息必须携带ECDSA签名（signature字段）
        2. 验证node_id与签名公钥的绑定关系
        3. 已注册的node_id不允许被新连接覆盖（防止Eclipse攻击）
        """
        data = MessageProtocol.get_data(msg)
        node_id = data.get('node_id', from_node)
        host = data.get('host', '')
        port = data.get('port', 0)

        # P1-9修复：防止已注册的node_id被新连接覆盖（Eclipse攻击防护）
        if node_id in self._peers:
            logger.warning(
                f"[P2PNode] 拒绝重复注册: node_id={node_id} 已存在于peer表中，"
                f"防止Eclipse攻击覆盖"
            )
            return

        # P1-9修复：ECDSA签名身份验证
        signature_hex = MessageProtocol.get_signature(msg)
        if signature_hex is None:
            logger.warning(
                f"[P2PNode] 拒绝无签名注册: node_id={node_id}，"
                f"REGISTER消息必须携带ECDSA签名"
            )
            return

        # 验证签名：构造注册消息体并验签
        # 签名覆盖字段：node_id + host + port + is_consensus
        try:
            reg_payload = {
                'node_id': node_id,
                'host': host,
                'port': port,
                'is_consensus': data.get('is_consensus', False),
            }
            message_bytes = json.dumps(reg_payload, sort_keys=True).encode('utf-8')
            message_hash = hashlib.sha256(message_bytes).digest()
            signature_bytes = bytes.fromhex(signature_hex)

            # 验证node_id与签名公钥绑定：
            # node_id格式为agent_N，公钥需通过identity_contract或key_manager查询
            # 此处采用简化验证：检查签名本身是否有效（公钥由identity模块提供）
            verified = self._verify_register_signature(
                node_id, message_hash, signature_bytes
            )
            if not verified:
                logger.warning(
                    f"[P2PNode] 注册签名验证失败: node_id={node_id}，"
                    f"node_id与签名公钥绑定校验不通过"
                )
                return
        except Exception as e:
            logger.warning(f"[P2PNode] 注册签名验证异常: node_id={node_id}, {e}")
            return

        self._peers[node_id] = NodeInfo(node_id, host, port)
        logger.info(f"[P2PNode] 新节点注册(签名验证通过): {node_id}@{host}:{port}")

        # 更新连接映射
        if from_node != node_id and from_node in self._connections:
            conn = self._connections.pop(from_node)
            self._connections[node_id] = conn

    def _verify_register_signature(
        self, node_id: str, message_hash: bytes, signature_bytes: bytes
    ) -> bool:
        """
        P1-9修复：验证注册签名（简化版）

        在有identity_contract/key_manager时，查询node_id对应的公钥严格验签。
        BUG1 修复：无密钥管理器时默认 fail-closed（拒绝注册），杜绝认证绕过后门。
        仅当显式开启 _allow_insecure_register 且 key_manager 为 None 时，
        才允许走长度兜底（仅用于纯连通性测试，非生产安全）。
        """
        # 查询密钥管理器（通过外部注入的key_manager）
        if self._key_manager is not None:
            pub_key = self._key_manager.get_public_key(node_id)
            if pub_key is None:
                logger.warning(f"[P2PNode] 无法获取node_id={node_id}的公钥")
                return False
            from ..crypto.ecdsa_utils import ECDSAUtils
            return ECDSAUtils.verify(pub_key, message_hash, signature_bytes)

        # 无密钥管理器：默认 fail-closed（生产必须配置 key_manager）
        if self._allow_insecure_register:
            # 仅连通性测试显式开启：宽松验证（仅检查签名格式合法性，非生产安全）
            if len(signature_bytes) >= 64:  # ECDSA签名最小长度
                logger.info(
                    f"[P2PNode] 非生产安全模式(insecure)，宽松验证注册签名: node_id={node_id}"
                )
                return True
            return False
        logger.warning(
            f"[P2PNode] 注册签名验证失败(默认fail-closed): key_manager未配置且未开启"
            f"insecure模式，拒绝注册 node_id={node_id}"
        )
        return False

    async def _on_heartbeat(self, msg: Dict, from_node: str):
        """处理心跳消息，更新节点活跃时间"""
        if from_node in self._peers:
            self._peers[from_node].last_heartbeat = time.time()
            self._peers[from_node].is_online = True

    # -------------------------------------------------------------------------
    # 自定义处理器注册
    # -------------------------------------------------------------------------

    def register_handler(self, msg_type: MessageType, handler: Callable):
        """注册自定义消息处理器"""
        self._handlers[msg_type] = handler

    # -------------------------------------------------------------------------
    # 心跳与健康检查
    # -------------------------------------------------------------------------

    async def _heartbeat_loop(self):
        """定期向所有节点发送心跳"""
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            await self.broadcast(MessageType.HEARTBEAT, {
                'node_id': self.node_id,
                'block_height': 0,  # 由外部更新
            })

    async def _health_check_loop(self):
        """定期检查节点心跳，标记下线节点"""
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            now = time.time()
            for node_id, info in self._peers.items():
                if info.is_online and (now - info.last_heartbeat) > self.NODE_TIMEOUT:
                    self._mark_offline(node_id)

    def _mark_offline(self, node_id: str):
        """标记节点下线"""
        if node_id in self._peers:
            self._peers[node_id].is_online = False
        if node_id in self._connections:
            _, writer = self._connections.pop(node_id)
            try:
                writer.close()
            except Exception as e:
                logger.warning(f"标记节点 {node_id} 下线时出错: {e}")
        logger.info(f"[P2PNode] 节点 {node_id} 已标记为下线")

    # -------------------------------------------------------------------------
    # 工具方法
    # -------------------------------------------------------------------------

    def _trim_msg_cache(self):
        """
        防止消息缓存无限增长
        P2-12 修复：使用 dict + set 替代纯 set，确保删除最旧条目而非随机条目
        - dict: _msg_order 记录插入顺序（Python 3.7+ dict保持插入序，等效OrderedDict），trim 时按 FIFO 删除最旧的
        - set: _seen_msg_ids 仍用于快速 O(1) 去重查询
        """
        if len(self._seen_msg_ids) > self.MAX_MSG_CACHE:
            # 按插入顺序删除最旧的一半（FIFO 策略）
            remove_count = self.MAX_MSG_CACHE // 2
            for _ in range(remove_count):
                if not self._msg_order:
                    break
                # P3-1修复: dict.popitem() 不接受 last 关键字参数（Python 3.7+），
                # 改用 next(iter()) 取最旧 key 再删除（FIFO）
                oldest_mid = next(iter(self._msg_order))
                del self._msg_order[oldest_mid]
                self._seen_msg_ids.discard(oldest_mid)

    def get_network_stats(self) -> Dict:
        """获取网络状态统计"""
        return {
            'node_id': self.node_id,
            'host': self.host,
            'port': self.port,
            'online_peers': len(self.get_online_peers()),
            'total_peers': len(self._peers),
            'active_connections': len(self._connections),
            'is_consensus': self.is_consensus_node,
        }
