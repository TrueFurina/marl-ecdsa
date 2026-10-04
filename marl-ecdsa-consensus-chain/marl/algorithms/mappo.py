"""
MAPPO 算法实现（多智能体近端策略优化，轻量版）
序贯决策的 CTDE 策略梯度方法，当前 MARL 协作任务的事实标准基线之一。

设计要点（与本项目 QMIXTrainer 接口对齐，可直接被 train.py 使用）：
- Actor-Critic：每智能体独立 Actor（随机策略）+ 1 个共享 Critic（全局状态）
- GAE(λ) 优势估计
- PPO clip 目标 + 熵正则
- 接口：get_actions / init_hidden / store_episode / train_step / epsilon / agents
"""
import numpy as np
import random
import logging
from collections import deque
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# 同 qmix.py：只在 torch 确实不存在时回退，装坏则 fail-closed（理由见 qmix.py 注释）。
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except ModuleNotFoundError as exc:
    if exc.name != "torch":
        raise
    HAS_TORCH = False
    logger.warning("[MAPPO] 未安装 PyTorch（MAPPO 训练不可用；测试将 skip）")


class MAPPOBuffer:
    """on-policy 回合缓冲：存完整 episode，训练时整批使用"""

    def __init__(self, capacity: int = 10):
        self.buffer = deque(maxlen=capacity)
        self._current = None

    def start_episode(self):
        self._current = {'obs': [], 'actions': [], 'log_probs': [],
                         'rewards': [], 'states': [], 'dones': []}

    def add_step(self, obs_n, actions_n, log_probs_n, rewards_n, state, done):
        c = self._current
        c['obs'].append(obs_n)
        c['actions'].append(actions_n)
        c['log_probs'].append(log_probs_n)
        c['rewards'].append(rewards_n)
        c['states'].append(state)
        c['dones'].append(done)

    def finish_episode(self, last_state):
        self._current['last_state'] = last_state
        self.buffer.append(self._current)
        self._current = None

    def append(self, episode: dict):
        """直接存入完整 episode 条目（store_episode 构建路径用）"""
        self.buffer.append(episode)

    def __len__(self):
        return len(self.buffer)

    def sample(self):
        """取全部（on-policy 用完即弃）"""
        eps = list(self.buffer)
        self.buffer.clear()
        return eps


if HAS_TORCH:

    class MAPPOActor(nn.Module):
        """个体策略网络：观测 → 动作分布"""

        def __init__(self, obs_dim: int, n_actions: int, hidden_dim: int = 64):
            super().__init__()
            self.n_actions = n_actions
            self.net = nn.Sequential(
                nn.Linear(obs_dim, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, n_actions),
            )

        def init_hidden(self):
            return None

        def forward(self, obs: torch.Tensor) -> torch.Tensor:
            return self.net(obs)

        def get_action(self, obs: np.ndarray, hidden=None, epsilon: float = 0.0,
                       deterministic: bool = False) -> Tuple[int, None]:
            """采样动作；epsilon 参数仅为接口兼容（MAPPO 用策略熵探索）"""
            with torch.no_grad():
                logits = self.forward(torch.FloatTensor(obs).unsqueeze(0))
                probs = torch.softmax(logits, dim=-1).squeeze(0)
                if deterministic:
                    action = int(torch.argmax(probs).item())
                else:
                    action = int(torch.multinomial(probs, 1).item())
            log_prob = float(torch.log(probs[action] + 1e-8).item())
            return action, log_prob, hidden

    class MAPPOCritic(nn.Module):
        """集中式价值网络：全局状态 → V(s)"""

        def __init__(self, state_dim: int, hidden_dim: int = 64):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(state_dim, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, 1),
            )

        def forward(self, state: torch.Tensor) -> torch.Tensor:
            return self.net(state).squeeze(-1)

    class MAPPOTrainer:
        """MAPPO 训练器（接口与 QMIXTrainer 对齐）"""

        def __init__(
            self,
            n_agents: int, obs_dim: int, state_dim: int, n_actions: int,
            hidden_dim: int = 64, lr: float = 3e-4, gamma: float = 0.95,
            epsilon_start: float = 0.0, epsilon_end: float = 0.0,
            epsilon_decay: int = 1,
            clip_eps: float = 0.2, gae_lambda: float = 0.95,
            entropy_coef: float = 0.01, value_coef: float = 0.5,
            ppo_epochs: int = 4, batch_episodes: int = 4,
            **kwargs,
        ):
            self.n_agents = n_agents
            self.obs_dim = obs_dim
            self.state_dim = state_dim
            self.n_actions = n_actions
            self.gamma = gamma
            self.clip_eps = clip_eps
            self.gae_lambda = gae_lambda
            self.entropy_coef = entropy_coef
            self.value_coef = value_coef
            self.ppo_epochs = ppo_epochs
            self.batch_episodes = batch_episodes
            self.algorithm = 'mappo'
            self.use_iql = False

            self.agents = nn.ModuleList([
                MAPPOActor(obs_dim, n_actions, hidden_dim) for _ in range(n_agents)
            ])
            self.critic = MAPPOCritic(state_dim, hidden_dim)
            # 目标接口兼容（QMIXTrainer 有 target_agents，训练循环不直接访问）
            self.target_agents = self.agents
            self.target_mixer = None
            self.mixer = None

            self.actor_opt = optim.Adam(self.agents.parameters(), lr=lr)
            self.critic_opt = optim.Adam(self.critic.parameters(), lr=lr)

            self.buffer = MAPPOBuffer(capacity=max(2, batch_episodes))
            self._episode_active = False

            # epsilon 接口兼容（固定 0，探索由策略采样承担）
            self.epsilon_start = 0.0
            self.epsilon_end = 0.0
            self.epsilon = 0.0

        # ---- 决策接口 ----
        def get_actions(
            self, observations: List[np.ndarray], hidden_states=None
        ) -> Tuple[List[int], List[None]]:
            if not self._episode_active:
                self.buffer.start_episode()
                self._episode_active = True
            actions, log_probs, hiddens = [], [], []
            for i, obs in enumerate(observations):
                a, lp, h = self.agents[i].get_action(obs)
                actions.append(a)
                log_probs.append(lp)
                hiddens.append(h)
            self._pending = {'actions': actions, 'log_probs': log_probs}
            return actions, hiddens

        def init_hidden(self) -> List[None]:
            return [agent.init_hidden() for agent in self.agents]

        def cache_step(self, rewards_n, state, done):
            """训练循环在拿到 state 后调用：把当前步经验入缓冲"""
            if not self._episode_active:
                return
            self.buffer.add_step(None, self._pending['actions'],
                                 self._pending['log_probs'], rewards_n,
                                 state, done)

        # ---- 经验存储接口（与 QMIXTrainer.store_episode 对齐签名）----
        def store_episode(self, episode_data: dict):
            """
            episode 结束时调用：直接从完整 episode 数据构建缓冲条目。
            train.py 的存储格式与 QMIXTrainer.store_episode 相同
            （observations/actions/rewards/next_observations/state_list/done）。
            old log-prob 不在此保存——train_step 首轮以 no-grad 重算（标准 PPO 做法）。
            """
            obs_list = episode_data.get('observations', [])
            act_list = episode_data.get('actions', [])
            rew_list = episode_data.get('rewards', [])
            state_list = episode_data.get('state_list', [])
            done = episode_data.get('done', False)
            T = min(len(obs_list), len(act_list), len(rew_list))
            if T == 0:
                return
            ep = {
                'obs': [obs_list[t] for t in range(T)],
                'actions': [act_list[t] for t in range(T)],
                'log_probs': [None] * T,          # 占位：train_step 首轮重算
                'rewards': [rew_list[t] for t in range(T)],
                'states': [state_list[t] if t < len(state_list) else None
                           for t in range(T)],
                'dones': [done if t == T - 1 else False for t in range(T)],
                'last_state': state_list[-1] if len(state_list) > 0 else None,
            }
            self.buffer.append(ep)
            self._episode_active = False
            if self.buffer._current is not None:
                self.buffer._current = None

        # ---- 训练 ----
        def _gae(self, episode) -> Tuple[np.ndarray, np.ndarray]:
            """计算单条 episode 的 GAE 优势与回报"""
            T = len(episode['rewards'])
            states = np.array(episode['states'], dtype=np.float32)      # [T, state_dim]
            with torch.no_grad():
                v = self.critic(torch.FloatTensor(states)).numpy()      # [T]
                last_s = np.array(episode['last_state'], dtype=np.float32).reshape(1, -1) \
                    if episode['last_state'] is not None else None
                v_next = float(self.critic(torch.FloatTensor(last_s)).item()) \
                    if last_s is not None else 0.0

            adv = np.zeros(T, dtype=np.float32)
            gae = 0.0
            for t in reversed(range(T)):
                r = float(np.mean(episode['rewards'][t]))               # 团队均值为 Critic 目标
                next_v = v[t + 1] if t + 1 < T else v_next
                mask = 0.0 if episode['dones'][t] else 1.0
                delta = r + self.gamma * next_v * mask - v[t]
                gae = delta + self.gamma * self.gae_lambda * mask * gae
                adv[t] = gae
            returns = adv + v
            return adv, returns

        def train_step(self, batch_size: int = 64) -> Optional[float]:
            """PPO 更新：缓冲攒够 batch_episodes 条 episode 后整批更新"""
            if len(self.buffer) < self.batch_episodes:
                return None
            episodes = self.buffer.sample()

            all_losses = []
            for _ in range(self.ppo_epochs):
                actor_loss_sum, critic_loss_sum, n = 0.0, 0.0, 0
                for ep in episodes:
                    adv, returns = self._gae(ep)
                    # 归一化优势
                    if adv.std() > 1e-8:
                        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
                    T = len(ep['actions'])
                    obs_flat = np.array(
                        [o for t_obs in ep['obs'] if t_obs is not None for o in t_obs],
                        dtype=np.float32)
                    if len(obs_flat) == 0:
                        continue
                    adv_flat = np.repeat(adv, self.n_agents)
                    ret_flat = np.repeat(returns, self.n_agents)

                    obs_arr = obs_flat.reshape(T, self.n_agents, -1)
                    # 逐智能体前向（权重不同）
                    logits_list = []
                    for i in range(self.n_agents):
                        logits_i = self.agents[i].forward(torch.FloatTensor(obs_arr[:, i]))
                        logits_list.append(logits_i.unsqueeze(1))
                    logits = torch.cat(logits_list, dim=1).reshape(T * self.n_agents, -1)

                    acts = np.array([a for t_acts in ep['actions'] for a in t_acts])
                    log_softmax = torch.log_softmax(logits, dim=-1)
                    # old log-prob：存储时为占位 None → 以更新前策略 no-grad 重算（标准 PPO 做法）
                    if ep['log_probs'][0] is None:
                        with torch.no_grad():
                            old_lp = log_softmax[
                                torch.arange(len(acts)), torch.LongTensor(acts)].numpy().copy()
                    else:
                        old_lp = np.array([lp for t_lp in ep['log_probs'] for lp in t_lp])

                    dist = torch.distributions.Categorical(logits=log_softmax)
                    new_lp = dist.log_prob(torch.LongTensor(acts))
                    entropy = dist.entropy().mean()

                    ratio = torch.exp(new_lp - torch.FloatTensor(old_lp))
                    adv_t = torch.FloatTensor(adv_flat)
                    surr1 = ratio * adv_t
                    surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * adv_t
                    actor_loss = -(torch.min(surr1, surr2).mean()
                                   + self.entropy_coef * entropy)

                    v_pred = self.critic(torch.FloatTensor(
                        np.array(ep['states'], dtype=np.float32)))
                    critic_loss = ((v_pred - torch.FloatTensor(ret_flat[:T])) ** 2).mean()

                    self.actor_opt.zero_grad()
                    actor_loss.backward()
                    self.actor_opt.step()
                    self.critic_opt.zero_grad()
                    critic_loss.backward()
                    self.critic_opt.step()

                    actor_loss_sum += float(actor_loss.item())
                    critic_loss_sum += float(critic_loss.item())
                    n += 1
                if n > 0:
                    all_losses.append((actor_loss_sum + self.value_coef * critic_loss_sum) / n)
            return float(np.mean(all_losses)) if all_losses else None

else:
    # 无 PyTorch 时的占位（本机 Python312 有 torch，正常不会走到）
    class MAPPOTrainer:  # pragma: no cover
        def __init__(self, *a, **k):
            raise ImportError("MAPPO 需要 PyTorch")

    MAPPOActor = MAPPOCritic = None
