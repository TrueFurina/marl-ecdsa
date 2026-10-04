"""
共识引擎工厂
根据 config.json 的 consensus_mode 字段创建对应的共识引擎实例

支持三种模式：
- cw_pbft       : CW-PBFT 贡献加权拜占庭容错（默认，核心创新）
- standard_pbft : 标准等权 PBFT（对照组，用于对比实验证明 CW-PBFT 优势）
- fast          : 快速共识（单轮确认，跳过权重阈值检查，性能演示模式）

用法：
    from blockchain.consensus.factory import create_consensus_engine
    engine = create_consensus_engine(node_id, all_node_ids)  # 自动读 config.json
    engine = create_consensus_engine(node_id, all_node_ids, mode='standard_pbft')
"""
import json
import logging
from pathlib import Path
from typing import List, Optional

from ..config_loader import CONFIG_PATH

logger = logging.getLogger(__name__)

# 默认模式（config.json 缺失或字段不存在时使用）
DEFAULT_MODE = 'cw_pbft'

# 合法模式集合
VALID_MODES = {'cw_pbft', 'standard_pbft', 'fast'}

# config.json 路径统一引用 blockchain.config_loader 单一真值源（2026-10-01 整改）
_CONFIG_PATH = CONFIG_PATH


def load_consensus_mode() -> str:
    """从 config.json 读取 consensus_mode，失败时回退默认值"""
    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            mode = cfg.get('blockchain', {}).get('consensus_mode', DEFAULT_MODE)
            if mode in VALID_MODES:
                return mode
            logger.warning(f"[ConsensusFactory] 未知 consensus_mode={mode}，回退 {DEFAULT_MODE}")
    except Exception as e:
        logger.warning(f"[ConsensusFactory] 读取 config.json 失败: {e}，使用默认模式")
    return DEFAULT_MODE


def create_consensus_engine(
    node_id: str,
    consensus_nodes: List[str],
    mode: Optional[str] = None,
) -> object:
    """
    创建共识引擎实例

    :param node_id: 当前节点ID
    :param consensus_nodes: 全部共识节点ID列表
    :param mode: 共识模式（cw_pbft / standard_pbft / fast），None 时从 config.json 读取
    :return: 共识引擎实例（CWPBFTConsensus / StandardPBFTConsensus）
    """
    mode = (mode or load_consensus_mode()).lower()
    if mode not in VALID_MODES:
        logger.warning(f"[ConsensusFactory] 非法模式 {mode}，回退 {DEFAULT_MODE}")
        mode = DEFAULT_MODE

    if mode == 'standard_pbft':
        from .standard_pbft import StandardPBFTConsensus
        logger.info(f"[ConsensusFactory] {node_id} 创建标准PBFT引擎（等权基线）")
        return StandardPBFTConsensus(node_id, consensus_nodes)

    # cw_pbft 与 fast 均基于 CWPBFTConsensus（fast 通过 NetworkConsensusNode 短路 fast_consensus）
    from .cw_pbft import CWPBFTConsensus
    engine = CWPBFTConsensus(node_id, consensus_nodes)
    if mode == 'fast':
        logger.info(f"[ConsensusFactory] {node_id} 创建快速共识引擎（单轮确认）")
    else:
        logger.info(f"[ConsensusFactory] {node_id} 创建CW-PBFT引擎（贡献加权）")
    return engine
