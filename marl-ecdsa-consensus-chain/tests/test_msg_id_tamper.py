"""
回归锁：P2-13 —— 去重必须基于「内容指纹」而非发送方自报的 msg_id。

背景：原实现在 P2PNode._dispatch / broadcast 中直接用 MessageProtocol.get_msg_id(msg)
（即报文 header.msg_id，发送方自报、接收方从未校验）做去重/防重放缓存键。
攻击者在共享 TLS 证书的成员网络内可随意填写唯一 msg_id，直接绕过 _seen_msg_ids
去重缓存，使同一条报文被反复处理（资源放大、绕过广播回环保护）。

修复：P2PNode 改用 MessageProtocol.recompute_msg_id(msg) —— 用与 build() 完全一致的
规范化串重算内容指纹作为去重键，从根本上封死伪造 msg_id 的绕过路径。recompute 会
把 msg_type 枚举归一为其值，确保「发送端内存态」与「JSON 编解码后的接收端」重算出的
去重键一致（否则回环保护会在接收端失效）。

本测试断言修复后的核心不变量：
1. build() 产出的 msg_id 与 recompute() 一致（合法报文不受影响）；
2. 伪造 header.msg_id 不改变 recompute() 结果（去重键仍是内容，伪造无法绕过）；
3. 不同内容得到不同指纹（不会因内容不同而误去重）；
4. recompute() 不返回攻击者伪造的任意值；
5. 经 encode→decode 的「线上」报文，其 recompute 去重键与发送端一致（收发一致）。
"""
import json
import hashlib

from blockchain.network.message_protocol import MessageProtocol, MessageType


def _canonical_id(msg_type, from_node, ts, nonce, data):
    """复刻 recompute_msg_id 的规范化逻辑（含枚举→值归一）作为 oracle。"""
    mt = getattr(msg_type, "value", msg_type)
    raw = f"{mt}{from_node}{ts}{nonce}{json.dumps(data, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def test_recompute_matches_build_and_oracle():
    msg = MessageProtocol.build(MessageType.HEARTBEAT, "agent_0", {"x": 1}, 5)
    assert MessageProtocol.recompute_msg_id(msg) == msg["header"]["msg_id"]
    # 与独立 oracle 一致，证明 recompute 复刻了 build 的规范化逻辑
    assert MessageProtocol.recompute_msg_id(msg) == _canonical_id(
        MessageType.HEARTBEAT, "agent_0", msg["header"]["timestamp"], 5, {"x": 1}
    )


def test_forged_msg_id_cannot_bypass_dedup():
    msg = MessageProtocol.build(MessageType.TRANSACTION, "agent_2", {"amt": 10}, 7)
    forged = json.loads(json.dumps(msg))  # 深拷贝
    forged["header"]["msg_id"] = "deadbeefdeadbeef"  # 攻击者伪造唯一 id

    # 去重键是内容指纹：伪造报文仍映射到与原文相同的键 → 无法绕过去重
    assert MessageProtocol.recompute_msg_id(forged) == MessageProtocol.recompute_msg_id(msg)
    # 且它绝不等于伪造值（证明接收方不再信任自报 id）
    assert MessageProtocol.recompute_msg_id(forged) != "deadbeefdeadbeef"


def test_distinct_content_yields_distinct_id():
    a = MessageProtocol.build(MessageType.TRANSACTION, "agent_0", {"n": 1}, 1)
    b = MessageProtocol.build(MessageType.TRANSACTION, "agent_0", {"n": 2}, 1)
    assert MessageProtocol.recompute_msg_id(a) != MessageProtocol.recompute_msg_id(b)

    # 仅改 nonce 也应有不同指纹（防重放语义依赖内容敏感性）
    c = MessageProtocol.build(MessageType.TRANSACTION, "agent_0", {"n": 1}, 2)
    assert MessageProtocol.recompute_msg_id(a) != MessageProtocol.recompute_msg_id(c)


def test_wire_roundtrip_dedup_key_consistent():
    """关键：发送端内存态与 JSON 编解码后的接收端，重算去重键必须一致。

    回归点：msg_type 是枚举，f-string 对其取 repr（"MessageType.HEARTBEAT"），
    而 JSON 解码后为字符串值（"heartbeat"）。若 recompute 不归一，则收发两端
    算出的去重键不同，广播回环保护会在接收端失效。"""
    msg = MessageProtocol.build(MessageType.TRANSACTION, "agent_3", {"k": [1, 2, 3]}, 9)
    wire = MessageProtocol.encode(msg)
    decoded = MessageProtocol.decode(wire)
    # 接收端重算键 == 发送端重算键
    assert MessageProtocol.recompute_msg_id(decoded) == MessageProtocol.recompute_msg_id(msg)
    # 且 build 写入的 msg_id 也与收发两端一致
    assert MessageProtocol.recompute_msg_id(decoded) == msg["header"]["msg_id"]
