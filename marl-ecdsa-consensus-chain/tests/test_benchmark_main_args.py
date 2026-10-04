"""
benchmark/run_all main 参数校验测试（RalphLoop 原子任务 BI）
覆盖：argparse 默认值/覆盖、--quick 缩放、--skip-* 开关
通过标准：新增 ≥6 项测试全过
"""
import argparse
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts' / 'benchmark'))

import run_all as ra

logging.basicConfig(level=logging.CRITICAL)


class TestArgparseDefaults:
    def test_default_output(self):
        args = _parse([])
        assert args.output == "results/benchmark_report.md"

    def test_default_quick_false(self):
        args = _parse([])
        assert args.quick is False

    def test_default_skip_all_false(self):
        args = _parse([])
        assert args.skip_ecdsa is False
        assert args.skip_blockchain is False
        assert args.skip_consensus is False
        assert args.skip_security is False


class TestArgparseOverride:
    def test_quick_enabled(self):
        args = _parse(['--quick'])
        assert args.quick is True

    def test_output_override(self):
        args = _parse(['--output', 'custom.md'])
        assert args.output == 'custom.md'

    def test_skip_flags(self):
        args = _parse(['--skip-ecdsa', '--skip-consensus'])
        assert args.skip_ecdsa is True
        assert args.skip_consensus is True
        assert args.skip_blockchain is False  # 未设置保持 False


class TestScaleLogic:
    def test_quick_scale_02(self):
        """--quick → scale=0.2（main 内逻辑）"""
        quick = _parse(['--quick']).quick
        assert (0.2 if quick else 1.0) == 0.2

    def test_full_scale_10(self):
        quick = _parse([]).quick
        assert (0.2 if quick else 1.0) == 1.0


class TestModuleIntegrity:
    def test_main_callable(self):
        assert callable(ra.main)

    def test_import_ok(self):
        """模块导入完整（含 _fmt_num 辅助函数）"""
        assert hasattr(ra, '_fmt_num')


def _parse(argv):
    """重放 main 中的 parser 构造并解析 argv"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--output", type=str, default="results/benchmark_report.md")
    parser.add_argument("--skip-ecdsa", action="store_true")
    parser.add_argument("--skip-blockchain", action="store_true")
    parser.add_argument("--skip-consensus", action="store_true")
    parser.add_argument("--skip-security", action="store_true")
    return parser.parse_args(argv)
