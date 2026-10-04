"""
CooperationDetector 子组件独立测试
覆盖：合作/背叛检测、累积统计、阈值判定、selfish标记、per-step结果、重置
"""
import pytest
import sys
import numpy as np

sys.path.insert(0, '.')

from marl.integration.cooperation_detector import CooperationDetector
from marl.envs.simple_spread import SimpleSpreadEnv


@pytest.fixture
def detector():
    """创建 CooperationDetector"""
    return CooperationDetector(n_agents=3, n_landmarks=3)


@pytest.fixture
def env_and_detector():
    """创建真实环境 + detector"""
    env = SimpleSpreadEnv(n_agents=3, n_landmarks=3, max_steps=25)
    detector = CooperationDetector(n_agents=3, n_landmarks=3)
    yield env, detector


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


def make_observations_near_landmark(agent_idx, n_landmarks=3, distance=0.3):
    """
    构造靠近目标点的观测值

    观测格式：[vel_x, vel_y, pos_x, pos_y, lm1_dx, lm1_dy, lm2_dx, lm2_dy, lm3_dx, lm3_dy, ...]
    own_idx = agent_idx % n_landmarks → 让第 own_idx 个 landmark 距离很近
    """
    obs = np.zeros(14, dtype=float)  # 2vel + 2pos + 6landmark_rel + 4other_agents_rel
    # 设置 landmark 相对距离
    for lm_idx in range(n_landmarks):
        if lm_idx == agent_idx % n_landmarks:
            # 自己的目标点很近
            obs[4 + 2 * lm_idx] = distance * 0.7  # dx
            obs[4 + 2 * lm_idx + 1] = distance * 0.7  # dy
        else:
            # 其他目标点远
            obs[4 + 2 * lm_idx] = 0.8  # dx
            obs[4 + 2 * lm_idx + 1] = 0.8  # dy
    return obs.tolist()


def make_observations_far_all(agent_idx, n_landmarks=3):
    """构造远离所有目标点的观测值"""
    obs = np.zeros(14, dtype=float)
    for lm_idx in range(n_landmarks):
        obs[4 + 2 * lm_idx] = 0.9  # dx
        obs[4 + 2 * lm_idx + 1] = 0.9  # dy
    return obs.tolist()


class TestCooperationDetectorInit:
    """初始化测试"""

    def test_init_defaults(self, detector):
        """默认参数初始化"""
        assert detector.n_agents == 3
        assert detector.n_landmarks == 3
        assert detector._episode_coop == {}
        assert detector._last_step_coop == {}

    def test_init_custom_params(self):
        """自定义参数初始化"""
        d = CooperationDetector(n_agents=5, n_landmarks=4)
        assert d.n_agents == 5
        assert d.n_landmarks == 4


class TestDetectCooperation:
    """每步合作检测"""

    def test_near_own_landmark_cooperates(self, detector):
        """靠近自己目标点 → 合作 True"""
        observations = [
            make_observations_near_landmark(0, distance=0.3),
            make_observations_near_landmark(1, distance=0.3),
            make_observations_near_landmark(2, distance=0.3),
        ]
        result = detector.detect_cooperation(observations, AGENT_IDS)
        # 阈值 0.5: dist < 0.5 → True
        for aid in AGENT_IDS:
            assert result[aid] is True, f"{aid} 靠近目标点应为合作"

    def test_far_all_landmarks_neutral(self, detector):
        """远离所有目标点 → 中性 None"""
        observations = [
            make_observations_far_all(0),
            make_observations_far_all(1),
            make_observations_far_all(2),
        ]
        result = detector.detect_cooperation(observations, AGENT_IDS)
        for aid in AGENT_IDS:
            assert result[aid] is None, f"{aid} 远离所有点应为中性"

    def test_near_other_landmark_cooperates(self, detector):
        """靠近其他目标点（不是自己的）仍为合作 True（v3修正：覆盖任何目标点=正向行为）"""
        # agent_0 靠近 landmark_1（不是自己的 landmark_0）
        obs = np.zeros(14, dtype=float)
        obs[4] = 0.9   # lm0 远
        obs[5] = 0.9
        obs[6] = 0.2   # lm1 近 (< 0.5 阈值)
        obs[7] = 0.2
        obs[8] = 0.9   # lm2 远
        obs[9] = 0.9
        observations = [obs.tolist(), make_observations_far_all(1), make_observations_far_all(2)]
        result = detector.detect_cooperation(observations, AGENT_IDS)
        assert result["agent_0"] is True, "靠近其他目标点仍为合作"

    def test_selfish_flag_overrides(self, detector):
        """selfish 标记强制覆盖为背叛 False"""
        observations = [
            make_observations_near_landmark(0, distance=0.1),  # 即使很近
            make_observations_near_landmark(1, distance=0.3),
            make_observations_near_landmark(2, distance=0.3),
        ]
        selfish_flags = [True, False, False]  # agent_0 是自私智能体
        result = detector.detect_cooperation(observations, AGENT_IDS, selfish_flags=selfish_flags)
        assert result["agent_0"] is False, "selfish智能体应被标记为背叛"
        assert result["agent_1"] is True
        assert result["agent_2"] is True

    def test_detect_accumulates_episode_stats(self, detector):
        """detect_cooperation 应累积到回合统计"""
        observations = [
            make_observations_near_landmark(0, distance=0.3),
            make_observations_near_landmark(1, distance=0.3),
            make_observations_near_landmark(2, distance=0.3),
        ]
        # 第一次检测
        detector.detect_cooperation(observations, AGENT_IDS)
        # 第二次检测（模拟第二步）
        detector.detect_cooperation(observations, AGENT_IDS)

        # 累积统计应记录 2 步
        for aid in AGENT_IDS:
            stats = detector._episode_coop[aid]
            assert stats['total'] == 2
            assert stats['coop'] == 2
            assert stats['betray'] == 0

    def test_detect_with_real_env(self, env_and_detector):
        """真实环境观测值检测"""
        env, detector = env_and_detector
        obs = env.reset()
        result = detector.detect_cooperation(obs, AGENT_IDS)
        assert len(result) == 3
        # 初始位置远离目标点 → 应为 None（中性）
        for aid in AGENT_IDS:
            assert result[aid] is None or result[aid] is True, \
                f"{aid} 应为 None 或 True，不应为 False"

    def test_detect_cooperation_threshold_custom(self, detector):
        """自定义阈值"""
        # distance=0.6, threshold=0.5 → dist > threshold → None
        # distance=0.6, threshold=0.7 → dist < threshold → True
        obs_far = make_observations_near_landmark(0, distance=0.6)

        result_default = detector.detect_cooperation([obs_far], ["agent_0"], cooperation_threshold=0.5)
        # 重置后用更宽松阈值
        detector.reset_episode()
        result_loose = detector.detect_cooperation([obs_far], ["agent_0"], cooperation_threshold=0.7)

        assert result_default["agent_0"] is None  # 0.6 > 0.5
        assert result_loose["agent_0"] is True     # 0.6 < 0.7


class TestGetEpisodeCooperation:
    """回合级合作判定"""

    def test_high_coop_rate_passes(self, detector):
        """合作步数 > 30% → did_cooperate=True"""
        # 模拟 5 步合作
        observations = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        for _ in range(5):
            detector.detect_cooperation(observations, AGENT_IDS)

        for aid in AGENT_IDS:
            did_coop, did_betray = detector.get_episode_cooperation(aid)
            assert did_coop is True, f"{aid} 合作率应超过30%"
            assert did_betray is False, f"{aid} 背叛率应不超过50%"

    def test_low_coop_rate_fails(self, detector):
        """合作步数 < 30% → did_cooperate=False"""
        observations = [make_observations_far_all(i) for i in range(3)]
        for _ in range(5):
            detector.detect_cooperation(observations, AGENT_IDS)

        for aid in AGENT_IDS:
            did_coop, did_betray = detector.get_episode_cooperation(aid)
            assert did_coop is False, f"{aid} 合作率应低于30%"
            # None steps不计入coop/betray → betray_rate=0 → did_betray=False
            assert did_betray is False

    def test_betrayal_threshold(self, detector):
        """背叛步数 > 50% → did_betray=True"""
        selfish_flags = [True, False, False]
        observations = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        # 模拟多步 selfish 行为
        for _ in range(6):
            detector.detect_cooperation(observations, AGENT_IDS, selfish_flags=selfish_flags)

        did_coop_0, did_betray_0 = detector.get_episode_cooperation("agent_0")
        assert did_betray_0 is True, "agent_0 背叛率应超过50%"
        assert did_coop_0 is False, "agent_0 合作步数应为0"

    def test_mixed_behavior(self, detector):
        """混合行为：部分合作部分中性"""
        # 3步合作 + 7步中性 → coop_rate=30% → 刚好在边界
        obs_near = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        obs_far = [make_observations_far_all(i) for i in range(3)]

        # 3步靠近
        for _ in range(3):
            detector.detect_cooperation(obs_near, AGENT_IDS)
        # 7步远离
        for _ in range(7):
            detector.detect_cooperation(obs_far, AGENT_IDS)

        did_coop_0, did_betray_0 = detector.get_episode_cooperation("agent_0")
        # 3/10 = 30%, 刚好在 > 0.3 的边界（使用 > 而非 >=）
        # 实际coop_rate=0.3, 0.3 > 0.3 = False → 不合作
        assert did_coop_0 is False, "30% 刚好在边界（>30%才通过）"


class TestGetCooperationStatus:
    """per-step 结果"""

    def test_last_step_status(self, detector):
        """get_cooperation_status 返回最近一步检测结果"""
        observations = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        detector.detect_cooperation(observations, AGENT_IDS)

        status = detector.get_cooperation_status()
        assert len(status) == 3
        for aid in AGENT_IDS:
            assert aid in status
            assert status[aid] is True

    def test_status_updated_each_step(self, detector):
        """每步调用后 status 应更新"""
        obs_near = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        obs_far = [make_observations_far_all(i) for i in range(3)]

        # 第一步：靠近
        detector.detect_cooperation(obs_near, AGENT_IDS)
        status_1 = detector.get_cooperation_status()
        assert status_1["agent_0"] is True

        # 第二步：远离
        detector.detect_cooperation(obs_far, AGENT_IDS)
        status_2 = detector.get_cooperation_status()
        assert status_2["agent_0"] is None


class TestResetEpisode:
    """回合重置"""

    def test_reset_clears_episode_coop(self, detector):
        """reset_episode 清空回合累积统计"""
        observations = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        detector.detect_cooperation(observations, AGENT_IDS)
        assert detector._episode_coop != {}

        detector.reset_episode()
        assert detector._episode_coop == {}

    def test_reset_preserves_last_step(self, detector):
        """reset_episode 保留 last_step_coop（不清空）"""
        observations = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        detector.detect_cooperation(observations, AGENT_IDS)
        status_before = detector.get_cooperation_status()

        detector.reset_episode()
        # last_step_coop 不在 reset_episode 的清空范围内
        # （只有 episode_coop 被清空）
        status_after = detector.get_cooperation_status()
        assert status_after == status_before  # 保留


class TestGetStats:
    """统计接口"""

    def test_get_stats_structure(self, detector):
        """get_stats 返回完整结构"""
        stats = detector.get_stats()
        assert 'episode_coop_agents' in stats
        assert 'last_step_coop' in stats

    def test_get_stats_after_detection(self, detector):
        """检测后统计应反映变化"""
        observations = [make_observations_near_landmark(i, distance=0.1) for i in range(3)]
        detector.detect_cooperation(observations, AGENT_IDS)

        stats = detector.get_stats()
        assert stats['episode_coop_agents'] == 3
        assert len(stats['last_step_coop']) == 3
