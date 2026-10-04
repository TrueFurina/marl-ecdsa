"""
analyze_all_experiments 分析脚本测试（RalphLoop 原子任务 AS）
覆盖：load_json、extract_metrics、safe_mean_std、welch_ttest 纯函数边界
通过标准：新增 ≥6 项测试全过
"""
import json
import logging
from pathlib import Path

import numpy as np
import pytest

import analyze_all_experiments as aae

logging.basicConfig(level=logging.CRITICAL)


class TestLoadJson:
    def test_missing_file_returns_none(self, tmp_path):
        assert aae.load_json(tmp_path / "nonexistent.json") is None

    def test_existing_file_returns_dict(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"a": 1}), encoding='utf-8')
        assert aae.load_json(p) == {"a": 1}


class TestExtractMetrics:
    def test_missing_file_none(self, tmp_path):
        assert aae.extract_metrics(tmp_path / "ghost.json") is None

    def test_empty_data_none_values(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({}), encoding='utf-8')
        m = aae.extract_metrics(p)
        assert m["env_reward"] is None
        assert m["coop_rate"] is None
        assert m["n_episodes"] == 0

    def test_basic_metrics(self, tmp_path):
        p = tmp_path / "basic.json"
        p.write_text(json.dumps({"env_rewards": [1.0] * 100,
                                 "episode_rewards": [2.0] * 100,
                                 "cooperation_rates": [0.5] * 100,
                                 "betrayal_rates": [0.1] * 100}), encoding='utf-8')
        m = aae.extract_metrics(p)
        assert m["env_reward"] == pytest.approx(1.0)
        assert m["total_reward"] == pytest.approx(2.0)
        assert m["coop_rate"] == pytest.approx(0.5)
        assert m["n_episodes"] == 100

    def test_metrics_window_100(self, tmp_path):
        """取最后 100 回合均值"""
        p = tmp_path / "window.json"
        p.write_text(json.dumps({"env_rewards": [0.0] * 50 + [2.0] * 100}), encoding='utf-8')
        m = aae.extract_metrics(p)
        assert m["env_reward"] == pytest.approx(2.0)  # 最后100个全为2.0


class TestSafeMeanStd:
    def test_empty_list_returns_none(self):
        assert aae.safe_mean_std([]) == (None, None)

    def test_all_none_returns_none(self):
        assert aae.safe_mean_std([None, None]) == (None, None)

    def test_mixed_values_filters_none(self):
        mean, std = aae.safe_mean_std([1.0, 2.0, None, 3.0])
        assert mean == pytest.approx(2.0)  # 过滤 None 后均值

    def test_known_values(self):
        mean, std = aae.safe_mean_std([10.0, 10.0, 10.0])
        assert mean == pytest.approx(10.0)
        assert std == pytest.approx(0.0)


class TestWelchTTest:
    def test_insufficient_data(self):
        r = aae.welch_ttest([1.0], [2.0, 3.0])
        assert r["test"] == "insufficient_data"

    def test_significant_difference(self):
        np.random.seed(3)
        a = np.random.normal(10.0, 0.5, 50)
        b = np.random.normal(5.0, 0.5, 50)
        r = aae.welch_ttest(a, b)
        assert bool(r["significant"]) is True
        assert float(r["p_value"]) < 0.05

    def test_same_group_not_significant(self):
        a = np.random.normal(5.0, 0.1, 50)
        r = aae.welch_ttest(a, a)
        assert float(r["p_value"]) > 0.05
