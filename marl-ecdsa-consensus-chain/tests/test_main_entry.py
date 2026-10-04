"""
main.py 入口参数校验测试（RalphLoop 原子任务 AG）
覆盖：argparse 默认值、mode choices、布尔开关、config 加载与回退
通过标准：新增 ≥6 项测试全过
"""
import json
import logging
from pathlib import Path

import pytest

import main as main_mod

logging.basicConfig(level=logging.CRITICAL)


class TestBuildParser:
    def test_default_mode(self):
        parser = main_mod._build_parser({})
        args = parser.parse_args([])
        assert args.mode == 'bc_marl'

    def test_mode_choices_valid(self):
        parser = main_mod._build_parser({})
        for mode in ['pure_marl', 'bc_marl', 'selfish']:
            args = parser.parse_args(['--mode', mode])
            assert args.mode == mode

    def test_mode_choices_invalid(self):
        parser = main_mod._build_parser({})
        with pytest.raises(SystemExit):
            parser.parse_args(['--mode', 'invalid_mode'])

    def test_config_defaults_injected(self):
        """config 默认值注入 argparse 默认"""
        defaults = {'n_agents': 5, 'n_episodes': 200, 'lambda_weight': 0.3, 'seed': 7}
        parser = main_mod._build_parser(defaults)
        args = parser.parse_args([])
        assert args.n_agents == 5
        assert args.n_episodes == 200
        assert args.lambda_weight == 0.3
        assert args.seed == 7

    def test_cli_override_config(self):
        """命令行参数覆盖 config 默认值"""
        defaults = {'n_agents': 5, 'n_episodes': 200}
        parser = main_mod._build_parser(defaults)
        args = parser.parse_args(['--n_agents', '8', '--n_episodes', '100'])
        assert args.n_agents == 8
        assert args.n_episodes == 100


class TestBooleanFlags:
    def test_flags_default_false(self):
        parser = main_mod._build_parser({})
        args = parser.parse_args([])
        assert args.use_p2p is False
        assert args.experiment is False
        assert args.demo is False
        assert args.dashboard is False

    def test_flags_enabled(self):
        parser = main_mod._build_parser({})
        args = parser.parse_args(['--use-p2p', '--experiment', '--demo', '--dashboard'])
        assert args.use_p2p is True
        assert args.experiment is True
        assert args.demo is True
        assert args.dashboard is True


class TestLoadConfig:
    def test_load_default_config(self):
        """默认 config.json 可加载且含 modes"""
        cfg = main_mod.load_config()
        assert 'modes' in cfg
        assert 'blockchain' in cfg

    def test_load_config_from_path(self, tmp_path):
        """自定义路径配置加载"""
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps({"test_key": 123}), encoding='utf-8')
        cfg = main_mod.load_config(str(p))
        assert cfg["test_key"] == 123

    def test_load_config_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            main_mod.load_config(str(Path('/nonexistent_path_xyz/cfg.json')))


class TestConfigDefaults:
    def test_defaults_from_config(self):
        """_load_config_defaults 从 config.json 读取 bc_marl 参数"""
        defaults = main_mod._load_config_defaults()
        assert defaults['n_agents'] >= 1
        assert defaults['n_episodes'] >= 1
        assert 'lambda_weight' in defaults
        assert 'seed' in defaults

    def test_defaults_fallback_on_error(self, monkeypatch):
        """config 加载失败 → 回退硬编码默认值"""
        def boom(*a, **kw):
            raise RuntimeError("模拟加载失败")
        monkeypatch.setattr(main_mod, 'load_config', boom)
        defaults = main_mod._load_config_defaults()
        assert defaults['n_agents'] == 3
        assert defaults['n_episodes'] == 500
