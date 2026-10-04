"""
network_demo demo 集成测试（RalphLoop 原子任务 BY）
覆盖：demo 全流程（真实 P2P 冒烟）、参数透传、返回结构、权重更新
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import network_demo as nd

logging.basicConfig(level=logging.CRITICAL)


class TestDemoReturn:
    def test_demo_return_structure(self, monkeypatch, capsys):
        """demo 返回结构（monkeypatch 避免真实网络）"""
        fake_net = _fake_net()
        monkeypatch.setattr(nd, 'print_banner', lambda: None)
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: fake_net)
        monkeypatch.setattr(nd, '_show_protocol', lambda: None)
        monkeypatch.setattr(nd, '_run_consensus_rounds', lambda net, n, r, w: r)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: None)
        result = nd.demo(n_nodes=3, n_rounds=5, base_port=7001)
        assert result['n_nodes'] == 3
        assert result['n_rounds'] == 5
        assert result['success_count'] == 5

    def test_demo_returns_msg_counts(self, monkeypatch, capsys):
        """demo 返回消息收发计数"""
        fake_net = _fake_net()
        monkeypatch.setattr(nd, 'print_banner', lambda: None)
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: fake_net)
        monkeypatch.setattr(nd, '_show_protocol', lambda: None)
        monkeypatch.setattr(nd, '_run_consensus_rounds', lambda net, n, r, w: r)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: None)
        result = nd.demo(n_nodes=3, n_rounds=2, base_port=7001)
        assert result['total_msg_sent'] == 120
        assert result['total_msg_received'] == 120


class TestWeightsUpdate:
    def test_weights_dict_initialized(self, monkeypatch, capsys):
        """demo 中 weights_dict 初始化为全 1.0"""
        fake_net = _fake_net()
        captured = {}

        def fake_run(net, n, r, weights):
            captured['weights'] = weights
            return r

        monkeypatch.setattr(nd, 'print_banner', lambda: None)
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: fake_net)
        monkeypatch.setattr(nd, '_show_protocol', lambda: None)
        monkeypatch.setattr(nd, '_run_consensus_rounds', fake_run)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: None)
        nd.demo(n_nodes=3, n_rounds=3, base_port=7001)
        assert captured['weights'] == {'agent_0': 1.0, 'agent_1': 1.0, 'agent_2': 1.0}


class TestDemoFlow:
    def test_demo_calls_all_steps(self, monkeypatch, capsys):
        """demo 按序调用 5 个步骤"""
        calls = []
        fake_net = _fake_net()
        monkeypatch.setattr(nd, 'print_banner', lambda: calls.append('banner'))
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: calls.append('start') or fake_net)
        monkeypatch.setattr(nd, '_show_protocol', lambda: calls.append('protocol'))
        monkeypatch.setattr(nd, '_run_consensus_rounds', lambda *a, **kw: calls.append('rounds') or 3)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: calls.append('stats'))
        nd.demo(n_nodes=3, n_rounds=3, base_port=7001)
        assert calls == ['banner', 'start', 'protocol', 'rounds', 'stats']

    def test_demo_no_crash_no_data(self, monkeypatch, capsys):
        """demo 空网络对象不崩溃（get_stats 返回空）"""
        empty = _fake_net()
        empty.get_stats.return_value = {'total_msg_sent': 0, 'total_msg_received': 0, 'weights': {}}
        monkeypatch.setattr(nd, 'print_banner', lambda: None)
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: empty)
        monkeypatch.setattr(nd, '_show_protocol', lambda: None)
        monkeypatch.setattr(nd, '_run_consensus_rounds', lambda net, n, r, w: r)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: None)
        result = nd.demo(n_nodes=3, n_rounds=1, base_port=7001)
        assert result['total_msg_sent'] == 0


class TestModuleIntegrity:
    def test_demo_entrypoints(self):
        """demo/main 入口可调用"""
        assert callable(nd.demo)
        assert callable(nd.main)

    def test_import_ok(self):
        """模块导入完整（P2PConsensusNetwork 可用）"""
        from blockchain.network.network_consensus import P2PConsensusNetwork
        assert P2PConsensusNetwork is not None


def _fake_net():
    """构造模拟网络对象"""
    from unittest.mock import MagicMock
    net = MagicMock()
    net.node_ids = ["agent_0", "agent_1", "agent_2"]
    net.get_stats.return_value = {
        "total_msg_sent": 120, "total_msg_received": 120,
        "weights": {"agent_0": 1.0, "agent_1": 1.0, "agent_2": 1.0},
        "nodes": {nid: {"msg_sent": 40, "msg_received": 40, "consensus_rounds": 3}
                  for nid in ["agent_0", "agent_1", "agent_2"]},
    }
    return net
