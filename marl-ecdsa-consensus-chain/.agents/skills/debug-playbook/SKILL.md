---
name: debug-playbook
description: MARL-ECDSA 共识链排障——测试失败定位、共识模式切换、密钥问题、竞赛提交包一致性；触发词：排障、报错、测试失败、debug
---
# 排障手册 — MARL-ECDSA 共识链

## 1. pytest 失败
1. 先跑单文件定位：`python -m pytest tests/test_xxx.py -v`
2. 区分三类：本次改动相关 / 既有失败 / 环境问题（依赖缺失）
3. 共识相关失败优先看 `cw_pbft.py` 权重计算与主节点转移日志

## 2. 共识行为异常
- 确认模式参数：`cw_pbft` / `standard_pbft` / `fast` 三者行为差异大
- 权重异常先查贡献分来源（MARL→BC 环路），再看 Shapley 三公理推导输入

## 3. 签名/身份报错
- k-reuse 检测触发 = 节点复用密钥，属防御正常工作，不是 bug
-nonce 防重放触发 = 检查时间戳与时钟偏差
- Dilithium 相关：确认 `dilithium-py` 已装；默认路径是 ECDSA，别在 ECDSA 问题里查 Dilithium

## 4. 竞赛提交包不一致
- 提交包有多份副本（`MARL-ECDSA_共识链_提交包/`、`competition_submission/`、backup）——以最新 `_提交包` 为准，禁止手工编辑旧包
- 口径数字必须能追溯到 `analyze_all_experiments.py` 输出

## 5. 外层工作区混乱
- 外层是竞赛工作区（多目录并存），核心代码只在 `marl-ecdsa-consensus-chain/`——先 cd 进核心目录再操作
