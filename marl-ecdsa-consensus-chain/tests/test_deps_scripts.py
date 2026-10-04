"""
启动脚本与依赖清单完整性测试（RalphLoop 原子任务 AN）
覆盖：requirements 依赖完整性、版本约束、一键脚本存在性、可导入性
通过标准：新增 ≥6 项测试全过
"""
import importlib
import logging
import re
from pathlib import Path

import pytest

logging.basicConfig(level=logging.CRITICAL)

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / 'requirements.txt'

EXPECTED_DEPS = ['cryptography', 'numpy', 'scipy', 'matplotlib', 'flask', 'tqdm', 'torch']


class TestRequirementsContent:
    def test_requirements_exists(self):
        assert REQ.exists()

    def test_all_core_deps_listed(self):
        """7 个核心依赖均在 requirements.txt 中"""
        content = REQ.read_text(encoding='utf-8')
        for dep in EXPECTED_DEPS:
            assert dep in content, f"缺少依赖 {dep}"

    def test_version_constraints(self):
        """核心依赖带版本约束（>=）"""
        content = REQ.read_text(encoding='utf-8')
        for dep in ['cryptography', 'numpy', 'scipy', 'matplotlib', 'flask', 'tqdm', 'torch']:
            m = re.search(rf'{dep}>=\d+\.\d+', content)
            assert m, f"{dep} 缺少版本约束"

    def test_deps_importable(self):
        """全部依赖可导入（当前环境）"""
        for dep in EXPECTED_DEPS:
            importlib.import_module(dep)  # 不抛 ImportError 即通过

    def test_comments_documented(self):
        """requirements 含安装说明注释"""
        content = REQ.read_text(encoding='utf-8')
        assert '安装命令' in content


class TestLaunchScripts:
    def test_one_click_launchers(self):
        """scripts/one-click 启动器存在"""
        oc = ROOT / 'scripts' / 'one-click'
        assert (oc / 'launch_dashboard.py').exists()
        assert (oc / 'run_full_experiment.py').exists()
        assert (oc / 'start_p2p_cluster.py').exists()

    def test_launch_dashboard_importable(self):
        """launch_dashboard 可导入"""
        import sys
        sys.path.insert(0, str(ROOT / 'scripts' / 'one-click'))
        try:
            import launch_dashboard
            assert launch_dashboard is not None
        finally:
            sys.path.pop(0)


class TestConfigConsistency:
    def test_config_blockchain_consensus(self):
        """config.json 区块链共识配置存在且合法"""
        import json
        cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        bc = cfg.get('blockchain', {})
        assert bc.get('consensus') == 'CW-PBFT'
        assert bc.get('consensus_mode') in ('cw_pbft', 'standard_pbft', 'fast')
