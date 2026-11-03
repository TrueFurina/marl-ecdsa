#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E50: 收敛速度分析（零新训练，读已有日志）
- 找 BC组 和 PURE组 的训练曲线
- 计算首次达到最终奖励90%的回合数
输出 results/delivery_main/e50_convergence_speed.json
"""
import json, glob, os
from pathlib import Path
from statistics import mean

results_dir = Path('results')

# 找BC和PURE的训练结果
bc_files = sorted(glob.glob(str(results_dir / 'convergence_3000' / 'bc_marl_seed*.json')))
pure_files = sorted(glob.glob(str(results_dir / 'convergence_3000' / 'pure_marl_seed*.json')))

print(f"BC files: {len(bc_files)}, PURE files: {len(pure_files)}")

def convergence_episodes(files, target_ratio=0.9):
    """对每个seed，找首次达到最终均值target_ratio的回合"""
    episodes = []
    for f in files:
        try:
            d = json.load(open(f, encoding='utf-8'))
            rewards = d.get('episode_rewards', d.get('rewards', []))
            if not rewards or len(rewards) < 100:
                continue
            final = mean(rewards[-50:])
            target = final * target_ratio if final < 0 else final * target_ratio
            # 对负奖励：target比final更差（更不负），找首次>=target
            for i, r in enumerate(rewards):
                if final < 0:
                    if r >= target:
                        episodes.append(i)
                        break
                else:
                    if r >= target:
                        episodes.append(i)
                        break
        except Exception as e:
            pass
    return episodes

bc_conv = convergence_episodes(bc_files)
pure_conv = convergence_episodes(pure_files)

result = {
    'bc_n': len(bc_conv),
    'bc_mean_convergence_ep': round(mean(bc_conv), 0) if bc_conv else None,
    'bc_min': min(bc_conv) if bc_conv else None,
    'bc_max': max(bc_conv) if bc_conv else None,
    'pure_n': len(pure_conv),
    'pure_mean_convergence_ep': round(mean(pure_conv), 0) if pure_conv else None,
    'pure_min': min(pure_conv) if pure_conv else None,
    'pure_max': max(pure_conv) if pure_conv else None,
}
print(json.dumps(result, indent=2))

os.makedirs('results/delivery_main', exist_ok=True)
with open('results/delivery_main/e50_convergence_speed.json', 'w', encoding='utf-8') as f:
    json.dump({'experiment': 'E50_convergence_speed', **result}, f, ensure_ascii=False, indent=2)
print("Saved.")
