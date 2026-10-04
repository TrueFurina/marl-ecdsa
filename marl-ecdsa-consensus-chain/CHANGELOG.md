# CHANGELOG
> ⚠️ **历史快照 · 口径已作废（2026-09-28 标注）**
> 本文件写成时的主实验口径为 **n=22 种子/组**（对应 +29.2%、Welch p=0.126 不显著）。该口径**已被后续扩种取代、现已作废**。
> 现行唯一权威口径为 **n=71/组**（`deliverables/number_registry.json` → NR-1 / NR-2）：
> ・末 50 回合 `env_reward`（不含 BC 激励）**+28.17%**，Welch p=0.009524，Cohen d=0.4412，95%CI [0.6476, +4.5761]，检验力≈0.742，**BH-FDR 下显著 / Bonferroni 下不显著**；
> ・全程平均 `env_reward` **+7.92%**，Welch p<1e-10，Cohen d=1.1962，检验力≈1.0。
> **两口径必须同报**，禁单点宣称「激励有效」「强证据」或「证明」。
> **本文件的历史数字一律保留、未作修改**（改历史数字等于伪造历史）；引用其数字前请先对齐登记簿。


> MARL-ECDSA 共识链 — 面向多智能体强化学习的区块链 AI 协同共识机制

> **⚠️ 历史存档说明（2026-09-14 追加）**：本 CHANGELOG 按时间顺序记录历次变更，其中的实验数字（如旧版提升率 +13.4% / +29.6% / +42.2% / +40.4% / +46.4%、p 值、测试数、λ 取值）反映**当时**的配置与口径，**均已退役、不代表现行申报口径、不得作为申报数字引用**。现行权威口径请以竞赛交付物为准：3000 回合收敛验证 env_reward **+29.2%**（n=22，Welch **p=0.126 不显著**，d=0.47）；测试 **1600+ 项全部通过（0 失败）**；Nash 安全裕度 **50%**（λ=0.1）。

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
> 本项目权威口径为 README 所述：n=22 / 3000 回合 / λ=0.1 的 `env_reward`
> （+29.2%，Welch p=0.126，**不显著**）与全程平均合作率（Δ+1.30%，p=0.0022，**显著**）。

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