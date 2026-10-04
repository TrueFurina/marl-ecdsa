"""
Dashboard 攻防演示 API 测试
覆盖 /api/attack/inject 全部攻击类型 + 关键页面/接口回归
（Web 面板一键注入攻击演示，CCF 竞赛功能）
"""
import logging

import pytest

from visualization.dashboard import _create_app

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture(scope="module")
def client():
    app = _create_app()
    assert app is not None, "Flask 应用创建失败"
    return app.test_client()


class TestAttackInjectAPI:
    """攻防演示 API：每种攻击应返回 200 且区块链防护拦截攻击"""

    def test_observation_forgery(self, client):
        r = client.get('/api/attack/inject?type=observation_forgery')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'observation_forgery'
        # 无BC基线攻击成功，有BC防护拦截
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_message_tampering(self, client):
        r = client.get('/api/attack/inject?type=message_tampering')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'message_tampering'
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_replay_attack(self, client):
        r = client.get('/api/attack/inject?type=replay_attack')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'replay_attack'
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_sybil_attack(self, client):
        r = client.get('/api/attack/inject?type=sybil_attack')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'sybil_attack'
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_k_reuse_attack(self, client):
        r = client.get('/api/attack/inject?type=k_reuse_attack')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'k_reuse_attack'
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_long_range_attack(self, client):
        r = client.get('/api/attack/inject?type=long_range_attack')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'long_range_attack'
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_byzantine_primary(self, client):
        r = client.get('/api/attack/inject?type=byzantine')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'byzantine_primary'
        # 拜占庭事件全部由动态故障切换恢复 → 防护拦截
        assert data['with_bc']['attack_successful'] is False
        assert data['with_bc']['all_recovered'] is True
        assert data['with_bc']['byzantine_events'] >= 1

    def test_all_attacks(self, client):
        r = client.get('/api/attack/inject?type=all')
        assert r.status_code == 200
        data = r.get_json()
        assert data['attack_type'] == 'all'
        assert len(data['results']) == 6
        # 全部被拦截
        for res in data['results']:
            assert res['with_bc']['attack_successful'] is False

    def test_unknown_attack_type(self, client):
        r = client.get('/api/attack/inject?type=not_a_real_attack')
        assert r.status_code == 400
        assert 'error' in r.get_json()


class TestDashboardRegression:
    """关键页面与接口回归"""

    def test_index_page(self, client):
        r = client.get('/')
        assert r.status_code == 200
        assert b'MARL-ECDSA' in r.data or b'marl' in r.data.lower()

    def test_consensus_votes_api(self, client):
        r = client.get('/api/consensus_votes')
        assert r.status_code == 200
        data = r.get_json()
        assert 'weights' in data
        assert 'vote_phases' in data

    def test_block_explorer_api(self, client):
        r = client.get('/api/block_explorer')
        assert r.status_code == 200
        data = r.get_json()
        assert 'blocks' in data

    def test_healthz(self, client):
        r = client.get('/healthz')
        assert r.status_code == 200
        assert r.get_json()['status'] == 'ok'
