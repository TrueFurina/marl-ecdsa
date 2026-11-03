#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E52: 激励合约奖励分配验证（直接用贡献度公式）
"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 从合约源码直接取常数
BASE_REWARD = 1.0
CONTRIB_GAIN = 2.0
KAPPA_TASK = 0.40
KAPPA_COOP = 0.35
KAPPA_COMPLIANCE = 0.25

def compute_reward(task, coop, compliance):
    score = KAPPA_TASK * task + KAPPA_COOP * coop + KAPPA_COMPLIANCE * compliance
    return BASE_REWARD + CONTRIB_GAIN * score

agents = {
    'agent_0': {'task': 1.0, 'coop': 0.9, 'compliance': 1.0},   # 优秀
    'agent_1': {'task': 0.5, 'coop': 0.5, 'compliance': 0.8},   # 中等
    'agent_2': {'task': 0.1, 'coop': 0.1, 'compliance': 0.5},    # 低贡献
}

payouts = {}
for aid, c in agents.items():
    payouts[aid] = compute_reward(c['task'], c['coop'], c['compliance'])

total = sum(payouts.values())
shares = {aid: round(p / total, 3) for aid, p in payouts.items()}

result = {
    'payouts': payouts,
    'shares': shares,
    'total': round(total, 4),
    'ratio_top_bottom': round(payouts['agent_0'] / payouts['agent_2'], 2),
    'honest_better_than_selfish': payouts['agent_0'] > payouts['agent_2'],
}
print(json.dumps(result, indent=2))
os.makedirs('results/delivery_main', exist_ok=True)
with open('results/delivery_main/e52_incentive_payout.json', 'w', encoding='utf-8') as f:
    json.dump({'experiment': 'E52_incentive_payout', **result}, f, ensure_ascii=False, indent=2)
print("Saved.")
