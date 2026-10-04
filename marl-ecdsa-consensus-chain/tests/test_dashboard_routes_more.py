"""
dashboard consensus_votes/block_explorer 路由测试（RalphLoop 原子任务 BX）
覆盖：consensus_votes 结构、block_explorer 结构、无数据降级、merkle 占位
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

import visualization.dashboard as dash

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def client():
    app = dash._create_app()
    assert app is not None
    return app.test_client()


class TestConsensusVotes:
    def test_route_structure(self, client):
        """consensus_votes 返回完整结构"""
        r = client.get('/api/consensus_votes')
        assert r.status_code == 200
        data = r.get_json()
        for key in ['weights', 'weight_history', 'vote_phases',
                    'n_consensus_rounds', 'n_transactions',
                    'security_stats', 'consensus_type', 'contribution_weights']:
            assert key in data

    def test_vote_phases_three(self, client):
        """三阶段投票：pre-prepare/prepare/commit"""
        data = client.get('/api/consensus_votes').get_json()
        phases = [p['phase'] for p in data['vote_phases']]
        assert phases == ['pre-prepare', 'prepare', 'commit']

    def test_consensus_type(self, client):
        data = client.get('/api/consensus_votes').get_json()
        assert 'CW-PBFT' in data['consensus_type']

    def test_weights_fallback(self, client):
        """无权重数据 → 回退默认三节点权重"""
        data = client.get('/api/consensus_votes').get_json()
        weights = data['weights']
        assert 'agent_0' in weights
        assert len(weights) >= 3


class TestBlockExplorer:
    def test_route_structure(self, client):
        """block_explorer 返回完整结构"""
        r = client.get('/api/block_explorer')
        assert r.status_code == 200
        data = r.get_json()
        for key in ['blocks', 'total_blocks', 'total_transactions',
                    'chain_valid', 'ecdsa_stats', 'consensus_stats', 'blockchain_stats']:
            assert key in data

    def test_no_data_fallback(self, client):
        """无数据 → blocks 为空 + message 提示；chain_valid 为 None（未做真实链校验）

        09-28 修复：此前断言 `chain_valid is True` 把「恒真的硬编码假值」锁死为契约，
        属于「绿灯测试掩盖零校验」。现契约为：真实链校验通过=裸 True，未校验=None。
        """
        data = client.get('/api/block_explorer').get_json()
        assert 'blocks' in data
        assert data['chain_valid'] is None          # 不再谎报 True
        assert data.get('synthetic') is True        # 明示示意数据

    def test_block_fields(self, client):
        """区块字段完整（若有数据）"""
        data = client.get('/api/block_explorer').get_json()
        for b in data['blocks']:
            for key in ['height', 'hash', 'prev_hash', 'timestamp',
                        'proposer', 'tx_count', 'consensus', 'state_root']:
                assert key in b


class TestMerklePlaceholder:
    def test_merkle_placeholder_format(self):
        """state_root 占位为 0x + 16 hex"""
        root = dash._compute_merkle_placeholder(3)
        assert root.startswith('0x')
        assert len(root) == 18  # 0x + 16 字符

    def test_merkle_placeholder_deterministic(self):
        """同一索引占位一致"""
        assert dash._compute_merkle_placeholder(5) == dash._compute_merkle_placeholder(5)

    def test_merkle_placeholder_differs(self):
        """不同索引占位不同"""
        assert dash._compute_merkle_placeholder(1) != dash._compute_merkle_placeholder(2)

    def test_demo_hash_deterministic_across_process(self):
        """演示哈希必须跨进程稳定（此前用内建 hash() 受 PYTHONHASHSEED 影响，
        服务重启后同一区块编号显示成不同哈希 → 现场演示重启即穿帮）"""
        # 独立子进程重算，验证与当前进程结果一致
        import subprocess, sys as _sys
        code = ("import sys; sys.path.insert(0, '.'); "
                "from visualization.dashboard import _demo_hash; "
                "print(_demo_hash('block-7'))")
        out = subprocess.run([_sys.executable, '-c', code], cwd='.',
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == dash._demo_hash('block-7')

    def test_demo_hash_format(self):
        """演示哈希为 0x + 16 hex"""
        h = dash._demo_hash('block-0')
        assert h.startswith('0x') and len(h) == 18
        int(h[2:], 16)  # 必须是合法十六进制
