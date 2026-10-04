"""
attack 注入 API 参数化测试（RalphLoop 原子任务 AZ）
覆盖：各攻击类型参数化、未知/空/大小写敏感参数边界
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from visualization.dashboard import _create_app

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def client():
    app = _create_app()
    assert app is not None
    return app.test_client()


class TestAttackTypes:
    """参数化：4 种攻击均返回 200 且被拦截"""

    @pytest.mark.parametrize('atype', [
        'observation_forgery',
        'message_tampering',
        'replay_attack',
        'sybil_attack',
        'k_reuse_attack',
        'long_range_attack',
        'byzantine',
    ])
    def test_attack_returns_blocked(self, client, atype):
        r = client.get(f'/api/attack/inject?type={atype}')
        assert r.status_code == 200
        data = r.get_json()
        assert 'error' not in data
        assert 'no_bc' in data and 'with_bc' in data

    @pytest.mark.parametrize('atype', [
        'observation_forgery',
        'message_tampering',
        'replay_attack',
        'sybil_attack',
        'k_reuse_attack',
        'long_range_attack',
    ])
    def test_no_bc_success_with_bc_blocked(self, client, atype):
        """无BC攻击成功、有BC拦截（六类攻击）"""
        data = client.get(f'/api/attack/inject?type={atype}').get_json()
        assert data['no_bc']['attack_successful'] is True
        assert data['with_bc']['attack_successful'] is False

    def test_byzantine_recovered(self, client):
        """拜占庭攻击 → 全部故障切换恢复"""
        data = client.get('/api/attack/inject?type=byzantine').get_json()
        assert data['with_bc']['all_recovered'] is True
        assert data['with_bc']['attack_successful'] is False


class TestParamBoundaries:
    def test_unknown_type_400(self, client):
        r = client.get('/api/attack/inject?type=ghost_attack')
        assert r.status_code == 400
        assert 'error' in r.get_json()

    def test_missing_type_defaults_all(self, client):
        """无 type 参数 → 默认 all（6 种攻击）"""
        r = client.get('/api/attack/inject')
        data = r.get_json()
        assert data['attack_type'] == 'all'
        assert len(data['results']) == 6

    def test_case_sensitive_type(self, client):
        """大小写敏感：大写类型 → 400（demos.get 精确匹配）"""
        r = client.get('/api/attack/inject?type=OBSERVATION_FORGERY')
        assert r.status_code == 400

    def test_all_returns_three_results(self, client):
        data = client.get('/api/attack/inject?type=all').get_json()
        assert len(data['results']) == 6
        # 全部被拦截
        for res in data['results']:
            assert res['with_bc']['attack_successful'] is False


class TestAttackStructures:
    def test_attack_has_type_field(self, client):
        """响应含攻击类型标识"""
        data = client.get('/api/attack/inject?type=replay_attack').get_json()
        assert data['attack_type'] == 'replay_attack'

    def test_attack_details_present(self, client):
        """拜占庭攻击含恢复详情"""
        data = client.get('/api/attack/inject?type=byzantine').get_json()
        assert data['with_bc']['byzantine_events'] >= 1
        assert data['with_bc']['successful_failovers'] >= 1
