"""
参与率驱动权重展宽（路线C机制合入主引擎）单测
覆盖：MAX_WEIGHT 钳制 / 参与率记录 / 纪元末展宽 / 恢复路径 / 边界
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.consensus.cw_pbft import CWPBFTConsensus

logging.basicConfig(level=logging.CRITICAL)

NODES = ['node_0', 'node_1', 'node_2', 'node_3', 'node_4', 'node_5']


@pytest.fixture
def pbft():
    return CWPBFTConsensus('node_0', NODES)


class TestMaxWeightClamp:
    def test_update_weight_clamped(self, pbft):
        """超上界请求被钳制到 MAX_WEIGHT=1.5（P1-15）"""
        pbft.update_weight('node_1', 9.9)
        assert pbft.get_weights()['node_1'] == 1.5

    def test_boundary_exact(self, pbft):
        """恰好 1.5 不被钳制"""
        pbft.update_weight('node_1', 1.5)
        assert pbft.get_weights()['node_1'] == 1.5

    def test_ban_still_zero(self, pbft):
        """封禁语义不受钳制影响（<=0 → 0）"""
        pbft.update_weight('node_1', 0.0)
        assert pbft.get_weights()['node_1'] == 0.0

    def test_min_still_protected(self, pbft):
        """下界保护不受钳制影响"""
        pbft.update_weight('node_1', 0.01)
        assert pbft.get_weights()['node_1'] == 0.1


class TestParticipationRecording:
    def test_record_counts_voters(self, pbft):
        """成功共识轮把 PREPARE 投票者计入窗口"""
        pbft.simulated_consensus('h1', 'node_0', byzantine_nodes={'node_5'})
        assert pbft._part_rounds == 1
        # 诚实 5 人投票，node_5 省略
        assert pbft._part_total['node_0'] == 1
        assert pbft._part_total['node_5'] == 0

    def test_sybil_not_counted(self, pbft):
        """非注册节点混入投票表不被统计（防女巫污染）"""
        pbft._votes['prepare']['ghost'] = object()
        pbft._record_participation()
        assert 'ghost' not in pbft._part_total


class TestEpochBroadening:
    def test_non_epoch_returns_none(self, pbft):
        """非纪元末调用返回 None 且权重不变"""
        before = pbft.get_weights()
        assert pbft.end_of_round_epoch_update() is None
        assert pbft.get_weights() == before

    def test_epoch_zero_participation_decays(self, pbft):
        """零参与节点纪元末权重衰减（FLOOR=0.25 温和衰减）

        注：每轮需 reset（真实协议路径）；省略数须使诚实方权重可达 2/3 阈值，
        否则共识失败、参与率无从记录。
        """
        silent = {'node_5'}  # 1/6 省略，诚实 5/6 权重可达阈值
        for i in range(100):  # 2 个完整纪元
            pbft.reset()
            pbft.simulated_consensus(f'h{i}', 'node_0', byzantine_nodes=silent)
            pbft.end_of_round_epoch_update()
        w = pbft.get_weights()
        # 省略节点权重显著低于诚实节点（多纪元累计衰减）
        assert w['node_5'] < w['node_0'] * 0.7
        # 全部仍在 [MIN, MAX] 安全区间
        assert all(pbft.MIN_WEIGHT <= v <= pbft.MAX_WEIGHT for v in w.values())

    def test_epoch_recovery(self, pbft):
        """恢复路径：被误降节点恢复参与后相对权重回升

        恢复语义：满参与节点因子 1.0 > 省略节点因子 0.25，归一化后
        恢复者的权重份额回升（而非绝对值回弹）。
        """
        for i in range(50):
            pbft.reset()
            pbft.simulated_consensus(f'a{i}', 'node_0', byzantine_nodes={'node_1'})
            pbft.end_of_round_epoch_update()
        w_after_decay = pbft.get_weights()['node_1']
        # 恢复阶段：node_1 满参与，换 node_2 持续省略 → node_1 因子(1.0) > node_2 因子(0.25)
        for i in range(100):
            pbft.reset()
            pbft.simulated_consensus(f'b{i}', 'node_0', byzantine_nodes={'node_2'})
            pbft.end_of_round_epoch_update()
        w_after_recover = pbft.get_weights()['node_1']
        assert w_after_recover > w_after_decay

    def test_epoch_history_recorded(self, pbft):
        """纪元演化历史被记录（R 值可追溯）"""
        for i in range(50):
            pbft.simulated_consensus(f'h{i}', 'node_0')
            pbft.end_of_round_epoch_update()
        assert len(pbft._epoch_history) == 1
        assert 'R' in pbft._epoch_history[0] and 'epoch' in pbft._epoch_history[0]

    def test_uniform_participation_stable(self, pbft):
        """全员满参与时权重保持稳定（展宽不惩罚诚实节点）"""
        for i in range(50):
            pbft.simulated_consensus(f'h{i}', 'node_0')
            pbft.end_of_round_epoch_update()
        w = pbft.get_weights()
        # 全员同参与率 → 衰减系数相同 → 归一后回到初始均匀状态
        assert max(w.values()) - min(w.values()) < 0.05


class TestEpochBroadeningRespectsBan:
    """09-28 修复：纪元末展宽不得复活封禁节点（w=0）

    原 bug：raw = 0·factor = 0，经 max(MIN_WEIGHT,·) 抬到 0.1，再走 update_weight(>0)
    把封禁节点从 0.0 静默复活到 ~0.1/mean，惩罚合约的封禁在一个纪元后被自动撤销。
    """

    def test_banned_node_not_revived(self, pbft):
        """封禁节点权重在纪元末跨纪元保持 0"""
        for i in range(50):
            pbft.reset()
            pbft.simulated_consensus(f'h{i}', 'node_0')
            pbft.end_of_round_epoch_update()
        pbft.update_weight('node_1', 0.0)                      # 封禁
        assert pbft.get_weights()['node_1'] == 0.0

        for i in range(100):                                   # 再跑两个纪元
            pbft.reset()
            pbft.simulated_consensus(f'b{i}', 'node_0')
            pbft.end_of_round_epoch_update()

        assert pbft.get_weights()['node_1'] == 0.0, "封禁节点被纪元展宽复活"

    def test_banned_reported_in_summary(self, pbft):
        """纪元摘要需显式报告被排除的封禁节点（可观测性）"""
        pbft.update_weight('node_3', 0.0)
        summary = None
        for i in range(50):
            pbft.reset()
            pbft.simulated_consensus(f'h{i}', 'node_0')
            summary = pbft.end_of_round_epoch_update() or summary
        assert summary is not None
        assert 'node_3' in summary.get('excluded_banned', [])

    def test_no_ban_unchanged(self, pbft):
        """无封禁节点时行为不变（excluded_banned 为空）"""
        summary = None
        for i in range(50):
            pbft.reset()
            pbft.simulated_consensus(f'h{i}', 'node_0')
            summary = pbft.end_of_round_epoch_update() or summary
        assert summary is not None
        assert summary.get('excluded_banned') == []

