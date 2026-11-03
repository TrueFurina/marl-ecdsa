"""观测布局契约测试（2026-10-18 新增）

背景（为什么必须有这组测试）：
`CooperationDetector.detect_cooperation()` 只认识 SimpleSpreadEnv 的观测布局

    [vel_x, vel_y, pos_x, pos_y, landmark_1_dx, landmark_1_dy, ..., other_agent_...]

它按 `obs[4 : 4+2*n_landmarks]` 切出"路标相对位移"再算欧氏距离。换到
DeliveryMARLEnv（骑手×2 + 无人机）后，观测布局是

    [pos_x, pos_y, is_rider, target_x, target_y, handoff_x, handoff_y, other_...]

同样的切片落在"目标点 y / 交接点 x,y / 其他智能体 x"这些**绝对坐标**上。
交付场景的坐标恒在 [0,1]、交接点固定 (0.5,0.5)，于是

    lm_rel[0] = (target_y, 0.5)  → 范数 ≥ sqrt(0.3² + 0.5²) = 0.583
    lm_rel[1] = (0.5, other_x)   → 范数 ≥ 0.5（仅当 other_x 恰为 0 时取等）

`dist < 0.5` 严格小于**永不成立** → 8000 回合合作率恒为 0。这不是"策略不合作"，
而是指标没接线；旧实现把"算不出来"写成了 0，属静默伪造。

本组测试钉住三条契约：
1. 布局匹配时行为学判定照常工作（该 True 的要 True）；
2. 布局不匹配时判**不可测**（全 None + `layout_mismatch`），绝不输出假 0；
3. 训练摘要不得把"不可测"平均成 0.0。
"""
import sys

import numpy as np
import pytest

sys.path.insert(0, '.')

from marl.integration.cooperation_detector import CooperationDetector


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


def _simple_spread_obs(n_agents=3, n_landmarks=3):
    """SimpleSpread 布局：vel2 + pos2 + landmark_rel(2n) + other_rel(2(n-1))。"""
    length = 4 + 2 * n_landmarks + 2 * (n_agents - 1)
    return [np.zeros(length, dtype=float).tolist() for _ in range(n_agents)]


def _delivery_obs(n_agents=3):
    """DeliveryMARLEnv 布局：pos2 + type1 + target2 + handoff2 + others(2(n-1))。"""
    length = 2 + 1 + 2 + 2 + 2 * (n_agents - 1)
    return [np.array([0.5, 0.5, 1.0, 0.2, 0.3, 0.5, 0.5] + [0.5] * (2 * (n_agents - 1))).tolist()
            for _ in range(n_agents)]


def test_expected_len_is_simple_spread_layout():
    det = CooperationDetector(n_agents=3, n_landmarks=3)
    assert det.expected_obs_len() == 4 + 2 * 3 + 2 * 2 == 14


def test_layout_ok_still_detects_cooperation():
    """布局匹配时，贴着路标的那一步必须判 True（防止布局门误伤正常路径）。"""
    det = CooperationDetector(n_agents=3, n_landmarks=3)
    obs = _simple_spread_obs()
    obs[0][4:6] = [0.1, 0.0]  # agent_0 距路标 0.1 < 0.5

    status = det.detect_cooperation(obs, AGENT_IDS, behavioral_only=True)

    assert det.layout_mismatch is False
    assert status["agent_0"] is True
    assert det.layout_report()["layout_ok"] is True


def test_delivery_layout_is_unmeasurable_not_zero():
    """交付布局：必须判不可测（None），而不是静默给 0。"""
    det = CooperationDetector(n_agents=3, n_landmarks=2)  # 交付场景 n_landmarks=2
    obs = _delivery_obs()

    status = det.detect_cooperation(obs, AGENT_IDS, behavioral_only=True)

    assert det.layout_mismatch is True
    assert status == {aid: None for aid in AGENT_IDS}
    assert det.layout_report()["observed_obs_len"] == 11
    assert det.layout_report()["expected_obs_len"] == 4 + 4 + 4


def test_delivery_env_slice_can_never_cross_threshold():
    """根因证书：交付环境里检测器切片的最小距离恰好 ≥ 0.5，严格小于永不成立。"""
    from marl.envs.delivery_env import DeliveryMARLEnv

    env = DeliveryMARLEnv(max_steps=60)
    rng = np.random.default_rng(7)
    worst = float("inf")
    for _ in range(20):
        env.reset()
        for _ in range(60):
            obs, _r, done, _info = env.step(rng.integers(0, 5, 3))
            for o in obs:
                lm_rel = np.asarray(o[4:8], dtype=float).reshape(-1, 2)
                worst = min(worst, min(float(np.linalg.norm(x)) for x in lm_rel))
            if done:
                break

    assert worst >= 0.5, f"切片最小距离 {worst:.4f} 跌破阈值，根因判断需复核"


def test_betray_flags_recorded_even_when_unmeasurable():
    """不可测时仍要记背叛步数——BC 结算靠它，不能因布局门丢掉惩罚依据。"""
    det = CooperationDetector(n_agents=3, n_landmarks=2)
    det.detect_cooperation(_delivery_obs(), AGENT_IDS,
                           selfish_flags=[True, False, False], behavioral_only=True)

    assert det.get_episode_betrayal("agent_0") == 1
    assert det.get_episode_betrayal("agent_1") == 0


def test_summary_does_not_average_unmeasurable_into_zero():
    """摘要：全 None → 均值 None + 状态原因；部分可测 → 只在可测值上平均。"""
    from train import TrainingStats

    stats = TrainingStats()
    for _ in range(3):
        stats.record_episode(1.0, 25, {}, None, betrayal_rate=0.0, env_reward=1.0)
    s = stats.summary()
    assert s["avg_cooperation_rate"] is None
    assert s["cooperation_metric_status"] == "unavailable_layout_mismatch"

    stats2 = TrainingStats()
    stats2.record_episode(1.0, 25, {}, 0.4, betrayal_rate=0.0, env_reward=1.0)
    stats2.record_episode(1.0, 25, {}, None, betrayal_rate=0.0, env_reward=1.0)
    s2 = stats2.summary()
    assert s2["avg_cooperation_rate"] == pytest.approx(0.4)
    assert s2["cooperation_metric_status"] == "ok"
