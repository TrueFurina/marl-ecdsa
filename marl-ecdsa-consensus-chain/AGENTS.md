# AGENTS.md — MARL-ECDSA 共识链项目事实源
> 🔴 **口径过期警示（2026-09-28 标注） — 引用前必须对齐登记簿**
> 本文件写成时的主实验口径为 **n=22 种子/组**（对应 +29.2%、Welch p=0.126 不显著）。该口径**已被后续扩种取代、现已作废**。
> 现行唯一权威口径为 **n=71/组**（`deliverables/number_registry.json` → NR-1 / NR-2）：
> ・末 50 回合 `env_reward`（不含 BC 激励）**+28.17%**，Welch p=0.009524，Cohen d=0.4412，95%CI [0.6476, +4.5761]，检验力≈0.742，**BH-FDR 下显著 / Bonferroni 下不显著**；
> ・全程平均 `env_reward` **+7.92%**，Welch p<1e-10，Cohen d=1.1962，检验力≈1.0。
> **两口径必须同报**，禁单点宣称「激励有效」「强证据」或「证明」。
> ⚠️ 本文件**仅加标注、未修改任何原数字**；正式对外出材料前须按 n=71 改写（见 `deliverables/gstack/full-check-marl-ecdsa-2026-09-28.md` §7 方案 B）。


> 外层是竞赛工作区，核心代码在本目录（marl-ecdsa-consensus-chain/）。权威真值详见 README.md / docs/VERIFICATION_INDEX.md 与 .agents/skills/。

## 这是什么
区块链-AI 协同共识：贡献加权 PBFT（CW-PBFT）+ ECDSA 无 CA 身份 + MARL 双向环路。CCF 第五届区块链大赛技术创新赛道 v4.1。

## 命令
- 测试: `python -m pytest tests/ -q`（基线 1600+ 项通过，跌破必须解释）
- 主实验: `python main.py --mode bc_marl --episodes 200`

## 诚实口径（最高红线）
- 实验结论保留完整统计表述（n=22 seeds, p=0.126 方向一致但不显著），禁止夸大显著性
  - 🔴 **2026-09-28 更正：本条口径已作废。** 现行唯一权威口径为 **n=71/组**（`deliverables/number_registry.json` NR-1 / NR-2）：末 50 回合 `env_reward` **+28.17%**（Welch p=0.0095，d=0.4412，**BH-FDR 显著 / Bonferroni 不显著**）＋全程 **+7.92%**（p<1e-10，d=1.1962），**两口径必须同报**；禁单点宣称「激励有效 / 强证据 / 证明」。上句原样保留仅为记录，**不得再据其出数**。
- Nash 均衡 = 参数边界推导+数值验证，非机器检验形式化证明
- 默认签名路径是 ECDSA；Dilithium 是适配器能力，切换需显式配置

## 禁区
- 提交包只走打包脚本，禁止手工编辑；旧包副本只读
- 私钥/密钥材料永不入库（keys/ 已隔离）
- 文档数字必须能追溯到 analyze_all_experiments.py 输出
  - ⚠️ **2026-09-28 更正**：`analyze_all_experiments.py` **自身仍在打印作废的 n=22 口径**（其报告生成段），在当前状态下**不能充当真值源**。改写完成前，数字一律以 `deliverables/number_registry.json`（NR-* 条目）为准。

## 项目级 skill（触发时读）
- `.agents/skills/project-context/` `.agents/skills/arch-rules/` `.agents/skills/test-gate/` `.agents/skills/debug-playbook/`
- 计划外脑：`plans/current.md` + `plans/decisions.md`
