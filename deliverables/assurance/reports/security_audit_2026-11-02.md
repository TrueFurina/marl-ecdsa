# 安全与正确性审计简报（security_audit_2026-11-02）

- 生成时间：2026-11-02T23:15+08:00
- 审计范围：`blockchain/crypto`、`blockchain/consensus`、`blockchain/network`、`blockchain/ledger`、`blockchain/contracts`、`marl/algorithms`、`marl/analysis`
- 方法：**源码审读 + 定向差分/性质测试**（经典博弈已知均衡、跨进程确定性、形状不变量），不依赖随机 fuzz
- 结论：发现 **9 处缺陷**，全部已修复并带回归
- ⚠️ **其中 6 处曾被 `d9e701c`（"sync: 源码对齐 V29 新基线"）静默回退**，仓库里的回归锁当时全红；已于 2026-11-03 恢复并加固，见 **§10 回退事件**。本文所有修复声明以 §10 的恢复提交为准
- 全量口径：本机实测 **1841 passed / 1 failed / 42 skipped**（唯一 failed 为 `test_deps_importable` 缺 `torch` —— 本机 torch 的 `shm.dll` 加载失败故已卸载；CI 由 `requirements.txt` 安装）。**该计数来自恢复后的本机工作树，不等于 main 的测试总数**（main 比本机多约 180 个文件）

## 汇总

| # | 严重度 | 模块 | 问题 | 修复 commit |
|---|---|---|---|---|
| 1 | **严重（安全）** | `blockchain/crypto/security_guard.py` | `r` 类型混淆绕过 k 重用检测（私钥可推导） | `12212a9` |
| 2 | 高（可用性） | 同上 | 非整数 `timestamp`/`nonce` 抛 `TypeError`（DoS） | `12212a9` |
| 3 | 中（正确性） | `marl/analysis/nash_verifier.py` | 混合策略纳什均衡被漏报 | `44b3962` |
| 4 | 中（可复现性） | `marl/algorithms/qmix.py` | NumPy 回退用内建 `hash()`，受 `PYTHONHASHSEED` 影响 | `e98d5ca` |
| 5 | 高（训练正确性） | `marl/algorithms/mappo.py` | Critic 回归目标与 `v_pred` 错位 | `bd56b87` |
| 6 | **严重（安全）** | `blockchain/crypto/ecdsa_utils.py` | 签名与载荷解绑：复用公开历史签名可伪造任意交易 | `7e20a94` |
| 7 | 高（共识安全） | `blockchain/consensus/standard_pbft.py` | 等权基线缺女巫门控：伪造 voter_id 即可凑够 Quorum | `5d509f9` |
| 8 | 中（指标失真） | `blockchain/consensus/cw_pbft_failover.py` | 心跳缺省值 0 被判「纪元 0 发过」→ 每轮虚假视图切换 | `b07953d` |
| 9 | 高（激励正确性） | `blockchain/contracts/incentive_contract.py` | NaN 奖励被钳成满分 → 算崩的智能体拿最高激励；NaN 还可永久污染账本 | `2e30262` |

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

**修复**：`verify_action_package` 用包内字段经 `build_message()` **重建**被签消息，与 `message_hex` 逐字节比对，不一致即拒绝。

**2026-11-03 加固（两处）**：

1. **缺字段一律 fail-closed**。首版写成「package 携带四个字段才比对」，于是把 `agent_id / action / timestamp / nonce` 删掉、只留 `message_hex + signature_hex`，绑定校验就整段被跳过。而 `cooperation_detector.filter_verified_packages()` 吃的正是**外部传入**的包（其 docstring 明写"含伪造/顶名包"）—— 删字段即绕过，这是后门不是兼容。现在缺任一字段直接拒绝；纯字节验签走明确的底层入口 `ECDSAUtils.verify()`。
2. **`extra` 纳入绑定**。原实现用 `package.get('extra')` 重建，语义正确但没有任何用例覆盖；现补三条回归（未声明键拒绝 / 声明键通过 / 声明键值被改拒绝），并允许 JSON 数值写法差异（`1000` 与 `1000.0` 等价），避免把同值 float 时间戳误判成篡改 —— 放宽的只是表示形式，不是字段集合。

收口点选在 `verify_action_package` 而非 `blockchain.py`：账本（`blockchain.py`）、签名服务（`signing_service.py`）、合谋检测验签门（`cooperation_detector.py`）三个调用方都走这里，一处修全覆盖。

**验证**：`tests/test_signature_payload_binding.py` **13 条**（本机实测全绿）——正常签名包仍通过、换 `action`/`nonce`/`timestamp`/`agent_id` 复用签名全部拒绝、区块层端到端拒绝伪造交易且接受真实交易、`int`/`float` 时间戳不误杀、裸字节包拒绝、缺任一字段拒绝、`extra` 三条（未声明/声明/被改）。另有 `tests/test_verify_package_field_binding.py` **11 条**（2026-10-15 那版绑定校验的守护）同时全绿。

## 7. 高：等权基线缺女巫门控（伪造 voter_id 即可凑够 Quorum）

**根因**：`StandardPBFTConsensus.receive_vote` 不校验投票者是否在共识成员集合内，而 `_check_vote_threshold` 按 `len(self._votes[phase])`（投票者**个数**）计数。于是任何调用方塞进任意伪造 `voter_id`，就能凭空凑够 `ceil(2n/3)`。

CW-PBFT 在 09-28（全检 #2）就加了「非共识成员身份一律拒收」，**等权基线漏了同一个门控** —— 同一套接口、同一个 `factory`，安全属性却不一样。

**影响**：

1. **共识安全性**：单节点可在无任何真实对等节点的情况下宣布共识达成。
2. **对比实验可信度**：等权基线正是论文对照组的实现（`factory` 以 `mode='standard_pbft'` 创建），它的安全属性不应弱于被对照的对象。

**复现**（n=4，阈值 `ceil(8/3)=3`，单个节点、零个真实对等节点）：

```
StandardPBFT: 达成共识=True   prepare池=['ghost_1','ghost_2','ghost_3']
CW-PBFT     : 达成共识=False  prepare池=[]
```

**修复**：与 CW-PBFT 对齐 —— 非成员投票一律拒收（不写 `_votes`、不计入 Quorum）；自报 `weight` 覆盖为权威值 `1.0`（存副本，不改写入参），杜绝第二个可信通道。

**验证**：`tests/test_standard_pbft_sybil_gate.py` 8 条 —— 非成员拒收、伪造凑不出阈值、端到端幻影共识失败、自报权重纠偏、入参不被就地改写、真实投票仍能达成共识（防误杀）、真伪混投只计真实票、两引擎行为一致；共识相关 **69 passed**。

**边界（诚实说明）**：网络层 `_on_prepare` / `_on_commit` 已有 `_verify_vote_signature`（要求 `voter_id` 与注册公钥绑定，无 `key_manager` 时 fail-closed），因此**走网络**的伪造身份本就被挡住。本次修的是**引擎边界**：`receive_vote` 是对外公开 API，`simulated_consensus` 与离线实验都直接驱动它。更彻底的方案是抽公共基类把门控下沉，但那是较大重构，本次按「两个实现行为对齐」做最小修复。

## 8. 中：心跳缺省值导致每轮虚假视图切换（failover 统计失真）

**根因**：`_last_heartbeat` 是空 dict，`check_primary_health` 用 `self._last_heartbeat.get(primary_id, 0)` 取缺省值。`0` 被当成「纪元 0 发过心跳」，于是 `now_ms - 0 > HEARTBEAT_TIMEOUT_MS` 恒真 —— **从未发过心跳的节点一律被判超时**。

**证据**：模块自带的自测第一段写着「1. Normal consensus (no Byzantine)...」，而它打出的第一行日志是：

```
View change: node_0(primary_timeout) → node_1 (view=1)
```

全新引擎、完全健康的主节点，第一轮就被判超时并切换。

**影响**：故障切换统计与真实拜占庭事件**完全脱钩**，而这正是论文用来量化 failover 有效性的数据。实测 `simulate_byzantine_primary_attack(n_rounds=20)`（只在 r=5/10/15 注入拜占庭）：

```
修复前：byzantine_events=3, successful_failovers=20  → 20/20 = 100%
修复后：byzantine_events=3, successful_failovers=15  → 15/20 =  75%
```

修复前那条 100% 是纯噪声（每轮都切）。**修复后剩下的 15 次不是缺陷**：拜占庭标记一旦打上就永久生效，而出块轮转每 10 块才换一次主，所以一个被标记的主节点会在后续多轮里持续触发切换——这是设计取舍，已在下方「剩余风险」登记。

**修复**（最终口径，2026-11-03 修订 —— 见 §11.2）：

- `_last_heartbeat` 保持**空表**，不伪造时间戳；
- `check_primary_health` 对「从未收到心跳」的节点返回 **`UNKNOWN`**，且**不改写**
  `_primary_status` —— 缺信息既不是「健康」也不是「超时」，只是没有信息；
  因为 UNKNOWN 不进入故障判定，虚假视图切换同样被消除；
- 心跳过旧（确实收到过、但超过 `HEARTBEAT_TIMEOUT_MS`）仍判 `TIMEOUT`。

> ⚠️ 本节最初写的修法是「构造时把心跳表按当前时刻预填、一律判 HEALTHY」。
> 该写法能消除虚假切换，但等于对「从未收到心跳」的节点**声称**它刚发过心跳 ——
> 状态表撒谎，审计时无法区分「真健康」与「没消息」。现行实现改取 UNKNOWN，
> 语义更严，与 `tests/test_cw_pbft_failover.py` 的断言一致。

**验证**：`tests/test_failover_heartbeat_semantics.py` 8 条 —— 全新引擎判
UNKNOWN 而非 TIMEOUT（不误报）、心跳表初始为空（不伪造成已知）、运行期查询不写入
伪造时间戳、正常轮不产生 failover 记录、显式补心跳同样不触发、心跳过旧仍判超时
（防误放）、注入拜占庭仍触发切换（防漏报）、重置后表清空且不退回到「一律超时」；
与 `tests/test_cw_pbft_failover.py` 合计 **27 passed**。

## 9. 高：NaN 奖励被钳成满分（算崩的智能体反而拿最高激励）

**根因**：奖励/贡献的钳位写成 `max(low, min(high, x))`。`min`/`max` 的比较对 NaN 恒为 False，NaN 会被原样「保留在上界」：

```
max(0.0, min(1.0, float('nan'))) == 1.0
```

**影响**：

1. **逆向激励**：NaN 通常来自策略发散 / 除零 / env bug。把 NaN 记成满分，等于奖励「制造 NaN」；这条 delta 还会经 `total = env + λ·bc` 回流到策略奖励，形成闭环。
2. **账本永久污染**：`WorldState.add_score` 不拦 NaN，一旦写进去 `NaN + x` 恒为 NaN，该智能体积分再也救不回来（实测：写入 NaN 后再加 5 仍是 NaN），并会污染 `cumulative_contribution` 与排行榜排序。

**复现**（修复前）：

```
good   (env_reward=0.0) → task=0.4286, delta=17.71
broken (env_reward=NaN) → task=1.0000, delta=20.00   ← 谁算崩了谁拿钱最多
```

**修复**：

- 新增 `clamp_finite()`：非有限值（NaN/±inf）一律返回 `fallback=0.0`，并在带 `field` 时打 WARNING（可定位到具体智能体与字段）；
- 收口五处：`compute_contribution` 的 `task_score`、`settle_rewards` 的 `weighted_score`、`compute_contribution_scores` 的奖励归一化、`compute_total_reward` 的 `bc_reward` 裁剪、`_simulate_settlement`；
- `WorldState.add_score` 改为「非有限值即拒收」（fail-closed，不静默钳位），保证账本里不可能出现 NaN。

选择「按 0 记」而非「抛异常」：训练循环里抛异常会中断长跑，而 0 的语义是「无有效贡献」，既不奖励垃圾也不掩盖问题（有 WARNING）。

**验证**：`tests/test_incentive_nonfinite_guard.py` 13 条 —— NaN 不成为最高分、算崩的智能体不再比正常的高、账本拒收 NaN/inf 且不被污染、累计贡献不被污染、`bc_reward=NaN` 不静默送 `λ*20`、**正常值路径逐项不变**（防误伤）。

---

## 10. 回退事件：9 处修复中有 6 处曾被静默回退（2026-11-03）

> ⚠️ **2026-11-03 续：其中 1 处判断已撤回。** 本节标题与正文的「6 处」按
> 当时的核查口径保留不改（改历史结论等于伪造过程），但实际成立的数字是 **5 处** ——
> `cw_pbft_failover` 那条是误判：main 现实现（显式 `UNKNOWN`）比 11-02 那版更好，
> 所谓"恢复"其实是回退。撤回与理由见 **§11.2**。

### 10.1 事实

`d9e701c`（`2026-11-03T07:58Z`，提交信息「sync: 源码对齐 V29 新基线（口径 n=101/2183 +
新版前端）」）一次改动 258 个文件。其中 10 个源文件被**整份覆盖**成更旧的基线
（`nash_verifier` 是 +825/−829，典型的整文件重写），把 11-01/11-02 的修复一起带走。

以 `d9e701c` 的父提交 `3fa6b19` 为对照，逐文件确认被回退的内容：

| 文件 | 被回退的保护 | 后果 |
|---|---|---|
| `blockchain/crypto/security_guard.py` | `_coerce_int` 字段归一、缺 `r` 的 fail-closed 分场景判定、淘汰归档 `_r_evicted_digests`、按 agent 淘汰、`get_detection_status` | k 重用检测被绕过（可推导私钥）；非整数时间戳打崩守卫 |
| `blockchain/crypto/ecdsa_utils.py` | 无（该提交保留了绑定校验，但实现较宽松） | 见 §10.3 的加固 |
| `marl/algorithms/mappo.py` | `_critic_targets()` | Critic 回归目标与 `v_pred` 错位 |
| `marl/algorithms/qmix.py` | `_state_index()`（sha256） | 状态离散化受 `PYTHONHASHSEED` 影响，复跑不一致 |
| `marl/analysis/nash_verifier.py` | `p_me` 公式 | 鹰鸽 p=0.5、猎鹿 p=0.75 的混合均衡被漏报 |
| `blockchain/consensus/standard_pbft.py` | 自报 `weight` 纠偏（`replace(vote, weight=1.0)`） | 真实成员可自带 `weight=999` 参与阈值计算 |
| `blockchain/consensus/cw_pbft_failover.py` | 心跳表构造/重置时初始化 | 从未发心跳的主节点永不被判超时（死主不替换） |
| `blockchain/contracts/incentive_contract.py` | `clamp_finite()` | NaN 被钳成满分：算崩的智能体拿最高激励 |
| `blockchain/ledger/world_state.py` | `add_score` 非有限值拒收 | `NaN + x` 永久污染该智能体积分 |
| `marl/integration/settlement_coordinator.py` | 三处 `clamp_finite` 钳位 | NaN delta 流入下游奖励 |

### 10.2 为什么没有被拦住

仓库里那 6 个回归锁文件**都在**、且断言完好（未随提交一起被改弱）。问题在 CI：

```
GET /repos/TrueFurina/marl-ecdsa/actions/workflows
→ build-binaries / Dependency Graph / pages-build-deployment     （共 3 个）
```

`CI - Test Suite` 写在 `marl-ecdsa-consensus-chain/.github/workflows/ci.yml`，
而 GitHub Actions **只扫描仓库根**的 `.github/workflows/`。子目录里的工作流
从未被注册，因此**一次都没运行过**。

实测代价：把 main 当前的 5 个源文件换进工作树后跑仓库自带的回归锁 ——
**19 failed + 1 collection error**（`test_mappo_critic_targets.py` 直接
`ImportError: cannot import name '_critic_targets'`）。这些红灯在 main 上躺了一整天。

### 10.3 恢复与加固

分 6 个提交逐条恢复（每个提交都保留 `d9e701c` 带来的**正当增量**，不回退 V29 内容）：

1. `8463c27` security_guard：三处保护 + 字段归一 + 淘汰归档 + 降级自检全部恢复；
2. `dd4c86d` / `b66ca09` ecdsa_utils：缺字段 fail-closed + `extra` 纳入绑定（新增实现，
   不是回退），测试同步更正 2 条错断言并新增 4 条；
3. `6fd86b1` mappo / qmix / nash：恢复 `_critic_targets`、sha256 离散化、`p_me` 同公式，
   同时保留 QMIX 的 S9 登记注释与 Nash 的 F16 `top_tier_bonus=10.0`；
4. `dfb7e56` standard_pbft / failover：补回女巫门控的自报权重纠偏；
   ~~心跳表按回归锁口径初始化~~ —— **此条已作废，见 §11.2**：failover 的"恢复"
   实为把更差的实现改回来，已撤回，该文件与 main 逐字节一致；
5. `7d88939` incentive / world_state / settlement：三处 NaN 护栏恢复，
   同时保留 F02 `clear_episode_rewards` 与 F05 `get_consensus_weight`；
6. `fda6cbd` CI 搬到仓库根，安全不变量拆成 fail-fast job。

**合并口径**（避免"恢复成旧版"）：
以 main 当前版本为底座做**定点补丁**，每个文件的差异只包含被回退的那几处；
`git diff` 上是 24 / 97 / 22 / 36 / 22 / 67 / 71 行级别的改动，不是整文件重写。

### 10.4 本节引用的哈希

汇总表里的 8 个修复提交哈希，早前版本写的是 `e7dfa59` / `c0ba7ab` / `2ba2a52` /
`9878a69` / `597cabe` / `4760fa9` / `7caa0d8` / `8ba090c` —— 这 8 个在远端
**全部 404**（`GET /commits/{sha}` 返回 422）。真实哈希为
`12212a9` / `44b3962` / `e98d5ca` / `bd56b87` / `7e20a94` / `5d509f9` /
`b07953d` / `2e30262`，已逐一核对存在。P1-11 的 k 重用那轮是 `8bc432b`。

---

## 11. 2026-11-03 续：CI 归位后首轮实测（修 8 处 / 撤回 1 处误判）

§10 记的是「恢复被回退的修复 + 把 CI 搬到会被执行的位置」。CI 真正跑起来之后，
暴露出 §10 里**至少一条判断是错的**，以及一批**与回退无关**的既有红灯。
按本项目的口径纪律（发现旧判断错误必须自我推翻），单独列一节。

### 11.1 第一道门：从「77 passed / 1 failed」到全绿

CI 归位后第一次运行的结果是 `77 passed / 1 failed`，失败项唯一：

```
FAILED tests/test_signature_payload_binding.py::
       TestBlockchainRejectsForgedTx::test_block_with_genuine_tx_accepted
AssertionError: assert False is True
日志：[Blockchain] 区块 #1 缺少出块者签名，拒绝上链
```

根因：账本自 2026-11-02 起有区块级完整性门（出块者签名 + `state_root` 可重算），
而该测试塞的是 `state_root="0"*64` 且不签名的**合成区块**。

> **本机为什么是绿的**：本地账本还是旧版（没有这道门）。这条用例本身就是
> 「CI 搬到仓库根是必要的」的反例证据 —— 本地绿 ≠ CI 绿。

修法：`_make_block()` 改走真实出块流程 `构造 → finalize() → sign_block()`
（顺序不可反：`finalize()` 重算 `state_root` 与 `block_hash`，签名不进哈希故可后签）。

顺带修掉一条**假通过**：`test_block_with_forged_tx_rejected` 原先也不签名，
在新账本上它会因为「区块没签名」而被拒绝 —— 等于这条用例在断言「区块没签名」，
根本没测到「伪造交易被拒」。补上签名后，区块本身合法，被拒只能来自交易级校验。

### 11.2 撤回：`cw_pbft_failover` 不是「被回退」

§10.3 第 4 条曾称「心跳表按回归锁口径初始化」。**这条已作废。**

事实：main 现在的实现是「空表 + 对从未心跳的节点返回 `UNKNOWN`」，比 2026-11-02
那版（构造时按 `now` 预填整表、一律判 `HEALTHY`）更好 —— 缺信息既不是健康也不是超时。
我按 11-02 版"恢复"，实际是把更好的实现改回更差的，**属回退**。
已撤回，`cw_pbft_failover.py` 与 main 逐字节一致（`diff -q` 无输出）。

连带发现 main 上有一对**自相矛盾**的测试：

| 文件 | 引入提交 | 断言 |
|---|---|---|
| `tests/test_cw_pbft_failover.py::test_initial_health_without_heartbeat_is_unknown` | `d9e701c` | UNKNOWN |
| `tests/test_failover_heartbeat_semantics.py` | `b07953d` | HEALTHY + 心跳表已预填 |

两者不可能同时通过；实测 main 上后者 4 条红（`FFF....F`）。已把后者按最终口径
重写（UNKNOWN / 空表 / 查询不写入伪造时间戳），两份测试并存 **27 passed**。

### 11.3 真修复：C4「FIFO 淘汰后重用」缺口关闭

不是回退，是 `security_guard` 淘汰摘要档案带来的实际语义变化：发 1002 个包把早期
`r` 挤出 `_r_registry` 后再重用，实测 `ok=False`，理由命中「历史档案」。

原测试 `test_c4_fifo_eviction_allows_reuse` 钉的是「缺口存在」这一旧事实，按该文件
自己写明的约定（「若将来修复了其中某项，翻转对应断言即有明确信号，不会无声退化」）
翻转为 `test_c4_evicted_r_is_still_detected`；另加
`test_c4_residual_archive_is_in_memory_only` 钉住**残留边界**：摘要档案只在进程内，
重启 / 换副本后仍可重放。

探针与证据同步重算（`scripts/security/_probe_combination_attacks.py` +
`combination_attack_result.json`）：**4/4 绕过 → 3/4 绕过**，C4 转为 ✅ 拦截。
顺带修掉探针 `write_text` 的平台行尾问题（Windows 会把 `\n` 翻成 `\r\n`，
让证据文件在 git 上显示整份重写，把真改动埋进行尾噪音）。

### 11.4 main 上的既有红灯（与回退无关，CI 归位才看见）

| # | 位置 | 现象 | 定性 |
|---|---|---|---|
| 1 | `scripts/smoke_test_e2e.py` P0-1 | `assert abs(lambda_weight - 0.1) < 0.001` 失败，实测 `0.10231058578630006` | P2-E 自适应 λ 引入后 λ 落在 `(0.05, 0.15)`，断言是旧口径 |
| 2 | `tests/test_f04_web_wiring.py` | 4 条失败（`get_pending_submit('1')` 得 None / `/api/distributed/resume` 404） | 通道键写死 `'1'`，全量套件里更早用例注册过用户后新用户 id 就不是 1 |
| 3 | `scripts/pre-commit/structure_guard.py --all` | 13 个根级文档被判违规平铺 | 存量布局问题（V18–V27 等），与代码改动无关 |

第 2 条特别值得记：**单独跑该文件 5 passed，全量跑 4 failed**。这不是环境差异，
是**测试之间的状态耦合**（`instance/accounts.sqlite3` 的用户自增 id）——
「本地绿 ≠ CI 绿」的另一种形态。

### 11.5 处理方式

1. **自适应 λ**：改为钉住两件真正该守的事 —— `λ_base == 0.1`（config → bridge
   传参通路不丢）+ 运行时 λ 不越出自适应带 `[0.5λ_base, 1.5λ_base]`。
2. **f04**：从 `session['uid']` 读真实 uid，与用户表状态解耦。
3. **structure_guard**：13 个文件登记为**存量冻结豁免**（常量集合，只减不增），
   `main()` 每次打印出来，不静默腐烂。搬目录会打断 README / thesis 的相对引用，
   属独立任务，不在此处草率处理。
   其中 `V18_σèƒΦâ╜σñìµá╕µèÑσæè.md` 的**文件名本身是乱码**（UTF-8 文件名被按
   CP437 解释），原意为「V18_功能复核报告.md」，另案记录。
4. **`test_f11_grandchild_cleanup.py`**：依赖 `launcher/supervisor.py`，该模块
   **不在本仓库**（全仓 grep `_make_job` 仅命中该测试；Job Object 的实现在
   `visualization/business_service.py`）。模块级 `exec_module` 抛
   `FileNotFoundError`，属**收集期错误**，会让整个 `pytest tests/` 中断
   （CI 实测 `Interrupted: 1 error during collection`，其余 2000+ 条一条没跑）。
   不删用例，改为缺模块时**整模块 skip**；模块一旦回来，用例自动恢复执行。

### 11.6 门禁自身的两个 bug

- `scripts/pre-commit/caliber_check.py`：`_RE_TESTS = (\d{3,5})` 不支持千分位，
  `2,183 passed` 被读成 **183**，于是 README 里等于下限的表述被判成
  「低于下限 2183」的**假红**。现同时接受 `1,234` 与 `1234`。
- `.agents/skills/test-gate/SKILL.md`：写着 `"1632 passed" 是当前基线`，
  低于 NR-19 下限 2183 —— 真正的过期数字。改为指向登记簿 NR-19，
  不再另抄一份（第二份真值源必然漂移）。

### 11.7 一条数字口径的待办（不在本次改动范围）

NR-19 记的是 2026-11-02 R5 轮「2192 收集 / 2183 通过 / 9 跳过 / 0 失败」。
CI 归位后本地实测的全量数字与之**不再一致**，但**本次不改 NR-19**：
改动登记簿需要配套的 junit 证据与扩种口径说明，属独立流程。

本次本地实测（Windows / Python 3.12.10）：

| 项 | 实测 |
|---|---|
| 结果 | **2227 passed / 2 failed / 22 skipped**（合计 2251） |
| 未计入 | `tests/test_qmix.py`、`tests/test_algorithm_family_contract.py` 因本机装不上 torch 无法收集，已 `--ignore` |
| failed #1 | `test_deps_scripts.py::test_deps_importable` —— 缺 torch（本机 `shm.dll` 加载失败已卸载；CI 会装） |
| failed #2 | `test_next_nr.py::TestConcurrentAllocation::test_threaded_no_duplicate` —— 并发取号报 Windows 文件锁 `PermissionError`，**main 上同样红** |

两条 failed 都不是本次改动引入的。用例总数已由 2192 增长到 2251+，
skip 数由 9 变为 22（本机缺 torch 导致更多 skip）—— NR-19 需要重新基线化。
在此之前，任何「全量测试数」的引用都应以 NR-19 的下限式表述为准，
并且**不得**把本次实测数当作对外口径。

---

## 12. 全量套件第一次在 CI 上跑完：3 failed / 2275 passed / 11 skipped

解除收集期错误后，`pytest tests/` 第一次在 CI 上跑到终点（3.11 与 3.12 两个 job 结果一致）：

```
3 failed, 2275 passed, 11 skipped, 2 subtests passed in 313.98s (0:05:13)   # py3.11
3 failed, 2275 passed, 11 skipped, 2 subtests passed in 621.52s (0:10:21)   # py3.12
```

三条失败，**没有一条是 §10 那些"被回退的修复"**，全部是新暴露的：

### 12.1 `test_qmix_state_index_determinism.py`（2 条）

```
AttributeError: 'QMIXAgent' object has no attribute '_state_index'
subprocess.CalledProcessError: ... from marl.algorithms.qmix import IQLEstimator ...
```

根因：`_state_index` 是 **NumPy 回退实现** `IQLEstimator` 的方法；CI 的全量 job 装了
torch，`IQLEstimator` 指向 torch 版 `QMIXAgent`，压根没有这个方法。

**这条暴露了本工作流自身的一个结构问题**：安全不变量门刻意只装
`numpy + cryptography`（为了让 fail-fast 在几十秒内出结果），于是它跑的是**回退路径**；
而全量 job 装了 torch，跑的是**torch 路径**。同一条断言在两道门里落在不同实现上 ——
这意味着"第一道门绿"不能推出"第二道门绿"。

处理：文件加 `pytestmark = skipif(HAS_TORCH)`，并在 docstring 里写明覆盖分工 ——
回退路径由安全不变量门（无 torch）覆盖，torch 环境下跳过而不是假通过。

### 12.2 `test_f04_round_recovery.py::test_transient_failure_resume_same_txid`（1 条）

```
AssertionError: 'quorum_failed' != 'replicated'
```

根因在**测试自己**的就绪判据：

```python
if sum(x.get('online', False) for x in dc.statuses()['nodes']) >= len(names):
```

判的是"在线节点**个数**"。在 node-1 / node-2 已经在跑的情况下，
`start(names=('node-3',))` 的 `>= 1` **立刻成立** —— 根本不等 node-3 起来就去 propose。
本机（未装 torch，子进程 import 快）恰好赶得上；CI 上装了 torch，
`visualization.distributed_consensus` 的导入要几秒，第二次 propose 只打到 2 个节点，
于是 `quorum_failed`。

处理：改为按 `node` 字段等**指定的这几个节点各自** online，等待预算从 3.6s 放宽到 16s。

> 两条都属「本地绿 ≠ CI 绿」的第三、第四种形态：
> 前者是**同一断言落在不同依赖组合的不同实现上**，后者是**就绪判据的语义写错了**
> （数个数 ≠ 等某人）。前两种（区块签名门缺区块签名、f04 用户 id 硬编码）
> 见 §11.1 与 §11.4。

---

## 验证口径

```
pytest tests/test_security_guard_type_confusion.py \
       tests/test_security_guard*.py tests/test_rfc6979_security.py   # 72 passed
pytest tests/test_nash_verifier_canonical.py tests/test_nash_verifier*.py  # 34 passed
pytest tests/test_qmix_state_index_determinism.py                    # 2 passed
pytest tests/test_mappo_critic_targets.py                            # 3 passed
pytest tests/test_signature_payload_binding.py                       # 13 passed
pytest tests/test_standard_pbft_sybil_gate.py                        # 8 passed
pytest tests/test_failover_heartbeat_semantics.py                    # 8 passed
pytest tests/test_incentive_nonfinite_guard.py                       # 13 passed
pytest tests/ -q                                                     # 1841 passed / 1 failed / 42 skipped
#   唯一 failed = test_deps_importable 缺 torch（本机 shm.dll 加载失败已卸载；CI 会装）
```

## 剩余风险（诚实说明）

- 本次审计是**定向**的（读源码 + 构造判据），不是全量形式化验证；未覆盖的路径不能据此认为安全。
- `network_consensus` 的签名验证依赖 `key_manager` 配置；未配置时默认 fail-closed（拒绝），但**纯连通性测试模式**（`_allow_insecure_vote`）不真验签，仅用于非生产场景。
- MAPPO 的 PyTorch 路径在本机缺 `torch`，相关训练测试在 CI 才完整执行；本次对 Critic 目标的修复用纯 numpy 不变量做了离线回归。
- 第 9 项把非有限值统一按「无有效贡献」记 0，而不是抛异常——这是为了不打断长跑训练，代价是上游的 NaN 不会被当成致命错误。若将来接入生产结算，建议把 WARNING 升级为可选严格模式（类似 `MARL_ECDSA_REQUIRE_KEY_PASSPHRASE` 的开关）。
- 第 8 项修复后，`simulate_byzantine_primary_attack` 仍有 15/20 轮触发切换：拜占庭标记一旦打上就永久生效，没有「节点恢复后重新准入」的路径，而出块轮转每 10 块才换主。这是设计取舍（悲观地把作恶节点永久排除），不是缺陷；但如果论文要报「failover 次数」，应同时给出 `byzantine_events`，否则 15 这个数会被误读成 15 次拜占庭。
- 第 6 项的绑定校验已改为 fail-closed（缺字段即拒绝），因此**不存在**"删字段跳过校验"的旁路；代价是任何依赖裸 `message_hex + signature_hex` 的新调用方会被拒 —— 这是刻意的：「签名包」语义下必须给全字段，纯字节验签请显式用 `ECDSAUtils.verify()`。
- `extra` 现已纳入绑定：签名体里出现、而 package 未声明的键一律拒绝。因此**不要**在签名后又往 package 里塞业务字段（例如把 `message_hex` 之外的东西放进 `extra`），否则会被判为篡改。账本路径（`blockchain.py`）当前不传 `extra`，不受影响。
- 绑定校验**没有**引入「低 s 归一化」，因此 ECDSA 可塑性（`(r, s)` 与 `(r, n-s)` 都合法）仍然存在。当前不影响本链的授权语义（tx_id 由 `agent_id/action_hash/timestamp/nonce/tx_type` 计算，不含签名），但若将来把签名纳入 tx_id，必须同时做低 s 归一化，否则会出现 txid 可变。
