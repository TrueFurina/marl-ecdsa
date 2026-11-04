# CHANGELOG
> ⚠️ **历史快照 · 口径已作废（2026-09-28 标注）**
> 本文件写成时的主实验口径为 **n=22 种子/组**（对应 +29.2%、Welch p=0.126 不显著）。该口径**已被后续扩种取代、现已作废**。
> 现行唯一权威口径为 **n=71/组**（`deliverables/number_registry.json` → NR-1 / NR-2）：
> ・末 50 回合 `env_reward`（不含 BC 激励）**+28.17%**，Welch p=0.009524，Cohen d=0.4412，95%CI [0.6476, +4.5761]，检验力≈0.742，**BH-FDR 下显著 / Bonferroni 下不显著**；
> ・全程平均 `env_reward` **+7.92%**，Welch p<1e-10，Cohen d=1.1962，检验力≈1.0。
> **两口径必须同报**，禁单点宣称「激励有效」「强证据」或「证明」。
> **【2026-10-18 更新】上节 n=71 口径亦已被 10 月扩种（+30 对，2001-2030）取代**——现行权威口径为 **n=101/组**（NR-129 末50 / NR-134 全程 / NR-135 合作率，三口径 Bonferroni 全显著），详见下方 2026-10-18 指针修正。
> **本文件的历史数字一律保留、未作修改**（改历史数字等于伪造历史）；引用其数字前请先对齐登记簿。


> MARL-ECDSA 共识链 — 面向多智能体强化学习的区块链 AI 协同共识机制

> **⚠️ 历史存档说明（2026-09-14 追加；2026-10-18 指针修正）**：本 CHANGELOG 按时间顺序记录历次变更，其中的实验数字（如旧版提升率 +13.4% / +29.6% / +42.2% / +40.4% / +46.4%、p 值、测试数、λ 取值）反映**当时**的配置与口径，**均已退役、不代表现行申报口径、不得作为申报数字引用**。下一行括号内「env_reward +29.2%（n=22，Welch p=0.126 不显著，d=0.47）」为 9-14 撰写本说明时点的旧引用，**已作废，仅存档**。**现行权威口径（2026-10-18）以 `deliverables/number_registry.json` 为准**：E31/E34 主证据 **n=101/组** —— 末 50 回合 `env_reward` **+25.7%**（Welch p=0.0034，NR-129）、全程 `env_reward` **+7.70%**（p=1.1×10⁻¹⁴，NR-134）、合作率 **+1.92%**（p=1.5×10⁻¹⁴，NR-135），三口径在 Bonferroni/BH-FDR/Holm 下均显著（**新增 30 对种子单独不显著 p=0.169 须同报**；末 50 口径另有独立种子批次符号翻转的稳健性边界，见 NR-192，⛔ 禁只报末 50 +25.7%）；测试口径为下限式「**1600+ 项自动化测试全部通过（0 失败）**」（NR-19）；Nash 安全裕度 **50%**（λ=0.1）。

---

## 2026-11-05 — 承重证据制度化：变异目标 2 → 14，并堵掉探针自身的两条「假绿」通道

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

`scripts/mutation_probe.py` 早就在仓库里，纪律也写得很足（locator 必须唯一定位、
恢复必须校验、报告落盘、未覆盖类别显式声明）。但它只登记了 **2 个**目标
（signing backend 值域、doctor 的 git head 格式）。审计简报 §1–§9 那 9 处安全与
正确性修复、加上 11-04 的 `flush_pending` 缺陷，**一处都没登记**。

工具在、纪律在、**证据不在** —— 那 9 条「已修复」仍然只是一句自述。本节把
它们变成可复跑的证据，并顺手修掉探针自身的两条假绿通道。

### 一、登记 12 个新目标（2 → 14），全部实测承重

每个目标必须同时满足四条：locator 在目标文件里**恰好**命中 1 次；未注入时关联
测试**绿**；注入后**红**；恢复后**逐字节**一致。14/14 实测：

| 目标 | 复原的缺陷 | 未注入 | 注入后 |
|---|---|---|---|
| `security-guard-r-type-normalization` | `r` 不归一 → `123` 与 `"123"` 两个键，k 重用检测被绕过（§1） | 7 绿 | 3 红 / 4 绿 |
| `security-guard-timestamp-normalization` | `timestamp` 非整数 → `abs(now_ms-ts)` 抛 TypeError，畸形包打崩守卫（§2） | 7 绿 | 2 红 / 5 绿 |
| `security-guard-nonce-normalization` | `nonce` 非整数 → `nonce <= last_nonce` 抛 TypeError（§2 第二处） | 7 绿 | 2 红 / 5 绿 |
| `ecdsa-payload-field-binding` | 不重建被签消息 → 复用公开历史签名可伪造任意交易（§6） | 24 绿 | 12 红 / 12 绿 |
| `mappo-critic-target-shape` | `np.repeat(returns,n)[:T]` 与 `v_pred` 错位（§5） | 3 绿 | 1 红 / 2 绿 |
| `qmix-state-index-hash-seed` | 走内建 `hash()` → 受 `PYTHONHASHSEED` 影响（§4） | 2 绿 | 1 红 / 1 绿 |
| `nash-mixed-p-me-formula` | `p_me` 与 `p_opp` 不同公式 → 混合均衡漏报（§3） | 3 绿 | 2 红 / 1 绿 |
| `pbft-self-reported-weight` | 吃成员自报权重（`weight=999` 撬阈值）（§7） | 8 绿 | 1 红 / 7 绿 |
| `failover-unknown-heartbeat` | 缺省 0 判超时 → 每轮虚假视图切换（§8） | 27 绿 | 5 红 / 22 绿 |
| `incentive-nan-clamp` | NaN 被钳成满分 → 算崩的拿最高激励（§9） | 13 绿 | 7 红 / 6 绿 |
| `world-state-nonfinite-reject` | NaN 写进积分 → 永久污染（§9 第二层） | 13 绿 | 2 红 / 11 绿 |
| `action-recorder-flush-clear` | `clear()` 嵌在 `bc_node` 判断内 → stub 模式不排空（11-04） | 34 绿 | 2 红 / 32 绿 |

原有两条也一并重跑：`signing-backend-value-domain` 22 绿 → 13 红；
`doctor-git-head-format` 3 绿 → 2 红。汇总 **14/14 目标探测且承重**。

### 二、探针自身有两条「假绿」通道（都已堵）

1. **pytest 类完全没有基线检查**。原实现对 `kind=pytest` 只跑一次「注入后」，
   退出码非 0 即判承重。于是一个**本来就红**的关联测试文件，能让任何变异体
   都"通过" —— 变异在红基线上不携带任何信息。现改为：基线必须绿，注入后必须红。

2. **`rc != 0` 不等于「有用例失败」**。pytest 的 2=被中断、3=内部错误、4=用法错、
   5=一条都没收集，全都是非零。原实现会把「args 路径写错 / 一条没收集」读成
   「守卫承重」—— **把门禁噪音当成证据**。现只认 rc=1，其余一律 fail-closed 记
   FAIL 并把退出码含义打进报告。

顺带把「目标文件 git 干净」的判定与 `tests/mutation_targets.json` 的静态校验
合并成一套规则 `validate_targets()`：探针拒跑的登记，测试也必须判红，不再有
「探针说不行、测试说没事」的两套真值。

### 三、恢复的是文本，不是字节（行尾）

原实现用 `Path.read_text()` / `write_text()`，默认做 universal newline 转换：
Windows 上把 LF 文件**整份**写成 CRLF。注入确实被"恢复"了，但恢复的是文本，
工作树留下整文件行尾翻转的假改动（`git status` 报 M，`git diff` 却是空的）。

现改为 `read_bytes` / `write_bytes`，显式记录原文行尾并在写回时还原，恢复校验
也改成**字节比对**（`path.read_bytes() == raw_before`）。报告里因此多两个字段：
`line_ending`（CRLF/LF）与 `original_sha256`（字节级）。实测：目标文件里既有 CRLF
（`security_guard.py`）也有 LF，14 个目标恢复后 `git status` 均无输出。

### 四、登记表本身进 CI：`tests/test_mutation_targets_registry.py`

探针是**手动**工具（刻意不进必需链），所以登记表漂移只会安静地烂掉 —— locator
指向的行被改掉之后，要等到下次有人手动跑才喊。新增 13 条静态守卫，把「探针拒跑
的条件」提前成 CI 里的红/绿：

* 必填字段齐全、id 唯一、`check.kind` 合法、关联测试文件真实存在；
* locator **恰好**命中 1 次（0 次 = 漂移，多次 = 歧义）；
* locator 与 mutation 不得相同（相同 = 空变异）；
* `AUDIT_INVARIANT_IDS`：12 个审计目标不得从登记表里消失（防止静默删证据）；
* 行尾往返自检（LF / CRLF 各一条，注入+还原的完整往返也要字节一致）。

七条负向自检防退化：目标文件不存在 / locator 命中 2 次 / 命中 0 次 / 空变异 /
关联测试不存在 / 未知 kind / 空登记表 —— 每一种都必须被判红。实测两种真实退化：
把 locator 改成漂移写法 → 3 条红；删掉 `action-recorder-flush-clear` → 1 条红
（命中 `AUDIT_INVARIANT_IDS`）。

### 五、CI 加第三道门：无 torch 回退档全量套件

审计简报 §12.1 记过一个结构问题：`qmix.py` 是**一个模块两套实现**，由模块级
`HAS_TORCH` 选择。全量 job 装了 torch ⇒ 2200+ 条用例全部落在 torch 实现上；
回退实现只有「安全不变量」那 10 个文件覆盖。于是「第一道门绿」推不出
「回退路径绿」，而回退路径**恰恰是 torch 装不上时真实会跑的那条**。

新增 `test-fallback` job：只从 `requirements.txt` 摘掉 torch 一行，其余依赖与全量
job 完全一致 —— 两个 job 的差异变量只有「torch 在不在」。两道保险：

* 一步 `find_spec('torch') is None` 断言：若依赖解析把 torch 作为传递依赖拖进来，
  本 job 会退化成全量 job 的复制品（假绿），断言直接拦下；
* 唯一豁免 `test_deps_importable` 用 `--deselect` 显式点名（它的契约就是
  "requirements 里每个依赖都能 import"，本 job 刻意不装 torch，此环境不适用）。
  不改软断言 —— 改软等于让它在全量 job 里也失去意义。

本机（Windows / py3.12 / 无 torch / 干净 tarball）实测该档：**2249 通过 / 3 失败 /
20 跳过**，三条失败全部是可解释的环境差异（tarball 无 `.git` 导致
`test_gate_source_is_machine_independent` 红、缺 torch 导致 `test_deps_importable`
红、Windows 文件锁导致 `test_next_nr` 并发用例红）；前两条在 CI 里分别由 `.git`
与 `--deselect` 消失，第三条只在 Windows 出现。

### 实测小结

* 探针：14/14 承重，基线全绿，恢复全字节一致；单次全跑约 10 秒。
* 新增守卫：13 条全绿；两种真实退化分别打红 3 条 / 1 条。
* 全量套件（干净 tarball，本机无 torch）：2249 通过 / 3 失败 / 20 跳过，
  失败集合与上一轮完全一致（未引入新红）。
* **没有**宣称「测试有覆盖率保证」：变异只证明**这 12 个点**上有用例真的盯着，
  未登记的地方仍然是未知。未覆盖类别已在 `UNCOVERED_NOTE` 里更新并随报告输出。

---

## 2026-11-04（续五）— 16 条「零断言」用例：其中两条各自掩盖了一个真实问题

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

用 AST 扫全仓 `tests/test_*.py`（2211 条 `test_*` 函数），找出**函数体内没有任何
断言**的用例：**16 条**。它们永远 PASS —— 被测行为完全错了也不会红。

这类用例比「被 skip」更危险：skip 至少会在报告里留下痕迹，零断言用例
**看起来是通过的**。而其中两条各自精确地描述了一个真实问题却从未失败过。

### 一、`flush_pending()` 在 stub 模式下从不回收缓冲（真实缺陷，已修）

`marl/integration/action_recorder.py`：

```python
if self.bc_node is not None and self._pending_actions:   # 修复前
    ...
    self._pending_actions.clear()                        # clear 嵌在 if 之内
```

`record_action()` 无条件 `append`，而 `flush_pending()` 只在有 `bc_node` 时才清 ——
stub 模式（`bc_node=None`）下 flush 是**空操作**，缓冲随回合数单调增长。实测：

| 场景 | flush 前 | flush 后 |
|---|---|---|
| 有 `bc_node` | 24 | **0** |
| stub（`bc_node=None`） | 24 | **24** |
| stub 跑 20 回合 ×100 步 | — | **2000（从不回收）** |

同一个类里的 `batch_upload()` 是把 `clear()` 放在 `bc_node` 判断**之外**的 ——
两个「排空缓冲」的方法处置不一致，这本身就是缺陷的旁证。

调用方 `Bridge.on_episode_end()` 的编排第 7 步还留着一句
`self._recorder._pending_actions.clear()` 兜底 —— 那正是这条缺陷的痕迹。
而仓库里正有 P1-4「替代直接操作 `_` 前缀属性」的整改号召，一旦有人把第 7 步
当冗余删掉，泄漏就会露出来。

修复：把 `clear()` 移出 `bc_node` 判断，与 `batch_upload()` 对齐；stub 模式下
记一条 debug 说明「无可上链节点，仅排空缓冲」。

### 二、`test_corrupted_priv_key_regenerates`：写错的是 docstring，不是实现

该用例名为「…regenerates」、docstring 写「新实例应能检测损坏并重新生成」，
但**既没有调用被测方法，也没有任何断言** —— 只留了准备代码（造一个损坏的
私钥文件），然后就结束了。

实测真实行为（探针，非推断）：抛 `ValueError`，且

* 损坏的私钥文件**不被改写**（不留半成品）
* 公钥文件**不被改写**（链上身份仍可读）
* 重复调用仍以同样方式失败（不会第二次「自愈」）

这是正确的 **fail-closed**：静默重新生成会换掉密钥对，而公钥可能已上链，
历史签名将全部失配，且用户不会知道自己被换了钥。所以改的是用例名与断言，
不改实现 —— 现更名为 `test_corrupted_priv_key_fails_closed`，把上面四条钉住。

### 三、其余 14 条补上可失败的断言

把 `*_noop` / `*_no_crash` 从「不抛异常」升级为「可判定无副作用」：

| 文件 | 用例 | 补的断言 |
|---|---|---|
| `test_world_state.py` | `add_score_unregistered_noop` | 不得凭空建条目；`get_all_scores()=={}`；读分仍 `KeyError` |
| `test_world_state.py` | `betrayal_unregistered_noop` | 不建积分/行为档案；权重 0.0；摘要 `{}` |
| `test_world_state_behavior.py` | `record_action_unregistered_noop` | 不建行为档案；`_behaviors` 仍恰好 2 项 |
| `test_world_state_behavior.py` | `record_betrayal_unregistered_noop` | 背叛计数 0；无档案 |
| `test_world_state_behavior.py` | `record_cooperation_unregistered_noop` | 不建积分条目；他人计数不受影响 |
| `test_action_recorder_boundary.py` | `flush_without_bc_noop` → `_drains_buffer` | 原断言 `len(...) >= 0` 对 list **恒真**；改为排空 + 不计数 |
| `test_dashboard_startup.py` | `run_server_flask_unavailable` | 断言记录了 error 日志（静默 return 会让「未装 Flask」表现为无响应） |
| `test_f11_process_and_lock.py` | `file_lock_acquire_release_ok` | 锁文件被建出；两次都真的走完上下文管理器 |
| `test_p2p_consensus_network.py` | `update_weights_unstarted_noop` | `nodes` 为空；`get_weights()=={}` |
| `test_p2p_node_msgs.py` | `broadcast_no_peers_no_crash` | 广播后 `_connections` 仍为空 |
| `test_plot_helpers.py` | `empty_no_crash` | 空数据仍产出非空图（契约是"能出图"） |
| `test_plot_results.py` | `empty_leaderboard_no_crash` | 无数据时**不**写空图 |
| `test_signing_service_boundary.py` | `verify_episode_none_bc_no_crash` | 验签/失败计数均不增长 |
| `test_signing_service_more.py` | `verify_no_bc_returns` | 同上 |

顺带修掉一处**假断言**：`assert len(ar._pending_actions) >= 0  # 不崩溃即可`
—— 对 list 恒真，任何实现都能过。

### 四、新增守卫 `tests/test_no_assertion_free_tests.py`

AST 扫描全仓 `test_*`（含 `async def`），要求函数体内至少有一种断言形态：
`assert` / `raise` / 名字以 `assert` 开头的调用（`self.assertEqual` 等）/
`pytest.raises|fail|warns|approx|deprecated_call`。

刻意**不拦弱断言**（如对 `len()` 恒真的 `assert x >= 0`）—— 那需要按表达式推断
恒真性，误报率高，属另一个族。

三条自检防退化：

1. 植入一条只有赋值的用例 → 必须被命中
2. 6 种合法断言形态 → 不得误报
3. `async def` 用例 → 必须纳入扫描

外加两项结构性检查：

* **分母自检**：扫到的用例数必须 ≥ 2000（当前 2211）；低于即说明 `rglob` 或
  判据退化，守卫在空转而不是在保护
* **双向对账**：`ALLOWED` 里每条都必须仍是一条真实存在的无断言用例；
  过期条目（用例已补断言/改名/删除）会报错 —— 否则将来同名的空用例被静默放过

例外仅 1 条：`test_deps_scripts.py::test_deps_importable`，理由写进 `ALLOWED`
—— 它的契约就是「import 不抛 ImportError」，写 `assert True` 只是把空转伪装成断言。

### 五、实测

* `marl/integration/action_recorder.py`：stub 模式 flush 后缓冲 24 → **0**；
  2000 步累积从 2000 → **0**；有 `bc_node` 路径行为不变（`_tx_count` 仍 24）
* 受影响的 9 个测试文件：**81 passed**
* 守卫自身：**4 passed**
* 全仓零断言用例：**16 → 1**（剩余 1 条为显式例外）
* 变异验证：
  - `flush_pending`：还原缺陷 → 2 条断言红；删掉 `clear()` → 3 条红
  - 守卫：清空 `ALLOWED` / 登记幽灵例外 / 判据恒 False / 扫描根为空 /
    真实用例摘掉断言 —— **5/5 命中**，且各自打到对应分支；
    分母自检单独验证（空根 + 空 `ALLOWED` → 「只扫到 0 条」）

---

## 2026-11-04（续四）— 一个模块两套实现：回退分支在 CI 上从未被执行

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

`marl/algorithms/qmix.py` 是**一个模块、两套实现**，由模块级 `HAS_TORCH` 选择：
有 torch 走 `QMIXAgent` / `VDNMixer` / 混合网络，无 torch 走纯 Q 表的 IQL 回退。

覆盖被环境劈成两半，而且**两半互不相交**：

| 环境 | 执行哪半 | 另半 |
|---|---|---|
| CI（`ubuntu-latest`，装了 torch） | PyTorch 分支 | 回退分支**一行不跑** |
| 开发机（常无 torch） | 回退分支 | PyTorch 分支**一行不跑** |

于是回退实现里的任何回归，**CI 全绿也发现不了**，只会在某台无 torch 的机器上炸。

`tests/test_torch_import_contract.py` 已经用假 `torch` 包验证过「回退分支能被
`import`」，但**import 成功 ≠ 能干活**。本节补的是"能干活"这一层。

### 一、新增 `tests/test_qmix_dual_path_contract.py`

用同一个会抛 `ModuleNotFoundError(name='torch')` 的假包遮蔽真 torch，
在**任何环境**（包括 CI）强制走回退分支，然后跑一遍真实训练动作：
构造 trainer → `init_hidden` → `get_actions` → `store_episode` ×2 → `train_step`。

同一段调用代码也用于驱动 PyTorch 分支。四条用例：

1. **回退分支可被驱动**（任何环境都跑）——并断言 `has_torch is False`，
   证明假包确实生效；否则它在重复测 PyTorch 路径，回退分支仍然零覆盖。
2. **PyTorch 分支可被驱动**（`importorskip("torch")`）。
3. **两条路径逐项对齐**：先断言本次真的拿到 `{False, True}` 两个取值
   （否则字段比对退化成"同一份实现自己比自己"），再比契约字段。
4. **对断言本身的自检**：注入 7 种违规（`train_step` 恒返回 None / 动作个数不符 /
   越界 / 非整数 / 三个公开名字被删），每一种都必须被拦下；外加合规基线必须通过。

### 二、只比契约，不比数值

模块自己在缺 torch 时就会警告「结果口径与 PyTorch 版不同，禁止跨实现混比」。
因此对齐的是**调用契约**：动作个数 = `n_agents`、动作是整数、取值在
`[0, n_actions)`、数据足够时 `train_step` 必须产出损失（而不是 `None`）、
`QMIXAgent` / `QMIXMixer` / `QMIXTrainer` 三个名字都在。

### 三、mappo 不需要同样的处理

`marl/algorithms/mappo.py` 的回退分支是**显式占位**：

```python
class MAPPOTrainer:  # pragma: no cover
    def __init__(self, *a, **k):
        raise ImportError("MAPPO 需要 PyTorch")
```

它在构造时就 fail-closed，不存在"悄悄换成另一套实现"的路径，因此没有两半覆盖问题。

### 四、一处自我更正

初次用 AST 比对 `QMIXTrainer.__init__`，得出「PyTorch 版 13 个参数 / 回退版 5 个，
接口不兼容」——**这个判断是错的**。两边的 `__init__` 与 `train_step` 都带 `**kwargs`
（回退版写作 `train_step(self, **kwargs)`），多出来的参数会被吸收，不会 `TypeError`。

真实差异只有两处，且都不影响位置调用：
- `store_episode` 的形参名不同（`episode_data` / `data`）—— 只有**关键字调用**会破；
- `train_step` 回退版是 `**kwargs`，**位置传参**（`train_step(64)`）会 `TypeError`，
  必须写 `train_step(batch_size=64)`。

新用例统一用关键字形式调用，正是为了同时兼容两侧。

### 五、实测

- 本机（Windows / py3.12 / 无 torch）：`2 passed, 2 skipped`。
- 干净 tarball 全量：`3 failed, 2245 passed, 20 skipped`。
  与上一轮基线（`2243 passed / 18 skipped`）相比 **+2 passed / +2 skipped**，
  精确对应新增的 4 条用例；失败集合不变，仍是三条环境差异
  （tarball 无 `.git` 的 tracked 门禁 / 本机缺 torch / Windows 文件锁）。
- PyTorch 分支的两条用例只在 CI 上执行 —— 这正是本次要修的那个缺口本身。

---

## 2026-11-04（续三）— 同名副本「为什么不构成缺陷」落成代码

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

前两节拆掉了「重复执行」与「假覆盖」。这一节处理第三种浪费：**看起来有守卫，
其实没人判**。`tests/test_module_resolution_contract.py` 把 5 对同名 basename 冻结
在 `FROZEN_DUPLICATES` 里，但检视后发现，**只有 `analyze_all_experiments` 那一对
被真正校验等价**；另外 4 对「为什么不需要等价」只写在 commit message 与讨论里。

后果是具体的：新增第 6 对副本时，最省力的过测方式是往白名单加一行（T1 立刻变绿），
而「这一对要不要等价」这个判断可以完全不做 —— 守卫在，判定不在。

### 一、处置登记表：三种 kind，每种都有既有断言背书

`DUPLICATE_DISPOSITION` 为 5 对逐一登记处置方式与实测依据，kind 只有三种：

| kind | 含义 | 背书断言 |
|---|---|---|
| `equivalent` | 两份必须语义等价 | T2 按本表**参数化**逐条校验（不再硬编码唯一一对） |
| `explicit_path` | 两份有意不同，消费者必须显式注入目录 | T4 |
| `orphan_unused` | 无任何消费者，歧义面为零 | T5 断言其保持无人引用 |

5 对的实际登记：`analyze_all_experiments` → equivalent；`run_all` → explicit_path；
`analyze_deep_tests` / `deep_test_driver` / `deep_test_orchestrator` → orphan_unused。

### 二、T7 交叉校验：四张表不得互相矛盾

新增 `test_every_duplicate_basename_declares_a_consistent_disposition`，六项检查：

1. 与 `FROZEN_DUPLICATES` 双向对账（新增副本不能只加白名单、也不能登记幽灵名）；
2. kind 必须在允许集合内；
3. `reason` 必须写实测依据，不接受占位符（短于 20 字符即失败）；
4. kind 蕴含的「有无消费者」必须与 `FROZEN_TEST_IMPORTERS` 一致
   （`orphan_unused` 不得有消费者；`equivalent`/`explicit_path` 必须有）；
5. `equivalent` 必须与 `SEMANTIC_EQUIVALENT_PAIR` 一一对应（T3 只读后者，
   多余的 `equivalent` 会被静默跳过）；
6. `orphan_unused` 必须与 T5 实际扫描的 `ORPHAN_BASENAMES` 一致
   （否则「声明为孤儿」只是个标签，没人断言它保持无人引用）。

外加一条防退化自检：T2 的参数表不得为空 —— 表一空，参数化用例整体消失，
核心断言静默失效。

### 三、变异验证：10/10 命中，且各自打到对应分支

不是"改一处然后看红"，而是逐条注错，确认每条变异触发的是**它自己**那条问题
条目（避免所有变异都被同一句兜底吞掉）：

| 变异 | 触发 |
|---|---|
| 删掉 `run_all` 登记 | 报 missing |
| 孤儿副本被登记为有消费者 | 报 kind 与消费者矛盾 |
| 孤儿改成 `equivalent` | 三重冲突：无消费者 + 等价表不一致 + 孤儿表脱节 |
| `run_all` 改成 `orphan_unused` | 消费者矛盾 + 孤儿表不一致 |
| `reason` 写 `TODO` | 报过短 |
| kind 写非法值 | 报不在允许集合 |
| 清空 T2 参数表 | 报核心断言静默失效 |
| 多登记一个不存在的名字 | 报 extra |
| `ORPHAN_BASENAMES` 被截断 | 报与登记不一致 |
| 两份等价副本出现真实漂移 | T2 用 unified diff 定位到具体行 |

### 四、顺手推翻两处旧记录（自我更正）

- 早前记的「`run_all` 两份相差 **531 行**」是 **diff 输出行数**，不是文件行数。
  实际两份分别是 ablation **263 行** / benchmark **359 行**。
- 5 对副本字节数已逐个复核：`analyze_all_experiments` 两份 **25183 B 逐字节相同**、
  `analyze_deep_tests` 两份 **12277 B 逐字节相同**；`deep_test_driver` 128 / 119 行、
  `deep_test_orchestrator` 126 / 118 行（漂移存在但无消费者，见上表 orphan_unused）。

回归：`tests/test_module_resolution_contract.py` **11 passed**（原 10 条，+1 条 T7；
T2 由 1 条硬编码改为按表参数化）。

---

## 2026-11-04（续二）— 六条覆盖被「顺手 skip」掩盖：连带修掉一处真实口径漂移

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

上一节清掉的是「重复执行」，这一节处理另一类浪费：**假的覆盖**。
`@pytest.mark.skip(reason=...)` 不带条件，等于永久放弃——它不会自己活过来，
也没人会被提醒。全仓当时恰好有 6 处，而且**共用同一个 reason 字符串**。

### 一、6 处无条件 skip 的背后是一处真实漂移

`d9e701c8`「sync 源码对齐 V29 新基线（口径 n=101/2183 + 新版前端）」改了根副本
`analyze_all_experiments.py` 的 `_REGISTRY_FALLBACK`（n=71 → n=101），但漏了
`scripts/legacy/analysis/` 下那份。两份副本于是语义漂移：

| 编号 | 根副本（与登记簿镜像 `declared` 一致） | legacy 副本（旧口径） |
|---|---|---|
| NR-1 | 25.75% / p=0.003348 / d=0.4179 / n_a=101 | 28.17% / p=0.009524 / d=0.4412 / **n_a=71** |
| NR-2 | 7.70% / p=1.142e-14 / d=1.1749 / n_a=101 | 7.92% / p=5.02e-11 / d=1.1962 / **n_a=71** |
| NR-3 | 1.92% / p=1.504e-14 / d=1.1691 / n_a=101 | 1.95% / p=7.28e-11 / d=1.1858 / **n_a=71** |

`test_live_copy_is_semantically_identical_to_its_legacy_sibling` 因此变红。
处置方式不是修数据，而是把 6 条用例一起标了 skip —— 其中 **5 条与漂移毫无关系**。

证据链（用 API 逐版取文件核对，非推断）：

| 时点 | 根副本 | legacy 副本 | 该测试状态 |
|---|---|---|---|
| `0997c829`（10-04 源码入库） | n=71 | n=71 | 两份等价 → 文件内 **0 个 skip** |
| `d9e701c8`（11-03 V29 sync） | n=101 | n=71 | 漂移 → 6 条无条件 skip |

### 二、先实测再改，不靠推断

写了个**运行时摘除 skip marker** 的探针插件（`.agents` 外的一次性脚本，不进仓库），
6 条一起跑：

- **5 条通过**：README 双语存在性、README 无真实仓库链接、门禁自扫源码零泄漏、
  同名 basename 冻结清单、两个消费者解析到同一份；
- **1 条失败**：就是上面那条副本等价性，失败信息把三行漂移原样打出来了。

所以「这 6 条都跑不了」是错的 —— 只有 1 条真跑不了，另外 5 条是连坐的。

### 三、修法与两处刻意不做

1. legacy 副本三行兜底值同步为 n=101，与根副本、与 `number_registry.json` 镜像
   里 NR-1/2/3 的 `declared` **三方一致**。两份现在逐字节相同。
2. 摘掉 6 处 skip 装饰器，每处留一行注释指明原因与出处（`d9e701c8`）。

刻意不做：**不改成薄转发**（`from analyze_all_experiments import *`）。legacy 那份的
`BASE = Path(__file__).parent / 'results'` 依赖自身位置，转发会让它读错目录 —— 那是把一个
「数据不一致」换成「路径不一致」，更隐蔽。

### 四、f11 那条也在跑一个不存在的实现

`tests/test_f11_grandchild_cleanup.py` 原先 `exec_module` 一个本仓库**没有**的
`launcher/supervisor.py`（那边才叫 `_make_job/_assign_job/_close_job`）。模块级加载失败
属**收集期错误**，会让整份套件中断，于是降级为整模块 skip —— **实际覆盖为零**，而且
无条件 skip 永远不会自己恢复。真实实现自 2026-11-02 起就在
`visualization/business_service._win_job_kill_on_close`，由 `business_service.py:248`
对每个训练子进程调用。现改为直接打真实实现。

这条以前从未执行过，所以不敢只看它变绿。做了负对照：

| 场景 | 直接子进程 | 孙进程 |
|---|---|---|
| 有 Job Object（正测：关闭句柄） | 死亡 | **死亡** |
| 仅 terminate 子进程（负对照：无 Job） | 死亡 | **仍存活（孤儿）** |

两个方向都验证到了 —— 断言不是空转，`_alive()` 探测也没有恒真/恒假。
负对照同时证明**病灶真实存在**：这正是 F11 要防的孤儿。

`_close_job()` 是**测试侧**工具，不是生产接口：生产代码刻意不提供「关 Job」的入口，
它把句柄挂在 `_JOB_HANDLES` 上持有到本进程退出 —— 正因如此 Web 崩溃时内核才会连带杀。
测试手动关句柄，就是为了构造「持句柄的进程退出」这一触发条件。

### 五、加守卫：无条件 skip 装饰器归零

`tests/test_no_unconditional_skip.py`：AST 扫 `@pytest.mark.skip(...)` 装饰器，必须为 0。

- **不拦** `skipif` / `importorskip`：条件满足时会自己恢复执行，是正当用法；
- **不拦**函数体内的 `pytest.skip()`：通常前面有 `if <条件>:`（缺 dilithium 后端、
  缺证据 JSON、非 Windows），这类不是放弃覆盖而是「本环境不适用」；
- 确需永久放弃，登记进 `ALLOWED` 并写明**为什么不能写成 skipif** —— 多数情况下
  写到这里理由就不成立了。

带两条自检：植入一个假 skip 必须被命中（防匹配写错退化成空转）；`skipif` /
`importorskip` 必须不被误报（防逼人绕过守卫）。

### 六、实测

本机（Windows / py3.12 / 无 torch），同配置跑全量：

| 项 | 改动前 | 改动后 | 差 |
|---|---|---|---|
| 收集 | 2260 | 2263 | **+3**（新增守卫 3 条） |
| 通过 | 2233 | **2243** | **+10** = +6（F15）+1（f11）+3（守卫） |
| 跳过 | 25 | **18** | **−7** = −6（F15）−1（f11 模块级 skip，Windows 上转为执行） |
| 失败 | 2 | 2 | 0 |

两条失败仍是**既有环境红灯**，与本次无关：`test_deps_importable`（缺 torch）、
`test_next_nr::test_threaded_no_duplicate`（Windows `PermissionError`，文件锁）。

**本次不宣称耗时变化**。300.30s 与上一节 445.92s 不可比 —— 同一天内同一条基线
曾出现 556.20s 与 866.36s（1.56×），这台机器的热状态漂移远大于本节改动的量级。

剩余 18 个 skip 逐条核对，全部为**条件性且理由具体**：缺 torch（qmix 2 + mappo 10 +
torch_import_contract 2）、缺 Dilithium 后端（2）、仓库外脚本缺失（1）、容器环境
派生不出用户名（1）、反向 skip「后端可用时回落路径不适用」（1）、
hybrid 契约另测（1）。

未做：NR-19 仍未重新基线化（需配套 junit 证据，属独立流程）。

---

## 2026-11-04（续）— 套件提速 48.5%：三处重复执行被去掉，断言一条未改

> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

三条线索都指向同一类浪费：**同一段确定性计算被多条用例各算了一遍**。

### 一、同一条用例被收集 3 遍（省 118.98s）

`tests/test_v12_consensus_invariants.py` 原先写的是：

```python
from tests.test_v11_epoch_view import ConsensusV11
class ConsensusV12(ConsensusV11):
```

pytest 的 `python_classes` 里的 `Test*` 前缀过滤**只对普通类生效**，
`unittest.TestCase` 子类**无条件收集**。于是同一条用例跑了 3 遍：
本模块命名空间里的 `ConsensusV11` 一遍、继承它的 `ConsensusV12` 一遍、
`test_v11_epoch_view.py` 自身一遍。`-v` 输出里 pytest 自己就标着
`tests/test_v12_consensus_invariants.py::ConsensusV11::test_... <- tests/test_v11_epoch_view.py`。

实测三条 `test_epoch_reconfiguration_old_certificate` 分别为
27.18s / 27.11s / 27.08s，四条用例的重复部分合计 **118.98s**。而
`visualization.distributed_consensus` 是无状态模块、`setUp` 每次新建临时目录，
重复执行**零新增覆盖**。

修法：把夹具抽成**不继承 TestCase** 的 `_ConsensusHarness`，两个类各自只继承夹具、
只保留定义在自己模块里的用例。两个文件合计收集数 16 → 8。

配套守卫 `tests/test_no_testcase_leaks.py`：AST 静态扫描「import 了别处的 TestCase
子类」与「继承了别处的 TestCase 子类」，并带一条自检用例，确保守卫本身不会退化成
永远通过的空转。

### 二、活代码共演化同一段计算跑 3 遍（省 219.34s）

`TestLiveCoevolution` 三条 live 用例各调一次 `_run_mini`，其中前两条参数**完全相同**
（2 轮 × 2 种子）——第二条纯属重算。

改之前先做了两项实测，不靠推断：

| 检验 | 结论 |
|---|---|
| 同参数（2 轮×2 种子）连跑两遍 | 逐轮指标逐位相同 |
| 3 轮运行的前 2 轮 vs 直接跑 2 轮 | 逐位相同 |

后者成立的理由：`run_round(r, benign, held, attack_cum)` 只依赖 `r` 与累计攻击轨迹，
`r<2` 时 `attack_cum` 只含前两轮；`N_ROUNDS` 只有 `main()` 在用，不参与单轮计算。

据此改为在 `scope="module"` 的 `mini_rounds` 夹具里跑一次 3 轮，2 轮的用例取
`rounds[:2]`。

### 三、代理训练重复 3 次（省 79.29s）

`train_ml_defender()` 与 `train_surrogate()` 都是确定性的，实测：

* 前者连跑两次，`classifier` / `train_accuracy` / `heldout_accuracy` 逐位相同，
  且在 441 个网格点上两份判信的判定 **0 差异**；
* 后者 `SURROGATE_SEED` 是常量、分类器 `random_state=42`，两次调用
  `agreement` 0.9625 / `trusted_cells` 575 / `target` / `target_fidelity` 全等。

改为 `ml_judge` / `surrogate` 两个 module 级夹具。`sweep()` 与 `arm_s2()` 只读
`surrogate["trusted"]`，不改该字典，跨用例共享无副作用。

### 实测（同条件 A/B：两棵树紧邻先后跑完）

| | 基线（pristine main `989785b2`） | 改动后 |
|---|---|---|
| 耗时 | 866.36s（14:26） | **445.92s（7:25）** |
| passed | 2239 | 2233 |
| failed | 2 | 2 |
| skipped | 25 | 25 |
| 收集 | 2266 | 2260 |

* 提速 **420.44s / 48.5%**（1.94×）
* 条数守恒：2266 − 8（去掉 8 次重复执行）+ 2（新增守卫两条）= 2260；passed 同差 −6
* 两条 failed 与基线完全相同，都是既有环境红灯：`test_deps_importable`（本机缺 torch）、
  `test_next_nr::test_threaded_no_duplicate`（Windows 文件锁，`PermissionError 13`）

> **为什么必须 A/B**：上午同一条基线是 556.20s，下午同一棵树跑出 866.36s（机器热状态
> 不同，1.56×）。拿上午那 556s 当基线，会得出「提速约 20%」的错误结论。

> **顺带推翻一次我自己的误判**：中途看到日志停在 `test_next_nr.py .....` 十一分钟不动，
> 一度判为「用例挂死」并据此杀掉了一轮测量。实际原因是 pytest 输出重定向到文件时
> **块缓冲**，日志整体滞后；加 `PYTHONUNBUFFERED=1` 与 `-u` 后可见一直在正常推进，
> 单独跑该文件 0.98s 就结束了。教训：**看进度必须关缓冲**，否则「没输出」会被误读成
> 「没进展」。

---

## 2026-11-04 — 合并后两处收敛：无 torch 也能跑套件 / C4 档案随快照跨重启


> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

### 一、`pytest tests/` 在无 torch 的机器上从「0 条执行」恢复为全量收集

两处**收集期**错误：`tests/test_qmix.py`、`tests/test_algorithm_family_contract.py`
在模块顶层 `from marl.algorithms.qmix import ReplayBuffer, VDNMixer`，而这两个名字
只在 `qmix.py` 的 PyTorch 分支（`if HAS_TORCH:`）里定义 —— NumPy 回退分支按设计
不提供它们（回退实现是纯 Q 表的 IQL，没有回放缓存、也没有混合器）。

缺 torch 时 import 直接抛 ImportError，pytest 记成收集期错误，实测
`Interrupted: 2 errors during collection`，**2259 条一条都不跑**。CI 因为装了 torch
所以一直是绿的——这层盲区一直没人看见。

修法与 F11 同源：**不造假桩**（假桩会让这两个文件在回退路径上绿得毫无意义，
正属本项目禁止的假通过），缺依赖就整模块 skip 并把理由写进报告。修后
`2259 tests collected`，零 error。

> 顺带纠正一处旧记录：`security_audit_2026-11-02.md` §11.7 里写的"已 `--ignore`
> 这两个文件"是当时的手段，需要人工记得加参数；现在是文件自己 skip，不再依赖
> 调用者记忆。

### 二、C4 淘汰档案在快照往返中丢失（真实缺陷，含两重后果）

`to_snapshot()` 只导出 `r_registry`，**没有导出** `_r_evicted_digests` /
`_r_evicted`。而 C4 修复（淘汰即入摘要档案）恰恰依赖后者。实测（探针与本机复现）：

| 时点 | `evicted_digest_count` | `is_degraded` | 重用被淘汰的 `r` |
|---|---|---|---|
| 重启前 | 2 | `True` | 拦下 |
| 快照往返后 | **0** | **`False`** | **放行** |

两层后果：① 上轮 C4 修复只在**进程存活期内**有效，重启后缺口原样回来；
② 重启后系统**自称「未降级」**，把"已滚过内存窗口"这件事瞒掉——比缺口本身更难发现。

修复：快照补入 `r_evicted` / `r_evicted_digests`；`from_snapshot` 对缺失键退化为
空档案（旧状态文件仍能加载，不阻断启动）。修后同一探针：`digests=2`、
`degraded=True`、重用仍被拦。

同时把两条边界写进代码注释，防止后人"优化"掉：
- `_r_evicted_digests` **刻意不设上限**。淘汰是攻击者可廉价触发的，档案一旦有界，
  攻击者继续灌就能把目标 agent 的旧摘要挤出去，等于用极低成本重置 C4 检测。
- `reset_agent()` **刻意不清档案**。`r` 被用第二次无论隔多久都是私钥可能泄露的
  硬事实，不该随"重新准入"一起忘掉。

### 三、测试

- 新增 `test_security_guard_persistence.py` 三条：档案随快照往返存活（正面钉住）、
  旧快照缺字段可加载（向后兼容）、走真实状态文件
  `SigningService.save_state → 新实例 load_state` 的端到端。
- `test_combination_attacks.py::test_c4_residual_archive_is_in_memory_only` 的
  docstring 同步改写：残留边界由「重启即遗忘」收窄为「裸进程之间不共享档案」，
  断言本身不动（仍成立，且现在与正面用例互为对照）。
- `scripts/security/_probe_combination_attacks.py` 的 C4 段补测快照往返，
  并把 `survives_snapshot_roundtrip` 等字段写进证据 JSON —— 证据要能证明新能力，
  不能只在 note 里写一句"已修"。

---

## 2026-11-03（续）— CI 归位后首轮实测：修 8 处、撤回 1 处误判

> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。取证与逐条判据见
> `deliverables/assurance/reports/security_audit_2026-11-02.md` §11。

### 一、第一道门转绿：区块签名

CI 首次运行 `77 passed / 1 failed`，失败项是
`test_signature_payload_binding.py::test_block_with_genuine_tx_accepted` ——
账本自 2026-11-02 起有「出块者签名 + `state_root` 可重算」门，而测试塞的是
`state_root="0"*64` 且不签名的合成区块。`_make_block()` 改走真实出块流程
（`构造 → finalize() → sign_block()`）。顺带修掉 `test_block_with_forged_tx_rejected`
的**假通过**（原先它拦的是「区块没签名」，不是「伪造交易」）。修后 **78 passed**。

### 二、撤回一处误判

`cw_pbft_failover` 的"恢复"实际是把 main 更好的实现（显式 `UNKNOWN`）改回较差的
（预填表、一律 `HEALTHY`），已撤回，与 main 逐字节一致。
连带修掉 main 上一对**自相矛盾**的测试（见上），两份心跳测试并存 **27 passed**。

### 三、真修复：C4 组合攻击缺口关闭

`security_guard` 的淘汰摘要档案让「FIFO 挤出后重用 `r`」被拦下；测试按该文件自述的
约定翻转断言，并新增残留边界测试（档案仅进程内）。探针与证据同步重算：
**4/4 绕过 → 3/4**，C4 转 ✅ 拦截。

### 四、main 上三处既有红灯（CI 归位才看见）

1. `scripts/smoke_test_e2e.py` 的 P0-1 断言 `λ == 0.1`：P2-E 自适应 λ 后取值为
   `(0.05, 0.15)` 带内，实测 `0.10231058578630006`。改为钉「`λ_base=0.1` 的传参通路 +
   运行时在自适应带内」。
2. `tests/test_f04_web_wiring.py` 把通道键写死 `'1'`：全量套件里更早用例注册过用户后
   新用户 id 就不是 1，4 条假红（**单独跑是 5 passed**）。改为从 `session['uid']` 读。
3. `structure_guard.py --all` 报根级历史文件（先 13 个 V18–V27 等说明文档，CI 上又报
   2 个训练结果 json）：登记为**存量冻结豁免**（常量 `LEGACY_ROOT_FILES`，只减不增），
   每次运行打印提醒，不静默腐烂。搬目录会打断 README/thesis 的相对引用，以及
   `visualization/dashboard.py` 等 4 处「按裸文件名从项目根读取」的调用。
   > 那 2 个 json 是第二次才发现的：本地核对用 `git ls-files`，而它们
   > **tracked 却命中 `.gitignore`**，在临时目录 `git add -A` 时被忽略 ——
   > 本地"13 个全过"，CI 报"多 2 个"。核对仓库文件清单要以远端 tree 为准。

### 五、`test_f11_grandchild_cleanup.py` 的收集期错误

依赖 `launcher/supervisor.py`，该模块不在本仓库，模块级 `exec_module` 抛
`FileNotFoundError` → 整个 `pytest tests/` 中断（其余 2000+ 条一条没跑）。
不删用例，缺模块时整模块 skip。

### 六、门禁自身的两个 bug

- `caliber_check.py` 的 `_RE_TESTS` 不支持千分位，`2,183 passed` 被读成 `183`，
  把等于下限的表述判成假红；现接受 `1,234` 与 `1234`。
- `.agents/skills/test-gate/SKILL.md` 里把历史基线数字写成 1632（低于 NR-19 下限 2183），
  改为指向登记簿，不再另抄一份数字。
  顺带一个反讽：本节初稿为了说明这件事，引用了那个数字加 "passed" 的原文写法，
  结果被 `caliber_check --strict` 当成"新声明"判为漂移 —— 门禁是对的，
  说明这类引用只能写数字、不能带 `passed` 后缀。

### 七、全量套件第一次在 CI 上跑完：3 failed / 2275 passed / 11 skipped

3.11 与 3.12 两个 job 结果一致。三条失败都不是"被回退的修复"，而是新暴露的：

1. `test_qmix_state_index_determinism.py` 2 条 —— `_state_index` 是 **NumPy 回退**实现的
   方法，CI 全量 job 装了 torch，`IQLEstimator` 指向 torch 版 `QMIXAgent`，没有该方法。
   这暴露了工作流自身的结构问题：安全不变量门只装 `numpy+cryptography`（跑回退路径），
   全量 job 装了 torch（跑 torch 路径），**同一断言在两道门里落在不同实现上**。
   处理：文件加 `skipif(HAS_TORCH)` 并写明覆盖分工。
2. `test_f04_round_recovery.py::test_transient_failure_resume_same_txid` —— 就绪判据
   写错了：数「在线节点**个数**」而不是等「**指定的**节点」。
   `start(names=('node-3',))` 在 node-1/2 已跑时 `>= 1` 立刻成立，根本没等 node-3。
   本机（无 torch，导入快）恰好赶上；CI 上导入慢几秒就稳定失败。
   处理：按 `node` 字段精确等待，预算 3.6s → 16s。

修后复跑：**2276 passed / 13 skipped / 0 failed**（py3.12，5m59s）。
条数守恒：2275+3+11 = 2276+0+13 = 2289。

随后暴露的是**门禁自身的误判**：本文件为了说明 SKILL.md 里那个过期数字，引用了原写法
（数字 + `passed`），被 `caliber_check --strict` 当成"新声明"判为漂移。门禁是对的 ——
这类引用只能写数字，不能带 `passed` 后缀。

### 实测（本机，非对外口径）

| 项 | 结果 |
|---|---|
| 安全不变量门（10 个文件） | 78 passed |
| 全量 `tests/` | 2227 passed / 2 failed / 22 skipped（合计 2251） |
| 2 条 failed | `test_deps_importable`（本机缺 torch）＋`test_next_nr::test_threaded_no_duplicate`（Windows 文件锁，main 上同样红） |
| 未计入 | `test_qmix.py`、`test_algorithm_family_contract.py`（本机装不上 torch，已 `--ignore`） |

> 这些是**本机实测**，不是对外口径。用例总数已由 NR-19 的 2192 增长到 2251+，
> 登记簿需重新基线化（属独立流程，本次不动）。

---

## 2026-11-03 — 恢复被「源码对齐」提交静默回退的 6 处修复 + CI 归位

> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

### 事故

`d9e701c`（"sync: 源码对齐 V29 新基线"）改动 258 个文件，其中 10 个源文件被整份
覆盖成更旧的基线，把 2026-11-01/11-02 的修复一并带走：

- `SecurityGuard`：k 重用检测回到 fail-open（缺 `r` 直接放行、淘汰静默遗忘、
  无字段归一）——k 重用可直接推导私钥；
- `mappo`：Critic 回归目标回到 `np.repeat(returns, n_agents)[:T]`（与逐时间步
  `v_pred` 错位）；
- `qmix`：NumPy 回退回到内建 `hash()`（受 `PYTHONHASHSEED` 影响，复跑不一致）；
- `nash_verifier`：`p_me` 回到 `(M[1,0]-M[1,1])/denom`（鹰鸽/猎鹿的混合均衡漏报）；
- `standard_pbft`：女巫门控还在，但自报 `weight` 纠偏被删（真实成员可自带 999）；
- ~~`cw_pbft_failover`：心跳表恒空 → 从未发心跳的主节点永不被判超时（死主不替换）~~
  **此条判断错误，已撤回**：main 现实现是「空表 + 对从未心跳的节点返回 `UNKNOWN`」，
  比 11-02 那版（预填整表、一律 `HEALTHY`）更严 —— 缺信息不等于健康。详见
  `security_audit_2026-11-02.md` §11.2；
- `incentive_contract` / `world_state` / `settlement_coordinator`：三处 NaN 护栏
  全被删 → NaN 被钳成满分、并永久污染账本积分。

仓库里 6 个回归锁文件都还在、断言完好，实测 **19 failed + 1 collection error**。

### 为什么没被拦住

`CI - Test Suite` 一直写在 `marl-ecdsa-consensus-chain/.github/workflows/ci.yml`。
GitHub Actions 只扫描**仓库根**的 `.github/workflows/`，子目录不会被注册 ——
该工作流**一次都没运行过**（`/actions/workflows` 只有 build-binaries 与 pages）。

### 恢复

6 个提交逐条恢复，**以 main 当前版本为底座做定点补丁**，保留 `d9e701c` 的正当增量
（QMIX 的 S9 登记注释、Nash 的 F16 `top_tier_bonus=10.0` 与 λ 边界表述、
`clear_episode_rewards`、`get_consensus_weight`、P1-12 注释）。
逐文件对照与提交清单见 `deliverables/assurance/reports/security_audit_2026-11-02.md` §10。

### 加固（不是回退）

- `verify_action_package`：把"缺字段就跳过绑定校验"改成 **fail-closed** ——
  首版允许把 `agent_id/action/timestamp/nonce` 删掉来整段跳过校验，而
  `cooperation_detector.filter_verified_packages()` 吃的正是外部传入的包；
- `extra` 纳入载荷绑定（原实现没有用例覆盖），并允许 JSON 数值写法差异
  （`1000` vs `1000.0`）以免误杀同值 float 时间戳；
- `test_signature_payload_binding.py` 里"裸字节包仍然通过"的断言是错的
  （把 fail-open 当成了不误杀），更正为断言拒绝，并新增 4 条。

### CI 归位

新增仓库根 `.github/workflows/ci.yml`（`defaults.run.working-directory` 指向子目录），
安全不变量单拆成 fail-fast job（只装 numpy + cryptography），全量套件 `needs` 它。
子目录那份保留不删，加抬头注明"不会被执⾏、可执行版在哪"。

### 审计简报的哈希修正

汇总表原先引用的 8 个哈希（`e7dfa59` 等）在远端**全部 404**，已换成真实存在的
`12212a9` / `44b3962` / `e98d5ca` / `bd56b87` / `7e20a94` / `5d509f9` /
`b07953d` / `2e30262`；P1-11 那轮为 `8bc432b`。

---

## v4.1 (2026-07-10) — 当前版本

### Bug 修复
- **`block.py` logger 未定义修复**：`sign_block()` 方法中 `logger` 未导入导致 `NameError`，已在模块级添加 `import logging` 和 `logger = logging.getLogger(__name__)`
- **`smoke_test_e2e.py` 浮点精度断言修复**：`bridge.lambda_weight == 0.3` 因自适应 λ 计算产生浮点误差而失败，改为 `abs(x - 0.3) < 0.001`
- **`qmix.py` NumPy 回退训练器增强**：原 `train_step()` 返回 `None` 无训练能力，现实现简易 Q 表 Q-learning 训练（含 TD-error 计算、ε 衰减、回放缓存采样）

### 命名修正
- **`QMIXAgent` → `IQLEstimator`**：主类名改为反映实际算法（IQL 独立 Q-learning），`QMIXAgent` 保留为向后兼容别名。PyTorch 路径和 NumPy 回退路径均已统一
- **`main.py` banner 修正**：`QMIX CTDE 多智能体强化学习` → `IQL 独立 Q-learning（CTDE 框架）`
- **`config.json` 算法标注修正**：`algorithm: "QMIX (CTDE)"` → `"IQL (Independent Q-learning, CTDE 框架)"`

### 文档修正
- **README §4 实验数据**：替换为 `fair_comparison_report.json` 实际数据（env_reward 公平口径，BC 提升 +13.4%），删除无法验证的 5 种子 t-test 表，增加消融实验 5 种子数据，增加 Nash 均衡定理证明
- **README §三 核心创新点**：CARS 共识塑形从核心创新点表中移除（实验显示负效果）。CARS 在文件结构中标注为「探索性方向」
- **README §8.5 CARS 整节删除**：因实验验证 CARS 显著降低性能（η=0.10 时 env_reward 降低 -24.2%, p=0.01），不再作为独立特性介绍
- **README §8.4 算法说明**：明确 IQL 为主算法，QMIX/VDN 为可选扩展
- **`delivery/00_集成交付汇总.md`**：数据基线从 V2 Bug 数据（+29.6%）更新为 V3.7 公平口径数据（+13.4%），X9 冲突裁决同步更新
- **`delivery/01_material_digest.md`、`02_research_report.md`、`03_高层架构设计.md`**：添加数据版本说明，标注历史数据来源于 V2 早期版本，竞赛提交以 V3.7 数据为准

### 质检报告
- 新增 `质检报告_MARL-ECDSA共识链_20260710.md`，记录 28 层深度分析结果

### 新增功能
- **真实 Merkle 树**：`block.py` 新增 `compute_merkle_root()` 和 `compute_state_root()`，用交易哈希的 Merkle 根替换 `"s"*64` 占位符。`Block.finalize()` 自动计算真实 state_root
- **私钥安全加固**：`Block.sign_block()` 改为接收 `KeyManager` 句柄和 `agent_id`，不再以 hex 字符串传递私钥。调用方 `bc_integration.py` 已同步更新
- **CARS Potential 函数修复**：将空间势能从"到最近路标的距离"改为"到分配路标的距离"，消除与 `env_reward`（`-dist_to_own`）的系统性冲突。势能权重从 0.7/0.3 调整为 0.5/0.5 减少震荡
- **多智能体规模实验脚本**：新增 `run_scale_experiment.py`，支持 3/5/10/20 agents 自动对比，多种子验证，自动生成报告
- **实验报告自动生成流水线**：新增 `run_experiment_pipeline.py`，一键运行规模实验 + 消融实验 + 生成综合报告 Markdown
- **`delivery/04~07` 数据版本标注**：为系统设计、UserStory、部署设计、安全设计四份文档添加数据版本说明
- **`train.py` 超大函数重构**：将 200 行的 `_run_episode()` 拆分为 6 个独立子方法，单方法不超过 30 行
- **全项目 17 个超大函数重构**：累计消除 2,907 行超大函数，拆分为 97 个小于 40 行的方法。
- **P2P 网络协议测试**：新增 `tests/test_p2p_network.py`，10 个测试覆盖消息协议编解码、所有消息类型、CW-PBFT 共识消息格式
- **PPT 数据更新**：`scripts/generate_ppt.py` 中 V2 旧数据（-63.91/-45.02/+29.6%）更新为 V3.7 公平口径数据（-35.11/-30.41/+13.4%），测试数 188→312

### 实验数据
> ⚠️ **以下为历史 V2 实验数据（1000 回合 / 5 种子 / λ=0.5），已作废，不得引用为结论。**
> 该配置样本量过小，且 λ 取值非竞赛配置（竞赛为 λ=0.1）；其 total_reward 数值
> （如 +42.2% / +40.4%）**含 BC 激励加成**，会系统性放大效应。
> 本项目权威口径【撰写本节时点，2026-09 前后】为 README 所述：n=22 / 3000 回合 / λ=0.1 的 `env_reward`
> （+29.2%，Welch p=0.126，**不显著**）与全程平均合作率（Δ+1.30%，p=0.0022，**显著**）。
> **【2026-10-18 标注】上句为当时时点引用，n=22 口径已作废**——现行权威口径见文件头部（n=101/组，NR-129/134/135）。

- **3 agents 1000回合实验**（5种子，λ=0.5）：total_reward 提升 **+42.2%**（-53.56→-30.96），env_reward 提升 +9.5%（-53.56→-48.46），合作率 50.73%→54.55%
- **5 agents 1000回合实验**（5种子，λ=0.5）：total_reward 提升 **+40.4%**（-76.34→-45.53），env_reward 提升 +4.3%（-76.34→-73.03），合作率 68.44%→69.61%
- **竞赛答辩PPT**：已生成 12 页幻灯片，保存至 `competition_submission/竞赛答辩_MARL-ECDSA共识链.pptx`
- **答辩Q&A文档**：新增 `答辩QA准备_MARL-ECDSA共识链.md`，覆盖 13 个高频问题

---

## v4.0 (2025-06) — 上一版本

### 核心变更
- **奖励 Bug 修复**：bc_score 从"加到每一步（25× 放大）"改为"均匀分配到每一步（÷25）"
- **环境奖励增强**：加入 `coverage_bonus=+2.0`，拉大学会/未学会差距
- **λ 参数基准**：竞赛基准 λ=0.1，env_reward 公平口径下 BC 提升 +13.4%
- **IQL 名实一致**：类名保留 QMIXAgent（历史原因），实际训练为 IQL 独立 TD-error
- **统计检验**：5 种子独立验证，Welch's t-test p < 0.001
- **消融实验**：`--ablate-*` 三开关（security/consensus/incentive），支持模块化验证

### 新增模块
- 合作检测服务 `CooperationDetector`（从 `BlockchainMARLBridge` 拆分）
- 结算协调服务 `SettlementCoordinator`（从 `BlockchainMARLBridge` 拆分）
- 签名服务 `SigningService`（从 `BlockchainMARLBridge` 拆分）
- 行为记录器 `ActionRecorder`（从 `BlockchainMARLBridge` 拆分）
- 共识塑形奖励 `ConsensusRewardShaper`（CARS 近似策略不变性）
- 自适应 λ 控制器 `AdaptiveLambdaController`（BC→MARL 双向反馈）
- Nash 均衡验证器 `NashEquilibriumVerifier`

### 修复
- 奖励分配 Bug：bc_score 放大 25 倍问题
- `SelfishAgentWrapper`：`int(3*0.3)=0` 导致自私智能体数为 0 的 Bug
- 合作检测阈值：从 50% 放宽到 30%，避免中性行为误判为背叛
- 环境奖励归一化：映射区间修正为 `[-1.5, 2.0] → [0.0, 1.0]`
- WorldState 公共接口：`_identities` 直接访问改为 `get_agent_summary()` 等公共方法
- 惩罚阈值：从硬编码改为 `config.json` 集中管理（`penalty_thresholds` 字段）
- SecurityGuard nonce 基线同步：`register_nonce_baseline()` 和 `reset_all_nonces()`
- 矿池条目上限：`MAX_R_ENTRIES=1000` 防止内存泄漏
- 创世区块：使用固定时间戳 0，保证跨运行确定性

### 实验数据
- **三模式对比**（5 种子 × 3 模式 × 1000 回合）：
  - bc_marl: avg_reward **-31.0 ± 1.4** / coop_rate 54.4%
  - pure_marl: avg_reward -52.2 ± 0.9 / coop_rate 51.4%
  - selfish: avg_reward -51.5 ± 1.4 / coop_rate 34.9%
- **统计显著性**：bc vs pure p < 0.001 ✓✓✓

---

## v3.0 (2025-03) — 已弃用

### 核心变更
- λ=0.05 实验，bc_marl 退化至 -86.15，合作率 42.6%
- 激励太弱导致合作崩溃

### 教训
- `lambda_weight` 至少 0.1，不可随意降低
- 纯负奖励环境 gamma 不能太高（>0.9 导致 Q 值发散）

---

## v2.0 (2025-03) — 已弃用（奖励 Bug）

### 核心变更
- 6 个 QMIX 致命 Bug 修复
- Dashboard v3.5（Flask + Chart.js，7 标签页）
- bc_integration v2 完整流水线（ECDSA 签名→SecurityGuard→Transaction→Block→CW-PBFT→链式追加）
- P2P 网络共识模块（3 节点 15 轮 / 4 节点 8 轮 100% 成功率）
- CW-PBFT 共识引擎（fast_consensus / simulated_consensus 两种模式）

### 实验数据
- 1000 回合，λ=0.1：
  - pure_marl avg=-63.91
  - bc_marl avg=-45.02（BC 提升 **+29.6%**）
  - selfish avg=-50.53
- 已知问题：bc_score 被错误地加到每一步（25× 放大），奖励口径非公平

### 修复
- 单向连接拓扑修复
- 副本节点 PREPARE 投票修复
- 主节点先加票再广播修复
- 严格校验 `current_block_hash`
- 每轮 reset 后 `clear_msg_cache()`
- 处理上轮残留 COMMITTED 状态先 reset

---

## v1.0 (2025-03) — 已弃用

### 核心变更
- MVP 完成，34 个源文件，端到端流水线跑通
- ECDSA 签名验证核心（secp256r1 + RFC 6979）
- SimpleSpreadEnv 环境（NumPy 自实现）
- QMIX 算法框架（CTDE 架构）
- 区块链账本核心（Transaction/Block/Blockchain）
- 网络共识模块（P2PConsensusNetwork）
- 基础可视化面板（Flask + Chart.js）
- 智能合约三件套（身份/激励/惩罚）

---

## 版本演进

| 版本 | 时间 | 状态 | 核心特点 |
|------|------|------|---------|
| v1.0 | 2025-03 | 弃用 | MVP 完成，34 源文件，端到端流水线 |
| v2.0 | 2025-03 | 弃用（奖励 Bug） | 6 个 Bug 修复，Dashboard v3.5，P2P 网络 |
| v3.0 | 2025-03 | 弃用（λ 过低） | λ=0.05 实验，合作崩溃 |
| **v4.0** | **2025-06** | **✅ 当前使用** | **奖励修复 + coverage_bonus + λ=0.1 + 5 种子验证** |

---

## 格式说明

本 CHANGELOG 遵循 [Keep a Changelog](https://keepachangelog.com/) 规范，版本号遵循 [Semantic Versioning](https://semver.org/)。