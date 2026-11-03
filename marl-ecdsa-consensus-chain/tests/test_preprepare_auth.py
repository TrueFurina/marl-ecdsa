"""
PRE-PREPARE 入口认证守卫（2026-10-11 独立代码审查 B1/B2 修复）

背景：三个投票 handler 中，唯独 `_on_preprepare` 不做签名校验，而 P2P 层
只对 REGISTER 验签（message_protocol 内无 verify），导致 PRE-PREPARE 处于
"应用层不验 + 传输层不验"的状态。伪造报文可触发 `reset()` 抹掉已达成的
COMMITTED 状态，构成活性攻击。

本文件同时钉住：
  B1 —— PRE-PREPARE 必须与 PREPARE/COMMIT 同口径验签
  B2 —— 声称的主节点必须是已知共识成员（女巫门控，与 receive_vote 同口径）

测试策略说明：
  B1 与 B2 是串行的两道门（先验签、后成员）。要隔离测试 B2，必须让 B1 放行，
  故 B2 用例统一使用 `allow_insecure_vote=True`（无签名时验签返回 True）。
"""
import asyncio
import hashlib
import inspect
import json
import logging
import re
import shutil
import tempfile

import pytest

from blockchain.network.network_consensus import NetworkConsensusNode
from blockchain.network.message_protocol import MessageProtocol, MessageType
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.ecdsa_utils import ECDSAUtils

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2']
PORT = 7900


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _signed_body(km, voter_id, block_hash="blk_hash_1", phase="pre_prepare",
                 weight=1.0, timestamp=0, sign_as=None, block_height=1):
    """构造与 `_broadcast_vote` 完全一致的签名报文体。

    `sign_as` 用于构造"身份与签名密钥不一致"的攻击面（voter_id 自称 node_0，
    实际用 node_1 的私钥签名）。
    """
    body = {
        "voter_id": voter_id,
        "block_hash": block_hash,
        "phase": phase,
        "weight": weight,
        "timestamp": timestamp,
        "block_height": block_height,  # F13：轮次高度进签名体（高度1-10合法主节点=node_0）
    }
    message_bytes = json.dumps(body, sort_keys=True).encode('utf-8')
    digest = hashlib.sha256(message_bytes).digest()
    signer = sign_as or voter_id
    priv = km.get_private_key(signer)
    if priv is None:
        raise RuntimeError(f"KeyManager 没有 {signer} 的私钥")
    return dict(body, signature_hex=ECDSAUtils.sign(priv, digest).hex())


def _unsigned_body(voter_id, block_hash="blk_hash_1", **kw):
    """无签名的报文体（用于验证 fail-closed 与 insecure 两条分支）"""
    return {
        "voter_id": voter_id,
        "block_hash": block_hash,
        "phase": "pre_prepare",
        "weight": 1.0,
        "timestamp": 0,
        "block_height": 1,  # F13：轮次高度进报文体
        **kw,
    }


def _msg(data, from_node="node_0"):
    return MessageProtocol.build(
        MessageType.CONSENSUS_PREPREPARE, from_node=from_node, data=data, nonce=1
    )


def _mk_node(node_id, **kw):
    """构造不启动网络的节点，并把 broadcast 换成记录调用的 AsyncMock。"""
    node = NetworkConsensusNode(
        node_id=node_id, host='127.0.0.1', port=PORT,
        all_node_ids=NODES, **kw,
    )
    calls = []

    async def _fake_broadcast(msg_type, data, signature=None):
        calls.append((msg_type, data, signature))

    node.p2p.broadcast = _fake_broadcast
    return node, calls


def _run(node, data, from_node="node_0"):
    return asyncio.run(node._on_preprepare(_msg(data, from_node), from_node))


@pytest.fixture
def km():
    key_dir = tempfile.mkdtemp(prefix="test_pp_auth_")
    manager = KeyManager(key_dir=key_dir)
    for nid in NODES:
        manager.generate_or_load(nid)
    yield manager
    shutil.rmtree(key_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# B1 —— PRE-PREPARE 必须验签
# ---------------------------------------------------------------------------

def test_unsigned_preprepare_rejected_when_no_keymanager():
    """B1：未配置 key_manager 时，无签名 PRE-PREPARE 必须 fail-closed 拒绝。"""
    node, calls = _mk_node('node_1')
    _run(node, _unsigned_body('node_0'))
    assert calls == [], "无 key_manager 且非 insecure 模式下，无签名 PRE-PREPARE 应被丢弃"
    assert node.msg_sent == 0


def test_valid_signed_preprepare_accepted(km):
    """B1：合法成员签名需放行（修复不得把正常流程打死）。"""
    node, calls = _mk_node('node_1', key_manager=km)
    _run(node, _signed_body(km, 'node_0'))
    assert len(calls) == 1, "合法签名应触发一次 PREPARE 广播"
    msg_type, data, signature = calls[0]
    assert msg_type == MessageType.CONSENSUS_PREPARE
    assert signature is not None, "广播出去的 PREPARE 应自带签名"


def test_tampered_signature_rejected(km):
    """B1：签名被篡改后必须拒绝（块哈希可比、签名不可比）。"""
    node, calls = _mk_node('node_1', key_manager=km)
    body = _signed_body(km, 'node_0')
    body["signature_hex"] = "00" * len(body["signature_hex"])
    _run(node, body)
    assert calls == [], "篡改签名的 PRE-PREPARE 应被丢弃"


def test_signer_mismatch_rejected(km):
    """B1：自称 node_0 却用 node_1 私钥签名，必须拒绝（防身份顶替）。"""
    node, calls = _mk_node('node_1', key_manager=km)
    _run(node, _signed_body(km, 'node_0', sign_as='node_1'))
    assert calls == [], "voter_id 与签名公钥不绑定时应被丢弃"


def test_block_hash_substitution_rejected(km):
    """B1：签名后偷换 block_hash（重放/篡改）必须拒绝。"""
    node, calls = _mk_node('node_1', key_manager=km)
    body = _signed_body(km, 'node_0', block_hash="honest_hash")
    body["block_hash"] = "evil_hash"          # 保持签名不变，只改内容
    _run(node, body)
    assert calls == [], "签名体覆盖的字段被改写后应验签失败"


# ---------------------------------------------------------------------------
# B2 —— 主节点必须是已知共识成员（用 insecure 模式隔离验签门）
# ---------------------------------------------------------------------------

def test_unknown_primary_rejected_even_insecure():
    """B2：即使验签门放行（insecure），非成员身份仍应被成员校验挡下。"""
    node, calls = _mk_node('node_1', allow_insecure_vote=True)
    _run(node, _unsigned_body('ghost_node'), from_node='ghost_node')
    assert calls == [], "未知主节点身份应被成员校验丢弃"


def test_known_member_allowed_in_insecure_mode():
    """对照：insecure 模式下合法成员应放行，证明上一条不是无条件拒绝。"""
    node, calls = _mk_node('node_1', allow_insecure_vote=True)
    _run(node, _unsigned_body('node_0'))
    assert len(calls) == 1, "insecure 模式下合法成员的无签名 PRE-PREPARE 应放行"


def test_state_not_reset_by_forged_preprepare():
    """回归语义：伪造 PRE-PREPARE 不得抹掉已达成的 COMMITTED 状态。"""
    from blockchain.consensus.cw_pbft import ConsensusState
    node, calls = _mk_node('node_1')
    node.cw_pbft._state = ConsensusState.COMMITTED
    _run(node, _unsigned_body('node_0'))
    assert node.cw_pbft._state == ConsensusState.COMMITTED, \
        "伪造 PRE-PREPARE 不应重置 COMMITTED（修复前此断言会失败）"
    assert calls == []


# ---------------------------------------------------------------------------
# 结构性守卫 —— 防止将来新增 handler 再次遗漏验签
# ---------------------------------------------------------------------------

def test_all_vote_handlers_call_signature_verification():
    """三个投票 handler 都必须调用 `_verify_vote_signature`。

    这是防复发的静态断言：B1 的根因不是"写错了"，而是"新增/复制 handler 时漏做"，
    只有把一致性钉成测试，才不会在下次重构中悄悄退化。
    """
    src = inspect.getsource(NetworkConsensusNode)
    parts = re.split(r"\n    (?:async )?def ", src)
    methods = {}
    for part in parts[1:]:
        methods[part.split("(", 1)[0]] = part

    for handler in ("_on_preprepare", "_on_prepare", "_on_commit"):
        assert handler in methods, f"未找到 {handler}"
        assert "_verify_vote_signature" in methods[handler], \
            f"{handler} 未调用 _verify_vote_signature —— PRE-PREPARE 裸奔缺口复发"
