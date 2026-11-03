# -*- coding: utf-8 -*-
"""F04 Web 接线负测（2026-11-02 赛后）：存证失败现场的登记/续跑/清障端点。"""
import json

import pytest

from visualization import business_service as biz
from visualization import distributed_consensus as dc
from visualization.dashboard import _create_app

USER = 'f04probe'
PASSWORD = 'probe123abc'


def _h(client):
    return {'X-CSRF-Token': getattr(client, '_f04_csrf', '')}


@pytest.fixture
def client():
    app = _create_app()
    app.config['TESTING'] = True
    c = app.test_client()
    reg = c.get('/register')
    import re
    m = re.search(r'name="([^"]*csrf[^"]*)"[^>]*value="([^"]+)"', reg.get_data(as_text=True))
    token = m.group(2) if m else ''
    c.post('/register', data={'username': USER, 'password': PASSWORD,
                              'confirm': PASSWORD, (m.group(1) if m else '_csrf'): token})
    login = c.get('/login')
    m2 = re.search(r'name="([^"]*csrf[^"]*)"[^>]*value="([^"]+)"', login.get_data(as_text=True))
    c.post('/login', data={'username': USER, 'password': PASSWORD,
                           (m2.group(1) if m2 else '_csrf'): m2.group(2) if m2 else ''})
    # 登录会轮换 session._csrf：从登录后首页的 window.APP_CSRF 取现行令牌
    home = c.get('/').get_data(as_text=True)
    import re as _re
    m3 = _re.search(r'APP_CSRF=(?:"([^"]+)"|([^;<\s]+))', home)
    c._f04_csrf = (m3.group(1) or m3.group(2)) if m3 else ''
    yield c
    biz.pop_pending_submit('1')


def _fake_propose(status='quorum_failed'):
    def fake(tx, **kw):
        return {'status': status, 'txid': tx['txid'], 'resumable': status == 'quorum_failed',
                'events': []}
    return fake


class TestWebWiring:
    def test_resume_without_pending_404(self, client):
        assert client.post('/api/distributed/resume', headers=_h(client)).status_code == 404

    def test_submit_registers_pending_on_quorum_failed(self, client, monkeypatch):
        monkeypatch.setattr(dc, 'propose', _fake_propose('quorum_failed'))
        r = client.post('/api/distributed/submit', json={'content': 'f04 wiring'}, headers=_h(client))
        assert r.status_code == 202
        pending = biz.get_pending_submit('1')
        assert pending and pending['txid']
        p = client.get('/api/distributed/pending').get_json()
        assert p['my_pending']['txid'] == pending['txid']

    def test_resume_replicates_and_clears(self, client, monkeypatch):
        biz.remember_pending_submit('1', {'txid': 'abc', 'payload': {}}, {'txid': 'abc'})
        monkeypatch.setattr(dc, 'propose', _fake_propose('replicated'))
        r = client.post('/api/distributed/resume', headers=_h(client))
        assert r.status_code == 201
        assert r.get_json()['status'] == 'replicated'
        assert biz.get_pending_submit('1') is None

    def test_resume_failure_keeps_pending(self, client, monkeypatch):
        biz.remember_pending_submit('1', {'txid': 'abc'}, {'txid': 'abc'})
        monkeypatch.setattr(dc, 'propose', _fake_propose('quorum_failed'))
        assert client.post('/api/distributed/resume', headers=_h(client)).status_code == 202
        assert biz.get_pending_submit('1') is not None  # 保留现场，可再次续跑

    def test_abort_endpoint(self, client, monkeypatch):
        biz.remember_pending_submit('1', {'txid': 'abc'}, {'txid': 'abc'})
        monkeypatch.setattr(dc, 'abort_pending_round',
                            lambda: {'coordinated': True, 'aborted_height': 1, 'ok_count': 3})
        r = client.post('/api/distributed/abort-pending', headers=_h(client))
        assert r.status_code == 200
        assert biz.get_pending_submit('1') is None
