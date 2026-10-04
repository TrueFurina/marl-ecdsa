"""
dashboard start_dashboard 启动测试（RalphLoop 原子任务 BG）
覆盖：无 Flask 降级、有 Flask 启动线程、_run_server 调用、update_data 桥接
通过标准：新增 ≥6 项测试全过
"""
import logging
import threading
from unittest.mock import MagicMock

import pytest

import visualization.dashboard as dash

logging.basicConfig(level=logging.CRITICAL)


class TestNoFlaskFallback:
    def test_start_dashboard_without_flask_returns(self, monkeypatch):
        """无 Flask → start_dashboard 直接返回（不启动线程）"""
        monkeypatch.setattr(dash, 'HAS_FLASK', False)
        monkeypatch.setattr(dash.threading, 'Thread', lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不应启动线程")))
        result = dash.start_dashboard(port=9191)  # 应直接 return，不启动线程
        assert result is None


class TestRunServer:
    def test_run_server_flask_unavailable(self, monkeypatch):
        """_run_server 无 Flask → 记录错误并返回"""
        monkeypatch.setattr(dash, '_create_app', lambda: None)
        dash._run_server(host='127.0.0.1', port=9292)  # 不抛异常


class TestStartDashboard:
    def test_starts_thread_when_flask_available(self, monkeypatch):
        """有 Flask → 启动守护线程"""
        captured = {}

        class FakeThread:
            def __init__(self, target=None, args=None, daemon=False):
                captured['target'] = target
                captured['args'] = args
                captured['daemon'] = daemon

            def start(self):
                captured['started'] = True

        monkeypatch.setattr(dash, 'HAS_FLASK', True)
        monkeypatch.setattr(dash.threading, 'Thread', FakeThread)
        dash.start_dashboard(port=9393)
        assert captured.get('started') is True
        assert captured.get('daemon') is True  # 守护线程

    def test_thread_target_is_run_server(self, monkeypatch):
        """线程目标为 _run_server"""
        captured = {}
        monkeypatch.setattr(dash, 'HAS_FLASK', True)

        class FakeThread:
            def __init__(self, target=None, args=None, daemon=False):
                captured['target'] = target

            def start(self):
                pass

        monkeypatch.setattr(dash.threading, 'Thread', FakeThread)
        dash.start_dashboard(port=9494)
        assert captured['target'] == dash._run_server

    def test_update_data_called_with_stats(self, monkeypatch):
        """有 stats → 调用 update_data 桥接"""
        monkeypatch.setattr(dash, 'HAS_FLASK', True)

        class FakeThread:
            def __init__(self, *a, **kw):
                pass

            def start(self):
                pass

        monkeypatch.setattr(dash.threading, 'Thread', FakeThread)
        called = {}

        def fake_update(stats, trainer):
            called['stats'] = stats

        monkeypatch.setattr(dash, 'update_data', fake_update)
        stats = MagicMock()
        dash.start_dashboard(stats=stats)
        assert called.get('stats') is stats


class TestCreateApp:
    def test_create_app_returns_flask(self):
        """_create_app 返回 Flask 应用（含路由）"""
        app = dash._create_app()
        assert app is not None
        rules = sorted(str(r) for r in app.url_map.iter_rules())
        assert '/api/status' in rules
        assert '/api/attack/inject' in rules
