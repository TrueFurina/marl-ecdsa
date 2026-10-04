# -*- coding: utf-8 -*-
"""项目级配置加载的单一真值源（2026-10-01 工程锐评整改）。

此前 ``_PENALTY_THRESHOLDS`` 默认值与 config.json 加载逻辑在
``contracts/penalty_contract.py`` 与 ``ledger/world_state.py`` 中**各重复一份**，
``_CONFIG_PATH`` 在三处独立定义 —— 改一处忘另一处即静默漂移且测试照绿。
现统一收敛到本模块：常量一处定义、加载逻辑一处实现，消费方只导入。
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# config.json 路径（项目根目录），唯一权威定义
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

# 惩罚阈值默认值（config.json 缺失/加载失败时回退），唯一权威定义
DEFAULT_PENALTY_THRESHOLDS: Dict[str, int] = {"warning": 10, "demotion": 30, "ban": 50}


def load_penalty_thresholds(caller_logger: Optional[logging.Logger] = None) -> Dict[str, int]:
    """从 config.json 加载惩罚阈值。

    优先 ``blockchain.penalty_thresholds``（简化格式），
    兼容旧 ``blockchain.penalty_levels``（分级格式）；
    任何失败回退 :data:`DEFAULT_PENALTY_THRESHOLDS`（返回副本，防调用方原地改坏共享常量）。

    :param caller_logger: 调用方 logger，用于保留原模块的日志归因标签。
    """
    log = caller_logger or logger
    thresholds = dict(DEFAULT_PENALTY_THRESHOLDS)
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        blockchain_cfg = cfg.get("blockchain", {})
        if "penalty_thresholds" in blockchain_cfg:
            thresholds = blockchain_cfg["penalty_thresholds"]
        elif "penalty_levels" in blockchain_cfg:
            levels = blockchain_cfg["penalty_levels"]
            thresholds = {
                "warning": levels.get("warning", {}).get("threshold", DEFAULT_PENALTY_THRESHOLDS["warning"]),
                "demotion": levels.get("demoted", {}).get("threshold", DEFAULT_PENALTY_THRESHOLDS["demotion"]),
                "ban": levels.get("banned", {}).get("threshold", DEFAULT_PENALTY_THRESHOLDS["ban"]),
            }
    except Exception as e:  # noqa: BLE001 —— 配置缺失/损坏时按设计回退默认值
        log.warning(f"加载 config.json 失败: {e}, 使用默认阈值 {DEFAULT_PENALTY_THRESHOLDS}")
    return thresholds
