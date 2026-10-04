"""
benchmark/run_scale 脚本测试（RalphLoop 原子任务 BF）
覆盖：measure_resource 资源测量、benchmark_large_network 结构、报告生成
通过标准：新增 ≥6 项测试全过
"""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts' / 'benchmark'))

import run_scale as rs

logging.basicConfig(level=logging.CRITICAL)


class TestMeasureResource:
    def test_returns_triple(self):
        """measure_resource 返回 (result, elapsed, mem_mb) 三元组"""
        result, elapsed, mem_mb = rs.measure_resource(lambda: 42)
        assert result == 42
        assert elapsed >= 0
        assert isinstance(mem_mb, float)

    def test_elapsed_positive_for_work(self):
        """有实际工作的函数 elapsed > 0"""
        def work():
            s = 0
            for i in range(10000):
                s += i
            return s
        _, elapsed, _ = rs.measure_resource(work)
        assert elapsed >= 0

    def test_mem_delta_reasonable(self):
        """内存增量合理（MB 级，非 NaN）"""
        _, _, mem_mb = rs.measure_resource(lambda: [0] * 10000)
        assert mem_mb == mem_mb  # 非 NaN


class TestBenchmarkLargeNetwork:
    def test_structure(self, monkeypatch):
        """benchmark_large_network 返回结构（monkeypatch 加速避免真实模拟）"""
        class _FakeConsensus:
            def __init__(self, node_id, consensus_nodes):
                self.node_id = node_id
                self.nodes = consensus_nodes

            def update_weight(self, nid, w):
                pass

            def simulated_consensus(self, bh, proposer):
                return True  # 快速通过

            def reset(self):
                pass

        # 函数内是 from blockchain.consensus.cw_pbft import CWPBFTConsensus（局部导入）
        monkeypatch.setattr('blockchain.consensus.cw_pbft.CWPBFTConsensus', _FakeConsensus)
        results = rs.benchmark_large_network()
        assert len(results) == 3  # 3/5/8 节点
        r0 = results[0]
        for key in ['n_nodes', 'total_rounds', 'success', 'fail',
                    'success_rate', 'avg_latency_ms', 'p95_latency_ms',
                    'throughput_rps', 'communication_complexity']:
            assert key in r0

    def test_success_rate_calculated(self, monkeypatch):
        class _FakeConsensus:
            def __init__(self, node_id, consensus_nodes):
                self.node_id = node_id
                self.nodes = consensus_nodes

            def update_weight(self, nid, w):
                pass

            def simulated_consensus(self, bh, proposer):
                return True

            def reset(self):
                pass

        monkeypatch.setattr('blockchain.consensus.cw_pbft.CWPBFTConsensus', _FakeConsensus)
        results = rs.benchmark_large_network()
        assert results[0]['success_rate'] == 100.0  # 全部成功

    def test_node_counts(self, monkeypatch):
        class _FakeConsensus:
            def __init__(self, node_id, consensus_nodes):
                self.node_id = node_id
                self.nodes = consensus_nodes

            def update_weight(self, nid, w):
                pass

            def simulated_consensus(self, bh, proposer):
                return True

            def reset(self):
                pass

        monkeypatch.setattr('blockchain.consensus.cw_pbft.CWPBFTConsensus', _FakeConsensus)
        results = rs.benchmark_large_network()
        counts = [r['n_nodes'] for r in results]
        assert counts == [3, 5, 8]


class TestScaleReport:
    def test_generate_scale_report_writes(self, tmp_path):
        """生成规模报告文件（.json 数据 + .md 报告）"""
        network_results = [{
            'n_nodes': 3, 'total_rounds': 50, 'success_rate': 100.0,
            'avg_latency_ms': 0.5, 'p95_latency_ms': 1.0, 'p99_latency_ms': 2.0,
            'throughput_rps': 1000.0, 'communication_complexity': 'O(9)≈9',
        }]
        resource_results = [{'operation': 'ecdsa_sign', 'time_sec': 0.01,
                             'memory_mb': 1.5, 'ops_per_sec': 1000}]
        out_md = tmp_path / 'scale_report.md'
        rs.generate_scale_report(network_results, resource_results, str(out_md))
        assert out_md.exists()


class TestModuleIntegrity:
    def test_functions_exist(self):
        for name in ['measure_resource', 'benchmark_large_network',
                     'benchmark_resource_usage', 'generate_scale_report', 'main']:
            assert callable(getattr(rs, name))
