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
        # 生成消息ID（基于内容哈希前16位）
        raw = f"{msg_type}{from_node}{ts}{nonce}{json.dumps(data, sort_keys=True)}"
        msg_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        return {
            "header": {
                "msg_id": msg_id,
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
