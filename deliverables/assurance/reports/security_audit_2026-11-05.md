# marl-ecdsa 深度审计（第 2 批）修复记录 — security_audit_2026-11-05

- 生成时间：2026-11-05
- 审计人：商汤小浣熊（独立只读审计 → 定向修复）
- 范围：`blockchain/crypto/ecdsa_utils.py`（B1）、`train.py`（A2）
- 方法：源码精读 + 运行时差分复现 + 定向回归测试
- **本报告是本地审计工作副本，未被推送/未提交（本地目录非 git 仓库）**
- 状态：**B1、A2 已修复并验证零回归；A1 待项目所有者定夺**

---

## 0. 重要：B1 定级纠错（诚实更正）

第一轮审计曾把 `ecdsa_utils.verify()` 标为 **HIGH「签名可延展性伪造」**，
并据「本仓 `sign()` 走 RFC6979 产出即低 s 形式」的假设，先实现了「强制低 s」校验。
**该假设被测试与实测双重推翻**，本轮据实证**降级并缩小修复范围**。

### 纠错过程（证据）

1. **强制低 s 导致 11 项回归**：`test_ecdsa / test_signature_payload_binding /
   test_verify_package_field_binding / test_signing_service_contract /
   test_signing_service_hybrid / test_train_identity_wiring / test_dilithium_adapter`
   共 11 个测试失败——全部是**本仓自产签名被自己的 verify 拒绝**。

2. **实测推翻「RFC6979 恒产低 s」假设**：用本仓 `sign()` 对 40 条消息签名，
   高 s(s>n/2) **20 条 / 低 s 20 条**——RFC6979 deterministic signing 约 50%
   概率产出合法的高 s 签名。早期「产出即低 s」的断言是错的。

3. **重估可延展性可利用面**：本仓防重放/去重**不依赖「同一签名只承认一次」**：
   - 防重放靠 `nonce`（`security_guard.check_package`）
   - 消息去重靠内容指纹（`message_protocol`）
   - 区块去重靠 `_dedup`（`blockchain.py`）

   攻击者拿可延展变体 `(r, n−s)` **无法绕过任何门禁**——没有「签名级去重」可绕。

### 结论

- 原定级 **HIGH「可延展性伪造」高估**。ECDSA 可延展性在此**无可利用面**，降级为
  **低（纵深防御 / 理论侧信道，与既有 S1 归一类）**。
- 但 `verify()` 原先对 **r/s 越界签名**（=0 / ≥n）只靠 `InvalidSignature`
  异常兜底，缺显式 fail-closed 边界校验。保留这一层加固（真实、低风险）。

---

## 1. B1（修正版）：`verify()` r/s 越界 fail-closed

**文件**：`blockchain/crypto/ecdsa_utils.py:257-308`

**改动**：新增 `_is_canonical_signature(signature, curve_order)`，在 `verify()`
密码学验签**之前**校验 `0 < s < n`（r 的越界由 cryptography 的 DER 解码/验签兜底）。

**关键设计（据纠错）**：**只挡真正非法的越界值，不强制低 s**——避免拒掉本仓
RFC6979 合法高 s 签名。曲线阶经 `public_key.curve.group_order` 取
（cryptography 50.x 的 `EllipticCurve` 对象无 `.order`/`.domain_parameters`，实测只有 `group_order`）。

**复现/验证（运行时实测）**：

```
合法低s签名 verify : True
合法高s签名 verify : True     ← 修正前会误拒
s=0   非法 verify : False     ← 显式 fail-closed
s>=n  非法 verify : False     ← 显式 fail-closed
```

---

## 2. A2：PyTorch 种子未播种（实验可复现性）

**文件**：`train.py:163-173` ｜ **严重度**：高（可复现性）｜ **类别**：已确认缺陷

**根因**：`MARLBlockchainTrainer.__init__` 只设 `np.random.seed(config.seed)`，
全文无 `torch.manual_seed`。MAPPO 的 Actor/Critic 权重初始化与 Categorical
策略采样走 **torch 全局 RNG**——未播种导致 `--algorithm mappo` 跨次运行
权重/动作序列漂移，**违反论文实验可复现性硬要求**（该仓重可复现）。

**改动**：在 `np.random.seed` 后补：

```python
if HAS_TORCH:                       # 复用 qmix 导入的守卫
    import torch
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
```

**验证**：AST 编译通过；沙箱无 torch 时 `HAS_TORCH=False` 守卫正确 no-op
不崩溃（实测 `import torch` 报 ModuleNotFoundError 时路径不中断）。

---

## 3. A1：MAPPO 损失记账口径（已按最小风险标注，未改行为）

**文件**：`mappo.py:331` ｜ **类别**：口径失真（不影响梯度/学习）

`all_losses.append((actor_loss_sum + value_coef*critic_loss_sum)/n)`，
但实际优化是 actor/critic **独立优化器、独立 backward/step**（`mappo.py:320-325`），
`value_coef` 从未作用于梯度——记录的 loss 是**加权组合、非实际优化目标**。

**本轮处理（据最小风险默认）**：两次决策请求未获用户选择，按可逆默认处理——
**保留返回值不变**（`train.py:350-351` 把它喂给 `record_loss` 落盘为 MAPPO loss
曲线，改返回值会动历史口径），仅在 `mappo.py` 该处补**诚实口径注释**：明确记录的
是「加权组合量、非任一网络的真实损失」，并说明若要对齐优化目标须改为分别记录
actor_loss / critic_loss（会变历史口径，需项目所有者拍板）。

**验证**：`mappo.py` AST 通过；返回值表达式逐字未变；actor_opt/critic_opt 各仍
1 次 `.step()`（梯度路径未触碰）；MAPPO/train 子集 9 passed / 0 failed。

---

## 4. 测试证据

签名链路子集（B1 改动面，含全部曾回归的测试）：
```
152 collected: 140 passed / 12 skipped / 0 failed
（跳过项为 torch 缺失 / 网络环境限制）
```

A2 + MAPPO/train 子集：
```
41 collected: 31 passed / 10 skipped / 0 failed
（test_mappo_r1 的 10 项 skip 为 torch 缺失）
```

全量基线（后台跑完，18m56s）：**2338 passed / 26 failed / 5 error / 30 skipped**。
26 失败 + 5 error **逐条分类后无一落在 B1/A2/A1 改动代码上**，全部既有环境噪音：

| 类别 | 数量 | 根因（与改动无关的证据） |
|------|------|------|
| torch 缺失 | 9（`test_torch_import_contract`×6、`test_deps_importable`、`test_qmix_dual_path`、`test_qmix_state_index`） | 本机 torch 已卸载（`shm.dll` 加载失败，AGENTS.md 审计报告亦记载，CI 才装） |
| Temp 密钥目录被运行时保留 | 5 failed + 5 error（`test_attack_api`、`test_attack_e6`、`test_signing_service_more`、`test_key_manager_boundary`×4） | `CHAT_REFERENCE_PROTECTED: Temp\keys_*` 保留扫描中断 → API 返 500 → `KeyError: 'no_bc'`；不触碰 `verify()` 签名校验 |
| 机器相关路径/匿名检测 | 13（`test_check_submission_anonymity`） | 检测真实路径/邮箱/手机号泄露标记，本机用户路径触发，机器相关 |

**回归确认**：第一版「强制低 s」的 11 个失败在修正后**全部消除**。

---

## 5. 当前状态与待办

- [x] B1（修正版）+ A2 已修复并本地验证零回归
- [ ] A1 损失记账口径：待项目所有者在「拆分记录 actor/critic loss」与
      「仅文档标注」之间定夺
- [ ] 推送：**本地目录非 git 仓库**（无 `.git`），需先 clone/配 remote 才能走
      fork→分支→测试→PR。AGENTS.md 多会话协作规则（push 前 fetch、非快进
      rebase 不 force、HTTPS 不通走 SSH）已在场，但推送属外部副作用，**未擅自执行**。

## 6. 与既有审计报告（security_audit_2026-11-02）的关系

该报告已修过 `ecdsa_utils` 的**签名-载荷解绑**（§6/#6）与 `mappo` 的
**Critic 目标错位**（§5/#5）等 9 处——**与本轮 B1/A2 不重叠**。本轮 B1 是
`verify()` 的**输入边界校验**（新增层），A2 是**种子播种**（`train.py`，
非 `mappo.py`），均为既有 9 处之外的增量发现。
