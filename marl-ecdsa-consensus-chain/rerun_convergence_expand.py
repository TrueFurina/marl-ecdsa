"""
实验补强：主结局 convergence_3000 扩种
从 n=22 扩展到 n=40（第一阶段），目标把 Welch p 从 0.126 压到 <0.05。
已有 seed（22个）：1,2,3,4,5,6,7,8,9,10,11,12,13,21,42,123,456,99,100,202,303,777
新增 seed（18个）：14,15,16,17,18,19,20,22,23,24,25,26,27,28,29,30,31,32
每个 seed 跑 bc_marl + pure_marl 两个模式，共 36 次运行，约 2 小时。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 前台加载 torch（避免后台 import 阶段 SIGSEGV）
import train  # noqa: F401

EXISTING_SEEDS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 21, 42, 123, 456, 99, 100, 202, 303, 777}
NEW_SEEDS = [14, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]
SAVE_DIR = 'results/convergence_3000'

def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    total = len(NEW_SEEDS) * 2
    done = 0
    t0 = time.time()

    for seed in NEW_SEEDS:
        for mode in ['bc_marl', 'pure_marl']:
            save = os.path.join(SAVE_DIR, f'{mode}_seed{seed}.json')
            if os.path.exists(save):
                print(f'[skip] {mode} seed={seed} already exists', flush=True)
                done += 1
                continue

            sys.argv = [
                'train.py',
                '--mode', mode,
                '--n_agents', '3',
                '--n_landmarks', '3',
                '--n_episodes', '3000',
                '--seed', str(seed),
                '--algorithm', 'iql',
                '--lambda_weight', '0.1',
                '--save', save,
            ]
            print(f'[run {done+1}/{total}] START {mode} seed={seed} -> {save}', flush=True)
            try:
                train.main()
                print(f'[run {done+1}/{total}] DONE  {mode} seed={seed} ({time.time()-t0:.0f}s elapsed)', flush=True)
            except Exception as e:
                print(f'[run {done+1}/{total}] ERROR {mode} seed={seed}: {e}', flush=True)
            done += 1

    print(f'[expand] ALL DONE in {time.time()-t0:.0f}s. n should now be {len(EXISTING_SEEDS)+len(NEW_SEEDS)}=40 per group.', flush=True)

if __name__ == '__main__':
    main()
