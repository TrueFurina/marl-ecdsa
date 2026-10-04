"""
行为学合作率口径回归测试（2026-09-22 新增）

背景（为什么必须有这组测试）：
legacy 口径下 `detect_cooperation()` 对 `selfish_flags=True` 的智能体**短路判 False 且不评估行为**，
导致 `avg_cooperation_rate` 退化为"未被标记背叛的步数占比"的确定性函数——
用它比较 greedy / random 两种背叛模式的"协作破坏力"是循环论证。

`behavioral_only=True` 让合作率回到纯行为学判定（距任意路标 < 阈值），
同时把"被标记背叛"独立记账，保证 BC 结算仍能惩罚背叛者。

下面每个测试都做过变异验证：故意改回错误行为必须 FAIL。
"""
import pytest
import sys
import numpy as np

sys.path.insert(0, '.')

from marl.integration.cooperation_detector import CooperationDetector


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


def _obs(near_idx=None, distance=0.3, far_distance=2.0, n_landmarks=3):
    """构造观测：第 near_idx 个路标距离为 distance，其余为 far_distance。"""
    o = np.zeros(4 + 2 * n_landmarks + 2 * 2, dtype=float)
    for j in range(n_landmarks):
        d = distance if j == near_idx else far_distance
        o[4 + 2 * j] = d
        o[4 + 2 * j + 1] = 0.0
    return o.tolist()


@pytest.fixture
def det():
    return CooperationDetector(n_agents=3, n_landmarks=3)


class TestBehavioralOnlyCooperation:
    """behavioral_only=True：合作判定只看行为，不看背叛标记"""

    def test_flagged_agent_near_landmark_is_still_cooperating(self, det):
        """变异验证：若把 behavioral_only 分支误删（退回 legacy），此测试 FAIL（False≠True）"""
        observations = [_obs(near_idx=0, distance=0.1), _obs(), _obs()]
        result = det.detect_cooperation(
            observations, AGENT_IDS,
            selfish_flags=[True, False, False],
            behavioral_only=True,
        )
        assert result["agent_0"] is True, (
            "行为学口径下，被标记背叛但确实靠近路标的智能体，行为上仍是合作的"
        )

    def test_flagged_agent_far_from_landmark_is_neutral_not_false(self, det):
        """行为学口径下不存在'因标记而判背叛'的 False，只可能是 None（未达标）"""
        observations = [_obs(near_idx=None, distance=2.0), _obs(), _obs()]
        result = det.detect_cooperation(
            observations, AGENT_IDS,
            selfish_flags=[True, False, False],
            behavioral_only=True,
        )
        assert result["agent_0"] is None, "距离未达标应是中性 None，而非背叛 False"

    def test_legacy_semantics_unchanged(self, det):
        """默认口径必须仍是 legacy：标记即判 False（保护既有历史数字）"""
        observations = [_obs(near_idx=0, distance=0.1), _obs(), _obs()]
        result = det.detect_cooperation(
            observations, AGENT_IDS, selfish_flags=[True, False, False]
        )
        assert result["agent_0"] is False, "默认口径保持 legacy 语义"

    def test_greedy_flag_every_step_does_not_crash_coop_rate_to_zero(self, det):
        """
        核心回归：greedy 模式每步都背叛（flags 全 True），
        但行为学合作率不应因此变成 0。
        变异验证：若 behavioral_only 未生效，coop 计数为 0 → FAIL。
        """
        flags = [True, True, True]  # 全部智能体每步都被标记
        observations = [_obs(near_idx=0, distance=0.1),
                        _obs(near_idx=1, distance=0.1),
                        _obs(near_idx=2, distance=0.1)]
        for _ in range(10):
            det.detect_cooperation(observations, AGENT_IDS,
                                   selfish_flags=flags, behavioral_only=True)
        stats = det._episode_coop["agent_0"]
        assert stats["coop"] == 10, (
            f"行为学口径下所有步都靠近路标 → coop 应为 10，实际 {stats['coop']}"
        )


class TestBetrayalAccountingDecoupled:
    """背叛标记必须与行为解耦但仍独立记账（BC 结算依赖它）"""

    def test_betrayal_counted_under_behavioral_only(self, det):
        """
        变异验证：若漏掉 flagged_ids 的 betray 记账，此测试 FAIL（betray=0）。
        """
        observations = [_obs(near_idx=0, distance=0.1), _obs(), _obs()]
        for _ in range(4):
            det.detect_cooperation(observations, AGENT_IDS,
                                   selfish_flags=[True, False, False],
                                   behavioral_only=True)
        stats = det._episode_coop["agent_0"]
        assert stats["betray"] == 4, (
            f"结算需要背叛记账：应为 4，实际 {stats['betray']}"
        )
        assert stats["coop"] == 4, "同一批步既是'被标记背叛'，行为上也是合作"
        assert det.get_episode_betrayal("agent_0") == 4

    def test_betrayal_all_zero_when_no_flags(self, det):
        observations = [_obs(near_idx=0, distance=0.1), _obs(), _obs()]
        for _ in range(3):
            det.detect_cooperation(observations, AGENT_IDS, behavioral_only=True)
        assert det.get_episode_betrayal("agent_0") == 0
        assert det._episode_coop["agent_0"]["betray"] == 0

    def test_reset_clears_betrayal(self, det):
        observations = [_obs(near_idx=0, distance=0.1), _obs(), _obs()]
        det.detect_cooperation(observations, AGENT_IDS,
                               selfish_flags=[True, False, False],
                               behavioral_only=True)
        assert det.get_episode_betrayal("agent_0") == 1
        det.reset_episode()
        assert det.get_episode_betrayal("agent_0") == 0, "reset 必须清空背叛记账"
        assert det._episode_coop == {}

    def test_episode_verdict_still_detects_betrayer(self, det):
        """
        get_episode_cooperation 的 did_betray 判定在行为学口径下必须仍然有效，
        否则 BC 结算会停止惩罚背叛者。
        """
        observations = [_obs(near_idx=0, distance=0.1), _obs(), _obs()]
        for _ in range(10):
            det.detect_cooperation(observations, AGENT_IDS,
                                   selfish_flags=[True, False, False],
                                   behavioral_only=True)
        did_cooperate, did_betray = det.get_episode_cooperation("agent_0")
        assert did_betray is True, "背叛率 100% > 50% → 必须判为背叛（结算依赖）"
