"""
κ（贡献维度权重）单一真源契约测试

背景（2026-11-05 审计实测）：P1-4 声称把 κ 收敛为「单一真源」，但收敛的只是
`cw_pbft.get_consensus_stats()` 的**统计回显**；真正参与链上结算的
`ContributionScore.weighted_score` 仍是 0.40/0.35/0.25 三个字面常量。
把 config.json 的 blockchain.contribution_weights 改成 0.6/0.3/0.1 后：

    weighted_score(实际) = 0.65      weighted_score(声明) = 0.70

两个口径可以静默不一致，且没有告警 —— 报告里写的权重和实际分钱的权重不是一回事。

本文件锁定四件事：
1. 只有一份权重来源：config.json → blockchain.contribution_weights → 两个消费方
2. 非法配置（非有限 / 越界 / 不归一 / 结构错 / JSON 坏）一律**整体**回退默认值
3. 默认值不变（对外口径零变化：0.40 / 0.35 / 0.25）
4. weighted_score 在三维输入 ∈ [0,1] 时仍在 [0,1]（结算 clamp 的前提）
"""
import json
import math

import pytest

from blockchain import contribution_weights as cw
from blockchain.consensus import cw_pbft
from blockchain.contracts import incentive_contract
from blockchain.contracts.incentive_contract import ContributionScore, IncentiveContract
from blockchain.ledger.world_state import WorldState


def _write_config(tmp_path, weights):
    """写一份只含 blockchain.contribution_weights 的最小配置。"""
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps({'blockchain': {'contribution_weights': weights}}),
        encoding='utf-8',
    )
    return p


def _write_raw(tmp_path, text):
    p = tmp_path / "config.json"
    p.write_text(text, encoding='utf-8')
    return p


def _make_contract():
    """结算需要 agent 已在 WorldState 注册，否则 add_score 后读积分抛 KeyError。"""
    ws = WorldState()
    ws.register_agent('agent_0', '0x' + 'ab' * 32)
    return IncentiveContract(ws)


@pytest.fixture
def patched_weights(monkeypatch):
    """把两个消费方看到的 κ 三元组替换成指定值（含缓存层）。"""
    def _apply(triple):
        monkeypatch.setattr(cw, '_cached', triple, raising=False)
        monkeypatch.setattr(cw, 'get_contribution_weights', lambda: triple)
        monkeypatch.setattr(
            incentive_contract, 'get_contribution_weights', lambda: triple)
        monkeypatch.setattr(
            cw_pbft, '_contribution_weights', lambda: triple)
        return triple
    return _apply


# --------------------------------------------------------------------------- #
# 1. 默认口径不变
# --------------------------------------------------------------------------- #

class TestDefaultsUnchanged:
    def test_kappa_defaults_are_design_values(self):
        assert cw.KAPPA_DEFAULTS == {
            'task_score': 0.40,
            'cooperation_score': 0.35,
            'compliance_score': 0.25,
        }

    def test_default_weights_helper_matches_defaults(self):
        assert cw.default_weights() == (0.40, 0.35, 0.25)

    def test_shipped_config_yields_design_values(self):
        """仓库自带的 config.json 必须解析出 0.40/0.35/0.25 —— 口径零变化。"""
        assert cw.load_contribution_weights() == (0.40, 0.35, 0.25)

    def test_shipped_config_uses_relative_path_resolution(self):
        assert cw.DEFAULT_CONFIG_PATH.name == 'config.json'
        assert cw.DEFAULT_CONFIG_PATH.exists()

    def test_default_weighted_score_keeps_legacy_formula(self):
        """缺省配置下 weighted_score 与旧内联公式逐值一致（回归锁）。"""
        cs = ContributionScore('a', 1.0, 0.0, 1.0)
        assert cs.weighted_score == pytest.approx(0.40 * 1.0 + 0.35 * 0.0 + 0.25 * 1.0)


# --------------------------------------------------------------------------- #
# 2. 消费方真的读这一份（反「假单一真源」）
# --------------------------------------------------------------------------- #

class TestSingleSourceWiring:
    def test_weighted_score_follows_config_not_literals(self, patched_weights):
        """config 改成 0.6/0.3/0.1 后 weighted_score 必须是 0.70，不是 0.65。

        这是本 PR 的核心断言：修复前该值为 0.65（字面常量），差 0.05。
        """
        patched_weights((0.6, 0.3, 0.1))
        cs = ContributionScore('a', 1.0, 0.0, 1.0)
        assert cs.weighted_score == pytest.approx(0.70)
        assert cs.weighted_score != pytest.approx(0.65)

    def test_weighted_score_reads_config_file_end_to_end(self, tmp_path, monkeypatch):
        """不 patch 函数，只 patch 缓存入口：从真实文件解析到算分链路打通。"""
        p = _write_config(tmp_path, {
            'task_score': 0.5, 'cooperation_score': 0.3, 'compliance_score': 0.2,
        })
        monkeypatch.setattr(
            incentive_contract, 'get_contribution_weights',
            lambda: cw.load_contribution_weights(p),
        )
        cs = ContributionScore('a', 1.0, 0.0, 1.0)
        assert cs.weighted_score == pytest.approx(0.7)

    def test_consensus_stats_and_scoring_share_one_triple(self, patched_weights):
        """统计回显与算分必须同源 —— 逐分量比对，不只比其中一个。"""
        triple = patched_weights((0.5, 0.3, 0.2))
        engine = cw_pbft.CWPBFTConsensus('n0', ['n0', 'n1', 'n2'])
        derivation = engine.get_consensus_stats()['weight_derivation']
        assert derivation['κ_task'] == triple[0]
        assert derivation['κ_coop'] == triple[1]
        assert derivation['κ_compliance'] == triple[2]

    def test_cw_pbft_reads_the_shared_accessor(self):
        """cw_pbft 必须绑定到同一个取数函数对象 —— 不能有第二套读取路径。"""
        assert cw_pbft._contribution_weights is cw.get_contribution_weights

    def test_cw_pbft_compat_wrapper_delegates(self, tmp_path):
        """兼容包装必须真的转发到单一实现（否则又出现第二套校验）。"""
        assert cw_pbft._load_contribution_weights() == cw.load_contribution_weights()
        p = _write_config(tmp_path, {
            'task_score': 0.4, 'cooperation_score': 0.4, 'compliance_score': 0.2,
        })
        assert cw.load_contribution_weights(p) == (0.4, 0.4, 0.2)

    def test_settlement_delta_follows_config(self, patched_weights):
        """结算 delta = 10 + 10·weighted_score，必须随 config 变。"""
        patched_weights((0.5, 0.3, 0.2))
        contract = _make_contract()
        cs = ContributionScore('agent_0', 1.0, 0.0, 1.0)
        deltas = contract.settle_rewards(1, [cs])
        # weighted = 0.5*1 + 0.3*0 + 0.2*1 = 0.7 → 10 + 7 = 17
        assert deltas['agent_0'] == pytest.approx(17.0)

    def test_settlement_delta_differs_from_legacy_weights(self, patched_weights):
        """同一份输入，不同 κ 得到不同 delta —— 证明配置真的参与算钱。"""
        cs = ContributionScore('agent_0', 1.0, 0.0, 1.0)

        patched_weights((0.40, 0.35, 0.25))
        legacy = _make_contract().settle_rewards(1, [cs])['agent_0']

        patched_weights((0.60, 0.30, 0.10))
        tuned = _make_contract().settle_rewards(1, [cs])['agent_0']

        assert legacy == pytest.approx(16.5)
        assert tuned == pytest.approx(17.0)
        assert tuned > legacy


# --------------------------------------------------------------------------- #
# 3. 非法配置一律整体回退
# --------------------------------------------------------------------------- #

class TestInvalidConfigFallsBack:
    def test_non_normalized_sum_falls_back(self, tmp_path, caplog):
        p = _write_config(tmp_path, {
            'task_score': 0.6, 'cooperation_score': 0.3, 'compliance_score': 0.3,
        })
        with caplog.at_level('WARNING'):
            assert cw.load_contribution_weights(p) == cw.default_weights()
        assert 'Σκ' in caplog.text

    def test_negative_weight_rejected_even_if_sum_is_one(self, tmp_path, caplog):
        """{1.5, -0.5, 0.0} 和为 1，旧实现会照单全收 → weighted_score 冲到 1.5。"""
        p = _write_config(tmp_path, {
            'task_score': 1.5, 'cooperation_score': -0.5, 'compliance_score': 0.0,
        })
        with caplog.at_level('WARNING'):
            assert cw.load_contribution_weights(p) == cw.default_weights()
        assert 'task_score' in caplog.text

    def test_weight_above_one_rejected(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': 1.2, 'cooperation_score': -0.1, 'compliance_score': -0.1,
        })
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_nan_weight_rejected(self, tmp_path):
        p = _write_raw(tmp_path,
                       '{"blockchain": {"contribution_weights": '
                       '{"task_score": NaN, "cooperation_score": 0.35, '
                       '"compliance_score": 0.65}}}')
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_infinite_weight_rejected(self, tmp_path):
        p = _write_raw(tmp_path,
                       '{"blockchain": {"contribution_weights": '
                       '{"task_score": Infinity, "cooperation_score": 0.0, '
                       '"compliance_score": -Infinity}}}')
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_non_numeric_weight_rejected(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': 'high', 'cooperation_score': 0.35, 'compliance_score': 0.25,
        })
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_none_weight_rejected(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': None, 'cooperation_score': 0.35, 'compliance_score': 0.25,
        })
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_non_dict_section_rejected(self, tmp_path):
        p = _write_config(tmp_path, [0.4, 0.35, 0.25])
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_blockchain_section_not_a_dict(self, tmp_path):
        p = _write_raw(tmp_path, '{"blockchain": [1, 2, 3]}')
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_missing_key_falls_back_when_sum_breaks(self, tmp_path):
        """缺项沿用默认值 → 0.5+0.35+0.25=1.1 ≠ 1 → 整体回退（不部分采纳）。"""
        p = _write_config(tmp_path, {'task_score': 0.5})
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_malformed_json_falls_back(self, tmp_path):
        p = _write_raw(tmp_path, '{not json')
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_missing_file_falls_back(self, tmp_path):
        assert cw.load_contribution_weights(tmp_path / 'nope.json') == cw.default_weights()

    def test_json_root_is_list(self, tmp_path):
        p = _write_raw(tmp_path, '[1, 2, 3]')
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_fallback_is_all_or_nothing(self, tmp_path):
        """非法配置不得「部分采纳」：结果要么全默认，要么与配置逐值相等。"""
        p = _write_config(tmp_path, {
            'task_score': 0.7, 'cooperation_score': 0.7, 'compliance_score': 0.25,
        })
        got = cw.load_contribution_weights(p)
        assert got == cw.default_weights()
        assert math.isclose(sum(got), 1.0, abs_tol=1e-9)


# --------------------------------------------------------------------------- #
# 4. 边界与不变式
# --------------------------------------------------------------------------- #

class TestBoundaries:
    def test_boundary_weights_accepted(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': 1.0, 'cooperation_score': 0.0, 'compliance_score': 0.0,
        })
        assert cw.load_contribution_weights(p) == (1.0, 0.0, 0.0)

    def test_zero_weights_rejected(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': 0.0, 'cooperation_score': 0.0, 'compliance_score': 0.0,
        })
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_tolerance_accepts_tiny_drift(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': 0.4 + 3e-7, 'cooperation_score': 0.35, 'compliance_score': 0.25,
        })
        assert cw.load_contribution_weights(p) == pytest.approx((0.4 + 3e-7, 0.35, 0.25))

    def test_tolerance_rejects_beyond_epsilon(self, tmp_path):
        p = _write_config(tmp_path, {
            'task_score': 0.4 + 5e-6, 'cooperation_score': 0.35, 'compliance_score': 0.25,
        })
        assert cw.load_contribution_weights(p) == cw.default_weights()

    def test_normalization_tolerance_is_tight(self):
        assert cw.NORMALIZATION_TOL <= 1e-6

    @pytest.mark.parametrize('task', [0.0, 0.5, 1.0])
    @pytest.mark.parametrize('coop', [0.0, 0.5, 1.0])
    @pytest.mark.parametrize('comp', [0.0, 0.5, 1.0])
    def test_weighted_score_stays_in_unit_interval(self, task, coop, comp):
        """三维输入 ∈ [0,1] ⇒ weighted_score ∈ [0,1]（结算 clamp 的前提不变式）。"""
        cs = ContributionScore('a', task, coop, comp)
        assert 0.0 <= cs.weighted_score <= 1.0

    def test_zero_scores_give_zero_weighted(self):
        assert ContributionScore('a', 0.0, 0.0, 0.0).weighted_score == 0.0

    def test_full_scores_give_one(self):
        assert ContributionScore('a', 1.0, 1.0, 1.0).weighted_score == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# 5. 缓存语义
# --------------------------------------------------------------------------- #

class TestCache:
    def test_cache_is_used_after_first_call(self, monkeypatch):
        calls = []

        def _counting(path=None):
            calls.append(path)
            return (0.4, 0.35, 0.25)

        monkeypatch.setattr(cw, 'load_contribution_weights', _counting)
        monkeypatch.setattr(cw, '_cached', None, raising=False)
        assert cw.get_contribution_weights() == (0.4, 0.35, 0.25)
        assert cw.get_contribution_weights() == (0.4, 0.35, 0.25)
        assert len(calls) == 1, '第二次调用不应再读配置'

    def test_reset_forces_reread(self, monkeypatch):
        calls = []

        def _counting(path=None):
            calls.append(path)
            return (0.4, 0.35, 0.25)

        monkeypatch.setattr(cw, 'load_contribution_weights', _counting)
        monkeypatch.setattr(cw, '_cached', None, raising=False)
        cw.get_contribution_weights()
        cw.reset_contribution_weights_cache()
        cw.get_contribution_weights()
        assert len(calls) == 2

    def test_cached_value_matches_loader(self):
        cw.reset_contribution_weights_cache()
        try:
            assert cw.get_contribution_weights() == cw.load_contribution_weights()
        finally:
            cw.reset_contribution_weights_cache()
