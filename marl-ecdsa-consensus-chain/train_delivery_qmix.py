"""
配送 MARL 训练（PyTorch QMIX）：A/B 对比
QMIX: CTDE 架构，mixing network 分解团队 Q 到个体
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
            nn.Linear(hidden, n_actions),
        )
    def forward(self, x):
        return self.net(x)


class MixingNetwork(nn.Module):
    def __init__(self, n_agents, state_dim, hidden=64):
        super().__init__()
        self.n = n_agents
        self.hidden = hidden
        self.hyper_w1 = nn.Linear(state_dim, hidden * n_agents)
        self.hyper_b1 = nn.Linear(state_dim, hidden)
        self.hyper_w2 = nn.Linear(state_dim, hidden)
        self.hyper_b2 = nn.Linear(state_dim, 1)

    def forward(self, agent_qs, states):
        # agent_qs: (batch, n_agents), states: (batch, state_dim)
        bs = agent_qs.size(0)
        w1 = torch.abs(self.hyper_w1(states)).view(bs, self.n, self.hidden)  # (bs, n, hidden)
        b1 = self.hyper_b1(states).view(bs, 1, self.hidden)  # (bs, 1, hidden)
        hidden = torch.relu(torch.bmm(agent_qs.unsqueeze(1), w1) + b1)  # (bs, 1, hidden)
        w2 = torch.abs(self.hyper_w2(states)).view(bs, self.hidden, 1)  # (bs, hidden, 1)
        b2 = self.hyper_b2(states).view(bs, 1, 1)
        out = torch.bmm(hidden, w2) + b2  # (bs, 1, 1)
        return out.view(bs)


class QMIX:
    def __init__(self, n_agents, obs_dim, state_dim, n_actions, lr=5e-4, gamma=0.95, target_update=200):
        self.n = n_agents
        self.gamma = gamma
        self.target_update = target_update
        self.update_count = 0
        self.agent_qs = [AgentQ(obs_dim, n_actions) for _ in range(n_agents)]
        self.target_qs = [AgentQ(obs_dim, n_actions) for _ in range(n_agents)]
        self.mixer = MixingNetwork(n_agents, state_dim)
        self.target_mixer = MixingNetwork(n_agents, state_dim)
        # 初始化 target = online
        for i in range(n_agents):
            self.target_qs[i].load_state_dict(self.agent_qs[i].state_dict())
        self.target_mixer.load_state_dict(self.mixer.state_dict())
        self.params = list(self.mixer.parameters())
        for q in self.agent_qs:
            self.params += list(q.parameters())
        self.opt = optim.Adam(self.params, lr=lr)
        self.memory = []
        self.epsilon = 0.5

    def _sync_target(self):
        for i in range(self.n):
            self.target_qs[i].load_state_dict(self.agent_qs[i].state_dict())
        self.target_mixer.load_state_dict(self.mixer.state_dict())

    def get_actions(self, obs_list):
        actions = []
        for i in range(self.n):
            if random.random() < self.epsilon:
                actions.append(random.randint(0, 4))
            else:
                with torch.no_grad():
                    q = self.agent_qs[i](torch.FloatTensor(obs_list[i]))
                    actions.append(int(q.argmax().item()))
        return actions

    def store(self, obs_list, actions, team_reward, next_obs_list, state, next_state, done):
        self.memory.append((obs_list, actions, team_reward, next_obs_list, state, next_state, done))

    def train_step(self, batch_size=64):
        if len(self.memory) < batch_size:
            return
        batch = random.sample(self.memory, batch_size)
        obs = torch.FloatTensor([b[0] for b in batch])  # (bs, n, obs)
        act = torch.LongTensor([b[1] for b in batch])  # (bs, n)
        rew = torch.FloatTensor([b[2] for b in batch])  # (bs,)
        next_obs = torch.FloatTensor([b[3] for b in batch])
        state = torch.FloatTensor([b[4] for b in batch])
        next_state = torch.FloatTensor([b[5] for b in batch])
        done = torch.FloatTensor([b[6] for b in batch])

        # current team Q
        cur_qs = []
        for i in range(self.n):
            q = self.agent_qs[i](obs[:, i, :])
            cur_qs.append(q.gather(1, act[:, i].unsqueeze(1)))
        cur_team = self.mixer(torch.cat(cur_qs, dim=1), state).squeeze()

        # target team Q
        with torch.no_grad():
            next_qs = []
            for i in range(self.n):
                q = self.target_qs[i](next_obs[:, i, :])
                next_qs.append(q.max(1)[0].unsqueeze(1))
            next_team = self.target_mixer(torch.cat(next_qs, dim=1), next_state).squeeze()
            target = rew + self.gamma * next_team * (1 - done)

        loss = nn.MSELoss()(cur_team, target)
        self.opt.zero_grad()
        loss.backward()
        self.opt.step()
        self.update_count += 1
        if self.update_count % self.target_update == 0:
            self._sync_target()


def run_episode(env, agent, use_credibility=False, lam=1.0):
    obs = env.reset()
    state = np.concatenate([env.agent_pos.flatten(), env.order_states.astype(float)])
    contrib = np.zeros(env.n_agents)
    for step in range(env.max_steps):
        actions = agent.get_actions(obs)
        next_obs, rewards, done, info = env.step(actions)
        next_state = np.concatenate([env.agent_pos.flatten(), env.order_states.astype(float)])
        team_reward = rewards.sum()

        for i in range(env.n_agents):
            if rewards[i] >= 4.0:
                contrib[i] += 1.0
            elif rewards[i] >= 1.5:
                contrib[i] += 0.5

        agent.store(obs, actions, team_reward, next_obs, state, next_state, done)
        agent.train_step()
        obs = next_obs
        state = next_state
        if done:
            break

    if use_credibility and contrib.sum() > 0:
        bonus = (contrib / contrib.sum()) * lam * 5.0
        info["cred_bonus"] = bonus.tolist()
    return info


def run_experiment(seed, use_credibility=False, n_episodes=5000, lam=1.0):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    env = DeliveryMARLEnv(max_steps=60)
    agent = QMIX(env.n_agents, env.obs_dim, env.state_dim, env.n_actions, lr=3e-3)

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
