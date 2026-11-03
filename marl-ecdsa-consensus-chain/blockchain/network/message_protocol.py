"""
消息协议定义
所有P2P通信消息的格式规范
"""
import json
import time
import hashlib
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    """消息类型枚举"""
    REGISTER = "register"          # 节点入网注册
    HEARTBEAT = "heartbeat"        # 心跳保活
    TRANSACTION = "transaction"    # 智能体行为上链交易
    BLOCK = "block"                # 新区块广播
    SYNC_REQUEST = "sync_request"  # 区块同步请求
    SYNC_RESPONSE = "sync_response"# 区块同步响应
    CONSENSUS_PREPREPARE = "preprepare"  # PBFT预准备
    CONSENSUS_PREPARE = "prepare"        # PBFT准备
    CONSENSUS_COMMIT = "commit"          # PBFT提交
    QUERY = "query"                # 数据查询
    RESPONSE = "response"          # 查询响应


class MessageProtocol:
    """
    自定义应用层消息协议
    所有消息均为JSON格式，含消息头与消息体
    消息格式：
    {
        "header": {
            "msg_id": "<sha256前16位>",
            "msg_type": "<MessageType>",
            "from_node": "<node_id>",
            "timestamp": <ms_timestamp>,
            "nonce": <int>
        },
        "body": {
            "data": <any>,
            "signature": "<hex_or_null>"
        }
    }
    """

    @staticmethod
    def build(
        msg_type: MessageType,
        from_node: str,
        data: Any,
        nonce: int,
        signature: Optional[str] = None
    ) -> Dict:
        """构造标准消息"""
        ts = int(time.time() * 1000)
        msg = {
            "header": {
                "msg_id": "",
                "msg_type": msg_type,
                "from_node": from_node,
                "timestamp": ts,
                "nonce": nonce,
            },
            "body": {
                "data": data,
                "signature": signature,
            }
        }
        # msg_id 以内容指纹为准（与 recompute_msg_id 完全一致，收发/编解码两端一致）
        msg["header"]["msg_id"] = MessageProtocol.recompute_msg_id(msg)
        return msg

    @staticmethod
    def encode(msg: Dict) -> bytes:
        """消息编码为字节（带长度前缀，4字节大端序）"""
        payload = json.dumps(msg, ensure_ascii=False).encode('utf-8')
        length = len(payload).to_bytes(4, 'big')
        return length + payload

    @staticmethod
    def decode(raw: bytes) -> Dict:
        """消息解码（去除长度前缀）"""
        if len(raw) < 4:
            raise ValueError("消息太短，无法解析长度")
        length = int.from_bytes(raw[:4], 'big')
        payload = raw[4:4 + length]
        return json.loads(payload.decode('utf-8'))

    @staticmethod
    def get_msg_id(msg: Dict) -> str:
        return msg.get("header", {}).get("msg_id", "")

    @staticmethod
    def recompute_msg_id(msg: Dict) -> str:
        """从消息内容重算 msg_id，替代不可信的自报 msg_id。

        设计本意：``header.msg_id`` 由发送方在 ``build()`` 中生成，接收方**绝不应信任**
        它做去重/防重放决策——攻击者可随意填写一个唯一 msg_id 直接绕过 ``_seen_msg_ids``
        去重缓存，使同一条消息被反复处理（资源放大、绕过广播回环保护）。

        本方法用与 ``build()`` 完全一致的规范化串重算内容指纹，使去重基于**内容**而非
        发送方自报的 id，从根本上封死伪造 msg_id 的绕过路径。
        """
        header = msg.get("header", {}) or {}
        body = msg.get("body", {}) or {}
        mt = header.get("msg_type")
        # msg_type 可能为 MessageType 枚举：发送端在内存中是枚举，经 JSON 编解码后变为其
        # 字符串值（如 "heartbeat"）。f-string 对枚举取 repr（"MessageType.HEARTBEAT"），
        # 对字符串取值，两端不一致会导致收发重算出的去重键不同、回环保护失效。
        # 统一落到枚举的值，保证收发/编解码两端规范化串一致。
        mt = getattr(mt, "value", mt)
        raw = (
            f"{mt}"
            f"{header.get('from_node', '')}"
            f"{header.get('timestamp', '')}"
            f"{header.get('nonce', '')}"
            f"{json.dumps(body.get('data'), sort_keys=True)}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def get_msg_type(msg: Dict) -> str:
        return msg.get("header", {}).get("msg_type", "")

    @staticmethod
    def get_from_node(msg: Dict) -> str:
        return msg.get("header", {}).get("from_node", "")

    @staticmethod
    def get_data(msg: Dict) -> Any:
        return msg.get("body", {}).get("data")

    @staticmethod
    def get_signature(msg: Dict) -> Optional[str]:
        return msg.get("body", {}).get("signature")
