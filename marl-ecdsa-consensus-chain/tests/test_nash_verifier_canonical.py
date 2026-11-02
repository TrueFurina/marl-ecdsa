"""NashEquilibriumVerifier 经典博弈回归（2026-11-02）。

用三个有已知纳什均衡的标准 2×2 博弈钉住判据：

- **囚徒困境** `[[3,0],[5,1]]`：唯一纯均衡 (D,D)，无混合均衡；
- **猎鹿** `[[4,0],[3,3]]`：纯 (C,C) + (D,D)，外加混合 p=0.75；
- **鹰鸽** `[[2,1],[3,0]]`：纯 (C,D) + (D,C)，外加混合 p=0.5。

旧实现把 p_me 算成 `(M[1,0]-M[1,1])/denom`，当 `M[0,1] != M[1,0]` 时得到
无效值（>1 或 0），于是**混合策略均衡被漏报**（鹰鸽 p=0.5、猎鹿 p=0.75
都被判成非均衡）。对称博弈中双方混合概率相同，p_me 应与 p_opp 同公式。
"""
import numpy as np

from marl.analysis.nash_verifier import NashEquilibriumVerifier


def _nash_results(M):
    return [r for r in NashEquilibriumVerifier().find_nash_equilibria(M) if r.is_nash]


def _pure_set(results):
    return {r.strategy_profile for r in results if r.strategy_profile[0] != "mixed"}


def _has_mixed(results):
    return any(r.strategy_profile[0] == "mixed" for r in results)


class TestCanonicalGames:
    def test_prisoners_dilemma_only_defect_defect(self):
        M = np.array([[3.0, 0.0], [5.0, 1.0]])
        res = _nash_results(M)
        assert _pure_set(res) == {("defect", "defect")}
        assert not _has_mixed(res), "囚徒困境没有混合策略均衡"

    def test_stag_hunt_two_pure_plus_mixed(self):
        M = np.array([[4.0, 0.0], [3.0, 3.0]])
        res = _nash_results(M)
        assert _pure_set(res) == {("cooperate", "cooperate"), ("defect", "defect")}
        assert _has_mixed(res), "猎鹿应有 p=0.75 的混合均衡"

    def test_hawk_dove_two_pure_plus_mixed(self):
        M = np.array([[2.0, 1.0], [3.0, 0.0]])
        res = _nash_results(M)
        assert _pure_set(res) == {("cooperate", "defect"), ("defect", "cooperate")}
        assert _has_mixed(res), "鹰鸽应有 p=0.5 的混合均衡"
