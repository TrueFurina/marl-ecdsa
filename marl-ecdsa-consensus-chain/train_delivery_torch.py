"""
配送 MARL 训练（PyTorch MLP-IQL）：A/B 对比
- A 组：纯环境奖励
- B 组：环境奖励 + λ·贡献度激励
"""
import sys, os, json, random, time
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from marl.envs.delivery_env import DeliveryMARLEnv


class QNetwork(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, n_actions),
        )
    def forward(self, x):
        return self.net(x)


class MLPIQL:
    def __init__(self, n_agents, obs_dim, n_actions, lr=1e-3, gamma=0.95):
        self.n_agents = n_agents
        self.n_actions = n_actions
        self.gamma = gamma
        self.q_nets = [QNetwork(obs_dim, n_actions) for _ in range(n_agents)]
        self.optimizers = [optim.Adam(q.parameters(), lr=lr) for q in self.q_nets]
        self.memory = [[] for _ in range(n_agents)]
        self.epsilon = 0.5

    def get_actions(self, obs_list):
        actions = []
        for i in range(self.n_agents):
            if random.random() < self.epsilon:
                actions.append(random.randint(0, self.n_actions - 1))
            else:
                with torch.no_grad():
                    q = self.q_nets[i](torch.FloatTensor(obs_list[i]))
                    actions.append(int(q.argmax().item()))
        return actions

    def store(self, obs_list, actions, rewards, next_obs_list, done):
        for i in range(self.n_agents):
            self.memory[i].append((obs_list[i], actions[i], rewards[i], next_obs_list[i], done))

    def train_step(self, batch_size=64):
        for i in range(self.n_agents):
            if len(self.memory[i]) < batch_size:
                continue
            batch = random.sample(self.memory[i], batch_size)
            obs = torch.FloatTensor([b[0] for b in batch])
            act = torch.LongTensor([b[1] for b in batch]).unsqueeze(1)
            rew = torch.FloatTensor([b[2] for b in batch])
            next_obs = torch.FloatTensor([b[3] for b in batch])
            done = torch.FloatTensor([b[4] for b in batch])

            q = self.q_nets[i](obs).gather(1, act).squeeze(1)
            with torch.no_grad():
                next_q = self.q_nets[i](next_obs).max(1)[0]
                target = rew + self.gamma * next_q * (1 - done)
            loss = nn.MSELoss()(q, target)
            self.optimizers[i].zero_grad()
            loss.backward()
            self.optimizers[i].step()


def run_episode(env, agent, use_credibility=False, lam=0.1):
    obs = env.reset()
    contrib = np.zeros(env.n_agents)
    total_env_reward = np.zeros(env.n_agents)

    for step in range(env.max_steps):
        actions = agent.get_actions(obs)
        next_obs, rewards, done, info = env.step(actions)

        for i in range(env.n_agents):
            total_env_reward[i] += rewards[i]
            if rewards[i] >= 4.0:
                contrib[i] += 1.0
            elif rewards[i] >= 1.5:
                contrib[i] += 0.5

        agent.store(obs, actions, rewards.tolist(), next_obs, done)
        obs = next_obs
        if done:
            break

    # B 组：贡献度激励加到 episode 末
    if use_credibility and contrib.sum() > 0:
        bonus = (contrib / contrib.sum()) * lam * 5.0
        total_env_reward += bonus

    return info, total_env_reward, contrib


def run_experiment(seed, use_credibility=False, n_episodes=1000, lam=0.1):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    env = DeliveryMARLEnv(max_steps=50)
    agent = MLPIQL(env.n_agents, env.obs_dim, env.n_actions, lr=3e-3)

    history = []
    for ep in range(n_episodes):
        agent.epsilon = max(0.1, 0.8 - ep / (n_episodes * 0.5))
        info, rew, contrib = run_episode(env, agent, use_credibility, lam)
        agent.train_step()
        if ep % 100 == 0:
            history.append({"ep": ep, "completed": info["completed"]})

    # 评估
    eval_completed = []
    agent.epsilon = 0.05
    for _ in range(30):
        info, _, _ = run_episode(env, agent, use_credibility, lam)
        eval_completed.append(info["completed"])

    return {
        "seed": seed, "use_credibility": use_credibility,
        "final_completed": float(np.mean(eval_completed)),
        "final_std": float(np.std(eval_completed)),
        "history": history,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--credibility", action="store_true")
    p.add_argument("--episodes", type=int, default=1000)
    p.add_argument("--lam", type=float, default=0.1)
    p.add_argument("--out", type=str, required=True)
    args = p.parse_args()

    t0 = time.time()
    r = run_experiment(args.seed, args.credibility, args.episodes, args.lam)
    r["wall_time"] = time.time() - t0
    print(json.dumps({k: v for k, v in r.items() if k != "history"}, ensure_ascii=False, indent=2))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
