"""激励链路的非有限值防御回归锁（2026-11-03）

缺陷形态：奖励/贡献的钳位写成 `max(low, min(high, x))`，而 `min`/`max` 的比较
对 NaN 恒为 False，NaN 会被原样「保留在上界」：

    max(0.0, min(1.0, float('nan'))) == 1.0

于是**奖励计算坏掉的智能体反而拿满分**。实测（修复前）：

    good   (env_reward=0.0) → task=0.4286, delta=17.71
    broken (env_reward=NaN) → task=1.0000, delta=20.00   ← 谁算崩了谁拿钱最多

更糟的是这条 delta 会经 `total = env + λ·bc` 回流到策略奖励，等于奖励「制造
NaN」；而 `WorldState.add_score` 也不拦 NaN，一旦写进去 `NaN + x` 恒为 NaN，
该智能体积分被**永久污染**（已实测，后续加减都救不回来）。

修复：新增 `clamp_finite()`（非有限值 → fallback=0.0），在四处收口——
贡献度 task_score、结算 weighted_score、奖励归一化、bc_reward 裁剪；
`WorldState.add_score` 改为「非有限值即拒收」（fail-closed，不静默钳位）。

本文件锁住：不误奖（NaN 不得成为最高分）、不污染账本、不误伤正常值。
"""
import math

import pytest

from blockchain.contracts.incentive_contract import (
    ContributionScore, IncentiveContract, clamp_finite,
)
from blockchain.ledger.world_state import WorldState
from marl.integration.settlement_coordinator import SettlementCoordinator

NAN = float("nan")
INF = float("inf")


def _setup(agent_ids=("good", "broken")):
    ws = WorldState()
    for aid in agent_ids:
        ws.register_agent(aid, "00" * 33)
    ic = IncentiveContract(ws)
    sc = SettlementCoordinator(incentive_contract=ic)
    return ws, ic, sc


class TestClampFinite:
    def test_nan_returns_fallback_not_upper_bound(self):
        """NaN 不得被钳成上界（这正是原始缺陷）"""
        assert clamp_finite(NAN, 0.0, 1.0) == 0.0
        assert clamp_finite(NAN, -20.0, 20.0) == 0.0

    def test_infinities_are_treated_as_invalid(self):
        """±inf 同属「计算坏了」，一律按 fallback 处理"""
        assert clamp_finite(INF, 0.0, 1.0) == 0.0
        assert clamp_finite(-INF, 0.0, 1.0) == 0.0

    def test_normal_values_still_clamped(self):
        """正常值仍按上下界钳位（不误伤）"""
        assert clamp_finite(0.5, 0.0, 1.0) == 0.5
        assert clamp_finite(-3.0, 0.0, 1.0) == 0.0
        assert clamp_finite(9.0, 0.0, 1.0) == 1.0

    def test_non_numeric_returns_fallback(self):
        """非数值同样按 fallback 处理，不抛异常"""
        assert clamp_finite("abc", 0.0, 1.0) == 0.0
        assert clamp_finite(None, 0.0, 1.0) == 0.0


class TestContributionScoreGuard:
    def test_nan_env_reward_scores_zero(self):
        """NaN 环境奖励 → task_score = 0（不是 1）"""
        _, ic, _ = _setup()
        cs = ic.compute_contribution("good", NAN, did_cooperate=True, did_betray=False)
        assert cs.task_score == 0.0

    def test_nan_agent_does_not_out_earn_normal_agent(self):
        """端到端：算崩的智能体不得比表现正常的拿得多"""
        _, ic, sc = _setup()
        scores = sc.compute_contribution_scores(
            agent_ids=["good", "broken"],
            env_rewards=[0.0, NAN],
            coop_results={"good": (True, False), "broken": (True, False)},
        )
        deltas = sc.settle(1, scores)
        assert deltas["good"] > deltas["broken"]

    def test_normal_reward_path_unchanged(self):
        """回归：正常奖励的贡献分与 delta 与修复前一致"""
        _, ic, sc = _setup()
        cs = ic.compute_contribution("good", 1.0, did_cooperate=True, did_betray=False)
        assert cs.task_score == 1.0
        assert cs.weighted_score == pytest.approx(1.0)
        deltas = sc.settle(2, [cs])
        assert deltas["good"] == pytest.approx(20.0)   # BASE 10 + CONTRIB 10*1.0


class TestLedgerNotPoisoned:
    def test_add_score_rejects_nan(self):
        """NaN 增量被拒收，积分不被永久污染"""
        ws = WorldState()
        ws.register_agent("a", "00" * 33)
        ws.add_score("a", NAN)
        assert ws.get_score("a") == 0.0
        ws.add_score("a", 5.0)
        assert ws.get_score("a") == 5.0

    def test_add_score_rejects_inf(self):
        ws = WorldState()
        ws.register_agent("a", "00" * 33)
        ws.add_score("a", INF)
        assert ws.get_score("a") == 0.0

    def test_nan_weighted_score_does_not_reach_ledger(self):
        """调用方直接塞带 NaN 的评分，账本仍保持有限值"""
        ws, ic, _ = _setup()
        ic.settle_rewards(3, [ContributionScore("good", NAN, 1.0, 1.0)])
        assert math.isfinite(ws.get_score("good"))
        assert ws.get_score("good") == pytest.approx(10.0)   # 只拿基础奖励

    def test_cumulative_contribution_not_poisoned(self):
        ws, ic, _ = _setup()
        ic.settle_rewards(4, [ContributionScore("good", NAN, 1.0, 1.0)])
        assert math.isfinite(ws.get_contribution("good"))


class TestTotalRewardGuard:
    def test_nan_bc_reward_gives_no_silent_bonus(self):
        """bc_reward 为 NaN 时不得静默送 λ*20 的分"""
        _, _, sc = _setup()
        sc._bc_rewards["good"] = NAN
        assert sc.compute_total_reward("good", 1.0) == pytest.approx(1.0)

    def test_normal_bc_reward_unchanged(self):
        """回归：正常 bc_reward 的融合结果不变"""
        _, _, sc = _setup()
        sc._bc_rewards["good"] = 10.0
        # total = env + λ*bc = 1.0 + 0.1*10
        assert sc.compute_total_reward("good", 1.0) == pytest.approx(2.0)
