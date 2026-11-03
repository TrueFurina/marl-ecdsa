"""F09：validate_chain(deep=True) 全链深度复验的证伪测试。
证明：默认 validate_chain 漏掉的「历史交易改明文而保留 tx_id（块哈希不变）」，
深验能通过重算 state_root + 逐交易 ECDSA 复验捕获。复用 f05 的真实签名链配方。"""
import hashlib
import json
import shutil
import tempfile

import pytest

from blockchain.contracts.identity_contract import IdentityContract
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.ledger.block import Block, Transaction
from blockchain.ledger.blockchain import Blockchain
from blockchain.ledger.world_state import WorldState

AGENTS = ['agent_0', 'agent_1', 'agent_2']


@pytest.fixture
def env():
    kb = tempfile.mkdtemp(prefix='f09_')
    ws = WorldState()
    km = KeyManager(key_dir=kb)
    idc = IdentityContract(ws)
    for aid in AGENTS:
        _, pk = km.generate_or_load(aid)
        ws.register_agent(aid, ECDSAUtils.public_key_to_hex(pk))
    bc = Blockchain(identity_contract=idc)
    yield {'bc': bc, 'km': km, 'idc': idc, 'ws': ws, 'kb': kb}
    shutil.rmtree(kb, ignore_errors=True)


def _signed_tx(env, agent_id, action=None):
    priv = env['km'].get_private_key(agent_id)
    act = action or {'step': 1}
    pkg = ECDSAUtils.sign_action(agent_id, priv, act, nonce=1)
    return Transaction(
        tx_id=hashlib.sha256(json.dumps(pkg['action'], sort_keys=True).encode()).hexdigest(),
        agent_id=agent_id, action=pkg['action'],
        action_hash=hashlib.sha256(json.dumps(act, sort_keys=True).encode()).hexdigest(),
        timestamp=pkg['timestamp'], nonce=pkg['nonce'], signature_hex=pkg['signature_hex'],
        extra={'verified': True, 'message_hex': pkg['message_hex'], 'r': pkg['r'], 's': pkg['s']})


def _append_block(env, tx):
    bc = env['bc']
    tip = bc._chain[-1]
    blk = Block(block_height=tip.block_height + 1, previous_hash=tip.block_hash,
                timestamp=tx.timestamp, proposer='agent_0', transactions=[tx], state_root='')
    blk.finalize()
    blk.sign_block(key_manager=env['km'], agent_id='agent_0')
    assert bc.append_block(blk) is True
    return blk


def test_clean_strict_chain_passes_deep(env):
    _append_block(env, _signed_tx(env, 'agent_0'))
    _append_block(env, _signed_tx(env, 'agent_1', {'step': 2}))
    assert env['bc'].validate_chain(deep=False) is True
    assert env['bc'].validate_chain(deep=True) is True   # 正常严格链深验也应通过


def test_deep_catches_action_tamper_that_default_misses(env):
    blk = _append_block(env, _signed_tx(env, 'agent_0', {'step': 1}))
    assert env['bc'].validate_chain(deep=True) is True
    # 篡改历史交易的 action 明文，但保留 tx_id / action_hash 字段 → 块哈希不变
    tx = env['bc']._chain[-1].transactions[0]
    tx.action = {'step': 999, 'injected': True}
    tampered_hash = env['bc']._chain[-1]._compute_hash()
    assert tampered_hash == env['bc']._chain[-1].block_hash  # 哈希层面看不出篡改
    assert env['bc'].validate_chain(deep=False) is True       # 默认：仅比对哈希 → 漏过
    assert env['bc'].validate_chain(deep=True) is False       # 深验：ECDSA 复验 action → 捕获


def test_stub_chain_not_false_flagged(env):
    # 未配 identity_contract 的合成链：深验按同一门控跳过内容校验，不应误判
    bc = Blockchain(allow_unsigned_stub=True)
    for i in range(1, 3):
        tip = bc._chain[-1]
        tx = Transaction(tx_id=f"stub{i}", agent_id="agent_x", action={}, action_hash="h",
                         timestamp=i, nonce=i, signature_hex="", extra={})
        blk = Block(block_height=tip.block_height + 1, previous_hash=tip.block_hash,
                    timestamp=i, proposer="agent_x", transactions=[tx], state_root="")
        blk.finalize()
        assert bc.append_block(blk) is True
    assert bc.validate_chain(deep=True) is True   # stub 门控放行，不假阳性
