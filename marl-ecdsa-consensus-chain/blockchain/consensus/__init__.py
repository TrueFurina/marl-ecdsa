"""
CW-PBFT 共识引擎
贡献加权PBFT（Contribution-Weighted PBFT）
在经典PBFT基础上引入智能体贡献度作为投票权重
支持拜占庭容错（容错 ⌊(n-1)/3⌋ 个恶意节点）
"""
from .cw_pbft import CWPBFTConsensus, ConsensusState

__all__ = ['CWPBFTConsensus', 'ConsensusState']
