# -*- coding: utf-8 -*-
"""全检 #8：省略故障注入的两个静默失效

背景（为什么要这两个测试）：
1) 故障节点数 k 由 `int(n * ratio)` 得出，小规模下会**塌缩为 0**
   —— n=3、ratio=0.33 时注入 0 个省略节点，机制完全不生效。比"故障率偏低"
   更糟：被抽掉的是"已注入故障"这一前提本身，后续所有容错结论都失去依据。
2) 对外方法 `get_omission_nodes()` 原先只读内部缓存而不触发懒初始化，
   于是"是否注入了故障"取决于调用顺序 —— 先问是空集、后问才非空，
   同一配置能给出两个答案。

只用轻量真对象（CWPBFTConsensus）构造，不依赖 torch / 磁盘 / 网络。
"""
import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus
from marl.integration.bc_integration import BlockchainMARLBridge


def _bridge(n_nodes: int = 3, ratio: float = 0.33, seed: int = 42):
    nodes = [f"node_{i}" for i in range(n_nodes)]
    consensus = CWPBFTConsensus("node_0", nodes)
    bridge = BlockchainMARLBridge(
        n_agents=n_nodes,
        n_landmarks=3,
        cw_pbft_consensus=consensus,
        omission_ratio=ratio,
        omission_seed=seed,
    )
    return bridge, nodes


class TestOmissionCountNoCollapse:
    """故障节点数不得在小规模下塌缩为 0"""

    def test_n3_ratio33_yields_one_node(self):
        bridge, nodes = _bridge(n_nodes=3, ratio=0.33)
        om = bridge._get_omission_nodes()
        # int(3*0.33) == 0 —— 这正是旧实现的 silent failure
        assert len(om) == 1, f"期望至少一个省略节点，实际 {len(om)}"

    def test_selected_nodes_are_real_members(self):
        bridge, nodes = _bridge(n_nodes=3, ratio=0.33)
        om = bridge._get_omission_nodes()
        assert set(om).issubset(set(nodes))

    def test_ratio40_rounds_to_one_and_deviation_is_known(self):
        """n=3 下 40% 只能取 1 个（33.3%）——记录离散取整的固有偏差"""
        bridge, nodes = _bridge(n_nodes=3, ratio=0.4)
        om = bridge._get_omission_nodes()
        assert len(om) == 1
        actual = len(om) / len(nodes)
        assert abs(actual - 1 / 3) < 1e-9
        # 对外材料必须标实测 k/n，不得沿用设定值 40%
        assert abs(actual - 0.4) > 0.05

    def test_ratio_above_one_is_clamped_not_crashed(self):
        """配置误配 >1 时不得抛 ValueError，夹到节点总数"""
        bridge, nodes = _bridge(n_nodes=3, ratio=1.5)
        om = bridge._get_omission_nodes()
        assert len(om) == 3

    def test_ratio_zero_means_no_omission(self):
        bridge, _ = _bridge(n_nodes=3, ratio=0.0)
        assert bridge._get_omission_nodes() == set()

    def test_no_consensus_engine_means_no_omission(self):
        bridge = BlockchainMARLBridge(
            n_agents=3, n_landmarks=3, cw_pbft_consensus=None, omission_ratio=0.33
        )
        assert bridge.get_omission_nodes() == set()

    def test_same_seed_is_deterministic(self):
        a, _ = _bridge(n_nodes=3, ratio=0.33, seed=7)
        b, _ = _bridge(n_nodes=3, ratio=0.33, seed=7)
        assert a._get_omission_nodes() == b._get_omission_nodes()


class TestPublicGetterIsOrderIndependent:
    """对外方法不得因调用顺序不同而给出不同答案"""

    def test_public_getter_populates_without_prior_internal_call(self):
        bridge, _ = _bridge(n_nodes=3, ratio=0.33)
        # 从不先调 _get_omission_nodes()，直接问对外方法
        assert len(bridge.get_omission_nodes()) == 1

    def test_both_call_orders_agree(self):
        bridge, _ = _bridge(n_nodes=3, ratio=0.33)
        first = bridge.get_omission_nodes()
        later = bridge._get_omission_nodes()
        assert first == later, "调用顺序不该影响结果"

    def test_getter_returns_copy_not_internal_set(self):
        bridge, _ = _bridge(n_nodes=3, ratio=0.33)
        got = bridge.get_omission_nodes()
        got.add("injected_by_caller")
        assert "injected_by_caller" not in bridge.get_omission_nodes()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
