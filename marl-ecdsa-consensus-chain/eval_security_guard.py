#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E53: SecurityGuard攻击检测实证
- 正常包：放行
- 重放包（相同nonce）：拦截
- 时间戳过旧包：拦截
- r值重用包：拦截
输出 results/delivery_main/e53_security_guard.json
"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blockchain.crypto.security_guard import SecurityGuard


def run():
    sg = SecurityGuard()
    now = time.time()

    results = {}

    # 1. 正常包
    good = {
        'agent_id': 'agent_0',
        'nonce': 1,
        'timestamp': now,
        'r_value': 'abc123',
        'action': 'delivery',
    }
    ok, msg = sg.check_package(good)
    results['legit_package'] = {'accepted': ok, 'reason': msg}

    # 2. 重放包（相同nonce再发一次）
    replay = dict(good)
    ok, msg = sg.check_package(replay)
    results['replay_same_nonce'] = {'accepted': ok, 'reason': msg}

    # 3. 时间戳过旧（5分钟前）
    old = dict(good)
    old['nonce'] = 2
    old['timestamp'] = now - 360
    ok, msg = sg.check_package(old)
    results['old_timestamp'] = {'accepted': ok, 'reason': msg}

    # 4. r值重用（不同agent，相同r值）
    r_reuse = {
        'agent_id': 'agent_1',
        'nonce': 1,
        'timestamp': now,
        'r_value': 'abc123',  # 和agent_0相同的r
        'action': 'delivery',
    }
    ok, msg = sg.check_package(r_reuse)
    results['r_value_reuse'] = {'accepted': ok, 'reason': msg}

    # 统计
    detected = sum(1 for v in results.values() if not v['accepted'])
    total = len(results)
    return {
        'test_cases': results,
        'total_attacks': total - 1,  # 减去legit
        'detected': detected - (0 if results['legit_package']['accepted'] else 1),
        'detection_rate': (detected - (0 if results['legit_package']['accepted'] else 1)) / (total - 1),
        'risk_levels': {aid: sg.get_risk_level(aid) for aid in ['agent_0', 'agent_1']},
    }


if __name__ == '__main__':
    r = run()
    print("=== E53 SecurityGuard Detection ===")
    print(json.dumps(r, indent=2, ensure_ascii=False))
    os.makedirs('results/delivery_main', exist_ok=True)
    with open('results/delivery_main/e53_security_guard.json', 'w', encoding='utf-8') as f:
        json.dump({'experiment': 'E53_security_guard', **r}, f, ensure_ascii=False, indent=2)
    print("Saved.")
