---
name: arch-rules
description: MARL-ECDSA 共识链架构红线——诚实口径、签名路径、实验可复现；触发词：架构红线、口径、诚实、签名、实验
---
# 架构红线 — MARL-ECDSA 共识链

## 诚实口径（本项目最高红线，违者 = 竞赛出局级风险）
1. 实验结论不得夸大显著性：headline 现行权威为 **n=71/组**（登记簿 NR-1：末 50 回合 +28.17%、Welch p=0.0095、**BH-FDR 显著/Bonferroni 不显著**；NR-2 全程 +7.92%、p<1e-10，**两口径必须同报**）。旧口径 n=22 seeds / p=0.126 / +29.2% **已作废，任何文档/提交材料不得再作为现行结论引用**（历史快照须打「口径过期」标注，不得悄悄改写历史文件）
2. Nash 均衡是"参数边界推导 + 数值验证"，**不是机器检验的形式化证明**——禁止写成"formally proven"
3. presolve/工具直出的结果不计 LLM 功劳；LLM 真推理贡献必须独立证明

## 签名路径
- 默认签名路径是 ECDSA；Dilithium 是适配器能力，切换需显式配置，禁止默认路径悄悄变更
- 私钥/密钥材料永不入库（keys/ 已隔离，keys_demo/ 仅演示用）

## 实验纪律
- 多 seed 统计必须报告 seed 数与 p 值，禁止只报最好 seed
- 消融矩阵、λ 敏感性结果改动时必须同步更新 README 的 Experiments 区
- 审计链完整性：sign → Guard → Tx → Block → consensus 任一环改动必须跑全量 pytest（1632 tests）
