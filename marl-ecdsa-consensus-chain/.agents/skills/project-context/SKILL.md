---
name: project-context
description: MARL-ECDSA 共识链项目上下文——CW-PBFT 共识、ECDSA 身份、双环路与竞赛材料入口；触发词：MARL、共识链、CW-PBFT、区块链、ECDSA、项目上下文
---
# 项目上下文 — MARL-ECDSA 共识链（CCF 区块链竞赛）

## 项目是什么
区块链-AI 协同共识：贡献加权 PBFT（CW-PBFT）+ ECDSA 无 CA 身份 + MARL 双向环路。CCF 第五届区块链大赛技术创新赛道，v4.1。

## 核心机制（先懂再改）
- **CW-PBFT**（blockchain/consensus/cw_pbft.py）：Shapley 风格权重（三公理）+ 动态主节点故障转移，模式 `cw_pbft` / `standard_pbft` / `fast`
- **双环路**：BC→MARL（链上激励进 MARL 奖励）+ MARL→BC（MARL 行为进贡献分加权共识）
- **SecurityGuard 三层防御**：k-reuse 检测 / nonce 防重放 / 时间戳校验
- **后量子**：ML-DSA-44 适配器已实装（2420 字节签名，sign≈24ms/verify≈4.4ms），混合 ECDSA+Dilithium AND 模式；**默认签名路径仍是 ECDSA**

## 真值文件
- `marl-ecdsa-consensus-chain/README.md`（英）/ `README.zh.md`（中）：项目全貌
- `docs/MARL-ECDSA共识链_完整技术文档报告.md`：技术报告（2026-09-23 由仓库根归位至 `docs/`）
- `docs/VERIFICATION_INDEX.md` / `QUALITY_AUDIT_LOG.md`：验证与审计索引

## 关键命令
```bash
pip install -r requirements.txt
python -m pytest tests/ -q                        # 1632 tests
python main.py --mode bc_marl --episodes 200      # 主实验
```

## 仓库布局（注意：外层是多目录竞赛工作区，核心代码在 marl-ecdsa-consensus-chain/）
- 提交包：`MARL-ECDSA_共识链_提交包/`、`competition_submission/`
- 实验与分析：`experiments/`、`analyze_all_experiments.py`
