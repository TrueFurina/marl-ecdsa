"""
Shapley 贡献维度权重（κ）单一真源

κ 三元组（任务 / 协作 / 合规）此前在 3 处各自内联：config.json、
incentive_contract.ContributionScore.weighted_score、cw_pbft.get_consensus_stats()。
2026-11-05 审计实测发现：P1-4 的"单一真源"只覆盖了**统计回显**一条路径 ——
cw_pbft 读 config，而真正参与算分的 ContributionScore.weighted_score 仍是
三个字面常量。把 config.json 改成 0.6/0.3/0.1 后：

    weighted_score(实际)   = 0.65   （0.40·1 + 0.35·0 + 0.25·1）
    weighted_score(声明)   = 0.70   （0.60·1 + 0.30·0 + 0.10·1）
    divergence             = -0.05

即对外报告的口径与链上结算实际使用的口径可以不一致，且没有任何告警。
本模块把读取与校验收敛到一处，两个消费方都调用 ``get_contribution_weights()``。

校验分三层，任一层不通过即整体回退默认值（fail-safe：宁可用已知正确的常量，
也不用一份不自洽的配置 —— 部分回退会让各维度权重之和 ≠ 1，直接破坏
weighted_score ∈ [0,1] 的不变式）：

1. 可解析：config.json 存在、是合法 JSON、blockchain.contribution_weights 是 dict
2. 可量化且有限：每个 κ 能转 float 且非 NaN / ±inf
3. 值域与归一：每个 κ ∈ [0, 1]，且 κ_task + κ_coop + κ_compliance == 1 (±1e-6)

第 3 层的值域检查是本次新增：旧实现在 cw_pbft 里只校验「和为 1」，因此
{1.5, -0.5, 0.0} 这类**和为 1 但有负权重**的配置会被原样接受，让高任务分
智能体的 weighted_score 冲到 1.5（超出 [0,1] 不变式）、高协作分智能体被压到
-0.5，结算时被 clamp 成两个极端档位。
"""
import json
import logging
import math
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: κ 默认值 —— 与设计报告/答辩材料的 0.40 / 0.35 / 0.25 逐值一致
KAPPA_DEFAULTS: Dict[str, float] = {
    'task_score': 0.40,
    'cooperation_score': 0.35,
    'compliance_score': 0.25,
}

#: 三个维度的固定读取顺序（决定返回三元组的分量次序）
KAPPA_KEYS: Tuple[str, str, str] = (
    'task_score',
    'cooperation_score',
    'compliance_score',
)

#: 归一约束的容差：|Σκ - 1| 超过此值即判定配置不自洽
NORMALIZATION_TOL: float = 1e-6

#: 默认配置文件位置（项目根目录 config.json）
DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parent.parent / "config.json"


def default_weights() -> Tuple[float, float, float]:
    """返回默认 κ 三元组 (κ_task, κ_coop, κ_compliance) 的副本。"""
    return (
        KAPPA_DEFAULTS['task_score'],
        KAPPA_DEFAULTS['cooperation_score'],
        KAPPA_DEFAULTS['compliance_score'],
    )


def _coerce_unit_interval(raw) -> Optional[float]:
    """把配置项转为 [0,1] 内的有限 float；任何不合格输入返回 None。

    不用 `0.0 <= float(raw) <= 1.0` 一把写：NaN 参与比较恒为 False，
    会让「值为 NaN」与「值越界」混成同一条分支，丢失可诊断性。
    这里的顺序是 先转 float → 再判有限 → 最后判值域。
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if not (0.0 <= value <= 1.0):
        return None
    return value


def load_contribution_weights(
    config_path: Optional[Path] = None,
) -> Tuple[float, float, float]:
    """从 config.json 读取并校验 κ 三元组，任何不合格都整体回退默认值。

    :param config_path: 配置文件路径；None 表示使用 DEFAULT_CONFIG_PATH
    :return: (κ_task, κ_coop, κ_compliance)
    """
    defaults = default_weights()
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.debug(f"[κ] 配置文件不存在: {path}，使用默认值 {defaults}")
        return defaults

    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        logger.warning(f"[κ] 读取 {path} 失败: {e}，回退默认值 {defaults}")
        return defaults

    try:
        section = cfg.get('blockchain', {}).get('contribution_weights', {})
    except AttributeError:
        logger.warning(f"[κ] {path} 结构异常（非 dict），回退默认值 {defaults}")
        return defaults

    if not isinstance(section, dict):
        logger.warning(
            f"[κ] contribution_weights 应为 dict，实际 {type(section).__name__}，"
            f"回退默认值 {defaults}"
        )
        return defaults

    # 缺项沿用默认值（与旧实现一致），最终仍要过归一校验
    resolved = []
    for key in KAPPA_KEYS:
        if key in section:
            value = _coerce_unit_interval(section[key])
            if value is None:
                logger.warning(
                    f"[κ] {key}={section[key]!r} 非法（需 [0,1] 内有限数），"
                    f"回退默认值 {defaults}"
                )
                return defaults
        else:
            value = KAPPA_DEFAULTS[key]
        resolved.append(value)

    total = sum(resolved)
    if abs(total - 1.0) > NORMALIZATION_TOL:
        logger.warning(
            f"[κ] Σκ={total:.6f} ≠ 1（容差 {NORMALIZATION_TOL}），"
            f"回退默认值 {defaults}"
        )
        return defaults

    return (resolved[0], resolved[1], resolved[2])


# 进程内缓存：config.json 在运行期不变，避免每次 weighted_score 都读盘。
# 副作用是测试里改配置后需调用 reset_contribution_weights_cache() 让新值生效。
_cached: Optional[Tuple[float, float, float]] = None


def get_contribution_weights() -> Tuple[float, float, float]:
    """返回进程内缓存的 κ 三元组（首次调用时读 config.json 并校验）。"""
    global _cached
    if _cached is None:
        _cached = load_contribution_weights()
    return _cached


def reset_contribution_weights_cache() -> None:
    """清空 κ 缓存，使下一次 get_contribution_weights() 重新读配置。"""
    global _cached
    _cached = None


__all__ = [
    'KAPPA_DEFAULTS',
    'KAPPA_KEYS',
    'NORMALIZATION_TOL',
    'DEFAULT_CONFIG_PATH',
    'default_weights',
    'load_contribution_weights',
    'get_contribution_weights',
    'reset_contribution_weights_cache',
]
