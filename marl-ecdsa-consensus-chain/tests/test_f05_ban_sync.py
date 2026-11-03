# -*- coding: utf-8 -*-
"""F05 负测（2026-11-02 赛后）：封禁状态同步到共识权重与链准入。

反例背景（engineering_findings F05）：世界状态的封禁/降级只写不读——
① bc_integration._update_consensus_weights 按 ContributionScore 更新权重，
   不读身份状态（封禁身份仍带 1.0–1.5 满权重投票）；
② Blockchain._validate_new_block 只验"持有注册私钥"，封禁身份交易照样过；
③ world_state.set_agent_status 只改 status 不同步 consensus_weight（内部失同步）。
"""
import hashlib
import json
import shutil
import tempfile

import pytest

from blockchain.contracts.identity_contract import ContractCaller, IdentityContract
from blockchain.contracts.incentive_contract import ContributionScore, IncentiveContract
from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.ledger.blockchain import Blockchain
from blockchain.ledger.world_state import AgentStatus, WorldState
from marl.envs.simple_spread import SimpleSpreadEnv
from marl.integration.bc_integration import BlockchainMARLBridge

AGENT_IDS = ['agent_0', 'agent_1', 'agent_2']


@pytest.fixture
def env():
    kb = tempfile.mkdtemp(prefix='test_f05_')
    ws = WorldState()
    km = KeyManager(key_dir=kb)
    idc = IdentityContract(ws)
    env = SimpleSpreadEnv(n_agents=3, n_landmarks=3, max_steps=25)
    for i, aid in enumerate(AGENT_IDS):
        _, pk = km.generate_or_load(aid)
        ws.register_agent(aid, ECDSAUtils.public_key_to_hex(pk))
    bc = Blockchain(identity_contract=idc)
    cw = CWPBFTConsensus(node_id='agent_0', consensus_nodes=AGENT_IDS)
    bridge = BlockchainMARLBridge(
        n_agents=3, n_landmarks=3, blockchain_node=bc,
        incentive_contract=IncentiveContract(ws), identity_contract=idc,
        key_manager=km, cw_pbft_consensus=cw, lambda_weight=0.1)
    yield {'bridge': bridge, 'ws': ws, 'idc': idc, 'bc': bc, 'km': km, 'cw': cw}
    shutil.rmtree(kb, ignore_errors=True)


def _scores():
    return [ContributionScore(a, 1.0, 1.0, 1.0) for a in AGENT_IDS]


class TestConsensusWeightSync:
    def test_banned_agent_weight_zeroed(self, env):
        env['idc'].update_status('agent_1', 'banned', ContractCaller.PENALTY)
        assert env['ws'].get_consensus_weight('agent_1') == 0.0
        env['bridge']._update_consensus_weights(_scores())
        assert env['cw']._weights['agent_1'] == 0.0
        assert env['cw']._weights['agent_0'] >= 1.0  # 正常身份不受牵连

    def test_demoted_agent_weight_scaled(self, env):
        env['idc'].update_status('agent_2', 'demoted', ContractCaller.PENALTY)
        env['bridge']._update_consensus_weights(_scores())
        base = (CWPBFTConsensus.WEIGHT_BASE
                + CWPBFTConsensus.WEIGHT_GAIN
                * _scores()[0].weighted_score)
        assert env['cw']._weights['agent_2'] == pytest.approx(base * 0.3)
        assert env['cw']._weights['agent_2'] < env['cw']._weights['agent_0']

    def test_set_agent_status_syncs_weight(self, env):
        """③ 状态/权重失同步修复：set_agent_status 必须同步 consensus_weight。"""
        env['ws'].set_agent_status('agent_0', AgentStatus.BANNED)
        assert env['ws'].get_consensus_weight('agent_0') == 0.0
        env['ws'].set_agent_status('agent_0', AgentStatus.DEMOTED)
        assert env['ws'].get_consensus_weight('agent_0') == 0.3
        env['ws'].set_agent_status('agent_0', AgentStatus.ACTIVE)
        assert env['ws'].get_consensus_weight('agent_0') == 1.0


class TestChainAdmission:
    def _signed_tx(self, env, agent_id, action=None):
        km = env['km']
        priv = km.get_private_key(agent_id)
        act = action or {'step': 1}
        pkg = ECDSAUtils.sign_action(agent_id, priv, act, nonce=1)
        from blockchain.ledger.block import Transaction
        return Transaction(
            tx_id=hashlib.sha256(json.dumps(pkg['action'], sort_keys=True).encode()).hexdigest(),
            agent_id=agent_id, action=pkg['action'],
            action_hash=hashlib.sha256(json.dumps(act, sort_keys=True).encode()).hexdigest(),
            timestamp=pkg['timestamp'], nonce=pkg['nonce'],
            signature_hex=pkg['signature_hex'],
            extra={'verified': True, 'message_hex': pkg['message_hex'],
                   'r': pkg['r'], 's': pkg['s']})

    def _block(self, env, tx):
        from blockchain.ledger.block import Block
        tip = env['bc']._chain[-1]
        blk = Block(block_height=tip.block_height + 1, previous_hash=tip.block_hash,
                    timestamp=pkg_ts(tx), proposer='agent_0',
                    transactions=[tx], state_root='')
        # 2026-11-02（区块级校验启用后）：本测试须产出**真实有效的区块**
        # （state_root 可重算 + 出块者签名可验），否则「交易被拒」可能是被
        # 区块级校验拦下造成的假阳性，负测失去意义。
        blk.finalize()
        blk.sign_block(key_manager=env['km'], agent_id='agent_0')
        return blk

    def test_banned_agent_tx_rejected(self, env):
        env['idc'].update_status('agent_1', 'banned', ContractCaller.PENALTY)
        tx = self._signed_tx(env, 'agent_1')
        blk = self._block(env, tx)
        assert env['bc'].append_block(blk) is False

    def test_active_agent_tx_accepted(self, env):
        tx = self._signed_tx(env, 'agent_0')
        blk = self._block(env, tx)
        assert env['bc'].append_block(blk) is True


def pkg_ts(tx):
    return tx.timestamp
