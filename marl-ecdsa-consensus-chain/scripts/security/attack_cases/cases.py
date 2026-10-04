# -*- coding: utf-8 -*-
"""
六类签名层攻击用例声明（任务 C：安全攻击测试框架化）

本模块**只声明元数据，不实现攻击逻辑**。攻击真实逻辑位于
scripts/legacy/analysis/attack_defense_demo.py 的 demo_* 函数（冲突区③，禁止修改）。
harness 通过 ALL_ATTACKS[name] 调用这些已验证函数，本模块提供人类可读的
「前置条件 / 注入方式 / 拦截机制 / 判定依据」声明，使框架可复现、可审计。

六类攻击（按 E6 扩展，2026-09-18 由 3 → 6 类）：
  1. observation_forgery  观测伪造
  2. message_tampering    消息篡改
  3. replay_attack        重放攻击
  4. sybil_attack         女巫 / Sybil
  5. k_reuse_attack       k 值重用（私钥提取）
  6. long_range_attack    长程攻击（旧纪元签名伪造历史）

口径边界（务必遵守）：
  - 拜占庭主节点（Byzantine primary）由 CW-PBFT failover 单独覆盖，**不计入六类**。
  - 判定依据里的字段名均取自 demo_* 函数返回的 with_bc 字典，harness 据此判定拦截。
"""

from typing import Dict, List

# 每条用例声明的字段
CASE_FIELDS = ["precondition", "injection", "interception", "judgment", "module", "notes"]

# 攻击显示名（中文）
DISPLAY_NAMES = {
    "observation_forgery": "观测伪造攻击",
    "message_tampering": "消息篡改攻击",
    "replay_attack": "重放攻击",
    "sybil_attack": "女巫 / Sybil 攻击",
    "k_reuse_attack": "k 值重用攻击",
    "long_range_attack": "长程攻击",
}

ATTACK_CASES: Dict[str, Dict[str, str]] = {
    "observation_forgery": {
        "precondition": "恶意节点持有合法 ECDSA 私钥，可对任何内容自签（验签必然通过）。",
        "injection": "用自己私钥签名伪造观测位置（如谎称在路口 x=0.5,y=0.5）并广播，诱导其他智能体让路。",
        "interception": "链上「承诺-揭示」绑定（commit-reveal）：开局节点先签名 H(true_position) 上链；"
                        "后续观测提交时链上校验 H(reported_position) == 承诺哈希。",
        "judgment": "with_bc.blocked_by_commitment_binding == True（承诺哈希不匹配→拒绝）。"
                    "诚实披露：ECDSA 验签通过（自签），签名仅认证签名者、不保证内容真实。",
        "module": "Blockchain（承诺交易）+ 链上承诺绑定校验",
        "notes": "旧版稻草人把『冒充他人被验签拦住』偷换为『伪造被拦截』虚高防护率；"
                 "本实现诚实承认自签通过、靠承诺绑定拦截。",
    },
    "message_tampering": {
        "precondition": "中间人可截获并转发动作消息，但**没有发送方私钥**，无法重新签名。",
        "injection": "篡改消息内容（yield→forward），原签名随之失效。",
        "interception": "动作消息必须 ECDSA 签名后传输；接收方验证签名 + 消息哈希比对。",
        "judgment": "with_bc.signature_valid_tampered == False 且 with_bc.hash_match == False（篡改消息被拒）。",
        "module": "ECDSAUtils.verify + sha256 完整性校验",
        "notes": "无BC模式无完整性校验，篡改无法检测→碰撞；有BC模式签名验证失败→拒绝执行。",
    },
    "replay_attack": {
        "precondition": "攻击者截获一条有效签名消息（5 分钟前、nonce=1）。",
        "injection": "在后续步骤（step 50）重放该旧消息，诱导接收方执行过期动作、重复占用资源。",
        "interception": "SecurityGuard 检测 nonce 重用 + 时间戳过期（TIMESTAMP_TOLERANCE_MS，±容差秒）。",
        "judgment": "with_bc.replay_blocked == True（nonce 重用 或 时间戳过期双重检测）。",
        "module": "SecurityGuard.check_package",
        "notes": "无BC模式无时间戳/nonce 验证，旧消息被当作新消息执行。",
    },
    "sybil_attack": {
        "precondition": "攻击者伪造大量身份（Sybil 8 个 vs 诚实 4 个），试图以数量淹没共识。",
        "injection": "以数量投票权重淹没共识，朴素一身份一票下 Sybil 多数即获胜。",
        "interception": "贡献度门控权重：每个身份须持 ECDSA 密钥且贡献权重需累积"
                        "（INITIAL_WEIGHT=0.3，MIN_WEIGHT=0.1 下界）；诚实方累积贡献后权重 >> Sybil。",
        "judgment": "with_bc.blocked == True（Sybil 累计权重 < 2/3 总权重阈值，恶意提案被拒）。",
        "module": "CWPBFTConsensus 贡献度门控权重",
        "notes": "拜占庭主节点由 CW-PBFT failover 单独覆盖，本类仅考核贡献度门控，不混入 failover。",
    },
    "k_reuse_attack": {
        "precondition": "同一私钥用相同随机数 k 对两条不同消息签名 → r 值相同 → 私钥可推导。",
        "injection": "复用 r 提交第二条消息（pkg_b 复用 pkg_a 的 r），暴露私钥。",
        "interception": "SecurityGuard k 值重用检测：相同 r 二次出现即告警（K_REUSE_ATTACK）。",
        "judgment": "with_bc.blocked == True（pkg_b 被拦，block_reason 含 K_REUSE_ATTACK）。",
        "module": "SecurityGuard.check_package",
        "notes": "无BC模式仅验签、不检测 r 重用→私钥静默泄露；有BC模式 r 重用被拦截。",
    },
    "long_range_attack": {
        "precondition": "攻击者保存诚实节点在旧纪元（1 小时前、epoch=1）的合法签名消息。",
        "injection": "在新区元（epoch=5）重放旧签名，伪造历史或注入过期但密码学仍有效的消息。",
        "interception": "时间戳窗口（±30s）+ 纪元绑定（epoch 单调）：旧纪元消息被拒。",
        "judgment": "with_bc.blocked == True（时间戳过期 或 epoch 不匹配双重拒绝）。",
        "module": "SecurityGuard.check_package + 纪元校验",
        "notes": "无BC模式仅验签、旧合法签名仍被接受→历史可被篡改；有BC模式时间戳+纪元双重拒绝。",
    },
}


def ordered_case_names() -> List[str]:
    """返回六类攻击的标准顺序名称。"""
    return [
        "observation_forgery",
        "message_tampering",
        "replay_attack",
        "sybil_attack",
        "k_reuse_attack",
        "long_range_attack",
    ]


def validate_cases() -> List[str]:
    """校验 ATTACK_CASES 结构完整性，返回问题列表（空=通过）。"""
    problems: List[str] = []
    expect = set(ordered_case_names())
    got = set(ATTACK_CASES.keys())
    if expect != got:
        problems.append(f"用例集合与标准六类不一致: 缺 {expect - got}, 多 {got - expect}")
    for name, case in ATTACK_CASES.items():
        for field in CASE_FIELDS:
            if field not in case or not str(case.get(field, "")).strip():
                problems.append(f"用例 {name} 缺字段 {field}")
        if name not in DISPLAY_NAMES:
            problems.append(f"用例 {name} 缺少中文显示名")
    return problems


if __name__ == "__main__":
    errs = validate_cases()
    if errs:
        for e in errs:
            print("PROBLEM:", e)
        raise SystemExit(1)
    print(f"OK: {len(ATTACK_CASES)} 类攻击用例声明完整")
