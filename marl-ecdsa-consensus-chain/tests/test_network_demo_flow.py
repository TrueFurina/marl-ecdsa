"""
network_demo 流程函数测试（RalphLoop 原子任务 AY）
覆盖：_print_stats 统计打印、demo 主流程返回结构、SimpleFormatter 格式
通过标准：新增 ≥6 项测试全过
"""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import network_demo as nd

logging.basicConfig(level=logging.CRITICAL)


def _fake_net():
    """构造模拟网络对象（含 get_stats）"""
    net = MagicMock()
    net.node_ids = ["agent_0", "agent_1", "agent_2"]
    net.get_stats.return_value = {
        "total_msg_sent": 120, "total_msg_received": 120,
        "weights": {"agent_0": 1.0, "agent_1": 1.0, "agent_2": 1.0},
        "nodes": {
            "agent_0": {"msg_sent": 40, "msg_received": 40, "consensus_rounds": 5},
            "agent_1": {"msg_sent": 40, "msg_received": 40, "consensus_rounds": 5},
            "agent_2": {"msg_sent": 40, "msg_received": 40, "consensus_rounds": 5},
        },
    }
    return net


class TestPrintStats:
    def test_print_stats_output(self, capsys):
        """统计打印含关键信息"""
        nd._print_stats(_fake_net(), 3, 5, 5)
        out = capsys.readouterr().out
        assert "Nodes" in out
        assert "success=5/5" in out
        assert "100.0%" in out  # 成功率

    def test_print_stats_success_rate(self, capsys):
        """成功率计算：2/5=40%"""
        nd._print_stats(_fake_net(), 3, 5, 2)
        out = capsys.readouterr().out
        assert "success=2/5" in out
        assert "40.0%" in out

    def test_print_stats_calls_stop(self):
        """统计打印后调用 net.stop()"""
        net = _fake_net()
        nd._print_stats(net, 3, 5, 5)
        net.stop.assert_called_once()


class TestDemo:
    def test_demo_returns_dict(self, monkeypatch, capsys):
        """demo 主流程返回结果 dict（monkeypatch 避免实际网络）"""
        monkeypatch.setattr(nd, 'print_banner', lambda: None)
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: _fake_net())
        monkeypatch.setattr(nd, '_show_protocol', lambda: None)
        monkeypatch.setattr(nd, '_run_consensus_rounds', lambda net, n, r, w: r)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: None)
        result = nd.demo(n_nodes=3, n_rounds=5, base_port=7001)
        assert result["n_nodes"] == 3
        assert result["n_rounds"] == 5
        assert result["success_count"] == 5

    def test_demo_returns_weights(self, monkeypatch, capsys):
        """demo 返回权重信息"""
        monkeypatch.setattr(nd, 'print_banner', lambda: None)
        monkeypatch.setattr(nd, '_start_network', lambda n, p, **kw: _fake_net())
        monkeypatch.setattr(nd, '_show_protocol', lambda: None)
        monkeypatch.setattr(nd, '_run_consensus_rounds', lambda net, n, r, w: r)
        monkeypatch.setattr(nd, '_print_stats', lambda *a, **kw: None)
        result = nd.demo(n_nodes=3, n_rounds=2, base_port=7001)
        assert "agent_0" in result["weights"]


class TestSimpleFormatter:
    def test_formatter_prefix(self):
        """SimpleFormatter 输出含时间/级别/名称前缀"""
        import logging as _log
        record = _log.LogRecord(name="test_mod", level=_log.INFO, pathname=__file__,
                                lineno=1, msg="hello", args=(), exc_info=None)
        fmt = nd.SimpleFormatter()
        out = fmt.format(record)
        assert "INFO" in out
        assert "test_mod" in out
        assert "hello" in out


class TestModuleIntegrity:
    def test_demo_importable(self):
        assert callable(nd.demo)
        assert callable(nd._print_stats)
        assert callable(nd._start_network)
        assert callable(nd._run_consensus_rounds)
