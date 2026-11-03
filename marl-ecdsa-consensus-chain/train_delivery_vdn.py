"""
配送 MARL 训练（PyTorch VDN）：A/B 对比
VDN: Q_total = sum(Q_i)，最简单的 CTDE 价值分解
credibility bonus 加在 team reward 上，自然分解到每个智能体
"""
import sys, os, json, random, time
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from marl.envs.delivery_env import DeliveryMARLEnv


class AgentQ(nn.Module):
    def __init__(self, obs_dim, n_actions, hidden=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, n_actions),
        )
    def forward(self, x):
        return self.net(x)


class VDN:
    def __init__(self, n_agents, obs_dim, n_actions, lr=1e-3, gamma=0.95, target_update=200):
        self.n = n_agents
        self.gamma = gamma
        self.target_update = target_update
        self.update_count = 0
        self.online_qs = [AgentQ(obs_dim, n_actions) for _ in range(n_agents)]
        self.target_qs = [AgentQ(obs_dim, n_actions) for _ in range(n_agents)]
        for i in range(n_agents):
            self.target_qs[i].load_state_dict(self.online_qs[i].state_dict())
        self.params = []
        for q in self.online_qs:
            self.params += list(q.parameters())
        self.opt = optim.Adam(self.params, lr=lr)
        self.memory = []
        self.epsilon = 0.5

    def _sync(self):
        for i in range(self.n):
            self.target_qs[i].load_state_dict(self.online_qs[i].state_dict())

    def get_actions(self, obs_list):
        actions = []
        for i in range(self.n):
            if random.random() < self.epsilon:
                actions.append(random.randint(0, 4))
            else:
                with torch.no_grad():
                    q = self.online_qs[i](torch.FloatTensor(obs_list[i]))
                    actions.append(int(q.argmax().item()))
        return actions

    def store(self, obs_list, actions, team_reward, next_obs_list, done):
        self.memory.append((obs_list, actions, team_reward, next_obs_list, done))

    def train_step(self, batch_size=64):
        if len(self.memory) < batch_size:
            return
        batch = random.sample(self.memory, batch_size)
        obs = torch.FloatTensor(np.array([b[0] for b in batch]))  # (bs, n, obs)
        act = torch.LongTensor([b[1] for b in batch])  # (bs, n)
        rew = torch.FloatTensor([b[2] for b in batch])  # (bs,)
        next_obs = torch.FloatTensor(np.array([b[3] for b in batch]))
        done = torch.FloatTensor([b[4] for b in batch])

        # current Q: sum of agent Qs
        cur_qs = []
        for i in range(self.n):
            q = self.online_qs[i](obs[:, i, :]).gather(1, act[:, i].unsqueeze(1))
            cur_qs.append(q)
        cur_total = torch.cat(cur_qs, dim=1).sum(dim=1)

        # target Q
        with torch.no_grad():
            next_qs = []
            for i in range(self.n):
                q = self.target_qs[i](next_obs[:, i, :]).max(1)[0]
                next_qs.append(q.unsqueeze(1))
            next_total = torch.cat(next_qs, dim=1).sum(dim=1)
            target = rew + self.gamma * next_total * (1 - done)

        loss = nn.MSELoss()(cur_total, target)
        self.opt.zero_grad()
        loss.backward()
        self.opt.step()
        self.update_count += 1
        if self.update_count % self.target_update == 0:
            self._sync()


def run_episode(env, agent, use_credibility=False, lam=1.0):
    obs = env.reset()
    contrib = np.zeros(env.n_agents)
    for step in range(env.max_steps):
        actions = agent.get_actions(obs)
        next_obs, rewards, done, info = env.step(actions)
        team_reward = rewards.sum()

        for i in range(env.n_agents):
            if rewards[i] >= 4.0:
                contrib[i] += 1.0
            elif rewards[i] >= 1.5:
                contrib[i] += 0.5

        # B组：credibility bonus 加在 team reward 上
        if use_credibility and step == env.max_steps - 1 and contrib.sum() > 0:
            bonus = (contrib / contrib.sum()) * lam * 5.0
            team_reward += bonus.sum()

        agent.store(obs, actions, team_reward, next_obs, done)
        agent.train_step()
        obs = next_obs
        if done:
            break
    return info


def run_experiment(seed, use_credibility=False, n_episodes=5000, lam=1.0):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    env = DeliveryMARLEnv(max_steps=60)
    agent = VDN(env.n_agents, env.obs_dim, env.n_actions, lr=3e-3)

    for ep in range(n_episodes):
        agent.epsilon = max(0.05, 0.8 - ep / (n_episodes * 0.5))
        run_episode(env, agent, use_credibility, lam)

    eval_c = []
    agent.epsilon = 0.05
    for _ in range(30):
        info = run_episode(env, agent, use_credibility, lam)
        eval_c.append(info["completed"])

    return {
        "seed": seed, "use_credibility": use_credibility,
        "final_completed": float(np.mean(eval_c)),
        "final_std": float(np.std(eval_c)),
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--credibility", action="store_true")
    p.add_argument("--episodes", type=int, default=5000)
    p.add_argument("--lam", type=float, default=1.0)
    p.add_argument("--out", type=str, required=True)
    args = p.parse_args()
    t0 = time.time()
    r = run_experiment(args.seed, args.credibility, args.episodes, args.lam)
    r["wall_time"] = time.time() - t0
    print(json.dumps(r, ensure_ascii=False, indent=2))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
