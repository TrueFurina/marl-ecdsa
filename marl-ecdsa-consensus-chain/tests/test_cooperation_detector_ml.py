"""
CooperationDetector ML 分类器路径测试（RalphLoop 原子任务 D）
覆盖：train_classifier / predict_ml / get_ml_accuracy / _extract_features / 降级行为
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from marl.integration.cooperation_detector import CooperationDetector

logging.basicConfig(level=logging.CRITICAL)


def _make_obs(n=30, n_lm=3):
    """构造 SimpleSpread 格式观测样本 [vel2, pos2, lm_rel(2*n_lm)]"""
    import numpy as np
    obs = []
    for i in range(n):
        lm = np.random.rand(n_lm, 2) * 0.8 + 0.1
        row = [0.1, 0.1, 0.5, 0.5] + lm.flatten().tolist()
        obs.append(row)
    return obs


def _make_labels(n=30, coop_ratio=0.6):
    import random
    return [1 if random.random() < coop_ratio else 0 for _ in range(n)]


class TestExtractFeatures:
    def test_feature_shape(self):
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _make_obs(10)
        features, ids = cd._extract_features(obs, ["a0", "a1", "a2"] * 3 + ["a0"])
        assert len(features) == 10
        assert len(features[0]) == 4  # [dist_to_own, min_dist_any, pos_x, pos_y]

    def test_extract_features_malformed_obs_fallback(self):
        """畸形观测不崩溃，回退默认特征 [0,0,0,0]"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = [[1.0]]  # 严重畸形
        features, _ = cd._extract_features(obs, ["a0"])
        assert features[0] == [0.0, 0.0, 0.0, 0.0]


class TestTrainClassifier:
    def test_train_success(self):
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _make_obs(40)
        labels = _make_labels(40)
        ok = cd.train_classifier(obs, [f"a{i % 3}" for i in range(40)], labels)
        assert ok is True
        assert cd._ml_available is True
        assert cd.get_stats()["ml_classifier"] == "ExtraTreesClassifier"

    def test_train_insufficient_samples_false(self):
        """样本不足(<2)时跳过训练返回 False"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        ok = cd.train_classifier(_make_obs(1), ["a0"], [1])
        assert ok is False
        assert cd._ml_available is False

    def test_train_single_label_false(self):
        """标签单一（全部同类）时跳过训练返回 False"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _make_obs(10)
        ok = cd.train_classifier(obs, ["a0"] * 10, [1] * 10)
        assert ok is False


class TestPredictML:
    def test_predict_without_train_returns_empty(self):
        """未训练时 predict_ml 返回空 dict"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        assert cd.predict_ml(_make_obs(5), ["a0"] * 5) == {}

    def test_predict_after_train_returns_mapping(self):
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _make_obs(40)
        labels = _make_labels(40)
        cd.train_classifier(obs, [f"a{i % 3}" for i in range(40)], labels)
        # 用唯一 agent_id（predict_ml 返回 dict，重复 id 会被去重覆盖）
        preds = cd.predict_ml(_make_obs(6), [f"n{i}" for i in range(6)])
        assert len(preds) == 6
        assert all(v in (True, False) for v in preds.values())


class TestGetMLAccuracy:
    def test_accuracy_without_train_none(self):
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        assert cd.get_ml_accuracy(_make_obs(5), ["a0"] * 5, [1] * 5) is None

    def test_accuracy_after_train_in_range(self):
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _make_obs(40)
        labels = _make_labels(40)
        cd.train_classifier(obs, [f"a{i % 3}" for i in range(40)], labels)
        acc = cd.get_ml_accuracy(obs, [f"a{i % 3}" for i in range(40)], labels)
        assert acc is not None
        assert 0.0 <= acc <= 1.0


class TestRuleBasedUnaffected:
    def test_rule_based_detect_still_works_after_ml(self):
        """ML 训练不破坏规则基 detect_cooperation"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _make_obs(40)
        labels = _make_labels(40)
        cd.train_classifier(obs, [f"a{i % 3}" for i in range(40)], labels)
        res = cd.detect_cooperation(_make_obs(3), ["a0", "a1", "a2"])
        assert set(res.keys()) == {"a0", "a1", "a2"}
