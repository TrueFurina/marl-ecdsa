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
- 全量测试基线以登记簿 **NR-19** 为准（下限式「2183+ 项通过」），跌破必须解释哪类失败、是否与本次改动相关；**不要在本文件另抄一个具体数字**——那会变成第二份真值源，随用例增减必然漂移
- 实验结果引用必须带 seed 数和 p 值，没有统计量的结论写"待验证"

## 写测试的硬约束（2026-11-04 事故后加）
- **夹具可共享，TestCase 不可跨模块复用**。`unittest.TestCase` 子类会被 pytest
  **无条件收集**（`python_classes` 的 `Test*` 前缀过滤对普通类才生效），所以
  `from tests.test_a import SomeTestCase` 或 `class B(SomeTestCase)` 会让同一批用例
  在多个模块里各跑一遍。共享夹具请放进**不继承 TestCase** 的普通类。
  机制守卫见 `tests/test_no_testcase_leaks.py`。
- **同一段确定性计算不要在多条用例里各跑一遍**。要先实测确认可复现
  （同参数连跑两遍逐位相同、或长跑的前缀与短跑逐位相同），再用
  `scope="module"` 夹具共享；若不可复现，说明该计算本身是随机源，应当登记而不是共享。
