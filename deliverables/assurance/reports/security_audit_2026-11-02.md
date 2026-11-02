# 安全与正确性审计简报（security_audit_2026-11-02）

- 生成时间：2026-11-02T23:15+08:00
- 审计范围：`blockchain/crypto`、`blockchain/consensus`、`blockchain/network`、`blockchain/ledger`、`blockchain/contracts`、`marl/algorithms`、`marl/analysis`
- 方法：**源码审读 + 定向差分/性质测试**（经典博弈已知均衡、跨进程确定性、形状不变量），不依赖随机 fuzz
- 结论：发现 **6 处缺陷**，全部已修复并带回归；全量 `1791 passed / 48 skipped`（唯一 failed 是缺 `torch` 的环境项，非代码缺陷）

## 汇总

| # | 严重度 | 模块 | 问题 | 修复 commit |
|---|---|---|---|---|
| 1 | **严重（安全）** | `blockchain/crypto/security_guard.py` | `r` 类型混淆绕过 k 重用检测（私钥可推导） | `e7dfa59` |
| 2 | 高（可用性） | 同上 | 非整数 `timestamp`/`nonce` 抛 `TypeError`（DoS） | `e7dfa59` |
| 3 | 中（正确性） | `marl/analysis/nash_verifier.py` | 混合策略纳什均衡被漏报 | `c0ba7ab` |
| 4 | 中（可复现性） | `marl/algorithms/qmix.py` | NumPy 回退用内建 `hash()`，受 `PYTHONHASHSEED` 影响 | `2ba2a52` |
| 5 | 高（训练正确性） | `marl/algorithms/mappo.py` | Critic 回归目标与 `v_pred` 错位 | `9878a69` |
| 6 | **严重（安全）** | `blockchain/crypto/ecdsa_utils.py` | 签名与载荷解绑：复用公开历史签名可伪造任意交易 | `597cabe` |

---

## 1. 严重：`r` 类型混淆绕过 k 重用检测

**根因**：`_check_r_reuse` 把 `r` 直接当 dict 键。`123`（int）与 `"123"`（str）是两个不同的键。攻击者只要把同一个 `r` 换成字符串形式重发，就被当成新值放行。

**影响**：ECDSA 中同一私钥使用相同 k 两次 → `r` 相同 → **私钥可被推导**。这条检测是唯一防线，绕过即等于密钥泄露。

**复现**（修复前）：
```
r=123 (int)      -> (True, 'OK')
r='123' (str)    -> (True, 'OK')   # 同一个 r，字符串形式
```

**修复**：新增 `_coerce_int`，把 `r` 归一为整数；非整数一律 fail-closed（拒绝该包）。数字字符串仍被接受，不误伤合法包。

**验证**：`tests/test_security_guard_type_confusion.py` 7 条；security 相关 **72 passed**。

## 2. 高：非整数字段导致守卫崩溃（DoS）

**根因**：`_check_timestamp` 直接做 `abs(now_ms - ts)`，`_check_nonce` 直接做 `nonce <= last_nonce`。收到非整数（如 `"x"`）时抛 `TypeError`，把守卫打成未捕获异常，而不是"拒绝这个包"。

**影响**：任一恶意成员发一个畸形包即可让安全守卫抛异常（可用性/DoS）。

**修复**：`timestamp` / `nonce` 同样走 `_coerce_int`；非整数 fail-closed。

**验证**：同上测试文件；数字字符串形式的时间戳仍被接受（不误伤）。

## 3. 中：混合策略纳什均衡被漏报

**根因**：`_find_mixed_strategy_nash` 中 `p_me = (M[1,0]-M[1,1])/denom`。对称 2×2 博弈中双方混合概率相同，`p_me` 应与 `p_opp` 用同一公式 `(M[0,1]-M[1,1])/denom`。当 `M[0,1] != M[1,0]` 时算出 >1 或 0 的无效值，均衡被判成"非均衡"。

**影响**：纳什分析（项目核心论证之一）漏报混合均衡。

**复现**（修复前）：

| 博弈 | 正确均衡 | 修复前 |
|---|---|---|
| 猎鹿 `[[4,0],[3,3]]` | (C,C)+(D,D)+混合 0.75 | 混合漏报 |
| 鹰鸽 `[[2,1],[3,0]]` | (C,D)+(D,C)+混合 0.5 | 混合漏报 |

**修复**：`p_me` 改用与 `p_opp` 同公式。

**验证**：`tests/test_nash_verifier_canonical.py`（囚徒困境 / 猎鹿 / 鹰鸽三个标准博弈）；nash 相关 **34 passed**。

## 4. 中：QMIX NumPy 回退不可复现

**根因**：`IQLEstimator` 用 `int(abs(hash(str(obs))) % hidden_dim)` 做状态离散化。Python 字符串 `hash()` 按 `PYTHONHASHSEED` 随机加盐，同一观测在不同进程落到不同 Q 表行。

**影响**：同一 seed/config 复跑结果不一致，与项目"数字可复算"的口径冲突。（项目在 `dashboard._demo_hash` 已因同款问题改掉内建 `hash()`，qmix 回退漏了。）

**修复**：新增 `_state_index`，用 sha256 前 8 字节取模；`get_action` / `train` 共用。

**验证**：`tests/test_qmix_state_index_determinism.py` —— `PYTHONHASHSEED=0/1` 两个子进程必须给出同一索引。

## 5. 高：MAPPO Critic 回归目标错位

**根因**：`train_step` 用 `np.repeat(returns, n_agents)[:T]` 作为 Critic 目标。`n_agents>1` 时那是 `[r0,r0,r1,...]`（agent 维重复后截断），而 `v_pred` 是逐时间步的 `[v0,v1,v2]`，两者错位。

**影响**：`n_agents>1` 时 Critic 永远在拟合错位的目标 → 价值估计错 → 优势估计错。训练能跑、loss 会降，但学的是错的东西（最隐蔽的一类）。

**复现**：`T=3, n_agents=2` 时 `returns=[1,2,3]`，`ret_flat[:T]=[1,1,2]`。

**修复**：抽出模块级 `_critic_targets`（校验长度 `== T`），直接用 `returns`。

**验证**：`tests/test_mappo_critic_targets.py`（纯 numpy，无需 torch）3 条。

## 6. 严重：签名与载荷解绑（复用公开签名即可伪造任意交易）

**根因**：`verify_action_package` 只对 `package['message_hex']` 里的字节验签，而 `message_hex` 是**交易自带字段**。`Blockchain._validate_new_block` 虽然把 `tx.agent_id / action / timestamp / nonce` 拼成 package 传了进去，该函数却**完全不看**这些字段——于是「签名覆盖的字节」与「交易声称的载荷」之间没有任何绑定。

更糟的是，`message_hex` 就存在链上 `tx.extra['message_hex']` 里，**每个 agent 的历史签名消息都是公开的**。

**影响**：任何人拿到 agent_A 一条无害行为的签名，就能以 agent_A 的名义写入任意行为：

1. 从链上取 agent_A 对 `{"type":"idle"}` 的签名 + 消息体；
2. 伪造一笔 agent_A 的 `{"type":"transfer","amount":999999}`；
3. 把旧 `message_hex` / `signature_hex` 原样贴上，`nonce` 换新（重放防护不触发）。

验签通过、区块校验通过。签名机制形同虚设——它证明「某人签过某段字节」，却被当成「某人授权了这笔交易」。

**复现**（修复前 → 修复后）：

```
受害者签 {"type": "idle"}（nonce=1）
攻击者构造 agent_A / {"type":"transfer","amount":999999} / nonce=99999
        + 受害者的 message_hex + signature_hex
Blockchain._validate_new_block(block) = True  →  False
```

**修复**：`verify_action_package` 增加载荷绑定校验——package 若携带 `agent_id / action / timestamp / nonce`，就解析 `message_hex` 中真正被签的内容，逐项比对 `agent_id` / `nonce` / `timestamp` / `action_hash`（`action_hash` 由 `action` 重算）。不一致即拒绝。

收口点选在 `verify_action_package` 而非 `blockchain.py`：账本（`blockchain.py`）、签名服务（`signing_service.py`）、合谋检测验签门（`cooperation_detector.py`）三个调用方都走这里，一处修全覆盖。

**验证**：`tests/test_signature_payload_binding.py` 9 条——正常签名包仍通过、换 `action`/`nonce`/`timestamp`/`agent_id` 复用签名全部拒绝、区块层端到端拒绝伪造交易且接受真实交易、旧式纯字节包语义不变、`int`/`float` 时间戳不误杀；相关子系统 **642 passed**。

---

## 验证口径

```
pytest tests/test_security_guard_type_confusion.py \
       tests/test_security_guard*.py tests/test_rfc6979_security.py   # 72 passed
pytest tests/test_nash_verifier_canonical.py tests/test_nash_verifier*.py  # 34 passed
pytest tests/test_qmix_state_index_determinism.py                    # 2 passed
pytest tests/test_mappo_critic_targets.py                            # 3 passed
pytest tests/test_signature_payload_binding.py                       # 9 passed
pytest tests/ -q                                                     # 1791 passed / 48 skipped
```

## 剩余风险（诚实说明）

- 本次审计是**定向**的（读源码 + 构造判据），不是全量形式化验证；未覆盖的路径不能据此认为安全。
- `network_consensus` 的签名验证依赖 `key_manager` 配置；未配置时默认 fail-closed（拒绝），但**纯连通性测试模式**（`_allow_insecure_vote`）不真验签，仅用于非生产场景。
- MAPPO 的 PyTorch 路径在本机缺 `torch`，相关训练测试在 CI 才完整执行；本次对 Critic 目标的修复用纯 numpy 不变量做了离线回归。
- 第 6 项的绑定校验只覆盖「package 携带四个字段」的路径。若将来新增调用方只传 `message_hex + signature_hex`（纯字节验签），绑定校验不会生效——**账本与签名服务路径必须继续传全字段**，这一点已写进函数 docstring。
- 绑定校验**没有**引入「低 s 归一化」，因此 ECDSA 可塑性（`(r, s)` 与 `(r, n-s)` 都合法）仍然存在。当前不影响本链的授权语义（tx_id 由 `agent_id/action_hash/timestamp/nonce/tx_type` 计算，不含签名），但若将来把签名纳入 tx_id，必须同时做低 s 归一化，否则会出现 txid 可变。
