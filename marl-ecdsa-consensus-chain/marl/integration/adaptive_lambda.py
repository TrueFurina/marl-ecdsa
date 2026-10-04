"""
自适应λ控制器 — 实现区块链→MARL方向的真正双向反馈（P2-E 新增组件）

竞赛审查发现的最大短板：λ=0.1 是静态常数，BC→MARL 方向缺乏动态反馈，
"双向协同"实质是单向并联。本模块让 λ 随 BC 性能指标动态调节，证明真正的互驱闭环。

核心公式：
    λ_t = λ_base * (0.5 + sigmoid(β * (κ_c*consensus_rate + κ_k*coop_rate + κ_s*security_rate - θ)))

参数含义：
    - consensus_rate: CW-PBFT共识成功率（反映系统可信度）
    - coop_rate: 全局合作率（反映智能体协作水平）
    - security_rate: SecurityGuard通过率（反映行为合规性）
    - β: 响应灵敏度（控制反馈强度，默认2.0）
    - κ_c=0.4, κ_k=0.35, κ_s=0.25: Shapley风格权重系数
    - θ=0.5: 激励激活阈值

λ 范围：[0.5*λ_base, 1.5*λ_base]，即 [0.05, 0.15]（以 λ_base=0.1 为例）

与其他子组件的关系：
    - 读取 BlockchainMARLBridge.get_stats() 的输出作为指标源
    - 产出的 λ_t 反馈给 SettlementCoordinator，替换静态 lambda_weight
    - 适应历史记录供 Dashboard 可视化
"""
import logging
import numpy as np
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AdaptiveLambdaController:
    """
    自适应λ控制器 — 区块链性能指标反向调节 MARL 训练参数 λ

    实现 BC→MARL 方向的真正双向反馈：
    当区块链共识成功率、合作率、安全通过率均较高时，λ 提升，
    增强区块链激励对 MARL 奖励的权重；反之 λ 降低，防止不稳定链上信号干扰训练。

    λ 调整采用 EMA 平滑（系数 0.9），避免剧烈波动，并记录每次调整的驱动原因。
    """

    def __init__(
        self,
        lambda_base: float = 0.1,
        beta: float = 2.0,
        kappa_c: float = 0.4,
        kappa_k: float = 0.35,
        kappa_s: float = 0.25,
        threshold: float = 0.5,
        ema_alpha: float = 0.9,
    ):
        """
        初始化自适应λ控制器

        :param lambda_base: λ 基准值，自适应范围 [0.5*λ_base, 1.5*λ_base]
        :param beta: 响应灵敏度，控制 sigmoid 曲线陡度
        :param kappa_c: 共识成功率权重系数（Shapley风格）
        :param kappa_k: 合作率权重系数
        :param kappa_s: 安全通过率权重系数
        :param threshold: 激励激活阈值，综合指标高于此值才提升 λ
        :param ema_alpha: EMA 平滑系数（0.9 = 强平滑，变化缓慢）
        """
        self.lambda_base = lambda_base
        self.beta = beta
        self.kappa_c = kappa_c
        self.kappa_k = kappa_k
        self.kappa_s = kappa_s
        self.threshold = threshold
        self.ema_alpha = ema_alpha

        # 当前平滑后的 λ 值（初始为 λ_base）
        self._current_lambda: float = lambda_base

        # 历史记录：每回合的 λ 值 + 各指标值 + 驱动原因
        self._history: List[Dict] = []

        # 累计统计
        self._total_updates: int = 0
        self._lambda_min: float = lambda_base
        self._lambda_max: float = lambda_base

    def compute_adaptive_lambda(self, bridge_stats: Dict) -> float:
        """
        从 bridge.get_stats() 提取指标，计算自适应 λ

        :param bridge_stats: BlockchainMARLBridge.get_stats() 返回的完整统计字典，
            包含 consensus_stats / security_pass_count / security_fail_count 等字段
        :return: 本回合的自适应 λ 值（经 EMA 平滑后）
        """
        # ── 1. 提取三大指标 ──

        # consensus_rate: CW-PBFT 共识成功率
        consensus_rate = self._extract_consensus_rate(bridge_stats)

        # coop_rate: 全局合作率（从 CooperationDetector 统计推导）
        coop_rate = self._extract_coop_rate(bridge_stats)

        # security_rate: SecurityGuard 安全通过率
        security_rate = self._extract_security_rate(bridge_stats)

        # ── 2. 计算综合指标 ──
        composite = (
            self.kappa_c * consensus_rate
            + self.kappa_k * coop_rate
            + self.kappa_s * security_rate
        )

        # ── 3. sigmoid 调节 ──
        # λ_t = λ_base * (0.5 + sigmoid(β * (composite - θ)))
        sigmoid_input = self.beta * (composite - self.threshold)
        sigmoid_val = self._sigmoid(sigmoid_input)
        raw_lambda = self.lambda_base * (0.5 + sigmoid_val)

        # ── 4. EMA 平滑 ──
        smoothed_lambda = (
            self.ema_alpha * self._current_lambda
            + (1.0 - self.ema_alpha) * raw_lambda
        )

        # ── 5. 范围裁剪 ──
        lambda_min = 0.5 * self.lambda_base
        lambda_max = 1.5 * self.lambda_base
        smoothed_lambda = max(lambda_min, min(lambda_max, smoothed_lambda))

        # ── 6. 记录驱动原因 ──
        reason = self._determine_reason(consensus_rate, coop_rate, security_rate, composite)

        # ── 7. 更新内部状态 ──
        self._current_lambda = smoothed_lambda
        self._total_updates += 1
        self._lambda_min = min(self._lambda_min, smoothed_lambda)
        self._lambda_max = max(self._lambda_max, smoothed_lambda)

        # ── 8. 追加历史记录 ──
        record = {
            'episode': self._total_updates,
            'lambda': smoothed_lambda,
            'lambda_raw': raw_lambda,
            'consensus_rate': consensus_rate,
            'coop_rate': coop_rate,
            'security_rate': security_rate,
            'composite': composite,
            'reason': reason,
        }
        self._history.append(record)

        logger.debug(
            f"[AdaptiveLambda] 回合#{self._total_updates}: "
            f"λ={smoothed_lambda:.4f} (raw={raw_lambda:.4f}) "
            f"| consensus={consensus_rate:.3f} coop={coop_rate:.3f} "
            f"security={security_rate:.3f} composite={composite:.3f} "
            f"| reason={reason}"
        )

        return smoothed_lambda

    def get_adaptation_history(self) -> List[Dict]:
        """
        返回适应历史记录（每回合的 λ 值 + 各指标值），供 Dashboard 可视化

        :return: 列表，每项为 Dict，包含 episode / lambda / 各指标 / reason
        """
        return list(self._history)

    def get_stats(self) -> Dict:
        """
        返回控制器统计信息

        :return: Dict，包含当前 λ / 基准值 / 更新次数 / λ 极值 / 最近记录
        """
        latest_record = self._history[-1] if self._history else {}
        return {
            'current_lambda': self._current_lambda,
            'lambda_base': self.lambda_base,
            'total_updates': self._total_updates,
            'lambda_min': self._lambda_min,
            'lambda_max': self._lambda_max,
            'lambda_range': [0.5 * self.lambda_base, 1.5 * self.lambda_base],
            'beta': self.beta,
            'kappa_c': self.kappa_c,
            'kappa_k': self.kappa_k,
            'kappa_s': self.kappa_s,
            'threshold': self.threshold,
            'ema_alpha': self.ema_alpha,
            'latest_record': latest_record,
        }

    def reset(self) -> None:
        """
        重置控制器（新训练时调用）

        清空历史记录和累计统计，λ 回归基准值。
        """
        self._current_lambda = self.lambda_base
        self._history.clear()
        self._total_updates = 0
        self._lambda_min = self.lambda_base
        self._lambda_max = self.lambda_base
        logger.info("[AdaptiveLambda] 控制器已重置，λ回归基准值")

    # -------------------------------------------------------------------------
    # 内部辅助方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _sigmoid(x: float) -> float:
        """
        numpy sigmoid 函数（与项目依赖一致）

        :param x: 输入值
        :return: sigmoid(x)，范围 [0, 1]
        """
        return float(1.0 / (1.0 + np.exp(-x)))

    def _extract_consensus_rate(self, bridge_stats: Dict) -> float:
        """
        从 bridge_stats 提取 CW-PBFT 共识成功率

        :param bridge_stats: BlockchainMARLBridge.get_stats() 的返回值
        :return: 共识成功率，范围 [0, 1]。无数据时返回默认 0.5
        """
        consensus_stats = bridge_stats.get('consensus_stats')
        if consensus_stats is not None:
            # CW-PBFT 统计格式：{'success_rate': float, ...}
            success_rate = consensus_stats.get('success_rate')
            if success_rate is not None:
                try:
                    return float(success_rate)
                except (TypeError, ValueError):
                    pass

            # fallback: 从 success_count / total_rounds 推导
            success_count = consensus_stats.get('success_count', 0)
            total_rounds = consensus_stats.get('total_rounds', 0)
            if total_rounds > 0:
                try:
                    return float(success_count) / float(total_rounds)
                except (TypeError, ValueError):
                    pass

        # 无共识数据时：返回 0.5（中性默认，既不提升也不降低 λ）
        logger.debug("[AdaptiveLambda] 无共识统计数据，consensus_rate 默认 0.5")
        return 0.5

    def _extract_coop_rate(self, bridge_stats: Dict) -> float:
        """
        从 bridge_stats 推导全局合作率

        :param bridge_stats: BlockchainMARLBridge.get_stats() 的返回值
        :return: 全局合作率，范围 [0, 1]。无数据时返回默认 0.5
        """
        # CooperationDetector 的 get_stats() 不直接在 bridge_stats 中暴露，
        # 但可通过 bc_scores 中的正值比例推导近似合作率
        bc_scores = bridge_stats.get('bc_scores', {})
        if bc_scores:
            positive_count = sum(1 for v in bc_scores.values() if v > 0)
            total_agents = len(bc_scores)
            if total_agents > 0:
                return float(positive_count) / float(total_agents)

        # fallback: 从 bc_rewards 正值比例推导（本回合）
        bc_rewards = bridge_stats.get('bc_rewards', {})
        if bc_rewards:
            positive_count = sum(1 for v in bc_rewards.values() if v > 0)
            total_agents = len(bc_rewards)
            if total_agents > 0:
                return float(positive_count) / float(total_agents)

        logger.debug("[AdaptiveLambda] 无合作统计数据，coop_rate 默认 0.5")
        return 0.5

    def _extract_security_rate(self, bridge_stats: Dict) -> float:
        """
        从 bridge_stats 提取 SecurityGuard 安全通过率

        :param bridge_stats: BlockchainMARLBridge.get_stats() 的返回值
        :return: 安全通过率，范围 [0, 1]。无数据时返回默认 0.5
        """
        pass_count = bridge_stats.get('security_pass_count', 0)
        fail_count = bridge_stats.get('security_fail_count', 0)
        total = pass_count + fail_count

        if total > 0:
            try:
                return float(pass_count) / float(total)
            except (TypeError, ValueError):
                pass

        # fallback: 从 security_stats 推导
        security_stats = bridge_stats.get('security_stats')
        if security_stats is not None:
            sp = security_stats.get('pass_count', 0)
            sf = security_stats.get('fail_count', 0)
            st = sp + sf
            if st > 0:
                try:
                    return float(sp) / float(st)
                except (TypeError, ValueError):
                    pass

        logger.debug("[AdaptiveLambda] 无安全统计数据，security_rate 默认 0.5")
        return 0.5

    def _determine_reason(
        self,
        consensus_rate: float,
        coop_rate: float,
        security_rate: float,
        composite: float,
    ) -> str:
        """
        判断 λ 变化的驱动原因（哪个指标主导了变化）

        :param consensus_rate: 共识成功率
        :param coop_rate: 合作率
        :param security_rate: 安全通过率
        :param composite: 综合指标值
        :return: 驱动原因描述字符串
        """
        if composite > self.threshold + 0.1:
            # λ 提升阶段：找出贡献最大的指标
            contributions = {
                'consensus': self.kappa_c * consensus_rate,
                'cooperation': self.kappa_k * coop_rate,
                'security': self.kappa_s * security_rate,
            }
            dominant = max(contributions, key=contributions.get)
            return f"λ↑ driven by {dominant} (composite={composite:.3f})"
        elif composite < self.threshold - 0.1:
            # λ 降低阶段：找出表现最差的指标
            rates = {
                'consensus': consensus_rate,
                'cooperation': coop_rate,
                'security': security_rate,
            }
            weakest = min(rates, key=rates.get)
            return f"λ↓ driven by weak {weakest} (composite={composite:.3f})"
        else:
            # 中性区间：λ 维持稳定
            return f"λ≈stable (composite={composite:.3f}≈θ={self.threshold})"
