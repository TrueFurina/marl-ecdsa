"""
合作检测服务 — 从 BlockchainMARLBridge 拆分出的子组件（P2-D）
职责：合作/背叛检测 + 回合内累积统计 + per-step 结果缓存
"""
import logging
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class CooperationDetector:
    """
    合作与背叛检测服务

    封装完整检测流水线：
    1. detect_cooperation() — 每步检测各智能体是否合作（simple_spread 场景）
    2. get_episode_cooperation() — 回合结束时判定最终合作/背叛
    3. get_cooperation_status() — 最近一步的检测结果（per-step）
    4. reset_episode() — 重置回合内累积状态

    观测格式：[vel_x, vel_y, pos_x, pos_y, lm1_dx, lm1_dy, lm2_dx, lm2_dy, ...]

    增量创新 #4（启发自 EquiChain ExtraTrees）：可选 ML 分类器路径。
    - 默认规则基模式不变（完全向后兼容）
    - 可训练 sklearn 分类器（train_classifier），并用 predict_ml 做补充判定
    """

    def __init__(self, n_agents: int = 3, n_landmarks: int = 3, verify_gate=None):
        self.n_agents = n_agents
        self.n_landmarks = n_landmarks
        # 增量创新 #4: 可选 ML 分类器（默认 None = 纯规则基）
        self._ml_clf = None
        self._ml_available = False

        # ── 任务书结合点②：合谋检测双通道（2026-10-04）──
        # verify_gate: Optional[Callable[[Dict], bool]]
        #   输入一条 sign_action() 格式的签名包，返回 True=验签通过（进入统计通道）。
        #   None = 单通道（不验签，旧行为，完全向后兼容）。
        #   双通道语义：统计检测的输入必须先通过 ECDSA 验签门——
        #   "可信输入下的统计检测"（伪造/顶名包在进统计前被拒收）。
        self.verify_gate = verify_gate
        self.verify_stats: Dict[str, int] = {'received': 0, 'verified': 0, 'rejected': 0}

        # 回合内合作状态累积 {agent_id: {'coop': count, 'betray': count, 'total': count}}
        self._episode_coop: Dict[str, Dict[str, int]] = {}

        # 【2026-09-22 新增】回合内"被标记背叛"步数（独立于合作判定，供 behavioral_only 口径使用）
        self._episode_betray: Dict[str, int] = {}

        # 最近一步的合作检测结果（per-step）
        self._last_step_coop: Dict[str, Optional[bool]] = {}

    def detect_cooperation(
        self,
        observations: List[Any],
        agent_ids: List[str],
        cooperation_threshold: float = 0.5,
        selfish_flags: Optional[List[bool]] = None,
        behavioral_only: bool = False,
    ) -> Dict[str, Optional[bool]]:
        """
        检测各智能体本步是否合作（v3 修正版）

        核心修正：
        1. 阈值 0.5（在 world_size=1.0 的环境中合理）
        2. 移除"靠近其他目标点=背叛"的误判
        3. 合作判定：dist < threshold → True / 中性 → None
        4. selfish_flags：P2修复后表示"本步是否实际背叛"而非"是否是自私智能体"

        ⚠️ 两种口径（2026-09-22 明确区分）：
        - legacy（behavioral_only=False，默认）：selfish_flags=True → 直接判 False 且**不评估行为**。
          此时 avg_cooperation_rate 退化为"未被标记背叛的步数占比 × 距离达标率"，
          **不是独立的行为度量**——用它比较不同背叛模式的"协作破坏力"属循环论证。
        - behavioral_only=True：**忽略标记**，一律按距离评估所有智能体的行为。
          背叛信息改由 `_episode_betray` 单独统计（见 get_episode_betrayal），与行为解耦。
          论文中作为**协作效果指标**的合作率必须走这一路。

        :param observations: 各智能体观测值列表
        :param agent_ids: 智能体 ID 列表
        :param cooperation_threshold: 合作距离阈值
        :param selfish_flags: 本步背叛标记列表（True=本步背叛，而非is_selfish标记）
        :param behavioral_only: True=纯行为学口径（合作率与背叛标记解耦）
        :return: {agent_id: True(合作) / False(背叛) / None(中性)}
        """
        import numpy as np
        step_status: Dict[str, Optional[bool]] = {}
        sf = selfish_flags if selfish_flags else [False] * len(agent_ids)

        flagged_ids = set()
        for i, (obs, agent_id) in enumerate(zip(observations, agent_ids)):
            flagged = bool(i < len(sf) and sf[i])
            if flagged:
                # 无论走哪种口径，"被标记背叛"都独立记账
                flagged_ids.add(agent_id)
                self._episode_betray[agent_id] = self._episode_betray.get(agent_id, 0) + 1

            if flagged and not behavioral_only:
                # legacy：本步实际背叛 → 判 False，不评估行为（完全保持旧语义）
                step_status[agent_id] = False
                continue

            try:
                obs_arr = np.array(obs, dtype=float)
                n_lm = self.n_landmarks
                lm_rel = obs_arr[4:4 + 2 * n_lm].reshape(-1, 2)
                own_idx = i % n_lm
                dist_to_own = float(np.linalg.norm(lm_rel[own_idx]))
                min_dist_any = min(
                    float(np.linalg.norm(lm_rel[j])) for j in range(n_lm)
                )

                if dist_to_own < cooperation_threshold:
                    step_status[agent_id] = True
                elif min_dist_any < cooperation_threshold:
                    step_status[agent_id] = True
                else:
                    step_status[agent_id] = None
            except Exception as e:
                logger.warning(f"[CooperationDetector] 合作检测异常 {agent_id}: {e}")
                step_status[agent_id] = None

        # 累积到回合统计（用于结算判定）
        for agent_id, status in step_status.items():
            if agent_id not in self._episode_coop:
                self._episode_coop[agent_id] = {'coop': 0, 'betray': 0, 'total': 0}
            self._episode_coop[agent_id]['total'] += 1
            if status is True:
                self._episode_coop[agent_id]['coop'] += 1
            elif status is False:
                self._episode_coop[agent_id]['betray'] += 1
            if behavioral_only and agent_id in flagged_ids:
                # 行为学口径下"背叛"不再由 status 承载，但结算仍需它 → 显式记账
                self._episode_coop[agent_id]['betray'] += 1

        # 存储 per-step 结果（用于实时合作率统计）
        self._last_step_coop = dict(step_status)

        return step_status

    def get_episode_cooperation(self, agent_id: str) -> Tuple[bool, bool]:
        """
        根据回合内累积状态判断最终合作/背叛（v2 修正版）

        :param agent_id: 智能体 ID
        :return: (did_cooperate, did_betray)

        修正逻辑：
        - 合作步数 > 30% → 合作（宽松阈值）
        - 背叛步数 > 50% → 背叛（严格阈值，仅 selfish 模式产生 False）
        - bc_marl 模式下不会产生真正背叛，中性不判背叛
        """
        stats = self._episode_coop.get(
            agent_id, {'coop': 0, 'betray': 0, 'total': 0}
        )
        total = max(1, stats['total'])
        coop_rate = stats['coop'] / total
        betray_rate = stats['betray'] / total

        did_cooperate = coop_rate > 0.3
        did_betray = betray_rate > 0.5
        return did_cooperate, did_betray

    def get_episode_betrayal(self, agent_id: str) -> int:
        """回合内该智能体"被标记背叛"的步数（与行为学合作率解耦，2026-09-22 新增）"""
        return int(self._episode_betray.get(agent_id, 0))

    def get_episode_betrayal_all(self) -> Dict[str, int]:
        return dict(self._episode_betray)

    def get_cooperation_status(self) -> Dict[str, Optional[bool]]:
        """获取最近一步的合作状态（per-step，用于实时统计）"""
        return dict(self._last_step_coop)

    def reset_episode(self) -> None:
        """重置回合内累积状态"""
        self._episode_coop = {}
        self._episode_betray = {}

    def get_stats(self) -> Dict:
        """获取合作检测统计"""
        return {
            'episode_coop_agents': len(self._episode_coop),
            'last_step_coop': dict(self._last_step_coop),
            'ml_classifier': self._ml_clf.__class__.__name__ if self._ml_clf else None,
        }

    # ----------------------------------------------------------------------
    # 增量创新 #4: 可选 ML 分类器路径（启发自 EquiChain ExtraTrees）
    # 默认纯规则基；调用 train_classifier 后启用 ML 补充判定
    # ----------------------------------------------------------------------

    def _extract_features(self, observations: List[Any], agent_ids: List[str]) -> Tuple[List[list], List[str]]:
        """
        从观测中提取分类特征（与规则基一致的分区）
        每智能体特征：到自身目标点距离、最近目标点距离、位置坐标
        :return: (feature_rows, agent_ids)
        """
        import numpy as np
        rows = []
        for i, obs in enumerate(observations):
            try:
                obs_arr = np.array(obs, dtype=float)
                n_lm = self.n_landmarks
                lm_rel = obs_arr[4:4 + 2 * n_lm].reshape(-1, 2)
                own_idx = i % n_lm
                dist_to_own = float(np.linalg.norm(lm_rel[own_idx]))
                min_dist_any = min(
                    float(np.linalg.norm(lm_rel[j])) for j in range(n_lm)
                )
                rows.append([dist_to_own, min_dist_any, float(obs_arr[2]), float(obs_arr[3])])
            except Exception as e:
                logger.warning(f"[CooperationDetector] 特征提取异常 {agent_ids[i] if i < len(agent_ids) else i}: {e}")
                rows.append([0.0, 0.0, 0.0, 0.0])
        return rows, agent_ids

    def train_classifier(
        self,
        observations: List[Any],
        agent_ids: List[str],
        labels: List[int],
        max_features: str = 'sqrt',
    ) -> bool:
        """
        训练 ExtraTrees 分类器（启发自 EquiChain 98.37% 方案）

        :param observations: 观测样本列表（与规则基相同格式）
        :param agent_ids: 智能体 ID 列表（与观测对齐）
        :param labels: 标签列表（1=合作, 0=背叛/中性）
        :param max_features: sklearn 参数
        :return: 是否训练成功
        """
        try:
            from sklearn.ensemble import ExtraTreesClassifier
        except ImportError:
            logger.warning("[CooperationDetector] sklearn 未安装，ML 路径不可用（保持规则基）")
            return False

        features, _ = self._extract_features(observations, agent_ids)
        if len(features) < 2 or len(set(labels)) < 2:
            logger.warning("[CooperationDetector] 样本不足或标签单一，跳过 ML 训练")
            return False

        self._ml_clf = ExtraTreesClassifier(
            n_estimators=50, max_depth=5, max_features=max_features, random_state=42
        )
        self._ml_clf.fit(features, labels)
        self._ml_available = True
        logger.info(
            f"[CooperationDetector] ML 分类器训练完成: "
            f"{self._ml_clf.__class__.__name__} 样本={len(features)}"
        )
        return True

    def predict_ml(self, observations: List[Any], agent_ids: List[str]) -> Dict[str, Optional[bool]]:
        """
        用 ML 分类器判定合作状态（补充规则基）
        :return: {agent_id: True(合作) / False(背叛) / None(无法判定)}
        """
        if not self._ml_available or self._ml_clf is None:
            return {}
        features, ids = self._extract_features(observations, agent_ids)
        try:
            preds = self._ml_clf.predict(features)
            return {aid: bool(p) for aid, p in zip(ids, preds)}
        except Exception as e:
            logger.warning(f"[CooperationDetector] ML 预测异常: {e}")
            return {}

    def get_ml_accuracy(self, observations: List[Any], agent_ids: List[str], labels: List[int]) -> Optional[float]:
        """评估 ML 分类器准确率（用于与规则基对比报告）"""
        if not self._ml_available or self._ml_clf is None:
            return None
        preds = self.predict_ml(observations, agent_ids)
        if not preds or not labels:
            return None
        correct = sum(
            1 for aid, lbl in zip(agent_ids, labels)
            if aid in preds and int(preds[aid]) == int(lbl)
        )
        return round(correct / max(1, len(labels)), 4)

    # ----------------------------------------------------------------------
    # 任务书结合点②：合谋检测双通道 —— 验签门（2026-10-04）
    # 单通道 = verify_gate 为 None（不验签，旧行为）；双通道 = 注入验签门后，
    # 统计检测的输入仅收 ECDSA 验签通过的行为记录包（复用 ecdsa_utils，真签名）。
    # ----------------------------------------------------------------------

    def set_verify_gate(self, gate) -> None:
        """注入/切换验签门（Callable[[Dict], bool]）；传 None 退回单通道。"""
        self.verify_gate = gate

    def filter_verified_packages(self, packages: List[Dict], public_keys: Dict[str, Any]):
        """验签门：过滤未通过 ECDSA 验签的行为记录包。

        :param packages: [sign_action() 格式的签名包]（含伪造/顶名包）
        :param public_keys: {agent_id: 公钥}（链上注册公钥——伪造包即使签名"有效"，
                            也无法匹配被顶名 agent 的注册公钥）
        :return: (verified_packages, rejected_packages)
        """
        from blockchain.crypto.ecdsa_utils import ECDSAUtils  # 惰性导入，保持模块依赖图不变

        verified, rejected = [], []
        for pkg in packages:
            self.verify_stats['received'] += 1
            aid = pkg.get('agent_id')
            pub = (public_keys or {}).get(aid)
            ok = False
            if pub is not None:
                try:
                    ok = bool(ECDSAUtils.verify_action_package(pkg, pub))
                except Exception as e:
                    logger.warning(f"[CooperationDetector] 验签门异常 {aid}: {e}")
            if ok and (self.verify_gate is None or self.verify_gate(pkg)):
                self.verify_stats['verified'] += 1
                verified.append(pkg)
            else:
                self.verify_stats['rejected'] += 1
                rejected.append(pkg)
        return verified, rejected

    def get_verify_stats(self) -> Dict[str, int]:
        """验签门统计（received/verified/rejected）"""
        return dict(self.verify_stats)
