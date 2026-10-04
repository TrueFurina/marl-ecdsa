"""
dashboard 顶层数据初始化测试（RalphLoop 原子任务 BK）
覆盖：_dashboard_data 初始结构、BASE_DIR 指向、app 全局
通过标准：新增 ≥6 项测试全过
"""
import logging
from pathlib import Path

import pytest

import visualization.dashboard as dash

logging.basicConfig(level=logging.CRITICAL)


class TestDashboardDataInit:
    def test_episode_rewards_initialized(self):
        """episode_rewards 初始为空列表"""
        assert dash._dashboard_data['episode_rewards'] == []

    def test_stats_lists_initialized(self):
        """各统计列表初始为空"""
        for key in ['cooperation_rates', 'betrayal_rates', 'losses', 'bc_scores_history']:
            assert dash._dashboard_data[key] == []

    def test_dict_fields_initialized(self):
        """各字典字段初始为空"""
        for key in ['bc_scores', 'leaderboard', 'config', 'summary']:
            assert dash._dashboard_data[key] == {} or dash._dashboard_data[key] == []

    def test_all_expected_keys_present(self):
        """_dashboard_data 含全部预期字段"""
        for key in ['episode_rewards', 'cooperation_rates', 'betrayal_rates',
                    'losses', 'bc_scores_history', 'bc_scores', 'leaderboard',
                    'settlements', 'config', 'summary']:
            assert key in dash._dashboard_data


class TestBaseDir:
    def test_base_dir_points_to_project_root(self):
        """_BASE_DIR 指向项目根目录"""
        assert (dash._BASE_DIR / 'config.json').exists()
        assert (dash._BASE_DIR / 'main.py').exists()

    def test_base_dir_has_templates(self):
        """项目根含 templates/dashboard.html"""
        assert (dash._BASE_DIR / 'templates' / 'dashboard.html').exists()


class TestAppGlobal:
    def test_app_none_initial(self):
        """app 全局初始为 None（延迟创建）"""
        assert dash.app is None

    def test_create_app_builds_flask(self):
        """_create_app 构建 Flask 应用（非 None）"""
        app = dash._create_app()
        assert app is not None
        # Flask 实例暴露路由
        rules = sorted(str(r) for r in app.url_map.iter_rules())
        assert '/' in rules
        assert '/api/status' in rules


class TestModuleConstants:
    def test_dashboard_version_comment(self):
        """模块含版本标识（v3.9 全功能平台）"""
        import inspect
        src = inspect.getsource(dash)
        assert 'v3.9' in src or '全功能' in src

    def test_import_ok(self):
        """模块导入完整（含关键函数）"""
        assert callable(dash._create_app)
        assert callable(dash.update_data)
        assert callable(dash.start_dashboard)
