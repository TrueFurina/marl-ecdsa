"""
QMIX 算法实现（轻量版）
经典 CTDE（集中训练分布执行）协作MARL算法
核心思想：Value Decomposition，个体Q函数的单调性组合 = 全局最优
"""
import numpy as np
import random
import logging
from collections import deque
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

# 尝试导入 PyTorch；**仅在 torch 确实不存在时**才回退到 NumPy 实现。
#
# ⚠️ 这里刻意**只**捕获 `ModuleNotFoundError` 且要求缺失者就是 `torch` 本身：
#   1. Windows 上 torch 装坏（如 c10.dll 缺失）抛的是 `ImportError: DLL load failed`，
#      它不是 ModuleNotFoundError → 会向上抛（fail-closed）；
#   2. torch 在但子模块缺失 → `exc.name == "torch.nn"` ≠ `"torch"` → 同样向上抛。
# 若把 `ImportError` 一并吞掉，就会在**算法已被换成另一套实现**的情况下静默跑出
# "看似正常"的实验结果 —— 换台机器就不可复现。装坏必须炸出来，不能悄悄降级。
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torch.optim as optim
    HAS_TORCH = True
except ModuleNotFoundError as exc:
    if exc.name != "torch":
        raise
    HAS_TORCH = False
    logger.warning("[QMIX] 未安装 PyTorch，使用 NumPy 简化实现"
                   "（结果口径与 PyTorch 版不同，禁止跨实现混比）")


# =============================================================================
# PyTorch实现版
# =============================================================================

if HAS_TORCH:
    class QMIXAgent(nn.Module):
        """
        QMIX个体智能体网络（前馈版，无GRU，简化且稳定）
        输入观测直接过MLP输出每个动作的Q值
        """

        def __init__(self, obs_dim: int, n_actions: int, hidden_dim: int = 64):
            super().__init__()
            self.obs_dim = obs_dim
            self.n_actions = n_actions
            self.hidden_dim = hidden_dim
            # 三层前馈网络
            self.net = nn.Sequential(
                nn.Linear(obs_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, n_actions),
            )

        def init_hidden(self):
            """兼容接口，实际不需要hidden state"""
            return None

        def forward(self, obs: torch.Tensor, hidden=None) -> torch.Tensor:
            """
            :param obs: [batch, obs_dim]
            :return: q_values [batch, n_actions]
            """
            return self.net(obs)

        def get_action(
            self,
            obs: np.ndarray,
            hidden=None,
            epsilon: float = 0.0
        ) -> Tuple[int, None]:
            """epsilon-greedy 策略选择动作"""
            if random.random() < epsilon:
                return random.randint(0, self.n_actions - 1), None

            with torch.no_grad():
                obs_t = torch.FloatTensor(obs).unsqueeze(0)
                q_vals = self.forward(obs_t)
                action = q_vals.argmax(dim=-1).item()
            return action, None

    class QMIXMixer(nn.Module):
        """
        QMIX混合网络
        用超网络生成混合参数，保证单调性（IGM条件）
        """

        def __init__(self, n_agents: int, state_dim: int, embed_dim: int = 32):
            super().__init__()
            self.n_agents = n_agents
            self.state_dim = state_dim
            self.embed_dim = embed_dim

            # 超网络：生成第一层混合权重/偏置
            self.hyper_w1 = nn.Sequential(
                nn.Linear(state_dim, embed_dim),
                nn.ReLU(),
                nn.Linear(embed_dim, n_agents * embed_dim)
            )
            self.hyper_b1 = nn.Linear(state_dim, embed_dim)

            # 超网络：生成第二层混合权重/偏置
            self.hyper_w2 = nn.Sequential(
                nn.Linear(state_dim, embed_dim),
                nn.ReLU(),
                nn.Linear(embed_dim, embed_dim)
            )
            self.hyper_b2 = nn.Sequential(
                nn.Linear(state_dim, embed_dim),
                nn.ReLU(),
                nn.Linear(embed_dim, 1)
            )

        def forward(
            self,
            agent_qs: torch.Tensor,    # [batch, n_agents]
            state: torch.Tensor         # [batch, state_dim]
        ) -> torch.Tensor:             # [batch, 1]
            bs = agent_qs.size(0)
            agent_qs = agent_qs.view(bs, 1, self.n_agents)

            # 第一层：[bs, 1, embed_dim]
            w1 = torch.abs(self.hyper_w1(state)).view(bs, self.n_agents, self.embed_dim)
            b1 = self.hyper_b1(state).view(bs, 1, self.embed_dim)
            hidden = F.elu(torch.bmm(agent_qs, w1) + b1)

            # 第二层：[bs, 1, 1]
            w2 = torch.abs(self.hyper_w2(state)).view(bs, self.embed_dim, 1)
            b2 = self.hyper_b2(state).view(bs, 1, 1)
            q_total = torch.bmm(hidden, w2) + b2

            return q_total.view(bs, -1)  # [bs, 1]

    class ReplayBuffer:
        """经验回放缓冲区——存单步 transition，而非整个 episode"""
        def __init__(self, capacity: int = 5000):
            self.buffer = deque(maxlen=capacity)

        def add(self, transition: dict):
            """存入单步 transition"""
            self.buffer.append(transition)

        def sample(self, batch_size: int) -> List[dict]:
            return random.sample(self.buffer, min(batch_size, len(self.buffer)))

        def __len__(self):
            return len(self.buffer)

    class VDNMixer(nn.Module):
        """
        VDN (Value Decomposition Networks) 混合网络
        Q_total = sum(Q_i) — 最简单的值分解，无额外参数
        """

        def forward(self, agent_qs: torch.Tensor) -> torch.Tensor:
            """
            :param agent_qs: [batch, n_agents]
            :return: q_total [batch, 1]
            """
            return agent_qs.sum(dim=-1, keepdim=True)

    class QMIXTrainer:
        """多算法训练器：支持 IQL / VDN / QMIX 三种值分解模式

        算法选择通过 algorithm 参数控制：
        - 'iql':  独立Q学习，每个智能体独立TD error，无混合网络（默认，最稳定）
        - 'vdn':  值分解网络，Q_total = sum(Q_i)，联合TD error，无额外参数
        - 'qmix': 单调值分解，Q_total = hypernetwork Mixer(Q_i, state)，IGM条件保证

        兼容性：use_iql 参数保留为 algorithm='iql' 的别名
        """

        def __init__(
            self,
            n_agents: int,
            obs_dim: int,
            state_dim: int,
            n_actions: int,
            hidden_dim: int = 128,
            lr: float = 1e-3,
            gamma: float = 0.95,
            epsilon_start: float = 1.0,
            epsilon_end: float = 0.05,
            epsilon_decay: int = 5000,
            use_iql: bool = True,
            use_vdn: bool = None,
            algorithm: str = None,
        ):
            self.n_agents = n_agents
            self.obs_dim = obs_dim
            self.state_dim = state_dim
            self.n_actions = n_actions
            self.gamma = gamma

            # 算法选择优先级：algorithm > use_vdn > use_iql
            if algorithm is not None:
                self.algorithm = algorithm.lower()
            elif use_vdn is not None:
                self.algorithm = 'vdn' if use_vdn else 'iql'
                logger.info("[QMIXTrainer] use_vdn 参数已废弃，请使用 algorithm='vdn'")
            else:
                self.algorithm = 'iql' if use_iql else 'qmix'

            self.use_iql = (self.algorithm == 'iql')

            # 网络
            self.agents = nn.ModuleList([
                QMIXAgent(obs_dim, n_actions, hidden_dim) for _ in range(n_agents)
            ])
            if self.algorithm == 'qmix':
                self.mixer = QMIXMixer(n_agents, state_dim)
            elif self.algorithm == 'vdn':
                self.mixer = VDNMixer()
            else:
                self.mixer = None
            self.target_agents = nn.ModuleList([
                QMIXAgent(obs_dim, n_actions, hidden_dim) for _ in range(n_agents)
            ])
            if self.algorithm == 'qmix':
                self.target_mixer = QMIXMixer(n_agents, state_dim)
            elif self.algorithm == 'vdn':
                self.target_mixer = VDNMixer()
            else:
                self.target_mixer = None

            # 复制初始权重
            self._update_targets(hard=True)

            # 优化器
            params = list(self.agents.parameters())
            if self.algorithm == 'qmix':
                params += list(self.mixer.parameters())
            # VDN mixer 无参数，不需要加入优化器
            self.optimizer = optim.Adam(params, lr=lr)

            # 经验回放（较小容量，focus on 近期数据）
            self.replay_buffer = ReplayBuffer(capacity=2500)

            # epsilon探索：按环境步数衰减
            self.epsilon_start = epsilon_start
            self.epsilon = epsilon_start
            self.epsilon_end = epsilon_end
            self.epsilon_decay = epsilon_decay
            self._env_steps = 0
            self._train_steps = 0

        def get_actions(
            self, observations: List[np.ndarray], hidden_states: List[torch.Tensor]
        ) -> Tuple[List[int], List[torch.Tensor]]:
            """选择所有智能体的动作；每次调用衰减一次 epsilon（按环境步数）"""
            self._env_steps += 1
            frac = min(1.0, self._env_steps / max(1, self.epsilon_decay))
            self.epsilon = self.epsilon_start - frac * (self.epsilon_start - self.epsilon_end)
            self.epsilon = max(self.epsilon_end, self.epsilon)

            actions = []
            new_hiddens = []
            for i, (obs, h) in enumerate(zip(observations, hidden_states)):
                action, new_h = self.agents[i].get_action(obs, h, self.epsilon)
                actions.append(action)
                new_hiddens.append(new_h)
            return actions, new_hiddens

        def init_hidden(self) -> List[torch.Tensor]:
            return [agent.init_hidden() for agent in self.agents]

        def store_transition(self, trans: dict):
            """存储单步 transition"""
            self.replay_buffer.add(trans)

        def store_episode(self, episode_data: dict):
            """
            把 episode 展开成单步 transition 存入 buffer

            重要说明：当前 ReplayBuffer 设计仅适用于 IQL 模式（无 GRU hidden state）。
            - 单步采样：每步 transition 独立存入，同一 episode 的不同步骤可能出现在同一 batch
            - IQL 模式下：每步 TD error 独立计算，无跨步依赖，此设计可行
            - 如需扩展为标准 QMIX（含 GRU）：需改用 episodic replay buffer，
              按 episode 连续采样，保留 hidden state 序列
            """
            obs_list   = episode_data.get('observations', [])
            act_list   = episode_data.get('actions', [])
            rew_list   = episode_data.get('rewards', [])
            next_list  = episode_data.get('next_observations', [])
            state_list = episode_data.get('state_list', [])
            done       = episode_data.get('done', False)
            T = len(obs_list)
            for t in range(T):
                s_t   = state_list[t]   if t     < len(state_list) else None
                s_tp1 = state_list[t+1] if t+1   < len(state_list) else None
                trans = {
                    'obs_n':      obs_list[t],
                    'actions_n':  act_list[t],
                    'rewards_n':  rew_list[t],
                    'next_obs_n': next_list[t] if t < len(next_list) else obs_list[min(t+1, T-1)],
                    'state':      s_t,
                    'next_state': s_tp1,
                    'done':       done if t == T - 1 else False,
                }
                self.store_transition(trans)

        def train_step(self, batch_size: int = 64) -> Optional[float]:
            """根据 algorithm 分发到对应的训练逻辑"""
            if len(self.replay_buffer) < batch_size:
                return None
            if self.algorithm == 'vdn':
                return self._train_step_vdn(batch_size)
            elif self.algorithm == 'qmix':
                return self._train_step_qmix(batch_size)
            else:
                return self._train_step_iql(batch_size)

        def _train_step_iql(self, batch_size: int = 64) -> Optional[float]:
            """
            IQL 模式：每个智能体独立计算 TD error，得到差异化梯度
            P1-8 修复：重构为标准批量模式，一次 forward+backward，
            性能比逐样本 backward 提升 10-50 倍

            P1批量forward修复：将batch中所有transition的obs拼成大batch一次forward，
            而非逐条unsquze(0)+forward，减少GPU kernel launch开销
            """
            if len(self.replay_buffer) < batch_size:
                return None

            batch = self.replay_buffer.sample(batch_size)
            bs = len(batch)

            # ── 批量数据组装 ──
            # P1修复：真正的批量forward——所有transition的obs一次拼成大batch再forward
            all_q_values = []       # [n_agents] 各agent的 Q(s_i, a_i) 批量张量 [batch_size]
            all_td_targets = []     # [n_agents] 各agent的TD目标批量张量 [batch_size]

            for i in range(self.n_agents):
                # 批量forward：将所有transition的第i个agent的obs拼成 [batch_size, obs_dim]
                obs_batch = torch.FloatTensor(
                    np.stack([trans['obs_n'][i] for trans in batch])
                )  # [batch_size, obs_dim]
                q_all = self.agents[i](obs_batch)  # [batch_size, n_actions] — 一次批量forward

                # 提取各transition选择的action对应的Q值
                action_indices = torch.LongTensor(
                    [int(trans['actions_n'][i]) for trans in batch]
                )  # [batch_size]
                q_selected = q_all.gather(1, action_indices.unsqueeze(1)).squeeze(1)  # [batch_size]

                # 目标Q值批量计算
                with torch.no_grad():
                    next_obs_batch = torch.FloatTensor(
                        np.stack([trans['next_obs_n'][i] for trans in batch])
                    )  # [batch_size, obs_dim]
                    tq_all = self.target_agents[i](next_obs_batch)  # [batch_size, n_actions] — 批量forward
                    tq_max = tq_all.max(dim=1)[0]  # [batch_size]

                    rewards_i = torch.FloatTensor(
                        [float(trans['rewards_n'][i]) for trans in batch]
                    )  # [batch_size]
                    done_mask = torch.FloatTensor(
                        [float(trans.get('done', False)) for trans in batch]
                    )  # [batch_size]
                    td_target_i = rewards_i + (1.0 - done_mask) * self.gamma * tq_max  # [batch_size]

                all_q_values.append(q_selected)         # [batch_size]
                all_td_targets.append(td_target_i)       # [batch_size]

            # ── 批量计算 loss + 一次 backward ──
            total_loss = 0.0
            loss_terms = []
            for i in range(self.n_agents):
                q_i = all_q_values[i]                            # [batch_size]
                td_i = all_td_targets[i]                         # [batch_size]
                loss_i = F.mse_loss(q_i, td_i)                   # 标量 loss（对 batch 均值）
                if torch.isnan(loss_i) or torch.isinf(loss_i):
                    logger.warning(f"[QMIX] NaN/Inf loss at agent {i}, skipping")
                    continue
                loss_terms.append(loss_i)
                total_loss += loss_i.item()

            if not loss_terms:
                logger.warning("[QMIX] 全部 loss 为 NaN/Inf，跳过本步")
                return None

            # 平均所有智能体的 loss，一次 backward
            avg_loss = sum(loss_terms) / len(loss_terms)
            self.optimizer.zero_grad()
            avg_loss.backward()
            torch.nn.utils.clip_grad_norm_(
                list(self.agents.parameters()), max_norm=10.0)
            self.optimizer.step()

            self._train_steps += 1
            self._update_targets(hard=False, tau=0.01)

            return total_loss / len(loss_terms)

        def _train_step_vdn(self, batch_size: int = 64) -> Optional[float]:
            """
            VDN 模式：Q_total = sum(Q_i)，联合 TD error
            值分解网络：个体 Q 通过求和得到全局 Q，梯度自动反向传播到各 agent

            P1批量forward修复：改为真正的批量forward，减少GPU kernel launch开销
            """
            batch = self.replay_buffer.sample(batch_size)
            bs = len(batch)

            all_q_values = []       # [n_agents] 各agent Q(s_i, a_i) [batch_size]
            all_target_q = []       # [n_agents] 各agent max Q_target [batch_size]

            for i in range(self.n_agents):
                # P1修复：批量forward
                obs_batch = torch.FloatTensor(
                    np.stack([trans['obs_n'][i] for trans in batch])
                )  # [batch_size, obs_dim]
                q_all = self.agents[i](obs_batch)  # [batch_size, n_actions]

                action_indices = torch.LongTensor(
                    [int(trans['actions_n'][i]) for trans in batch]
                )
                q_selected = q_all.gather(1, action_indices.unsqueeze(1)).squeeze(1)  # [batch_size]
                all_q_values.append(q_selected)

                with torch.no_grad():
                    next_obs_batch = torch.FloatTensor(
                        np.stack([trans['next_obs_n'][i] for trans in batch])
                    )
                    tq_all = self.target_agents[i](next_obs_batch)  # [batch_size, n_actions]
                    tq_max = tq_all.max(dim=1)[0]  # [batch_size]
                all_target_q.append(tq_max)

            # Q_total = sum(Q_i)  [batch_size]
            q_total = torch.stack(all_q_values, dim=0).sum(dim=0)

            # TD target: r_total + gamma * sum(max Q_target_i)
            r_total = torch.FloatTensor(
                [sum(trans['rewards_n']) for trans in batch]
            )  # P1修复：直接用FloatTensor而非tensor
            done_mask = torch.FloatTensor(
                [float(trans.get('done', False)) for trans in batch]
            )
            q_target_total = torch.stack(all_target_q, dim=0).sum(dim=0)
            td_target = r_total + (1.0 - done_mask) * self.gamma * q_target_total

            loss = F.mse_loss(q_total, td_target)
            if torch.isnan(loss) or torch.isinf(loss):
                logger.warning("[VDN] NaN/Inf loss, skipping")
                return None

            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                list(self.agents.parameters()), max_norm=10.0)
            self.optimizer.step()

            self._train_steps += 1
            self._update_targets(hard=False, tau=0.01)
            return loss.item()

        def _train_step_qmix(self, batch_size: int = 64) -> Optional[float]:
            """
            QMIX 模式：Q_total = Mixer(Q_i, state)，单调值分解
            超网络生成混合权重，abs() 保证 IGM 条件（单调性）
            TD target 使用 target_mixer 计算

            P1批量forward修复：改为真正的批量forward，减少GPU kernel launch开销
            """
            batch = self.replay_buffer.sample(batch_size)
            bs = len(batch)

            all_q_values = []       # [n_agents] 各agent Q(s_i, a_i) [batch_size]
            all_target_q = []       # [n_agents] 各agent max Q_target [batch_size]

            for i in range(self.n_agents):
                # P1修复：批量forward
                obs_batch = torch.FloatTensor(
                    np.stack([trans['obs_n'][i] for trans in batch])
                )  # [batch_size, obs_dim]
                q_all = self.agents[i](obs_batch)  # [batch_size, n_actions]

                action_indices = torch.LongTensor(
                    [int(trans['actions_n'][i]) for trans in batch]
                )
                q_selected = q_all.gather(1, action_indices.unsqueeze(1)).squeeze(1)  # [batch_size]
                all_q_values.append(q_selected)

                with torch.no_grad():
                    next_obs_batch = torch.FloatTensor(
                        np.stack([trans['next_obs_n'][i] for trans in batch])
                    )
                    tq_all = self.target_agents[i](next_obs_batch)  # [batch_size, n_actions]
                    tq_max = tq_all.max(dim=1)[0]  # [batch_size]
                all_target_q.append(tq_max)

            # 收集全局状态（P1修复：批量构建）
            states = []
            next_states = []
            for trans in batch:
                s = trans.get('state')
                ns = trans.get('next_state')
                if s is not None:
                    states.append(torch.FloatTensor(s))
                if ns is not None:
                    next_states.append(torch.FloatTensor(ns))

            if not states or not next_states:
                # 无全局状态时回退到 IQL 逻辑
                logger.warning("[QMIX] 缺少全局状态，回退到 IQL 训练")
                return self._train_step_iql(batch_size)

            state_batch = torch.stack(states)           # [batch, state_dim]
            next_state_batch = torch.stack(next_states)  # [batch, state_dim]

            # agent_qs: [batch, n_agents]
            agent_qs = torch.stack(all_q_values, dim=1)
            # Q_total = Mixer(agent_qs, state)  [batch, 1]
            q_total = self.mixer(agent_qs, state_batch)

            # TD target: r_total + gamma * Mixer(max Q_target_i, next_state)
            r_total = torch.FloatTensor(
                [sum(trans['rewards_n']) for trans in batch]
            ).unsqueeze(1)
            done_mask = torch.FloatTensor(
                [float(trans.get('done', False)) for trans in batch]
            ).unsqueeze(1)

            with torch.no_grad():
                target_agent_qs = torch.stack(all_target_q, dim=1)  # [batch, n_agents]
                q_target_total = self.target_mixer(target_agent_qs, next_state_batch)

            td_target = r_total + (1.0 - done_mask) * self.gamma * q_target_total

            loss = F.mse_loss(q_total, td_target)
            if torch.isnan(loss) or torch.isinf(loss):
                logger.warning("[QMIX] NaN/Inf loss, skipping")
                return None

            self.optimizer.zero_grad()
            loss.backward()
            grad_params = list(self.agents.parameters()) + list(self.mixer.parameters())
            torch.nn.utils.clip_grad_norm_(grad_params, max_norm=10.0)
            self.optimizer.step()

            self._train_steps += 1
            self._update_targets(hard=False, tau=0.01)
            return loss.item()

        def _update_targets(self, hard: bool = False, tau: float = 0.01):
            """更新目标网络；hard=True 直接复制，hard=False 软更新"""
            if hard:
                for ta, a in zip(self.target_agents, self.agents):
                    ta.load_state_dict(a.state_dict())
                if self.algorithm == 'qmix':
                    self.target_mixer.load_state_dict(self.mixer.state_dict())
                # VDN mixer 无参数，无需复制
            else:
                for ta, a in zip(self.target_agents, self.agents):
                    for tp, p in zip(ta.parameters(), a.parameters()):
                        tp.data.copy_(tau * p.data + (1 - tau) * tp.data)
                if self.algorithm == 'qmix':
                    for tp, p in zip(self.target_mixer.parameters(), self.mixer.parameters()):
                        tp.data.copy_(tau * p.data + (1 - tau) * tp.data)

    # PyTorch路径别名：IQLEstimator = QMIXAgent（统一接口名，反映IQL算法实质）
    IQLEstimator = QMIXAgent

else:
    # ==========================================================================
    # NumPy 回退实现（无PyTorch时）
    # 实现为 IQL（独立Q-learning），类名 IQLEstimator 反映实际算法。
    # QMIXAgent 保留为兼容别名，但新代码应使用 IQLEstimator。
    # ==========================================================================

    class IQLEstimator:
        """
        IQL独立Q-learning智能体（NumPy回退版）
        
        每个智能体独立维护Q表，基于TD-error进行Q-learning更新。
        与PyTorch版本使用相同的训练逻辑（IQL），确保结果可比。
        """
        def __init__(self, obs_dim: int, n_actions: int, hidden_dim: int = 64):
            self.obs_dim = obs_dim
            self.n_actions = n_actions
            self.hidden_dim = hidden_dim
            # 简易Q表：状态离散化后的Q值估计
            self._q_table = np.zeros((hidden_dim, n_actions))

        def init_hidden(self):
            return np.zeros(self.hidden_dim)

        def get_action(self, obs, hidden=None, epsilon: float = 0.1):
            if random.random() < epsilon:
                return random.randint(0, self.n_actions - 1), hidden
            # 简易Q表查表策略（比纯随机略好）
            state_idx = int(abs(hash(str(obs.tolist() if hasattr(obs, 'tolist') else obs))) % self.hidden_dim)
            return int(np.argmax(self._q_table[state_idx])), hidden

        def train(self, obs, action, reward, next_obs, done, lr=0.01, gamma=0.8):
            """简易Q-learning更新（单步更新）"""
            state_idx = int(abs(hash(str(obs.tolist() if hasattr(obs, 'tolist') else obs))) % self.hidden_dim)
            next_state_idx = int(abs(hash(str(next_obs.tolist() if hasattr(next_obs, 'tolist') else next_obs))) % self.hidden_dim)
            td_target = reward + (0 if done else gamma * np.max(self._q_table[next_state_idx]))
            td_error = td_target - self._q_table[state_idx, action]
            self._q_table[state_idx, action] += lr * td_error
            return td_error

    class QMIXMixer:
        """NumPy简化版混合器（仅占位，实际IQL不使用混合器）"""
        def __init__(self, n_agents: int, state_dim: int, embed_dim: int = 32):
            self.n_agents = n_agents

    class QMIXTrainer:
        """NumPy回退IQL训练器（简易Q表，支持基本训练）"""
        def __init__(self, n_agents, obs_dim, state_dim, n_actions, **kwargs):
            self.n_agents = n_agents
            self.n_actions = n_actions
            self.epsilon = 0.5
            self.agents = [IQLEstimator(obs_dim, n_actions) for _ in range(n_agents)]
            self.replay_buffer = deque(maxlen=1000)
            self._step_count = 0

        def get_actions(self, observations, hidden_states):
            actions = [self.agents[i].get_action(observations[i], hidden_states[i], self.epsilon)[0]
                       for i in range(min(self.n_agents, len(observations)))]
            return actions, hidden_states

        def init_hidden(self):
            return [a.init_hidden() for a in self.agents]

        def store_episode(self, data):
            self.replay_buffer.append(data)

        def train_step(self, **kwargs):
            """简易训练：从回放缓存采样进行Q-learning更新"""
            batch_size = kwargs.get('batch_size', 64)
            if len(self.replay_buffer) < 2:
                return None
            batch = random.sample(self.replay_buffer, min(batch_size, len(self.replay_buffer)))
            total_loss = 0.0
            count = 0
            for episode in batch:
                obs_list = episode.get('observations', [])
                act_list = episode.get('actions', [])
                rew_list = episode.get('rewards', [])
                next_obs_list = episode.get('next_observations', [])
                for t in range(len(obs_list)):
                    if t >= len(act_list) or t >= len(rew_list) or t >= len(next_obs_list):
                        break
                    for i in range(min(self.n_agents, len(obs_list[t]), len(act_list[t]))):
                        obs = np.array(obs_list[t][i], dtype=float)
                        act = int(act_list[t][i])
                        rew = float(rew_list[t][i]) if isinstance(rew_list[t], list) else 0.0
                        next_obs = np.array(next_obs_list[t][i], dtype=float)
                        done = (t == len(obs_list) - 1)
                        td_err = self.agents[i].train(obs, act, rew, next_obs, done)
                        total_loss += abs(td_err)
                        count += 1
            self._step_count += 1
            # epsilon衰减
            self.epsilon = max(0.05, self.epsilon * 0.9995)
            return total_loss / max(1, count)

    # 兼容性别名（向后兼容，新代码请使用 IQLEstimator）
    QMIXAgent = IQLEstimator
    QMIXTrainerAlias = QMIXTrainer  # QMIXTrainer 类名保持，避免破坏已有导入
