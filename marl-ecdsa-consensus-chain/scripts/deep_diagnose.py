"""
深度诊断：逐步追踪 Q-learning 更新过程
"""
import sys
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from marl.envs.simple_spread import SimpleSpreadEnv
from marl.algorithms.qmix import QMIXTrainer, HAS_TORCH
import torch

import torch.nn.functional as F


def _run_episode(env, trainer, max_steps):
    """执行单个训练回合"""
    observations = env.reset()
    episode_obs, episode_actions, episode_rewards, episode_next_obs = [], [], [], []
    episode_states = [env.get_state()]
    for step in range(max_steps):
        actions, _ = trainer.get_actions(observations, [None]*3)
        next_observations, _, local_rewards, done, _ = env.step(actions)
        episode_states.append(env.get_state())
        episode_obs.append(observations)
        episode_actions.append(actions)
        episode_rewards.append(list(local_rewards))
        episode_next_obs.append(next_observations)
        observations = next_observations
        if done:
            break
    trainer.store_episode({
        'observations': episode_obs, 'actions': episode_actions,
        'rewards': episode_rewards, 'next_observations': episode_next_obs,
        'state_list': episode_states, 'done': done,
    })
    return episode_obs, episode_actions, episode_rewards, episode_next_obs, episode_states, done


def _print_diagnostic_info(trainer, episode, loss):
    """每 200 回合打印深度诊断"""
    print(f"\n{'='*60}")
    print(f"[Episode {episode}] epsilon={trainer.epsilon:.3f} loss={loss:.5f}")
    trans = trainer.replay_buffer.sample(1)[0]
    obs_n, actions_n, rewards_n, next_obs_n, done = trans['obs_n'], trans['actions_n'], trans['rewards_n'], trans['next_obs_n'], trans['done']
    print(f"  rewards_n: {[f'{r:.3f}' for r in rewards_n]}")
    print(f"  actions_n: {actions_n}, done: {done}")
    with torch.no_grad():
        for i in range(3):
            o = torch.FloatTensor(obs_n[i]).unsqueeze(0)
            q_all = trainer.agents[i](o)[0]
            no = torch.FloatTensor(next_obs_n[i]).unsqueeze(0)
            tq_all = trainer.target_agents[i](no)[0]
            td_t = float(rewards_n[i]) + (1-float(done)) * 0.8 * tq_all.max().item()
            print(f"  agent_{i} Q(s): {[f'{v:.3f}' for v in q_all.tolist()]} | chosen={actions_n[i]} Q={q_all[int(actions_n[i])]:.3f} | max={q_all.max():.3f}")
            print(f"    target Q(s'): max={tq_all.max():.3f} | TD target={td_t:.3f} | TD error={td_t - q_all[int(actions_n[i])].item():.3f}")
    _check_gradients(trainer, obs_n, actions_n, rewards_n, next_obs_n, done)
    _print_action_comparison(trainer, obs_n)


def _check_gradients(trainer, obs_n, actions_n, rewards_n, next_obs_n, done):
    """检查梯度流向"""
    trainer.optimizer.zero_grad()
    test_qs, test_targets = [], []
    for i in range(3):
        o = torch.FloatTensor(obs_n[i]).unsqueeze(0)
        q_all_i = trainer.agents[i](o)[0]
        test_qs.append(q_all_i[int(actions_n[i])])
        with torch.no_grad():
            no = torch.FloatTensor(next_obs_n[i]).unsqueeze(0)
            tq_all_i = trainer.target_agents[i](no)[0]
            r_i = float(rewards_n[i])
            test_targets.append(r_i + (1-float(done)) * 0.8 * tq_all_i.max().item())
    test_loss = sum(F.mse_loss(q.unsqueeze(0), torch.tensor([t])) for q, t in zip(test_qs, test_targets)) / 3
    test_loss.backward()
    print(f"  Test loss: {test_loss.item():.5f}")
    print(f"  Gradient norms (before clip):")
    for i in range(3):
        for name, param in trainer.agents[i].named_parameters():
            if param.grad is not None and param.grad.norm().item() > 0.001:
                print(f"    agent_{i}.{name}: {param.grad.norm().item():.6f}")


def _print_action_comparison(trainer, obs_n):
    """打印动作对比"""
    print(f"\n  动作对比测试 (agent_0):")
    o0 = torch.FloatTensor(obs_n[0]).unsqueeze(0)
    with torch.no_grad():
        q0_all = trainer.agents[0](o0)[0]
    print(f"    所有动作 Q值: {[f'{v:.3f}' for v in q0_all.tolist()]}")
    print(f"    max-min gap: {q0_all.max().item() - q0_all.min().item():.3f}")
    print(f"    argmax: action_{q0_all.argmax().item()}")


def _evaluate_policy(env, trainer):
    """最终评估：用学习到的策略跑 10 个回合"""
    print(f"\n{'='*60}")
    print("最终评估：用学习到的策略跑 10 个回合（epsilon=0）")
    print(f"{'='*60}")
    for ep_test in range(10):
        obs = env.reset()
        total_r = 0
        for step in range(25):
            actions = []
            for i in range(3):
                o = torch.FloatTensor(obs[i]).unsqueeze(0)
                with torch.no_grad():
                    q = trainer.agents[i](o)[0]
                actions.append(q.argmax().item())
            obs, grewards, _, done, _ = env.step(actions)
            total_r += sum(grewards)
            if done:
                break
        print(f"  测试回合 {ep_test+1}: total_reward={total_r:.1f}")


def deep_diagnose():
    np.random.seed(42)
    torch.manual_seed(42)
    env = SimpleSpreadEnv(n_agents=3, n_landmarks=3)
    trainer = QMIXTrainer(
        n_agents=3, obs_dim=env.obs_dim, state_dim=env.state_dim,
        n_actions=env.n_actions, hidden_dim=128, lr=1e-3, gamma=0.8,
        epsilon_start=1.0, epsilon_end=0.05, epsilon_decay=5000, use_vdn=True,
    )
    for episode in range(1, 1001):
        _run_episode(env, trainer, 25)
        loss = trainer.train_step(batch_size=64)
        if episode % 200 == 0 and loss is not None:
            _print_diagnostic_info(trainer, episode, loss)
    _evaluate_policy(env, trainer)
