"""
更多模块剩余边界测试（RalphLoop 原子任务 DB）
覆盖：cooperation_detector 合作判定、回合累积、重置、统计
通过标准：新增 ≥6 项测试全过
"""
import logging

import numpy as np
import pytest

from marl.integration.cooperation_detector import CooperationDetector

logging.basicConfig(level=logging.CRITICAL)


def _obs(n=3, n_lm=3, near_own=False, far=False):
    """构造观测：近/远路标可选"""
    rows = []
    for i in range(n):
        lm = np.random.rand(n_lm, 2) * 0.8 + 0.1
        if near_own:
            lm[i % n_lm] = np.array([0.01, 0.01])  # 近分配路标
        if far:
            lm = np.full((n_lm, 2), 0.9)  # 全远
        rows.append(np.array([0.1, 0.1, 0.5, 0.5] + lm.flatten().tolist()))
    return rows


class TestDetectCooperation:
    def test_near_landmark_cooperates(self):
        """近路标 → 合作 True"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        result = cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        assert all(result[a] is True for a in ["a0", "a1", "a2"])

    def test_selfish_flag_marks_betrayal(self):
        """selfish_flags=True → 背叛 False"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        result = cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"],
                                       selfish_flags=[True, False, False])
        assert result["a0"] is False  # 背叛
        assert result["a1"] is True  # 正常合作

    def test_far_landmark_neutral(self):
        """全远路标 → 中性 None"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        result = cd.detect_cooperation(_obs(3, far=True), ["a0", "a1", "a2"])
        assert all(result[a] is None for a in ["a0", "a1", "a2"])

    def test_malformed_obs_fallback_none(self):
        """畸形观测 → None（异常捕获）"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        result = cd.detect_cooperation([[1.0], [1.0], [1.0]], ["a0", "a1", "a2"])
        assert all(result[a] is None for a in ["a0", "a1", "a2"])


class TestEpisodeCooperation:
    def test_episode_accumulates(self):
        """回合内累积：3 步中 2 步背叛 → did_betray=True（判定阈值 >0.5）"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        obs = _obs(3, near_own=True)
        cd.detect_cooperation(obs, ["a0", "a1", "a2"])
        cd.detect_cooperation(obs, ["a0", "a1", "a2"], selfish_flags=[True, False, False])
        cd.detect_cooperation(obs, ["a0", "a1", "a2"], selfish_flags=[True, False, False])
        # a0: 1 合作 + 2 背叛 → betray_rate=2/3>0.5 → did_betray=True
        did_coop, did_betray = cd.get_episode_cooperation("a0")
        assert did_coop is True
        assert did_betray is True

    def test_episode_coop_rate_threshold(self):
        """合作率 >0.3 → did_cooperate=True"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        did_coop, did_betray = cd.get_episode_cooperation("a0")
        assert did_coop is True  # 2/2 合作
        assert did_betray is False

    def test_episode_never_called_returns_false(self):
        """未检测智能体 → (False, False)"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        coop, betray = cd.get_episode_cooperation("ghost")
        assert (coop, betray) == (False, False)

    def test_get_cooperation_status(self):
        """get_cooperation_status 返回最近一步状态"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        status = cd.get_cooperation_status()
        assert status["a0"] is True


class TestResetStats:
    def test_reset_episode(self):
        """reset_episode 清空回合累积"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        cd.reset_episode()
        coop, betray = cd.get_episode_cooperation("a0")
        assert (coop, betray) == (False, False)

    def test_get_stats_structure(self):
        """get_stats 含合作统计"""
        cd = CooperationDetector(n_agents=3, n_landmarks=3)
        cd.detect_cooperation(_obs(3, near_own=True), ["a0", "a1", "a2"])
        stats = cd.get_stats()
        assert isinstance(stats, dict)
        assert len(stats) >= 1
