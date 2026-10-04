---
name: test-gate
description: MARL-ECDSA 共识链测试闸门——1632 全量测试、实验复现验证；触发词：测试、pytest、验证、跑测试
---
# 测试闸门 — MARL-ECDSA 共识链

## 标准命令
```bash
cd marl-ecdsa-consensus-chain
pip install -r requirements.txt
python -m pytest tests/ -q          # 全量 1632 tests，应全绿
```

## 改动类型 → 验证方式
| 改动 | 必须跑 |
|------|--------|
| consensus/（cw_pbft 等） | 全量 pytest + 一次短跑 `python main.py --mode standard_pbft --episodes 5` |
| SecurityGuard / 签名 | 全量 pytest（安全测试在其中）+ keys_demo 冒烟 |
| MARL 奖励/训练 | 全量 pytest + 小 episodes 实验（`--episodes 10`）确认奖励环路通 |
| 文档/README 数字 | 与 `analyze_all_experiments.py` 输出对账，数字必须来自代码真值 |

## 汇报纪律
- "1632 passed" 是当前基线，跌破必须解释哪类失败、是否与本次改动相关
- 实验结果引用必须带 seed 数和 p 值，没有统计量的结论写"待验证"
