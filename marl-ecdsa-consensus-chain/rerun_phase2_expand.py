"""
实验补强 第二阶段
==================
1. 主结局 convergence_3000 继续扩种：从 n=40 扩展到 n=71
   已有 22 + 第一阶段 18 = 40 个 seed
   新增 31 个 seed: 33-64（跳过已存在的）
   每个 seed 跑 bc_marl + pure_marl，IQL，3000ep

2. E14 QMIX 同批扩种：从 n=10 扩展到 n=20
   已有 seed 100-109
   新增 seed 110-119
   bc_marl -> results/dispatch_20260921/e14_qmix_seed{}.json
   pure_marl -> results/dispatch_20260921/e14pure_qmix_seed{}.json
   QMIX 算法，3000ep

自动跳过已存在的结果文件，可随时中断续跑。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train  # noqa: F401  (前台加载 torch 避免后台 SIGSEGV)

# ============================================================================
# 第一部分：主结局扩种 (n=40 -> n=71)
# ============================================================================
MAIN_EXISTING = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,
                 21,22,23,24,25,26,27,28,29,30,31,32,42,123,456,99,100,202,303,777}
MAIN_NEW = [33,34,35,36,37,38,39,40,41,43,44,45,46,47,48,49,50,
            51,52,53,54,55,56,57,58,59,60,61,62,63,64]  # 31 seeds -> n=71
MAIN_DIR = 'results/convergence_3000'

# ============================================================================
# 第二部分：QMIX 扩种 (n=10 -> n=20)
# ============================================================================
QMIX_EXISTING = set(range(100, 110))
QMIX_NEW = list(range(110, 120))  # 10 seeds -> n=20
QMIX_DIR = 'results/dispatch_20260921'


def run_train(mode, seed, algorithm, save_path, n_episodes=3000, lambda_weight='0.1'):
    """运行一次训练，返回是否成功"""
    if os.path.exists(save_path):
        print(f'  [skip] {mode} {algorithm} seed={seed} exists', flush=True)
        return True
    sys.argv = [
        'train.py',
        '--mode', mode,
        '--n_agents', '3',
        '--n_landmarks', '3',
        '--n_episodes', str(n_episodes),
        '--seed', str(seed),
        '--algorithm', algorithm,
        '--lambda_weight', lambda_weight,
        '--save', save_path,
    ]
    print(f'  [run] {mode} {algorithm} seed={seed} -> {save_path}', flush=True)
    try:
        train.main()
        return True
    except Exception as e:
        print(f'  [ERROR] {mode} {algorithm} seed={seed}: {e}', flush=True)
        return False


def main():
    t0 = time.time()
    os.makedirs(MAIN_DIR, exist_ok=True)
    os.makedirs(QMIX_DIR, exist_ok=True)

    # ---- Part 1: 主结局扩种 ----
    print('=' * 60, flush=True)
    print(f'PART 1: 主结局扩种 n=40->n=71 ({len(MAIN_NEW)} new seeds x 2 modes)', flush=True)
    print('=' * 60, flush=True)
    main_done = 0
    main_total = len(MAIN_NEW) * 2
    for seed in MAIN_NEW:
        for mode in ['bc_marl', 'pure_marl']:
            save = os.path.join(MAIN_DIR, f'{mode}_seed{seed}.json')
            ok = run_train(mode, seed, 'iql', save)
            main_done += 1
            if ok:
                print(f'  [progress] main {main_done}/{main_total} ({time.time()-t0:.0f}s)', flush=True)

    # ---- Part 2: QMIX 扩种 ----
    print('=' * 60, flush=True)
    print(f'PART 2: QMIX 扩种 n=10->n=20 ({len(QMIX_NEW)} new seeds x 2 modes)', flush=True)
    print('=' * 60, flush=True)
    qmix_done = 0
    qmix_total = len(QMIX_NEW) * 2
    for seed in QMIX_NEW:
        # bc_marl
        save_bc = os.path.join(QMIX_DIR, f'e14_qmix_seed{seed}.json')
        run_train('bc_marl', seed, 'qmix', save_bc)
        qmix_done += 1
        # pure_marl
        save_pure = os.path.join(QMIX_DIR, f'e14pure_qmix_seed{seed}.json')
        run_train('pure_marl', seed, 'qmix', save_pure)
        qmix_done += 1
        print(f'  [progress] qmix {qmix_done}/{qmix_total} ({time.time()-t0:.0f}s)', flush=True)

    print('=' * 60, flush=True)
    print(f'ALL DONE in {time.time()-t0:.0f}s', flush=True)
    print(f'  Main: n should be ~{len(MAIN_EXISTING)+len(MAIN_NEW)} per group', flush=True)
    print(f'  QMIX: n should be ~{len(QMIX_EXISTING)+len(QMIX_NEW)} per group', flush=True)
    print('Next: run verify_numbers.py to update registry declared values', flush=True)


if __name__ == '__main__':
    main()
