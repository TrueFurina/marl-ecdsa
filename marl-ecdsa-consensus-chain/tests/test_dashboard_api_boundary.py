"""
dashboard 数据 API 边界测试（RalphLoop 原子任务 AW）
覆盖：status/data/p2p_stats/load 路由返回结构与边界
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from visualization.dashboard import _create_app, _dashboard_data

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def client():
    app = _create_app()
    assert app is not None
    return app.test_client()


class TestStatusAPI:
    def test_status_ok(self, client):
        r = client.get('/api/status')
        assert r.status_code == 200
        data = r.get_json()
        assert 'comparison_baseline' in data

    def test_healthz(self, client):
        r = client.get('/healthz')
        assert r.status_code == 200
        assert r.get_json()['status'] == 'ok'


class TestDataAPI:
    def test_data_structure(self, client):
        r = client.get('/api/data')
        assert r.status_code == 200
        data = r.get_json()
        for key in ['status', 'ecdsa_stats', 'security_stats', 'consensus_stats',
                    'blockchain_stats', 'signing_stats', 'recorder_stats',
                    'detector_stats', 'settlement_stats']:
            assert key in data

    def test_data_status_has_baseline(self, client):
        data = client.get('/api/data').get_json()
        assert 'comparison_baseline' in data['status']


class TestP2PStatsAPI:
    def test_p2p_disabled_when_no_data(self, client):
        # 清空实时数据 → p2p 未启用分支
        _dashboard_data['consensus_stats'] = {}
        _dashboard_data['blockchain_stats'] = {}
        r = client.get('/api/p2p_stats')
        assert r.status_code == 200
        data = r.get_json()
        assert data['p2p_enabled'] is False
        assert data['n_nodes'] == 0

    def test_p2p_enabled_with_weights(self, client):
        # 注入权重数据 → p2p 启用分支
        _dashboard_data['consensus_stats'] = {'weights': {'agent_0': 1.0, 'agent_1': 1.0}}
        _dashboard_data['blockchain_stats'] = {'height': 5}
        r = client.get('/api/p2p_stats')
        data = r.get_json()
        assert data['p2p_enabled'] is True
        assert data['n_nodes'] == 3
        assert 'agent_0' in data['weights']


class TestLoadAPI:
    def test_load_unknown_mode_404(self, client):
        r = client.get('/api/load/not_a_mode')
        assert r.status_code == 404
        assert 'error' in r.get_json()

    def test_load_known_mode_returns_json_or_404(self, client):
        """已知 mode：有结果文件返回 200，否则 404（两种都合法）"""
        r = client.get('/api/load/pure')
        assert r.status_code in (200, 404)
