"""
训练级权重展宽端到端对照实验（路线C · MARL训练内真实发生）

设计（配对对照）：
- 两臂共用相同省略故障节点集（omission_seed=0 确定性采样，n_agents=5 → 2 节点省略）
- ON 臂：--weight-broadening（纪元50轮展宽启用）
- OFF 臂：不开展开宽（静态贡献度权重，权重冻结）
- 3 种子 × 2 臂 × 500 回合（= 10 个纪元窗口）
- 预期（与 NR-29 双层解耦自洽）：学习指标两臂接近；共识活性 ON 恢复 / OFF 持续失活

输出：results/training_broadening_e2e/{on,off}_seed{S}.json + report.json（落盘判成功）
支持断点续跑（已有输出自动跳过），可反复调用直至全部完成。
"""
import os
import sys
import time
import json

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPT_DIR)  # 仓库根目录（train.py 所在）
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)  # save/results 相对路径统一锚定仓库根

import train  # noqa: F401  前台加载 torch

SEEDS = [42, 123, 456]
CONDITIONS = {
    'on': ['--weight-broadening'],
    'off': [],
}
OMISSION_ARGS = ['--omission-ratio', '0.4', '--omission-seed', '0']
N_EPISODES = 500
SAVE_DIR = 'results/training_broadening_e2e'


def run_one(cond, seed, save):
    sys.argv = [
        'train.py',
        '--mode', 'bc_marl',
        '--n_agents', '5',
        '--n_landmarks', '5',
        '--n_episodes', str(N_EPISODES),
        '--seed', str(seed),
        '--algorithm', 'iql',
        '--lambda_weight', '0.1',
        '--save', save,
    ] + CONDITIONS[cond] + OMISSION_ARGS
    train.main()


def _load_result(path):
    """读取单次运行结果；文件缺失/损坏/关键字段缺失返回 None（不信任半写文件）。"""
    try:
        d = json.load(open(path, encoding='utf-8'))
        wb = d.get('weight_broadening_stats') or {}
        if wb.get('consensus_success_rate') is None or wb.get('honest_weight_share') is None:
            return None
        return d
    except (OSError, json.JSONDecodeError):
        return None


def aggregate():
    rows = []
    for cond in CONDITIONS:
        for seed in SEEDS:
            p = os.path.join(SAVE_DIR, f'{cond}_seed{seed}.json')
            d = _load_result(p)
            if d is None:
                return False
            wb = d.get('weight_broadening_stats', {})
            env = d.get('env_rewards', [])
            coop = d.get('cooperation_rates', [])
            rows.append({
                'cond': cond, 'seed': seed,
                'consensus_success_rate': wb.get('consensus_success_rate'),
                'honest_weight_share': wb.get('honest_weight_share'),
                'epochs_triggered': wb.get('epochs_triggered'),
                'omission_nodes': wb.get('omission_nodes'),
                'env_reward_last50': sum(env[-50:]) / max(1, len(env[-50:])),
                'coop_rate_last50': sum(coop[-50:]) / max(1, len(coop[-50:])),
            })
    summary = {}
    for cond in CONDITIONS:
        arm = [r for r in rows if r['cond'] == cond]
        summary[cond] = {
            'n': len(arm),
            'consensus_success_rate_mean': round(sum(r['consensus_success_rate'] for r in arm) / len(arm), 4),
            'honest_weight_share_mean': round(sum(r['honest_weight_share'] for r in arm) / len(arm), 4),
            'env_reward_last50_mean': round(sum(r['env_reward_last50'] for r in arm) / len(arm), 4),
            'coop_rate_last50_mean': round(sum(r['coop_rate_last50'] for r in arm) / len(arm), 4),
        }
    out = {
        'meta': {
            'n_agents': 5, 'omission_ratio': 0.4, 'omission_seed': 0,
            'n_episodes': N_EPISODES, 'seeds': SEEDS,
            'epoch_rounds': 50, 'algorithm': 'iql', 'lambda': 0.1,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        },
        'summary': summary,
        'rows': rows,
    }
    path = os.path.join(SAVE_DIR, 'report.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[report] {path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return True


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    total = len(SEEDS) * len(CONDITIONS)
    done = 0
    t0 = time.time()
    for cond in CONDITIONS:
        for seed in SEEDS:
            save = os.path.join(SAVE_DIR, f'{cond}_seed{seed}.json')
            if os.path.exists(save):
                if _load_result(save) is not None:
                    print(f'[skip] {cond} seed={seed} exists', flush=True)
                    done += 1
                    continue
                corrupt = save + '.corrupt'
                os.replace(save, corrupt)
                print(f'[warn] {cond} seed={seed} 半写/损坏文件已改名 {corrupt}，重跑', flush=True)
            print(f'[run {done+1}/{total}] START {cond} seed={seed}', flush=True)
            try:
                run_one(cond, seed, save)
                print(f'[run {done+1}/{total}] DONE  {cond} seed={seed} '
                      f'({time.time()-t0:.0f}s elapsed)', flush=True)
            except Exception as e:
                print(f'[run {done+1}/{total}] ERROR {cond} seed={seed}: {e}', flush=True)
            done += 1
    # 落盘判成功：全部 6 个产出 + report.json 存在才算完成
    if aggregate():
        print('[done] ALL RUNS + report.json OK', flush=True)
    else:
        print('[partial] 部分完成，重新调用本脚本续跑', flush=True)
        sys.exit(2)


if __name__ == '__main__':
    main()
