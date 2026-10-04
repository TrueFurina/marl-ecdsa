"""
诊断脚本：深入检查 QMIX 训练是否真正在学习
"""
import sys
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from marl.envs.simple_spread import SimpleSpreadEnv
from marl.algorithms.qmix import QMIXTrainer, HAS_TORCH
import torch

def _run_training_loop(env, trainer, n_episodes, max_steps, batch_size):
    """训练主循环：返回 losses 和 episode_rewards"""
    losses, episode_rewards = [], []
    for episode in range(1, n_episodes + 1):
        total_reward = _run_single_episode(env, trainer, episode, max_steps)
        episode_rewards.append(total_reward)
        loss = trainer.train_step(batch_size=batch_size)
        if loss is not None:
            losses.append(loss)
        if episode % 50 == 0:
            _diagnose_snapshot(env, trainer, episode, losses, episode_rewards)
    return losses, episode_rewards


def _run_single_episode(env, trainer, episode, max_steps):
    """执行单个回合"""
    observations = env.reset()
    episode_obs, episode_actions, episode_rewards_list, episode_next_obs, episode_states = [], [], [], [], []
    episode_states.append(env.get_state())
    total_reward = 0.0

    if episode == 1:
        _print_initial_q_values(trainer, observations)

    for step in range(max_steps):
        actions, _ = trainer.get_actions(observations, [None] * 3)
        next_obs, _, local_rewards, done, _ = env.step(actions)
        episode_states.append(env.get_state())
        episode_obs.append(observations)
        episode_actions.append(actions)
        episode_rewards_list.append(list(local_rewards))
        episode_next_obs.append(next_obs)
        total_reward += sum(local_rewards)
        observations = next_obs
        if done:
            break

    trainer.store_episode({
        'observations': episode_obs, 'actions': episode_actions,
        'rewards': episode_rewards_list, 'next_observations': episode_next_obs,
        'state_list': episode_states, 'done': done,
    })
    return total_reward


def _print_initial_q_values(trainer, observations):
    """打印初始 Q 值"""
    import torch
    with torch.no_grad():
        for i in range(3):
            o = torch.FloatTensor(observations[i]).unsqueeze(0)
            q = trainer.agents[i](o)[0]
            print(f"  [初始] agent_{i} Q值: min={q.min().item():.3f}, max={q.max().item():.3f}, mean={q.mean().item():.3f}")


def _diagnose_snapshot(env, trainer, episode, losses, episode_rewards):
    """每 50 回合输出诊断快照"""
    import torch
    np = __import__('numpy')
    with torch.no_grad():
        obs_test = env.reset()
        agent_qs = []
        for i in range(3):
            o = torch.FloatTensor(obs_test[i]).unsqueeze(0)
            q = trainer.agents[i](o)[0]
            agent_qs.append(q.max().item())
        q_total = _compute_q_total(trainer, agent_qs, env.get_state())
    recent_loss = float(np.mean(losses[-20:])) if len(losses) >= 20 else (float(np.mean(losses)) if losses else 0)
    print(f"[E{episode:3d}] ε={trainer.epsilon:.3f} "
          f"AvgR(last50)={float(np.mean(episode_rewards[-50:])):.1f} "
          f"Loss(20avg)={recent_loss:.5f} "
          f"Q_agents={[f'{q:.3f}' for q in agent_qs]} "
          f"Q_total={q_total:.3f}")


def _compute_q_total(trainer, agent_qs, state):
    """计算 Q_total（VDN 或 QMIX 混合）"""
    import torch
    if not trainer.use_vdn and trainer.mixer is not None:
        s_t = torch.FloatTensor(state).unsqueeze(0)
        aqs = torch.FloatTensor(agent_qs).unsqueeze(0)
        return trainer.mixer(aqs, s_t).item()
    return sum(agent_qs)


def _print_final_diagnosis(env, trainer, losses, episode_rewards):
    """最终诊断输出"""
    import torch
    np = __import__('numpy')

    with torch.no_grad():
        obs_test = env.reset()
        state_test = env.get_state()
        print("\n最终 Q 值 (重置后):")
        agent_max_qs = []
        for i in range(3):
            o = torch.FloatTensor(obs_test[i]).unsqueeze(0)
            q = trainer.agents[i](o)[0]
            agent_max_qs.append(q.max().item())
            print(f"  agent_{i}: {[f'{v:.3f}' for v in q.tolist()]} (max={q.max().item():.3f})")
        q_total = _compute_q_total(trainer, agent_max_qs, state_test)
        print(f"  Q_total: {q_total:.3f}")

    if len(losses) >= 100:
        first_100 = float(np.mean(losses[:100]))
        last_100 = float(np.mean(losses[-100:]))
        trend = '下降' if last_100 < first_100 else '上升' if last_100 > first_100 else '不变'
        print(f"\nLoss 趋势: 前100均值={first_100:.5f} → 后100均值={last_100:.5f} ({trend})")

    first_100r = float(np.mean(episode_rewards[:100]))
    last_100r = float(np.mean(episode_rewards[-100:]))
    trend_r = '改善' if last_100r > first_100r else '恶化' if last_100r < first_100r else '不变'
    print(f"奖励趋势: 前100均值={first_100r:.1f} → 后100均值={last_100r:.1f} ({trend_r})")

    print(f"\n梯度检查 (agent_0 第一层权重梯度范数):")
    for name, param in trainer.agents[0].named_parameters():
        status = f"grad_norm={param.grad.norm().item():.6f}" if param.grad is not None else "grad=None"
        print(f"  {name}: {status}")

    if not trainer.use_vdn and trainer.mixer is not None:
        print(f"\n混合网络梯度检查:")
        for name, param in trainer.mixer.named_parameters():
            status = f"grad_norm={param.grad.norm().item():.6f}" if param.grad is not None else "grad=None"
            print(f"  {name}: {status}")
    else:
        print(f"\n[VDN模式，无混合网络]")


def diagnose():
    """运行诊断训练并输出关键指标"""
    np.random.seed(42)
    torch.manual_seed(42)

    env = SimpleSpreadEnv(n_agents=3, n_landmarks=3)
    trainer = QMIXTrainer(
        n_agents=3, obs_dim=env.obs_dim, state_dim=env.state_dim,
        n_actions=env.n_actions, hidden_dim=128, lr=1e-3, gamma=0.95,
        epsilon_start=1.0, epsilon_end=0.05, epsilon_decay=5000, use_vdn=True,
    )

    print("=" * 60)
    print("QMIX 诊断训练开始")
    print(f"obs_dim={env.obs_dim}, state_dim={env.state_dim}, n_actions={env.n_actions}")
    print("=" * 60)

    losses, episode_rewards = _run_training_loop(env, trainer, 1000, 25, 64)

    print("\n" + "=" * 60)
    print("最终诊断")
    print("=" * 60)
    _print_final_diagnosis(env, trainer, losses, episode_rewards)


if __name__ == '__main__':
    diagnose()
