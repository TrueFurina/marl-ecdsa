"""S1–S9 建议项（2026-10-11 独立代码审查报告 §二）的守卫测试。

覆盖可测项（行为变化类）：
- S1  ``get_consensus_stats()['weights']`` 必须是副本，外部篡改不得污染内部权重表
- S4  ``fast_consensus`` 跳过阈值检查 → 必须发出 warning 级醒目告警
- S5  超时判定使用单调时钟（monotonic 前进才触发超时；wall clock 回拨不冻结判定）
- S6  空节点集 ``get_primary`` 返回空串而非抛 ZeroDivisionError
- S7  纪元展宽 R 排除封禁节点（有封禁时不再恒为 inf；无封禁时与旧公式一致）
- S8  ``update_weight`` 未知节点必须告警（不再静默丢弃）

S2/S3/S9 为"标注登记"类（代码内注释 + 报告登记，零行为变化），无测试；
S9 的"VDN 训练路径不经 mixer"契约另由 test_algorithm_family_contract.py 守护。
"""
import logging
import time

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

ENGINES = [CWPBFTConsensus, StandardPBFTConsensus]
NODES = ["node_0", "node_1", "node_2"]
_CW_LOGGER = "blockchain.consensus.cw_pbft"


# ---------------------------------------------------------------- S1

class TestStatsReturnsCopy:
    """S1：get_consensus_stats 返回内部引用 → 已改为副本。"""

    @pytest.mark.parametrize("engine_cls", ENGINES, ids=["cw", "std"])
    def test_mutating_returned_weights_does_not_pollute_internal(self, engine_cls):
        eng = engine_cls("node_0", NODES)
        stats = eng.get_consensus_stats()
        stats["weights"]["node_0"] = 999.0  # 就地篡改返回值
        assert eng.get_weights()["node_0"] != 999.0, \
            "get_consensus_stats 返回的权重被外部篡改污染了内部表（S1 回归）"

    def test_weights_values_still_live_after_update(self):
        """副本不得是过期快照：内部权重更新后新取的 stats 必须反映新值。"""
        eng = CWPBFTConsensus("node_0", NODES)
        eng.update_weight("node_0", 1.2)
        assert eng.get_consensus_stats()["weights"]["node_0"] == 1.2


# ---------------------------------------------------------------- S4

class TestFastConsensusWarning:
    """S4：fast_consensus 跳阈值恒 True → 必须有 warning 级醒目告警。"""

    def test_fast_consensus_emits_warning(self, caplog):
        pbft = CWPBFTConsensus("node_0", NODES)
        with caplog.at_level(logging.WARNING, logger=_CW_LOGGER):
            ok = pbft.fast_consensus("hash_s4", "node_0")
        assert ok
        assert any(
            r.levelno == logging.WARNING and "fast_consensus" in r.getMessage()
            and "跳过权重阈值检查" in r.getMessage()
            for r in caplog.records
        ), "fast_consensus 必须发出'跳过阈值检查'告警（S4 回归）"


# ---------------------------------------------------------------- S5

class TestTimeoutUsesMonotonic:
    """S5：读写两侧都必须走 time.monotonic。

    三用例组合分别杀死：全 wall clock 回归、读写时钟口径混用、wall 回拨冻结。
    """

    @pytest.mark.parametrize("engine_cls", ENGINES, ids=["cw", "std"])
    def test_monotonic_advance_triggers_timeout(self, monkeypatch, engine_cls):
        fake = {"t": 1_000_000.0}
        monkeypatch.setattr(time, "monotonic", lambda: fake["t"])
        eng = engine_cls("node_0", NODES)
        eng.start_consensus("hash_s5")
        fake["t"] += 6.0  # 前进 6 秒（超时阈值 5 秒）
        assert eng.is_timed_out(), "单调时钟前进 6s 后必须判定超时（S5 回归）"

    @pytest.mark.parametrize("engine_cls", ENGINES, ids=["cw", "std"])
    def test_no_timeout_immediately_after_start(self, monkeypatch, engine_cls):
        fake = {"t": 2_000_000.0}
        monkeypatch.setattr(time, "monotonic", lambda: fake["t"])
        eng = engine_cls("node_0", NODES)
        eng.start_consensus("hash_s5b")
        assert not eng.is_timed_out(), \
            "刚开始共识不得误报超时（读/写侧时钟口径混用会在此暴露）"

    @pytest.mark.parametrize("engine_cls", ENGINES, ids=["cw", "std"])
    def test_wall_clock_rollback_does_not_freeze_timeout(self, monkeypatch, engine_cls):
        """NTP 回拨场景：wall clock 后退 1000s、真实经过 6s → 仍正确判定超时。"""
        fake_mono = {"t": 3_000_000.0}
        fake_wall = {"t": 1_000_000.0}
        monkeypatch.setattr(time, "monotonic", lambda: fake_mono["t"])
        monkeypatch.setattr(time, "time", lambda: fake_wall["t"])
        eng = engine_cls("node_0", NODES)
        eng.start_consensus("hash_s5c")
        fake_wall["t"] -= 1000.0   # wall clock 回拨
        fake_mono["t"] += 6.0      # monotonic 前进（真实经过时间）
        assert eng.is_timed_out(), "wall clock 回拨不得导致永不超时（S5 回归）"


# ---------------------------------------------------------------- S6

class TestGetPrimaryEmptyNodes:
    """S6：n=0 时 get_primary 不得抛 ZeroDivisionError。"""

    @pytest.mark.parametrize("engine_cls", ENGINES, ids=["cw", "std"])
    def test_empty_nodes_returns_blank_not_crash(self, engine_cls):
        eng = engine_cls("node_0", [])
        assert eng.get_primary(0) == ""
        assert eng.get_primary(12345) == ""
        assert eng.is_primary(0) is False


# ---------------------------------------------------------------- S7

class TestREpochMetricExcludesBanned:
    """S7：纪元度量 R 排除封禁节点（修复前任一 w=0 使 R 恒为 inf）。"""

    @staticmethod
    def _drive_to_epoch_end(pbft):
        summary = None
        for _ in range(pbft.EPOCH_ROUNDS):
            pbft._record_participation()
            summary = pbft.end_of_round_epoch_update() or summary
        return summary

    def test_R_not_inf_when_banned_exists(self):
        pbft = CWPBFTConsensus("node_0", NODES)
        for nid in NODES:
            pbft.update_weight(nid, 1.2)
        pbft.update_weight("node_2", -1.0)  # 封禁 node_2 → w=0
        summary = self._drive_to_epoch_end(pbft)
        assert summary is not None, "第 50 轮应触发纪元末展宽"
        assert summary["R"] != float("inf"), \
            "存在封禁节点时 R 不得恒为 inf（S7 回归）"
        assert "node_2" in summary["excluded_banned"]
        active = [w for w in summary["weights"].values() if w > 0]
        assert active, "封禁后仍应有非封禁节点"
        assert abs(summary["R"] - max(active) / min(active)) < 1e-9

    def test_R_matches_plain_formula_when_no_banned(self):
        """无封禁时 R 与修复前逐值一致（保护既有实验复现的回归护栏）。"""
        pbft = CWPBFTConsensus("node_0", NODES)
        pbft.update_weight("node_0", 1.0)
        pbft.update_weight("node_1", 1.25)
        pbft.update_weight("node_2", 1.5)
        summary = self._drive_to_epoch_end(pbft)
        assert summary is not None
        vals = list(summary["weights"].values())
        assert summary["excluded_banned"] == []
        assert abs(summary["R"] - max(vals) / min(vals)) < 1e-9


# ---------------------------------------------------------------- S8

class TestUpdateWeightUnknownNode:
    """S8：update_weight 未知节点不得静默丢弃。"""

    def test_unknown_node_emits_warning_and_no_change(self, caplog):
        pbft = CWPBFTConsensus("node_0", NODES)
        before = pbft.get_weights()
        with caplog.at_level(logging.WARNING, logger=_CW_LOGGER):
            pbft.update_weight("ghost_node", 1.2)
        assert pbft.get_weights() == before, "未知节点更新不得影响权重表"
        assert any(
            r.levelno == logging.WARNING and "ghost_node" in r.getMessage()
            for r in caplog.records
        ), "未知节点的 update_weight 必须告警（S8 回归）"
