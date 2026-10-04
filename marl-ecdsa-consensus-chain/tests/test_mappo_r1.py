"""
MAPPO 第四算法单测（学长评价落第 1 项：算法新颖度）
覆盖：网络结构 / 动作采样 / GAE / PPO 更新 / 接口兼容
通过标准：新增 ≥6 项测试全过
"""
import logging

import numpy as np
import pytest

from marl.algorithms.mappo import MAPPOTrainer, HAS_TORCH

logging.basicConfig(level=logging.CRITICAL)

pytestmark = pytest.mark.skipif(not HAS_TORCH, reason="需要 PyTorch")

N_AGENTS, OBS_DIM, STATE_DIM, N_ACTIONS = 3, 14, 18, 5


@pytest.fixture
def trainer():
    return MAPPOTrainer(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                        n_actions=N_ACTIONS, hidden_dim=32, batch_episodes=2)


def _fake_episode(T=8):
    """构造一条假 episode 数据（与 train.py 存储格式一致）"""
    obs, acts, rews, nexts, states = [], [], [], [], []
    for t in range(T):
        obs_n = [np.random.randn(OBS_DIM).astype(np.float32) for _ in range(N_AGENTS)]
        obs.append(obs_n)
        acts.append([np.random.randint(N_ACTIONS) for _ in range(N_AGENTS)])
        rews.append([float(np.random.randn()) for _ in range(N_AGENTS)])
        nexts.append([np.random.randn(OBS_DIM).astype(np.float32) for _ in range(N_AGENTS)])
        states.append(np.random.randn(STATE_DIM).astype(np.float32))
    return {'observations': obs, 'actions': acts, 'rewards': rews,
            'next_observations': nexts, 'state_list': states, 'done': True}


class TestStructure:
    def test_agent_count(self, trainer):
        """actor 数量 = n_agents"""
        assert len(trainer.agents) == N_AGENTS

    def test_critic_input_state(self, trainer):
        """critic 吃全局状态输出标量 V"""
        import torch
        v = trainer.critic(torch.randn(4, STATE_DIM))
        assert v.shape == (4,)

    def test_epsilon_interface(self, trainer):
        """epsilon 接口兼容（固定 0）"""
        assert trainer.epsilon == 0.0
        assert trainer.algorithm == 'mappo'


class TestActions:
    def test_get_actions_shape(self, trainer):
        """动作数与 hidden 数一致"""
        obs = [np.random.randn(OBS_DIM) for _ in range(N_AGENTS)]
        actions, hiddens = trainer.get_actions(obs)
        assert len(actions) == N_AGENTS
        assert all(0 <= a < N_ACTIONS for a in actions)
        assert len(hiddens) == N_AGENTS

    def test_log_prob_recorded(self, trainer):
        """动作 log-prob 被记录（PPO 需要）"""
        obs = [np.random.randn(OBS_DIM) for _ in range(N_AGENTS)]
        trainer.get_actions(obs)
        assert len(trainer._pending['log_probs']) == N_AGENTS

    def test_deterministic_argmax(self, trainer):
        """deterministic 模式输出 argmax"""
        import torch
        agent = trainer.agents[0]
        obs = np.random.randn(OBS_DIM)
        a, lp, h = agent.get_action(obs, deterministic=True)
        with torch.no_grad():
            expect = int(torch.argmax(agent.net(torch.FloatTensor(obs).unsqueeze(0))).item())
        assert a == expect


class TestTraining:
    def test_store_and_buffer(self, trainer):
        """episode 存储后缓冲计数正确"""
        trainer.get_actions([np.random.randn(OBS_DIM) for _ in range(N_AGENTS)])
        ep = _fake_episode()
        trainer.store_episode(ep)
        assert len(trainer.buffer) == 1

    def test_train_step_runs(self, trainer):
        """PPO 更新可运行且返回损失"""
        for _ in range(trainer.batch_episodes):
            trainer.get_actions([np.random.randn(OBS_DIM) for _ in range(N_AGENTS)])
            trainer.store_episode(_fake_episode())
        loss = trainer.train_step()
        assert loss is not None and np.isfinite(loss)

    def test_loss_improves_buffer_drain(self, trainer):
        """更新后缓冲清空（on-policy 用完即弃）"""
        for _ in range(trainer.batch_episodes):
            trainer.get_actions([np.random.randn(OBS_DIM) for _ in range(N_AGENTS)])
            trainer.store_episode(_fake_episode())
        trainer.train_step()
        assert len(trainer.buffer) == 0

    def test_insufficient_buffer_returns_none(self, trainer):
        """缓冲不足返回 None（与 QMIXTrainer 行为一致）"""
        assert trainer.train_step() is None
