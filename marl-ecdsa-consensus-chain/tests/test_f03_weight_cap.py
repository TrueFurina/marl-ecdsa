# -*- coding: utf-8 -*-
"""F03 负测（2026-11-02 赛后）：加权 quorum 权重集中度上限。

反例背景（engineering_findings F03）：修复前 build_contribution_snapshot 对
share=[1,0,0] 产出 [8667,667,667]——恶意 node-1（86.67%）可同时与 {2}、{3}
凑成两张 >2/3 证书，对冲突提案双签分叉；activate 也不校验集中度。
修复：贡献权重缩放至 9999 并瀑布重分，任一单节点 ≤ total//3；激活 fail-closed。
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visualization import distributed_consensus as dc


class TestBftCapWeights:
    def test_extreme_share_collapses_to_uniform(self):
        # 修复前：share=[1,0,0] → [8667,667,667]（单节点 86.67%）
        w = dc._bft_cap_weights([0.2 / 3 + 0.8 * 1.0, 0.2 / 3, 0.2 / 3])
        assert sum(w) == dc.BFT_WEIGHT_TOTAL
        assert max(w) * 3 <= sum(w), w
        assert w == [3333, 3333, 3333]

    def test_equal_share_stays_uniform(self):
        w = dc._bft_cap_weights([1 / 3, 1 / 3, 1 / 3])
        assert w == [3333, 3333, 3333]

    def test_moderate_imbalance_capped_and_full_sum(self):
        w = dc._bft_cap_weights([0.5, 0.3, 0.2])
        assert sum(w) == dc.BFT_WEIGHT_TOTAL
        assert max(w) * 3 <= sum(w)

    def test_validation_rejects_findings_counterexample(self):
        with pytest.raises(ValueError):
            dc.validate_weight_cap([8667, 667, 667])

    def test_validation_rejects_static_legacy(self):
        with pytest.raises(ValueError):
            dc.validate_weight_cap([4, 3, 3])  # 旧静态配置：node-1 40%

    def test_validation_rejects_over_cap_candidate(self):
        with pytest.raises(ValueError):
            dc.validate_weight_cap([5000, 2500, 2500])

    def test_validation_accepts_capped_vectors(self):
        assert dc.validate_weight_cap([3, 3, 3]) == [3, 3, 3]
        assert dc.validate_weight_cap([3333, 3333, 3333]) == [3333, 3333, 3333]


class TestForkImpossibility:
    def _cfg(self, weights):
        return {'network': 'test-f03', 'version': 1,
                'peers': [{'id': f'node-{i+1}', 'weight': w,
                           'public_key': dc.pubkey(self.keys[i])}
                          for i, w in enumerate(weights)]}

    @pytest.fixture(autouse=True)
    def _keys(self):
        self.keys = [dc.ec.generate_private_key(dc.ec.SECP256R1()) for _ in range(3)]

    def test_only_unanimous_quorum_exists_under_cap(self):
        """cap 下唯一 >2/3 子集是全集——恶意单节点无法绕开诚实节点凑证书。"""
        cfg = self._cfg([3333, 3333, 3333])
        total = sum(n['weight'] for n in cfg['peers'])
        quorums = []
        for mask in range(1, 8):
            subset = [i for i in range(3) if mask >> i & 1]
            weight = sum(cfg['peers'][i]['weight'] for i in subset)
            if len(subset) >= 2 and weight * 3 > total * 2:
                quorums.append(tuple(subset))
        assert quorums == [(0, 1, 2)]
        # 交集论证：任意两张证书的投票集都是全集 ⇒ 诚实节点必然在交集内

    def test_legacy_weights_allow_fork_pairs(self):
        """修复前 [4,3,3]：存在交集仅为 node-1 的两张 quorum（分叉自由度）。"""
        cfg = self._cfg([4, 3, 3])
        total = sum(n['weight'] for n in cfg['peers'])
        quorums = []
        for mask in range(1, 8):
            subset = [i for i in range(3) if mask >> i & 1]
            weight = sum(cfg['peers'][i]['weight'] for i in subset)
            if len(subset) >= 2 and weight * 3 > total * 2:
                quorums.append(tuple(subset))
        assert (0, 1) in quorums and (0, 2) in quorums  # 交集={0}

    def test_malicious_alone_cannot_certify(self):
        """恶意单节点（3333/9999）的 PREPARE 证书不过 quorum 线。"""
        import json
        cfg = self._cfg([3333, 3333, 3333])
        payload = {'kind': 'attack', 'side': 'B'}
        txid = dc.digest(payload)
        proposal = {'snapshot': dc.snapshot_digest(cfg), 'phase': 'PREPARE',
                    'network': cfg['network'], 'height': 1, 'previous': '0' * 64,
                    'transaction': {'txid': txid, 'payload': payload,
                                    'public_key': dc.pubkey(self.keys[0]),
                                    'signature': dc.sign(self.keys[0], payload)}}
        assert dc.proposal_valid(proposal)
        msg = dc.vote_message(proposal)
        malicious_only = {'proposal_hash': dc.digest(proposal),
                          'votes': [{'node': 'node-1',
                                     'signature': dc.sign(self.keys[0], msg)}]}
        assert not dc.certificate_valid(cfg, proposal, malicious_only)
        # 全体签署（诚实节点被骗共同签署）才构成有效证书——分叉需诚实方合谋
        all_votes = {'proposal_hash': dc.digest(proposal),
                     'votes': [{'node': n['id'],
                                'signature': dc.sign(k, msg)}
                               for n, k in zip(cfg['peers'], self.keys)]}
        assert dc.certificate_valid(cfg, proposal, all_votes)


class TestContributionSnapshotCap:
    def test_build_snapshot_weights_capped(self, tmp_path):
        root = Path(dc.__file__).resolve().parent.parent / 'results' / 'contribution'
        root.mkdir(parents=True, exist_ok=True)
        fixture = root / '_f03_test_fixture.json'
        fixture.write_text(json.dumps({
            'agent_ids': ['agent_0', 'agent_1', 'agent_2'],
            'records': [{'contribution_share': [1.0, 0.0, 0.0]},
                        {'contribution_share': [1.0, 0.0, 0.0]}],
        }, ensure_ascii=False), encoding='utf-8')
        try:
            snap = dc.build_contribution_snapshot(str(fixture))
            ws = snap['weights']
            assert sum(ws) == dc.BFT_WEIGHT_TOTAL
            assert max(ws) * 3 <= sum(ws)
            assert ws == [3333, 3333, 3333]  # 修复前此处是 [8667,667,667]
        finally:
            os.unlink(fixture)
