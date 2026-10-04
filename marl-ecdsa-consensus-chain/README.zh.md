> 📌 **口径**：主实验口径为 **n=71 种子/组**（权威：`deliverables/number_registry.json` → NR-1 / NR-2）。
> 末 50 回合 `env_reward` **+28.17%**（Welch p=0.0095，**BH-FDR 下显著 / Bonferroni 下不显著**）；全程平均 `env_reward` **+7.92%**（p<1e-10）。**两口径必须同报**。

<!-- README.zh.md (中文版) | English: README.md -->
# MARL-ECDSA 共识链

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-1600%2B%20passed-brightgreen)](tests/)
[![Consensus](https://img.shields.io/badge/Consensus-CW--PBFT-00d4ff)](blockchain/consensus/cw_pbft.py)

**English**: [README.md](README.md)

> 面向多智能体强化学习（MARL）的区块链 AI 协同共识机制：基于 ECDSA 安全身份与贡献加权共识（CW-PBFT），并给出严格优势策略的参数边界推导与数值验证。
>
> **CCF 第五届区块链技术与创新应用竞赛 · 技术创新赛道** | 版本 v4.1

---

## 📖 目录

1. [项目亮点](#-项目亮点)
2. [系统架构](#-系统架构)
3. [核心创新](#-核心创新)
4. [快速开始](#-快速开始)
5. [实验结果](#-实验结果)
6. [仓库结构](#-仓库结构)
7. [测试](#-测试)
8. [CI / 自动化](#-ci--自动化)
9. [引用](#-引用)
10. [开源协议](#-开源协议)

---

## ✨ 项目亮点

- **区块链 ↔ MARL 深度闭环**：区块链激励塑造 MARL 奖励（BC→MARL），MARL 行为数据反向生成贡献度权重（MARL→BC）。
- **ECDSA 无 CA 身份体系**：链上公钥注册 + SecurityGuard 三阶防护（k 值重用检测 / nonce 防重放 / 时间戳校验）。
- **贡献加权共识 CW-PBFT**：Shapley 风格权重推导（三条公理）+ 动态主节点故障切换；支持 `cw_pbft` / `standard_pbft` / `fast` 三模式切换。
- **严格优势策略的参数边界推导与数值验证**：严格证明 + 参数边界 + 50% 安全裕度；**后量子 ML-DSA-44（CRYSTALS-Dilithium2）适配器已实现**（`dilithium-py` 纯 Python 后端，真实密钥生成/签名/验签；签名 2420 字节 / 公钥 1312 字节 / 私钥 2560 字节；冷跑均值签名 44.64ms / 验签 10.40ms，暖跑中位签名 17.04ms / 验签 4.15ms，抖动极大仅可写双值；比 ECDSA 慢约 2 个数量级），零 API 变更切换 + ECDSA+Dilithium 混合 AND 模式。**尚未接入主链路 SigningService（默认签名链路仍为 ECDSA），系统整体暂不具备抗量子能力。**
- **自研 Gossip 动态节点发现**：基于 asyncio，针对 MARL 场景优化。
- **全链路密码学可审计**：签名 → 防护 → 交易 → 区块 → 共识。
- **严谨实验体系**：消融矩阵 + λ 敏感度 + 多种子统计，**按诚实口径呈现**（头号指标：n=71 种子/组，末 50 回合 +28.17%，Welch p=0.0095 —— BH-FDR 显著/Bonferroni 不显著，须与全程口径 +7.92%（p<1e-10）同报；详见[实验结果](#-实验结果)）。

---

## 🏗 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        应用层                                  │
│   MARL 训练（IQL / QMIX）· Web 可视化面板 · 攻防演示          │
├──────────────────────────────────────────────────────────────┤
│                        智能合约层                              │
│   身份合约 · 激励合约 · 惩罚合约                               │
├──────────────────────────────────────────────────────────────┤
│                        共识层                                  │
│   CW-PBFT（加权）· 标准 PBFT · 快速共识 · 故障切换            │
├──────────────────────────────────────────────────────────────┤
│                      网络与密码学层                            │
│   P2P（asyncio TCP）· Gossip 发现 · ECDSA · SecurityGuard     │
└──────────────────────────────────────────────────────────────┘
```

数据流：`ECDSA 签名 → SecurityGuard 校验 → 交易 → 区块 → CW-PBFT 共识 → 链式追加`

---


## 🛡 威胁模型与故障边界（诚实声明）

| 层 | 覆盖范围 | 成功判据 |
|---|---|---|
| 签名层攻击 | ECDSA + SecurityGuard（k 值重用 / 重放 / 时间戳 / 观测伪造 / 消息篡改 / 长程 / 女巫）—— **六类 100% 拦截** | 密码学校验 |
| 省略/崩溃故障 | 共识实验覆盖（主节点被标记不健康→视图切换） | 加权法定人数可达性（n ≥ 2f+1） |
| **矛盾投票 / 任意拜占庭** | **超出当前模拟器范围，列为 future work** | 未建模 |

> 说明：本仓库中无定语的「拜占庭」指**受控的省略/崩溃故障**（节点被静默丢弃或停止投票），**不**指任意拜占庭行为（如矛盾投票/双重提案）。任意拜占庭的安全界（n ≥ 3f+1）**不**作声称。

## 🔑 核心创新

| 维度 | 同类已知项目 | 本项目 |
|---|---|---|
| 区块链 ↔ MARL 双向赋能 | ❌ 无或弱耦合 | ✅ 深度闭环 |
| ECDSA 无 CA 身份 | ❌ 无或用 CA | ✅ 链上注册 + 三阶防护 |
| 贡献加权共识 | ❌ 等权 PBFT / PoS | ✅ CW-PBFT（Shapley 公理 + 故障切换） |
| Nash 均衡分析 | ❌ 无 | ✅ 参数边界推导 + 数值验证（非机器可验证的形式化证明） |
| 后量子兼容（ML-DSA-44 / Dilithium2） | ❌ 无 | ✅ 适配器已实现（`dilithium-py` 纯 Python 后端；签名 2420B / 公钥 1312B / 私钥 2560B；冷跑均值签名 44.64ms / 验签 10.40ms，暖跑中位签名 17.04ms / 验签 4.15ms；混合 AND 模式）；**尚未接入主链路 SigningService（默认链路仍为 ECDSA）** |
| Gossip 动态发现 | ⚠ libp2p 仅通用 | ✅ 自研 + asyncio + MARL 优化 |
| 全链路密码学可审计 | ❌ 无 | ✅ 签名→防护→交易→区块→共识 |
| 消融 + λ + 多种子统计 | ⚠ 部分 | ✅ 完整矩阵，诚实口径报告 |

---

## 🚀 快速开始

```bash
# 1. 安装依赖（Python 3.11+）
pip install -r requirements.txt
# 如需精确可复现（锁定本机实测版本），改用:
#   pip install -r requirements.lock.txt

# 生成或加载私钥前必须设置（程序无内置回退口令）：
# PowerShell: $env:MARL_ECDSA_KEY_PASSPHRASE = "请替换为强口令"
export MARL_ECDSA_KEY_PASSPHRASE="请替换为强口令"

# 2. 运行全量测试（1600+ 项自动化测试全部通过（0 失败））
python -m pytest tests/ -q

# 3. 运行训练实验（pure / bc / selfish）
python main.py --mode bc_marl --n_episodes 200

# 4. 启动交互式 Web 可视化面板
python -c "from visualization.dashboard import start_dashboard; start_dashboard()"
# 打开 http://127.0.0.1:9090

# 5. 运行攻防演示（6 类签名层攻击：观测伪造 / 消息篡改 / 重放 / 女巫·Sybil / k 值重用 / 长程）
python scripts/legacy/analysis/attack_defense_demo.py

# 6. 一键复现（安装 → 50 回合冒烟训练 → 关键测试 → verify_numbers）
#    幂等且可断点续跑，失败重跑即从断点继续。
python scripts/one_click_reproduce.py
```

### 多共识模式切换

在 `config.json` 中设置 `consensus_mode`：`cw_pbft`（默认）/ `standard_pbft` / `fast`。

---

## 📊 实验结果

**头号指标（诚实口径）**：3000 回合充分收敛后，BC-MARL 相比 Pure-MARL 的**纯环境奖励（`env_reward`，不含 BC 激励）**提升 **+28.17%**。该结果基于**每组 n=71 个独立随机种子**；Welch **p=0.0095 → BH-FDR 显著 / Bonferroni 校正后不显著**，Cohen's **d=0.4412**（小到中等效应）。效应方向稳定为正，但在此样本量下差异**BH-FDR 显著 / Bonferroni 校正后不显著**，我们如实呈现。

| 模式 | env_reward 后50回合（均值 ± 标准差） | 合作率 后50回合（均值 ± 标准差） | 种子数 | Welch p |
|---|---|---|---|---|
| **BC-MARL** | **-6.66 ± 6.04** | 69.4% ± 2.7% | 71 | （基准） |
| Pure-MARL | -9.27 ± 5.79 | 69.5% ± 3.0% | 71 | 0.0095（BH-FDR 显著 / Bonferroni 不显著） |

- **BC vs Pure（`env_reward`）**：相对提升 +28.17%，**n=71，p=0.0095 —— 方向一致且 BH-FDR 显著 / Bonferroni 校正后不显著**（种子方差 sd≈5.5 限制了检验力）。
- **历史对照口径已作废**：早期版本曾引用 V3.7（500 回合，未收敛）与 V2（1000 回合，含 BC 激励）两个对照口径的数值。二者均**未收敛或口径不统一**（含 BC 激励的 `total_reward` 与竞赛统一的纯环境奖励 `env_reward` 不可比），**已作废、不再引用**；口径登记见 `number_registry.json`。
- **全程平均合作率 —— 唯一统计显著的正向结果**：3000 回合全程平均，BC 组 **0.6246 ± 0.0094** vs Pure 组 **0.6127 ± 0.0107**（每组 n=71），即 **+0.0119（+1.95%），Welch p<0.0001，Cohen d=1.19** —— **显著且为大效应**。⚠️ 此口径（全程平均）与头号指标的"后 50 回合"口径**不同，禁止混用**（后 50 回合口径下两组几乎相同：差 0.0016、p=0.739）。
- **抗背叛**：`avg_betrayal_rate` 在**全部 142 次运行中恒为 0.000**（71 种子 × 2 模式，各 3000 回合）；对照 `selfish` 模式约 0.35。BC 激励/惩罚设计可避免背叛崩溃。
- **CW-PBFT vs PBFT —— 优势的适用边界（如实报告）**：在**已把故障先验编码进权重**的合成权重下（展宽比 R≈8），CW-PBFT 在 40% 省略故障（⚠ 早期文档曾写作"40% 拜占庭"，属口径错误——本实现故障节点从不投恶意票、不做 equivocation）时仍达 97–99%，而标准 PBFT 归零。但**早期 5 种子 × 2000 轮 PoC（已降级为溯源）**表明：当权重为**均匀分布（R=1）**或由**真实 MARL 贡献度**导出（**R≈1.007**）时，CW-PBFT 与标准 PBFT **完全等价**。即**加权投票本身不提供额外容错**——安全条件为 `b < n/(2R+1)`，R≈1.007 时退化为经典 `n/3`。所有「CW-PBFT 优于标准 PBFT」的共识成功率增益均来自**受控权重展宽配置（R≈15）**；在真实 MARL 贡献度权重（R≈1.01）下，贡献度加权与标准 PBFT **逐 seed 完全相同**（NR-39~44 verdict=IDENTICAL），本工作**不宣称**贡献度加权带来容错性能提升。
- **攻击防御**：**6 类**签名层攻击（观测伪造 / 消息篡改 / 重放 / 女巫·Sybil / k 值重用 / 长程）**100% 拦截**（见 `attack_defense_report.json` 与批量统计 `results/attack_defense_batch_report.json`）；主节点故障场景由 failover 测试套件单独覆盖（标记驱动模拟，未注入真实矛盾提案/equivocation）。

> **项目定位**：MARL-ECDSA 共识链的价值主张是 **信任增强** —— 拜占庭容错共识、密码学身份锚定、六类签名层攻击 100% 拦截（观测伪造/消息篡改/重放/女巫·Sybil/k 值重用/长程）+ 主节点故障 failover 测试通过（标记驱动模拟，未注入真实矛盾提案）、激励公平可验证，而非强化学习性能优化。BC 对环境奖励的增益为 **BH-FDR 显著 / Bonferroni 校正后不显著**（须与全程口径同报），我们如实报告。激励机制的**设计目标**是塑造协作，而全程合作率的提升在两种口径下均**统计显著**（末 50 与全程 p<0.0001、d=1.19）。**CW-PBFT 的容错优势同样有明确适用边界**（见上：R 判据，真实贡献度下无增益）。

---

## 📁 仓库结构

```
marl-ecdsa-consensus-chain/
├── blockchain/
│   ├── consensus/    # CW-PBFT、标准 PBFT、快速共识、故障切换、工厂
│   ├── crypto/       # ECDSA、SecurityGuard、密钥管理、Dilithium 适配器
│   ├── contracts/    # 身份 / 激励 / 惩罚合约
│   ├── ledger/       # 区块、区块链、世界状态
│   └── network/      # P2P、Gossip、消息协议
├── marl/
│   ├── algorithms/   # QMIX 等
│   ├── envs/         # SimpleSpread 环境
│   └── integration/  # 桥接、自私智能体、合作检测、自适应 λ
├── visualization/    # Flask 可视化面板（攻防演示、共识动画）
├── scripts/          # export_dataset.py、benchmark、ablation、一键启动脚本
├── tests/            # 144 个测试模块（1600+ 项自动化测试全部通过（0 失败））
```

---

## 🧪 测试

- **1600+ 项自动化测试全部通过（0 失败）**，覆盖 144 个测试模块：共识、密码学安全（RFC 6979、k 值重用、重放）、区块链、MARL 集成、P2P 网络、Dashboard 攻防 API。
- 静态检查：`python -m compileall -q blockchain/ marl/ visualization/`。

---

## 🤖 CI / 自动化

| 工作流 | 触发 | 用途 |
|---|---|---|
| `ci.yml` | push / PR | 跑全量测试（py3.11/3.12） |

> 本仓库**不含任何定时提交 / 自动提交工作流**，也不含任何活动量刷取（activity farming）自动化。

---

## 📖 引用

```bibtex
@misc{marl-ecdsa-consensus-chain,
  title  = {MARL-ECDSA Consensus Chain: Blockchain--AI Synergistic Consensus for Multi-Agent Reinforcement Learning},
  author = {{MARL-ECDSA Team}},
  year   = {2026}
}
```

