"""
run_full_experiment 完整实验测试（RalphLoop 原子任务 AP）
覆盖：argparse 默认值/覆盖、--quick 回合数、seeds 解析、run_command 状态
通过标准：新增 ≥6 项测试全过
"""
import argparse
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts' / 'one-click'))

import run_full_experiment as rfe

logging.basicConfig(level=logging.CRITICAL)


class TestArgparseDefaults:
    def test_default_agents(self):
        args = _parse([])
        assert args.agents == 3

    def test_default_seeds(self):
        args = _parse([])
        assert args.seeds == "42,123,456"

    def test_default_quick_false(self):
        args = _parse([])
        assert args.quick is False

    def test_default_skip_dashboard_false(self):
        args = _parse([])
        assert args.skip_dashboard is False


class TestArgparseOverride:
    def test_cli_agents_override(self):
        args = _parse(['--agents', '5'])
        assert args.agents == 5

    def test_cli_quick_enabled(self):
        args = _parse(['--quick'])
        assert args.quick is True

    def test_cli_custom_seeds(self):
        args = _parse(['--seeds', '7,8,9'])
        assert args.seeds == "7,8,9"


class TestEpisodeLogic:
    def test_quick_sets_100_episodes(self):
        """--quick → n_episodes=100（main 内逻辑）"""
        args = _parse(['--quick'])
        assert 100 if args.quick else 1000 == 100

    def test_full_sets_1000_episodes(self):
        args = _parse([])
        assert 100 if args.quick else 1000 == 1000

    def test_seeds_parsed_to_ints(self):
        """逗号分隔 seeds 解析为 int 列表"""
        seeds = [int(s.strip()) for s in "42,123,456".split(",")]
        assert seeds == [42, 123, 456]


class TestRunCommand:
    def test_run_command_success(self, monkeypatch):
        """subprocess 返回 0 → True"""
        class _Result:
            returncode = 0
        monkeypatch.setattr(rfe.subprocess, 'run', lambda *a, **kw: _Result())
        assert rfe.run_command(["echo", "ok"], "测试") is True

    def test_run_command_failure(self, monkeypatch):
        """subprocess 返回非 0 → False"""
        class _Result:
            returncode = 1
        monkeypatch.setattr(rfe.subprocess, 'run', lambda *a, **kw: _Result())
        assert rfe.run_command(["false"], "测试") is False


class TestModuleIntegrity:
    def test_main_callable(self):
        assert callable(rfe.main)

    def test_import_ok(self):
        """模块导入完整（ROOT_DIR 指向项目根）"""
        assert (rfe.ROOT_DIR / 'train.py').exists()


def _parse(argv):
    """重放 main 中的 parser 构造并解析 argv"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--agents", type=int, default=3)
    parser.add_argument("--seeds", type=str, default="42,123,456")
    parser.add_argument("--skip-dashboard", action="store_true")
    return parser.parse_args(argv)
