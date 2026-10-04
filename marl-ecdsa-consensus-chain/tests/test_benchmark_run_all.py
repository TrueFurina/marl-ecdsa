"""
benchmark/run_all 批量脚本测试（RalphLoop 原子任务 BD）
覆盖：各 benchmark 函数返回结构、数值合理性、报告生成
通过标准：新增 ≥6 项测试全过
"""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts' / 'benchmark'))

import run_all as ra

logging.basicConfig(level=logging.CRITICAL)


class TestBenchmarkEcdsa:
    def test_ecdsa_structure(self):
        """ECDSA benchmark 返回标准指标（小参数避免耗时）"""
        r = ra.benchmark_ecdsa(num_iterations=10)
        for key in ['keygen_ms', 'sign_ms', 'verify_ms', 'full_sign_pipeline_ms',
                    'sign_per_sec', 'verify_per_sec']:
            assert key in r

    def test_ecdsa_values_nonnegative(self):
        r = ra.benchmark_ecdsa(num_iterations=10)
        assert r['keygen_ms'] >= 0
        assert r['sign_ms'] >= 0
        assert r['verify_ms'] >= 0

    def test_ecdsa_ops_per_sec_positive(self):
        r = ra.benchmark_ecdsa(num_iterations=10)
        assert r['sign_per_sec'] > 0
        assert r['verify_per_sec'] > 0


class TestBenchmarkBlockchain:
    def test_blockchain_structure(self):
        """Blockchain benchmark 返回标准指标（小参数避免耗时）"""
        r = ra.benchmark_blockchain(num_blocks=5, txs_per_block=3)
        assert isinstance(r, dict)
        assert len(r) > 0

    def test_blockchain_tps_reported(self):
        r = ra.benchmark_blockchain(num_blocks=5, txs_per_block=3)
        # 应包含 TPS 或耗时类指标
        assert any(k in r for k in ['tps', 'throughput', 'avg_block_ms', 'total_txs'])


class TestBenchmarkOthers:
    def test_cw_pbft_structure(self):
        """CW-PBFT benchmark 返回结构（小参数避免耗时）"""
        r = ra.benchmark_cw_pbft(num_rounds=3, n_nodes=3)
        assert isinstance(r, dict)
        assert len(r) > 0

    def test_security_guard_structure(self):
        """SecurityGuard benchmark 返回结构（小参数避免耗时）"""
        r = ra.benchmark_security_guard(num_checks=50)
        assert isinstance(r, dict)
        assert len(r) > 0


class TestGenerateReport:
    def test_report_writes_json(self, tmp_path):
        """报告写入 JSON 文件（output_path 为 .md，自动生成 .json 兄弟文件）"""
        results = {'ecdsa': {'sign_ms': 0.01}, 'blockchain': {'tps': 100}}
        out_md = tmp_path / 'report.md'
        ra.generate_report(results, str(out_md))
        # .md 报告 + .json 数据文件均生成
        assert out_md.exists()
        out_json = tmp_path / 'report.json'
        assert out_json.exists()
        data = json.loads(out_json.read_text(encoding='utf-8'))
        assert 'ecdsa' in data


class TestModuleIntegrity:
    def test_main_callable(self):
        assert callable(ra.main)

    def test_benchmark_functions_exist(self):
        for name in ['benchmark_ecdsa', 'benchmark_blockchain',
                     'benchmark_cw_pbft', 'benchmark_security_guard']:
            assert callable(getattr(ra, name))
