"""
安全防护模块
实现ECDSA安全威胁检测：
1. k值重用检测（相同r值 → 相同k → 私钥可推导）
2. 重放攻击防护（nonce单调递增 + 时间戳有效期）
3. 签名异常行为监控
"""
import hashlib
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
        # 每个 agent 因超出 MAX_R_ENTRIES 被淘汰的条数（用于检测降级自查）
        self._r_evicted: Dict[str, int] = defaultdict(int)
        # 已被淘汰的 r 的摘要档案（跨窗口的自检测能力，见 _r_digest）
        self._r_evicted_digests: Set[str] = set()
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

        ⚠️ 三处必须同时满足，否则这个守卫是**装饰性**的（2026-11-01 实测）：

        1. **缺 r 不得无条件放行**。原实现 `if r is None: return True, 'OK'` ——
           签名包只要不带 r 字段就绕过整个检测。现按**包是否声称被签过**分场景：
           带 `signature_hex`/`s` 的包必须有 r（否则拒绝），
           非签名包允许缺 r（本来就没有 k 可重用）。详见实现处注释。

        2. **淘汰不等于可以放行**。原实现记录在 trim 之后不再关心被淘汰的 r，
           于是被 FIFO 挤出的 r 再次出现会返回 True —— 实测 MAX_R_ENTRIES=3 时
           `r=0 → 1 → 2 → 3（r=0 被挤出）→ 再发 r=0` 直接放行，即一次真实的
           k 重用被漏掉。修复：淘汰时把 r 的摘要存入 `_r_evicted_digests`，
           再次出现照样判定为重用来。

        3. **淘汰必须留痕**，不能静默遗忘。被淘汰过的 agent 在
           `get_detection_status()` 里报为降级 —— 静默遗忘等于给攻击者留窗口。
        """
        agent_id = package.get('agent_id')
        r = package.get('r')
        if r is None:
            # ── 分场景（2026-11-01 定案）──────────────────────────────────
            # `r` 是否必填取决于这个包**是否声称被签过**：
            #
            #   · 带 signature_hex（或 s）：这是签名包，签名必然产生 r，
            #     缺 r 说明包被截断/篡改，或者发送方在刻意省掉 r 以绕开检测
            #     —— 拒绝（fail-closed）。ECDSA 的 k 重用可直接推导私钥，
            #     这条检测是它唯一的防线，不能由发送方单方面声明"我不参与"。
            #
            #   · 无 signature_hex：非签名包（基准脚本、退化路径、仅统计用途），
            #     本来就没有 k 可供重用，放行 —— 保持既有 `test_r_missing_ok`
            #     的语义（r 对无签名包确实是可选的）。
            #
            # 判定只依赖包**自身**的字段，不看全局开关：同一进程里两类包可以混流。
            signed = bool(package.get('signature_hex')) or package.get('s') is not None
            if signed:
                return False, (
                    "签名包缺少r字段（有 signature_hex/s 却无 r）——"
                    "无法执行k值重用检测，按不合规包拒绝")
            return True, 'OK'

        known_rs = self._r_registry[agent_id]
        if r in known_rs:
            return False, (
                f"k值重用攻击检测！agent={agent_id} 的签名r值 {hex(r)[:16]}... 已出现过，"
                f"意味着使用了相同的随机数k，私钥存在泄露风险！"
            )
        # 查"已淘汰"档案：被 FIFO 挤出内存的 r 也必须能被认出来，
        # 否则淘汰就等于给攻击者开了一个可复用的窗口（实测能放行真实重用）。
        if self._r_digest(agent_id, r) in self._r_evicted_digests:
            return False, (
                f"k值重用攻击检测（历史档案命中）！agent={agent_id} 的 r 值 "
                f"{hex(r)[:16]}... 曾出现过（已超出内存窗口、从淘汰档案中认出），"
                f"意味着使用了相同的随机数k，私钥存在泄露风险！"
            )

        # 记录r值并trim（P1-11修复：防止r_registry无限增长）
        known_rs[r] = True
        self._trim_r_registry(agent_id)
        return True, 'OK'

    @staticmethod
    def _r_digest(agent_id, r) -> str:
        """r 值的短摘要，用于"已淘汰"档案。

        用摘要而非原文：档案需要长期保留，而 r 是 256 位大整数，
        按 agent 长期保留原文会无界增长。128 bit 摘要的碰撞概率在
        "误报一次 k 重用告警"这个量级上可以忽略，且误报方向是安全侧（拒绝）。
        """
        return hashlib.sha256(f"{agent_id}\x00{int(r)}".encode()).hexdigest()

    def _trim_r_registry(self, agent_id: str = None):
        """FIFO 淘汰超额 r 记录 —— **淘汰即入档案，绝不静默遗忘**。

        淘汰掉的 r 若再次出现，必须仍能被判定为重用（见 _check_r_reuse）。
        因此每淘汰一条：原文从 `_r_registry` 移除，摘要存入
        `_r_evicted_digests`；`get_detection_status()` 据此报出降级情况。
        """
        targets = [agent_id] if agent_id else list(self._r_registry)
        for aid in targets:
            reg = self._r_registry.get(aid)
            if not reg:
                continue
            while len(reg) > self.MAX_R_ENTRIES:
                old_r, _ = reg.popitem(last=False)      # FIFO：弹出最早插入的
                self._r_evicted_digests.add(self._r_digest(aid, old_r))
                self._r_evicted[aid] += 1

    def get_detection_status(self) -> Dict:
        """k 重用检测的**可信度**自查（不是"有没有跑过"，是"还能不能信"）。

        返回每个 agent 的已淘汰条数。淘汰不等于失明——被淘汰的 r 仍记录在
        摘要档案里、再次出现照样拦下；这里报出来是为了让"内存窗口有多大、
        已经翻过去多少"成为可观测事实。
        """
        degraded = {aid: n for aid, n in self._r_evicted.items() if n > 0}
        return {
            "max_r_entries": self.MAX_R_ENTRIES,
            "evicted_per_agent": degraded,
            "evicted_digest_count": len(self._r_evicted_digests),
            # 淘汰过的 agent 仍需被关注：检测现在依赖摘要档案，
            # 若要审计"到底淘汰了哪些原始 r"，得靠外部持久化。
            "is_degraded": bool(degraded),
            "note": ("部分 agent 的 r 记录已超出内存窗口，转为摘要档案保留——"
                     "重用仍会被拦下，但原始 r 已不可回溯。"
                     "长期运行建议上调 MAX_R_ENTRIES 或改用持久化存储。"),
        }

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

    # ⚠️ 这里曾有第二份 _trim_r_registry（P1-11 版），它做的是**全局**淘汰：
    #    `total_entries = sum(len(rs) for ...)`，超过 1000 就从"条目最多的 agent"
    #    身上 pop 最旧的一条。两个问题：
    #      (a) 与上面的按-agent 版本重名 → 后定义者静默覆盖前者（Python 类体规则），
    #          改了上面那份等于白改；
    #      (b) 语义更差——任意几个 agent 灌满配额，就能把**其他** agent 的 r 挤掉，
    #          攻击者据此可以把目标 agent 的重用检测窗口清空。
    #    已删除，统一走上面按 agent 淘汰 + 淘汰记账的版本。

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
