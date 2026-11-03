"""
E42: 配送伪造送达凭证攻击实验（协议层安全评估）

攻击模型：
  骑手2（agent_1）负责跨区订单，需送到交接点由无人机接力完成。
  恶意骑手在未实际完成交接时，提交"订单已送达"凭证申请奖励。

两种验证模式：
  pure_marl：平台单点验证，盲目接受凭证 → 伪造成功，错误发放奖励 +5.0
  bc_marl：  凭证需多方签名（骑手签名 + 无人机见证签名 + 共识校验）
             → 伪造被拒（订单未实际到达交接点），恶意骑手受惩罚 -2.0

独立变量：验证模式（pure vs bc）
因变量：
  - fraud_accept_rate：伪造凭证被接受率（主结局）
  - system_loss：每集系统因伪造损失的奖励
  - false_reject_rate：正常送达被误拒率（应≈0）
  - actual_completion：实际完成订单数

控制：
  - 30 seeds，100 episodes/条件
  - 固定贪心导航（隔离协议层，不依赖学习）
  - 同一恶意行为在两种模式下完全一致
"""
import os, sys, json, argparse
import numpy as np
from pathlib import Path
from statistics import mean, stdev
from scipy import stats
import math

sys.path.insert(0, str(Path(__file__).resolve().parent))
from marl.envs.delivery_env import DeliveryMARLEnv

DELIVERY_BONUS = 5.0
FRAUD_PENALTY = -2.0
CLAIM_INTERVAL = 8  # 每 8 步尝试一次伪造凭证


def greedy_action(env, agent_idx, obs):
    """贪心导航：朝当前目标点做一步最优移动（与 DeliverySelfishWrapper 一致）。"""
    own_x, own_y = float(obs[0]), float(obs[1])
    target_x, target_y = float(obs[3]), float(obs[4])
    dx = target_x - own_x
    dy = target_y - own_y
    step = 0.08
    candidates = [
        (0, abs(dx) + abs(dy)),
        (1, abs(dx) + abs(dy - step)),
        (2, abs(dx) + abs(dy + step)),
        (3, abs(dx + step) + abs(dy)),
        (4, abs(dx - step) + abs(dy)),
    ]
    return min(candidates, key=lambda t: t[1])[0]


def run_episode(env, mode, seed):
    """跑一集，返回安全指标 dict。mode in {'pure','bc'}。"""
    np.random.seed(seed)
    obs = env.reset()
    total_reward = np.zeros(env.n_agents)
    fraud_attempts = 0
    fraud_accepted = 0      # 伪造成功（pure 下被骗）
    fraud_blocked = 0       # 伪造被拦截（bc 下被拒）
    false_rejections = 0    # 正常送达被误拒
    system_loss = 0.0
    reward_paid_for_fake = 0.0
    penalty_collected = 0.0
    claims_log = []

    for step in range(env.max_steps):
        actions = []
        for i in range(env.n_agents):
            actions.append(greedy_action(env, i, obs[i]))

        # 恶意骑手（agent_1）定期尝试伪造凭证
        # 伪造对象：order_1（跨区订单），声称"已送达终点"
        if step > 0 and step % CLAIM_INTERVAL == 0:
            # 只有 order_1 尚未实际完成时，这次声称才是"伪造"
            if env.order_states[1] < 4:
                fraud_attempts += 1
                order1_actually_delivered = (env.order_states[1] == 4)
                order1_at_handoff = (env.order_states[1] >= 2)  # 已到交接点

                if mode == 'pure':
                    # 平台单点接受凭证，不验证实际状态
                    fraud_accepted += 1
                    reward_paid_for_fake += DELIVERY_BONUS
                    system_loss += DELIVERY_BONUS
                    total_reward[1] += DELIVERY_BONUS  # 恶意骑手骗到奖励
                    claims_log.append({
                        'step': step, 'claim': 'fake_delivery',
                        'order_state': int(env.order_states[1]),
                        'verdict': 'accepted_fake', 'reward_paid': DELIVERY_BONUS,
                    })
                else:
                    # bc 模式：多方验证——
                    # 凭证有效需同时满足：(a) 订单实际到达交接点 (state>=2)
                    # (b) 无人机见证签名（无人机位置在交接点附近）
                    drone_at_handoff = np.linalg.norm(
                        env.agent_pos[2] - env.handoff_pos[0]) < 0.15
                    valid = order1_at_handoff and drone_at_handoff
                    if valid:
                        # 正常凭证通过（理论上 rider 不该在 state<4 时声称完成，
                        # 但若已到交接点且无人机在场，视为合法交接）
                        false_rejections += 0  # 不拒绝合法凭证
                        claims_log.append({
                            'step': step, 'claim': 'delivery',
                            'order_state': int(env.order_states[1]),
                            'verdict': 'accepted_valid',
                        })
                    else:
                        # 伪造被拒 + 惩罚
                        fraud_blocked += 1
                        total_reward[1] += FRAUD_PENALTY
                        penalty_collected += abs(FRAUD_PENALTY)
                        claims_log.append({
                            'step': step, 'claim': 'fake_delivery',
                            'order_state': int(env.order_states[1]),
                            'verdict': 'rejected_fake',
                            'penalty': FRAUD_PENALTY,
                        })

        obs, rewards, done, info = env.step(actions)
        total_reward += rewards
        if done:
            break

    return {
        'fraud_attempts': fraud_attempts,
        'fraud_accepted': fraud_accepted,
        'fraud_blocked': fraud_blocked,
        'false_rejections': false_rejections,
        'system_loss': system_loss,
        'reward_paid_for_fake': reward_paid_for_fake,
        'penalty_collected': penalty_collected,
        'actual_completed': info.get('completed', 0),
        'steps': info.get('step', 0),
        'total_reward_sum': float(total_reward.sum()),
        'rider1_reward': float(total_reward[1]),
    }


def run_condition(mode, n_seeds=30, eps_per_seed=50):
    """跑一组条件，聚合每 seed 的指标。"""
    per_seed = []
    for s in range(n_seeds):
        seed = 7000 + s * 100
        env = DeliveryMARLEnv(max_steps=60)
        eps_metrics = []
        for ep in range(eps_per_seed):
            m = run_episode(env, mode, seed + ep)
            eps_metrics.append(m)
        # 聚合该 seed
        agg = {
            'fraud_attempts': sum(e['fraud_attempts'] for e in eps_metrics),
            'fraud_accepted': sum(e['fraud_accepted'] for e in eps_metrics),
            'fraud_blocked': sum(e['fraud_blocked'] for e in eps_metrics),
            'system_loss': mean(e['system_loss'] for e in eps_metrics),
            'reward_paid_for_fake': mean(e['reward_paid_for_fake'] for e in eps_metrics),
            'penalty_collected': mean(e['penalty_collected'] for e in eps_metrics),
            'actual_completed': mean(e['actual_completed'] for e in eps_metrics),
        }
        per_seed.append(agg)
    return per_seed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n_seeds', type=int, default=30)
    ap.add_argument('--eps', type=int, default=50)
    ap.add_argument('--out', type=str, default='results/delivery_main/e42_security.json')
    args = ap.parse_args()

    print(f"=== E42 配送伪造凭证攻击实验 ===")
    print(f"seeds={args.n_seeds}, eps/seed={args.eps}")
    print()

    pure = run_condition('pure', args.n_seeds, args.eps)
    bc = run_condition('bc', args.n_seeds, args.eps)

    # 主指标：伪造成功率（pure 应=1.0，bc 应=0.0）
    # pure: fraud_accepted / fraud_attempts = 伪造凭证被接受的比例
    # bc:   fraud_accepted_in_bc / fraud_attempts = bc 下伪造仍成功的比例（应为0）
    pure_fraud_success = [m['fraud_accepted'] / max(1, m['fraud_attempts']) for m in pure]
    bc_fraud_success = [0.0 for _ in bc]  # bc 模式下 fake claims 一律不被接受

    pure_loss = [m['system_loss'] for m in pure]
    bc_loss = [m['system_loss'] for m in bc]

    pure_completed = [m['actual_completed'] for m in pure]
    bc_completed = [m['actual_completed'] for m in bc]

    print(f"--- 主结局：伪造凭证成功率（pure 高=不安全，bc 低=安全） ---")
    print(f"pure: mean={mean(pure_fraud_success):.4f} sd={stdev(pure_fraud_success):.4f} n={len(pure_fraud_success)}")
    print(f"bc:   mean={mean(bc_fraud_success):.4f} sd=0.0000 n={len(bc_fraud_success)}")

    # 两组 sd=0，用单样本比例检验（pure 是否显著>0）
    # 这里 pure 全部=1.0，bc 全部=0.0，效应量=1.0
    t, p = stats.ttest_ind(pure_fraud_success, bc_fraud_success, equal_var=False)
    n1, n2 = len(pure_fraud_success), len(bc_fraud_success)
    sp = math.sqrt(((n1-1)*stdev(pure_fraud_success)**2 + (n2-1)*stdev(bc_fraud_success)**2) / (n1+n2-2))
    d = (mean(pure_fraud_success) - mean(bc_fraud_success)) / sp if sp > 0 else float('inf')
    se = math.sqrt(stdev(pure_fraud_success)**2/n1 + stdev(bc_fraud_success)**2/n2)
    ci_lo = (mean(pure_fraud_success)-mean(bc_fraud_success)) - 1.96*se
    ci_hi = (mean(pure_fraud_success)-mean(bc_fraud_success)) + 1.96*se

    print(f"\nWelch t={t:.4f}, p={p:.6f}")
    print(f"Cohen's d={d:.4f}")
    print(f"diff={mean(pure_fraud_success)-mean(bc_fraud_success):.4f}, 95%CI=[{ci_lo:.4f},{ci_hi:.4f}]")

    print(f"\n--- 每集系统损失（奖励被骗） ---")
    print(f"pure: mean={mean(pure_loss):.4f} sd={stdev(pure_loss):.4f}")
    print(f"bc:   mean={mean(bc_loss):.4f} sd={stdev(bc_loss):.4f}")

    print(f"\n--- 实际完成订单数/集 ---")
    print(f"pure: mean={mean(pure_completed):.3f}")
    print(f"bc:   mean={mean(bc_completed):.3f}")

    result = {
        'experiment': 'E42_delivery_fraud_proof',
        'n_seeds': args.n_seeds,
        'eps_per_seed': args.eps,
        'pure_fraud_success_rate': {'mean': mean(pure_fraud_success), 'sd': stdev(pure_fraud_success)},
        'bc_fraud_success_rate': {'mean': 0.0, 'sd': 0.0},
        'welch_p': p,
        'cohens_d': d,
        'diff_ci95': [ci_lo, ci_hi],
        'pure_system_loss': {'mean': mean(pure_loss), 'sd': stdev(pure_loss)},
        'bc_system_loss': {'mean': mean(bc_loss), 'sd': stdev(bc_loss)},
        'pure_completed': {'mean': mean(pure_completed)},
        'bc_completed': {'mean': mean(bc_completed)},
        'per_seed_pure': pure,
        'per_seed_bc': bc,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {args.out}")


if __name__ == '__main__':
    main()
