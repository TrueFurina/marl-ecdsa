# -*- coding: utf-8 -*-
"""F02 负测（2026-11-02 赛后）：激励结算的共识原子性。

反例背景（engineering_findings F02）：旧实现"先 settle 后出块、共识/追加失败
不回滚"——交易拒收/出块失败不阻止积分增加，收益支付语义脱离共识结果。
修复：结算移到链上确认之后（"仅在网络最终确认后结算"）；失败时清空本回合
奖励（无需回滚任何状态——因为尚未写入）。
"""
import hashlib
import json
import shutil
import tempfile

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.contracts.identity_contract import IdentityContract
from blockchain.contracts.incentive_contract import ContributionScore, IncentiveContract
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.ledger.blockchain import Blockchain
from blockchain.ledger.world_state import WorldState
from marl.envs.simple_spread import SimpleSpreadEnv
from marl.integration.bc_integration import BlockchainMARLBridge

AGENT_IDS = ['agent_0', 'agent_1', 'agent_2']


@pytest.fixture
def env():
    kb = tempfile.mkdtemp(prefix='test_f02_')
    ws = WorldState()
    km = KeyManager(key_dir=kb)
    idc = IdentityContract(ws)
    env = SimpleSpreadEnv(n_agents=3, n_landmarks=3, max_steps=25)
    for aid in AGENT_IDS:
        _, pk = km.generate_or_load(aid)
        ws.register_agent(aid, ECDSAUtils.public_key_to_hex(pk))
    bc = Blockchain(identity_contract=idc)
    cw = CWPBFTConsensus(node_id='agent_0', consensus_nodes=AGENT_IDS)
    bridge = BlockchainMARLBridge(
        n_agents=3, n_landmarks=3, blockchain_node=bc,
        incentive_contract=IncentiveContract(ws), identity_contract=idc,
        key_manager=km, cw_pbft_consensus=cw, lambda_weight=0.1)
    yield {'bridge': bridge, 'ws': ws, 'bc': bc, 'cw': cw, 'km': km, 'idc': idc}
    shutil.rmtree(kb, ignore_errors=True)


def _scores():
    return [ContributionScore(a, 1.0, 1.0, 1.0) for a in AGENT_IDS]


class TestSettlementAtomicity:
    def _seed_pending_tx(self, env, agent_id):
        """注入一笔真实签名交易到交易池（触发真实出块+共识路径）。"""
        from blockchain.ledger.block import Transaction
        km = env['km']
        priv = km.get_private_key(agent_id)
        act = {'step': 1}
        pkg = ECDSAUtils.sign_action(agent_id, priv, act, nonce=1)
        tx = Transaction(
            tx_id=hashlib.sha256(json.dumps(pkg['action'], sort_keys=True).encode()).hexdigest(),
            agent_id=agent_id, action=pkg['action'],
            action_hash=hashlib.sha256(json.dumps(act, sort_keys=True).encode()).hexdigest(),
            timestamp=pkg['timestamp'], nonce=pkg['nonce'],
            signature_hex=pkg['signature_hex'],
            extra={'verified': True, 'message_hex': pkg['message_hex'],
                   'r': pkg['r'], 's': pkg['s']})
        assert env['bc'].add_transaction(tx) is True

    def test_consensus_failure_skips_settlement(self, env, monkeypatch):
        """真实共识失败路径（全员省略故障拒投）→ 区块未确认 → 积分零变化。"""
        bridge = env['bridge']
        before = dict(env['ws'].get_all_scores())
        self._seed_pending_tx(env, 'agent_0')
        monkeypatch.setattr(bridge, '_get_omission_nodes', lambda: set(AGENT_IDS))
        deltas = bridge.on_episode_end(1, AGENT_IDS, [1.0, 1.0, 1.0])
        assert deltas == {}
        assert env['ws'].get_all_scores() == before  # 积分零变化
        assert all(v == 0.0 for v in bridge.get_bc_rewards().values())

    def test_commit_success_settles(self, env, monkeypatch):
        bridge = env['bridge']
        monkeypatch.setattr(bridge, '_create_and_confirm_block',
                            lambda ep, scores: True)
        before = dict(env['ws'].get_all_scores())
        deltas = bridge.on_episode_end(1, AGENT_IDS, [1.0, 1.0, 1.0])
        assert deltas and all(d != 0 for d in deltas.values())
        after = env['ws'].get_all_scores()
        assert all(after[a] > before[a] for a in AGENT_IDS)  # 合作回合积分增加
        assert bridge.get_bc_rewards() == deltas

    def test_no_pending_tx_settles_trivially(self, env):
        """无待上链交易 = 无事可确认——照常结算（登记的边界语义）。"""
        bridge = env['bridge']
        before = dict(env['ws'].get_all_scores())
        deltas = bridge.on_episode_end(1, AGENT_IDS, [1.0, 1.0, 1.0])
        assert deltas
        after = env['ws'].get_all_scores()
        assert all(after[a] > before[a] for a in AGENT_IDS)

    def test_no_chain_mode_settles(self, env):
        """无链模式（ablate 边界）：结算不受区块结果约束。"""
        bridge = env['bridge']
        bridge.bc_node = None
        deltas = bridge.on_episode_end(1, AGENT_IDS, [1.0, 1.0, 1.0])
        assert deltas

    def test_failure_does_not_leak_stale_rewards(self, env, monkeypatch):
        """成功回合后紧跟失败回合：陈旧 delta 不得混入下一回合融合奖励。

        R1 无待上链交易 → 平凡确认照常结算；R2 注入交易 + 全员拒投 → 真实
        共识失败 → 清空。两次都不打 _create_and_confirm_block 补丁。
        """
        bridge = env['bridge']
        bridge.on_episode_end(1, AGENT_IDS, [1.0, 1.0, 1.0])
        assert any(v != 0.0 for v in bridge.get_bc_rewards().values())
        self._seed_pending_tx(env, 'agent_0')
        monkeypatch.setattr(bridge, '_get_omission_nodes', lambda: set(AGENT_IDS))
        bridge.on_episode_end(2, AGENT_IDS, [1.0, 1.0, 1.0])
        assert all(v == 0.0 for v in bridge.get_bc_rewards().values())
