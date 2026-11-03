"""F06：负奖励区间贡献→治理份额映射的序性单测（移位归一修正）。

旧实现 `m/sum(m)` 在 sum(m)<0 时把最差智能体放大成最大份额（反直觉）；
移位归一 `share_i ∝ (m_i − min(m) + eps)` 修复为严格保序。"""
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from marl.analysis.contribution import ContributionLogger


def _logger(n=3):
    tmp = tempfile.mkdtemp()
    return ContributionLogger(n_agents=n, agent_ids=[f"agent_{i}" for i in range(n)],
                              log_dir=tmp, enabled=False)


def test_negative_rewards_are_order_monotonic():
    cd = _logger(3)
    share = cd._contribution_share(np.array([-3.0, -2.0, -1.0]))
    # 最优（离目标最近、奖励最大 = -1）份额最大；最差（-3）份额最小——旧实现恰好相反
    assert share[2] > share[1] > share[0], share
    assert abs(float(share.sum()) - 1.0) < 1e-9
    assert (share >= 0).all()


def test_ordering_is_monotonic_in_reward_random():
    cd = _logger(4)
    rng = np.random.default_rng(7)
    for _ in range(50):
        r = rng.normal(-5, 3, size=4)          # 常含负值、常 sum<0
        s = cd._contribution_share(r)
        order_r = np.argsort(r)                 # 奖励升序
        # 份额应随奖励单调不减：按奖励排序后份额不下降
        assert np.all(np.diff(s[order_r]) >= -1e-12), (r, s)
        assert abs(float(s.sum()) - 1.0) < 1e-9
        assert (s >= -1e-12).all()


def test_all_equal_gives_uniform():
    cd = _logger(3)
    s = cd._contribution_share(np.array([-2.0, -2.0, -2.0]))
    assert np.allclose(s, [1 / 3, 1 / 3, 1 / 3]), s


def test_positive_and_mixed_still_monotonic():
    cd = _logger(3)
    for r in ([5.0, 3.0, 1.0], [2.0, -1.0, -4.0], [0.0, 0.0, -1.0]):
        s = cd._contribution_share(np.array(r))
        assert abs(float(s.sum()) - 1.0) < 1e-9
        order = np.argsort(r)
        assert np.all(np.diff(s[order]) >= -1e-12), (r, s)
