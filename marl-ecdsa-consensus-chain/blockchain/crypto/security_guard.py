"""
安全防护模块
实现ECDSA安全威胁检测：
1. k值重用检测（相同r值 → 相同k → 私钥可推导）
2. 重放攻击防护（nonce单调递增 + 时间戳有效期）
3. 签名异常行为监控
"""
import time
import logging
from collections import defaultdict, OrderedDict
from typing import Dict, Set, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SecurityGuard:
    """
    ECDSA安全防护守卫
    部署于共识节点，对所有接收到的签名包进行安全校验
    """

    # 时间戳有效窗口：±30秒
    TIMESTAMP_TOLERANCE_MS = 30_000
    # 单智能体最大失败签名次数（超过则触发告警）
    MAX_FAIL_COUNT = 5
    # P1-11修复：r_registry最大条目数，超过时FIFO淘汰最旧的
    MAX_R_ENTRIES = 1000

    def __init__(self):
        # {agent_id: OrderedDict(r_value → True)} 用于k值重用检测 + FIFO淘汰
        # P1-11修复：改用OrderedDict记录插入顺序，支持FIFO trim
        self._r_registry: Dict[str, OrderedDict] = defaultdict(OrderedDict)
        # {agent_id: last_nonce} 用于重放攻击防护
        self._nonce_registry: Dict[str, int] = {}
        # {agent_id: fail_count}
        self._fail_counts: Dict[str, int] = defaultdict(int)
        # 告警事件列表
        self._alerts: List[Dict] = []

    # -------------------------------------------------------------------------
    # 核心校验入口
    # -------------------------------------------------------------------------

    def check_package(self, package: Dict) -> Tuple[bool, str]:
        """
        对签名包进行完整安全校验
        :return: (is_safe, reason)
        """
        agent_id = package.get('agent_id', 'unknown')

        # 1. 时间戳有效性校验
        ok, reason = self._check_timestamp(package)
        if not ok:
            self._record_fail(agent_id, 'TIMESTAMP_EXPIRED', reason)
            return False, reason

        # 2. Nonce连续性校验（防重放）
        ok, reason = self._check_nonce(package)
        if not ok:
            self._record_fail(agent_id, 'NONCE_REPLAY', reason)
            return False, reason

        # 3. k值重用检测
        ok, reason = self._check_r_reuse(package)
        if not ok:
            self._record_fail(agent_id, 'K_REUSE_ATTACK', reason)
            return False, reason

        return True, 'OK'

    # -------------------------------------------------------------------------
    # 内部校验方法
    # -------------------------------------------------------------------------

    def _check_timestamp(self, package: Dict) -> Tuple[bool, str]:
        """时间戳有效期校验：±30秒窗口"""
        ts = package.get('timestamp')
        if ts is None:
            return False, "缺少时间戳字段"
        now_ms = int(time.time() * 1000)
        delta = abs(now_ms - ts)
        if delta > self.TIMESTAMP_TOLERANCE_MS:
            return False, f"时间戳过期或超前 {delta}ms，超出允许范围 {self.TIMESTAMP_TOLERANCE_MS}ms"
        return True, 'OK'

    def _check_nonce(self, package: Dict) -> Tuple[bool, str]:
        """
        Nonce单调递增校验
        每个智能体的nonce必须严格递增，防止重放攻击
        """
        agent_id = package.get('agent_id')
        nonce = package.get('nonce')
        if nonce is None:
            return False, "缺少nonce字段"

        last_nonce = self._nonce_registry.get(agent_id)
        if last_nonce is not None and nonce <= last_nonce:
            return False, f"nonce重放攻击检测: 收到 nonce={nonce}，上次 nonce={last_nonce}"

        # 通过则更新nonce记录
        self._nonce_registry[agent_id] = nonce
        return True, 'OK'

    def _check_r_reuse(self, package: Dict) -> Tuple[bool, str]:
        """
        k值重用检测（基于r值）
        ECDSA中：同一私钥使用相同k值签名两次 → r值相同 → 私钥可被推导
        """
        agent_id = package.get('agent_id')
        r = package.get('r')
        if r is None:
            return True, 'OK'  # 没有r值信息时跳过检测

        known_rs = self._r_registry[agent_id]
        if r in known_rs:
            return False, (
                f"k值重用攻击检测！agent={agent_id} 的签名r值 {hex(r)[:16]}... 已出现过，"
                f"意味着使用了相同的随机数k，私钥存在泄露风险！"
            )

        # 记录r值并trim（P1-11修复：防止r_registry无限增长）
        known_rs[r] = True
        self._trim_r_registry()
        return True, 'OK'

    # -------------------------------------------------------------------------
    # 告警记录
    # -------------------------------------------------------------------------

    def _record_fail(self, agent_id: str, attack_type: str, detail: str):
        """记录安全失败事件"""
        self._fail_counts[agent_id] += 1
        alert = {
            'timestamp': int(time.time() * 1000),
            'agent_id': agent_id,
            'attack_type': attack_type,
            'detail': detail,
            'total_fails': self._fail_counts[agent_id],
        }
        self._alerts.append(alert)
        logger.warning(f"[SecurityGuard] 安全告警: {attack_type} | agent={agent_id} | {detail}")

        if self._fail_counts[agent_id] >= self.MAX_FAIL_COUNT:
            logger.error(
                f"[SecurityGuard] ⚠️ 高危告警: agent={agent_id} 累计失败 "
                f"{self._fail_counts[agent_id]} 次，建议封禁！"
            )

    # -------------------------------------------------------------------------
    # 查询接口
    # -------------------------------------------------------------------------

    def get_alerts(self, agent_id: Optional[str] = None) -> List[Dict]:
        """获取告警记录"""
        if agent_id:
            return [a for a in self._alerts if a['agent_id'] == agent_id]
        return list(self._alerts)

    def get_fail_count(self, agent_id: str) -> int:
        """获取指定智能体的失败次数"""
        return self._fail_counts.get(agent_id, 0)

    def get_risk_level(self, agent_id: str) -> str:
        """
        获取智能体风险等级
        0-1次: 正常, 2-4次: 警告, 5+次: 高危
        """
        count = self.get_fail_count(agent_id)
        if count == 0:
            return 'NORMAL'
        elif count < self.MAX_FAIL_COUNT:
            return 'WARNING'
        else:
            return 'DANGER'

    def _trim_r_registry(self):
        """
        P1-11修复：防止r_registry无限增长
        每个agent的r值记录超过MAX_R_ENTRIES时，FIFO淘汰最旧的条目
        """
        total_entries = sum(len(rs) for rs in self._r_registry.values())
        if total_entries <= self.MAX_R_ENTRIES:
            return
        # 按FIFO策略淘汰：优先淘汰总条目数最多的agent的旧r值
        while total_entries > self.MAX_R_ENTRIES:
            # 找到条目最多的agent
            max_agent = max(self._r_registry.keys(), key=lambda a: len(self._r_registry[a]))
            oldest = self._r_registry[max_agent].popitem(last=False)  # FIFO: pop最旧
            total_entries -= 1

    def get_stats(self) -> Dict:
        """获取安全统计信息"""
        return {
            'total_alerts': len(self._alerts),
            'monitored_agents': len(self._r_registry),
            'danger_agents': [
                aid for aid in self._fail_counts
                if self._fail_counts[aid] >= self.MAX_FAIL_COUNT
            ],
            'recent_alerts': self._alerts[-10:],
        }

    def register_nonce_baseline(self, agent_id: str, nonce: int):
        """
        注册 nonce 基线（P0-2 修复：与 Bridge nonce_counters 同步）
        当 Bridge 的 nonce_counter 已处于某个值时，SecurityGuard 需要知道这个基线，
        否则 Bridge 产生的 nonce 会被 SecurityGuard 误判为重放攻击。
        例如：Bridge nonce_counter[agent_0]=50，SecurityGuard nonce_registry 为空，
        Bridge 产生 nonce=51，SecurityGuard 首次见到 nonce=51 时 last_nonce=None，
        校验通过但逻辑上不正确（期望从 1 开始递增）。
        此方法显式注册基线，确保 SecurityGuard 知道 agent 的 nonce 已到哪一步。
        """
        last = self._nonce_registry.get(agent_id)
        if last is not None and nonce <= last:
            logger.warning(
                f"[SecurityGuard] nonce基线注册异常: agent={agent_id} "
                f"baseline={nonce} <= last={last}，忽略"
            )
            return
        self._nonce_registry[agent_id] = nonce
        logger.info(f"[SecurityGuard] nonce基线注册: agent={agent_id} baseline={nonce}")

    def reset_all_nonces(self, agent_ids: List[str] = None):
        """
        批量重置 nonce 记录（P0-2 修复：与 Bridge 重置同步）
        当 Bridge 重置 nonce_counters 时，必须同步重置 SecurityGuard 的 nonce_registry，
        否则 Bridge 从 nonce=1 开始而 SecurityGuard 仍记录 last_nonce=50，
        nonce=1 会被误判为重放攻击。
        """
        if agent_ids is None:
            self._nonce_registry.clear()
            logger.info("[SecurityGuard] nonce_registry 全量清空")
        else:
            for aid in agent_ids:
                self._nonce_registry.pop(aid, None)
            logger.info(f"[SecurityGuard] nonce_registry 部分清空: {agent_ids}")

    def reset_agent(self, agent_id: str):
        """重置智能体的安全记录（封禁后重新接入时使用）"""
        self._r_registry.pop(agent_id, None)
        self._nonce_registry.pop(agent_id, None)
        self._fail_counts.pop(agent_id, None)
        logger.info(f"[SecurityGuard] 已重置 {agent_id} 的安全记录")

    # -------------------------------------------------------------------------
    # 持久化（P1-17 修复：统一快照，避免单修自伤式 DoS）
    # -------------------------------------------------------------------------

    def to_snapshot(self) -> Dict:
        """
        导出可序列化快照。
        注意：nonce_registry 也一并导出，但必须与 SigningService 的
        nonce_counters 写入【同一份快照文件】，才能保证重启后两边一致、
        不会把合法 nonce 误判为重放（即自伤式 DoS）。单独持久化本表是危险的，
        因此本方法仅供 SigningService.save_state 统一调用。
        """
        return {
            'r_registry': {aid: dict(rs) for aid, rs in self._r_registry.items()},
            'nonce_registry': dict(self._nonce_registry),
            'fail_counts': dict(self._fail_counts),
            'alerts': list(self._alerts),
        }

    def from_snapshot(self, snap: Dict) -> None:
        """
        从快照恢复检测状态（须与 SigningService.nonce_counters 同源写入）。
        文件缺失/损坏时由调用方决定降级为全新状态，本方法只做尽力恢复。
        """
        if not isinstance(snap, dict):
            return

        def _coerce_r_keys(d) -> "OrderedDict":
            # JSON 序列化会把 int 键变成 str，这里把 r 值键还原回整数
            out = OrderedDict()
            for k, v in (d or {}).items():
                try:
                    nk = int(k)
                except (ValueError, TypeError):
                    nk = k
                out[nk] = v
            return out

        try:
            self._r_registry = defaultdict(
                OrderedDict,
                {aid: _coerce_r_keys(rs) for aid, rs in (snap.get('r_registry') or {}).items()},
            )
            self._nonce_registry = dict(snap.get('nonce_registry') or {})
            self._fail_counts = defaultdict(int, snap.get('fail_counts') or {})
            self._alerts = list(snap.get('alerts') or [])
        except Exception as e:  # 快照结构异常时保留内存状态，避免崩溃
            logger.warning(f"[SecurityGuard] 快照恢复部分失败，保留当前状态: {e}")
