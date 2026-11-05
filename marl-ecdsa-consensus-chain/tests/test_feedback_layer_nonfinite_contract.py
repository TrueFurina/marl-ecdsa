#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BC→MARL 反馈层契约测试：非有限值处置 + 统计口径（2026-11-05）

背景（三处实测缺陷，全部在"链上指标 → 训练参数"这条反馈回路上）：

1. ``adaptive_lambda``：三项指标任一为 NaN 时，λ 直接跳到 **1.5*λ_base（上限）**
   并绕过 EMA 平滑。根因是收尾裁剪写成 ``max(lo, min(hi, x))`` —— 对 NaN 而言
   ``min(hi, nan)`` 返回 hi（比较恒 False），NaN 被"洗"成上界。实测 λ=0.15。
2. ``rl_lambda``：综合指标读的是 ``success_rate`` / ``success_count`` /
   ``total_rounds``，而 ``cw_pbft.get_consensus_stats()`` 只给
   ``consensus_success_rate``；合作率读 ``detector_stats``，而 ``bridge.get_stats()``
   从不产出这个键。两项都恒 0.5 ⇒ composite 与链上状态无关。另外
   ``episode_reward=NaN`` 会经 EMA 写进桶估值，``np.argmax`` 随后永久选中它。
3. ``consensus_shaper``：权重/贡献分不经值域检查，NaN/inf 直接进**奖励向量**
   （训练侧单步 NaN 奖励足以让整批梯度变 NaN）；``avg_shaping_per_step``
   累计的是 η 之前的量且不含势能项，实测比真实均值高 20 倍（η=0.05）。

本文件只断言"可判定的副作用"，不做实现细节耦合。
"""
import json
import math

import numpy as np
import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus
from marl.integration.adaptive_lambda import AdaptiveLambdaController
from marl.integration.consensus_shaper import ConsensusRewardShaper
from marl.integration.rl_lambda import RLLambdaScheduler

NAN = float("nan")
INF = float("inf")

BASE_STATS = {
    "consensus_stats": {"consensus_success_rate": 0.8},
    "cooperation_rate": 0.8,
    "security_pass_count": 8,
    "security_fail_count": 2,
}


def _pw(**over):
    """BASE_STATS 的浅覆盖（不修改原字典）。"""
    d = {k: v for k, v in BASE_STATS.items()}
    d.update(over)
    return d


def _obs(n_agents=3, width=10):
    return [np.zeros(width) for _ in range(n_agents)]


AGENT_IDS = ["a0", "a1", "a2"]


# =============================================================================
# 一、adaptive_lambda：NaN 不得把 λ 顶到上限
# =============================================================================


class TestAdaptiveLambdaNonFinite:
    def test_nan_consensus_does_not_pin_lambda_to_ceiling(self):
        """NaN 共识率曾被洗成上限 0.15（绕过 EMA）。现在应按"指标缺失"处理。"""
        c = AdaptiveLambdaController()
        lam = c.compute_adaptive_lambda(
            _pw(consensus_stats={"consensus_success_rate": NAN})
        )
        ceiling = 1.5 * c.lambda_base
        assert math.isfinite(lam), f"λ 非有限：{lam!r}"
        # 关键：不是"略低于上限"，而是完全没被拉上去
        assert lam < 1.4 * c.lambda_base, (
            f"NaN 共识率把 λ 抬到了 {lam!r}（上限 {ceiling}）——"
            "NaN 被裁剪洗成了上界"
        )
        assert c._lambda_max <= 1.4 * c.lambda_base

    def test_nan_cooperation_equals_metric_absent(self):
        """NaN 合作率与"没给合作率"应得到同一个 λ（都按缺失→中性 0.5）。"""
        a = AdaptiveLambdaController()
        b = AdaptiveLambdaController()
        lam_nan = a.compute_adaptive_lambda(_pw(cooperation_rate=NAN))
        lam_absent = b.compute_adaptive_lambda(
            {
                "consensus_stats": BASE_STATS["consensus_stats"],
                "security_pass_count": 8,
                "security_fail_count": 2,
            }
        )
        assert lam_nan == pytest.approx(lam_absent), (
            f"NaN 合作率 {lam_nan!r} 与缺失 {lam_absent!r} 处置不一致"
        )
        assert math.isfinite(lam_nan)

    def test_nan_security_counts_treated_as_missing(self):
        """NaN 计数不得被当成 0/0 或直接崩，应按缺失回退。"""
        c = AdaptiveLambdaController()
        lam = c.compute_adaptive_lambda(
            _pw(security_pass_count=NAN, security_fail_count=2)
        )
        assert math.isfinite(lam)
        assert 0.5 * c.lambda_base <= lam <= 1.5 * c.lambda_base

    def test_out_of_range_rate_is_clamped_to_documented_domain(self):
        """文档声明比率值域 [0,1]；150（百分数误传）必须按 1.0 处理。"""
        c_at_1 = AdaptiveLambdaController()
        c_150 = AdaptiveLambdaController()
        lam_1 = c_at_1.compute_adaptive_lambda(
            _pw(consensus_stats={"consensus_success_rate": 1.0})
        )
        lam_150 = c_150.compute_adaptive_lambda(
            _pw(consensus_stats={"consensus_success_rate": 150.0})
        )
        assert lam_150 == pytest.approx(lam_1, rel=1e-9)

    def test_non_numeric_counts_do_not_raise(self):
        """字符串计数曾能拼成 "8abc2" 再比较 → TypeError。必须不抛。"""
        c = AdaptiveLambdaController()
        for bad in ("abc", None, [], {}):
            lam = c.compute_adaptive_lambda(
                _pw(security_pass_count=bad, security_fail_count=2)
            )
            assert math.isfinite(lam), f"计数 {bad!r} 产出非有限 λ {lam!r}"

    @pytest.mark.parametrize(
        "stats",
        [
            {"consensus_stats": {"consensus_success_rate": NAN}, "cooperation_rate": NAN,
             "security_pass_count": NAN, "security_fail_count": NAN},
            {"consensus_stats": {"consensus_success_rate": INF}, "cooperation_rate": -INF},
            {"consensus_stats": {"consensus_success_rate": NAN, "success_count": NAN,
                                 "total_rounds": 0}},
            {"bc_scores": {"x": NAN, "y": NAN}, "bc_rewards": {"z": NAN}},
            {"cooperation_rate": "0.7", "security_stats": {"pass_count": "3",
                                                           "fail_count": "1"}},
        ],
    )
    def test_lambda_always_finite_and_in_range(self, stats):
        """对抗输入下 λ 必须始终有限且落在 [0.5λ, 1.5λ]。"""
        c = AdaptiveLambdaController()
        for _ in range(3):  # 多回合，覆盖 EMA 状态累积
            lam = c.compute_adaptive_lambda(stats)
            assert math.isfinite(lam), f"λ 非有限：{lam!r}（输入 {stats}）"
            assert 0.5 * c.lambda_base - 1e-12 <= lam <= 1.5 * c.lambda_base + 1e-12


# =============================================================================
# 二、rl_lambda：键契约 + NaN 不劫持元学习
# =============================================================================


def _cw_stats(success: int, fail: int) -> dict:
    node = CWPBFTConsensus("n0", ["n0", "n1", "n2", "n3"])
    node.consensus_success_count = success
    node.consensus_fail_count = fail
    return {"consensus_stats": node.get_consensus_stats()}


class TestRLLambdaContract:
    def test_composite_reacts_to_real_consensus_keys(self):
        """共识全失败与全成功必须给出不同的 composite（曾双双锁死在 0.5）。"""
        s = RLLambdaScheduler()
        c_fail = s._composite_metric(_cw_stats(0, 10))
        c_ok = s._composite_metric(_cw_stats(10, 0))
        assert c_fail == pytest.approx(0.5 - 0.4 * 0.5, abs=1e-9), (
            f"共识 0/10 的 composite={c_fail}（应为 0.3：只有共识项降到 0）"
        )
        assert c_ok == pytest.approx(0.5 + 0.4 * 0.5, abs=1e-9)
        assert abs(c_fail - 0.5) > 0.1, "共识项被钉死在默认 0.5，对链上状态不敏感"

    def test_composite_uses_top_level_cooperation_injection(self):
        """bridge.get_stats() 不产出 detector_stats；顶层 cooperation_rate 才是权威。"""
        s = RLLambdaScheduler()
        low = s._composite_metric({"cooperation_rate": 0.0})
        high = s._composite_metric({"cooperation_rate": 1.0})
        assert high - low == pytest.approx(0.35, abs=1e-9)

    def test_nan_metrics_yield_neutral_composite_and_finite_lambda(self):
        bad = {
            "consensus_stats": {"consensus_success_rate": NAN},
            "cooperation_rate": NAN,
            "security_stats": {"pass_count": NAN, "fail_count": 1},
        }
        s = RLLambdaScheduler()
        composite = s._composite_metric(bad)
        assert math.isfinite(composite) and composite == pytest.approx(0.5)
        lam = s.select_lambda_by_metric(bad)
        assert math.isfinite(lam), f"λ 为 {lam!r}：np.clip 不拦 NaN"
        assert s.lambda_min - 1e-12 <= lam <= s.lambda_max + 1e-12

    def test_nan_episode_reward_does_not_poison_bucket_state(self):
        """一次 NaN 回报曾让 argmax 永久锁死在同一桶（实测 20 回合 100%）。"""
        s = RLLambdaScheduler(epsilon=0.0)
        s.compute_adaptive_lambda({}, episode_reward=1.0)
        s.compute_adaptive_lambda({}, episode_reward=NAN)
        assert np.all(np.isfinite(s._bucket_rewards)), (
            f"桶估值被 NaN 污染：{s._bucket_rewards}"
        )
        assert s._last_reward == pytest.approx(1.0), "NaN 回报不该刷新回报基线"

    def test_history_is_strict_json_serializable(self):
        """历史记录要导出给 Dashboard；`NaN` 字面量会让 JSON.parse 直接抛错。"""
        s = RLLambdaScheduler(epsilon=0.0)
        for r in (1.0, NAN, 2.0, INF, 3.0):
            s.compute_adaptive_lambda({}, episode_reward=r)
        text = json.dumps(s.get_adaptation_history(), allow_nan=False)
        assert "NaN" not in text and "Infinity" not in text


# =============================================================================
# 三、consensus_shaper：非有限值不得进奖励向量；统计口径必须可对账
# =============================================================================


class TestShaperNonFiniteAndCaliber:
    def test_nan_weight_does_not_enter_reward_vector(self):
        s = ConsensusRewardShaper(n_agents=3)
        r = s.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                           consensus_weights={"a0": NAN})
        assert all(math.isfinite(v) for v in r), f"奖励向量含非有限值：{r}"

    def test_inf_weight_does_not_poison_cumulative_stats(self):
        """inf 权重曾让 total_consensus_bonus / avg 永久变 inf。"""
        s = ConsensusRewardShaper(n_agents=3)
        s.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                       consensus_weights={"a0": INF})
        st = s.get_stats()
        for k, v in st.items():
            if isinstance(v, float):
                assert math.isfinite(v), f"{k} 非有限：{v!r}"

    def test_nan_weight_equals_neutral_weight(self):
        """非有限权重按"与均值持平"处理 → 奖励与不传权重时一致。"""
        a = ConsensusRewardShaper(n_agents=3)
        b = ConsensusRewardShaper(n_agents=3)
        ra = a.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                            consensus_weights={"a0": NAN})
        rb = b.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                            consensus_weights={"a0": 1.0 / 3.0})
        assert ra == pytest.approx(rb)

    def test_nan_contribution_score_does_not_enter_potential(self):
        s = ConsensusRewardShaper(n_agents=3)
        r = s.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                           contribution_scores={"a0": NAN})
        assert all(math.isfinite(v) for v in r), f"奖励向量含非有限值：{r}"

    def test_nan_observation_is_blocked_at_outlet(self):
        """观测含 NaN → 空间势能 NaN → 曾直接进奖励。出口兜底必须挡住。"""
        bad = [np.array([0.0, 0.0, 0.0, 0.0, NAN, 0.0, 1.0, 2.0, 3.0, 4.0])
               for _ in range(3)]
        s = ConsensusRewardShaper(n_agents=3)
        r = s.shape_reward(bad, bad, [0, 0, 0], AGENT_IDS)
        assert all(math.isfinite(v) for v in r), f"奖励向量含非有限值：{r}"

    def test_avg_shaping_per_step_matches_actual_mean(self):
        """统计字段名就是"每步每智能体平均塑形"，必须与真实返回值的均值一致。

        修复前：累计 η 之前的原始分量、且不含势能项 → η=0.05 时高报 20 倍
        （0.18 vs 0.009）。
        """
        s = ConsensusRewardShaper(n_agents=3, eta=0.05)
        returned = []
        for _ in range(10):
            returned.append(
                s.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                               verification_status=[True, True, True])
            )
        actual = sum(sum(r) for r in returned) / (10 * 3)
        reported = s.get_stats()["avg_shaping_per_step"]
        assert reported == pytest.approx(actual, rel=1e-6, abs=1e-9), (
            f"报告 {reported!r} != 实际均值 {actual!r}"
        )

    def test_component_totals_sum_to_reported_average(self):
        """四个分量累计必须能对账到 avg（防止再加回"漏一项"的口径 bug）。"""
        s = ConsensusRewardShaper(n_agents=3, eta=0.05)
        for _ in range(5):
            s.shape_reward(_obs(), _obs(), [0, 0, 0], AGENT_IDS,
                           verification_status=[True, True, True],
                           consensus_weights={"a0": 0.6, "a1": 0.2, "a2": 0.2})
        st = s.get_stats()
        total = (st["total_potential_shaping"] + st["total_verification_bonus"]
                 + st["total_cooperation_bonus"] + st["total_consensus_bonus"])
        assert st["avg_shaping_per_step"] == pytest.approx(
            total / (5 * 3), rel=1e-5, abs=1e-8)

    def test_potential_based_invariant_still_holds(self):
        """F = η·(γΦ(s') − Φ(s))，Φ = 0.5·空间 + 0.5·贡献。这条不变式不许被改动带偏。"""
        s = ConsensusRewardShaper(n_agents=1, eta=0.5, gamma=0.8)
        curr = [np.array([0.0, 0.0, 0.0, 0.0, 3.0, 4.0, 0.0, 0.0, 0.0, 0.0])]
        nxt = [np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])]
        # cooperation_status 全 False 关掉合作 bonus，隔离出纯势能项
        r = s.shape_reward(curr, nxt, [0], ["a0"],
                           cooperation_status={"a0": False})
        phi_curr = 0.5 * (-5.0)   # 到自家路标的距离 = 5
        phi_next = 0.5 * 0.0
        expected = 0.5 * (0.8 * phi_next - phi_curr)
        assert r == [pytest.approx(expected)], f"{r} != {expected}"
