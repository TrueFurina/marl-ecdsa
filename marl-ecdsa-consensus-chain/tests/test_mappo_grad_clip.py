"""
MAPPO 第三算法单测（自进化 backlog #8：训练稳定性 — 梯度爆炸护栏）
覆盖：opt-in 梯度范数裁剪的「默认零改动」与「开启后正确钳制」两条路径。

设计原则（fail-closed，不影响已固化主结局 +6.54%）：
- 默认 max_grad_norm=None：train_step 与历史版本逐字一致，clip_grad_norm_ 永不调用。
- 显式开启：在 actor/critic 各自 optimizer.step() 之前对参数梯度做全局范数裁剪，
  裁剪后梯度总范数严格 ≤ 阈值。
通过标准：新增测试全过；既有 mappo 测试零回归。
"""
import logging
import types

import numpy as np
import pytest
import torch

from marl.algorithms.mappo import MAPPOTrainer, HAS_TORCH

logging.basicConfig(level=logging.CRITICAL)

pytestmark = pytest.mark.skipif(not HAS_TORCH, reason="需要 PyTorch")

N_AGENTS, OBS_DIM, STATE_DIM, N_ACTIONS = 3, 14, 18, 5


@pytest.fixture
def base_kwargs():
    return dict(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                n_actions=N_ACTIONS, hidden_dim=32, batch_episodes=2)


def _fake_episode(T=8):
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


def _fill(trainer):
    for _ in range(trainer.batch_episodes):
        trainer.get_actions([np.random.randn(OBS_DIM) for _ in range(N_AGENTS)])
        trainer.store_episode(_fake_episode())


class TestConfig:
    def test_default_is_none(self, base_kwargs):
        """默认关闭：max_grad_norm 必须为 None（保证历史行为不变）"""
        t = MAPPOTrainer(**base_kwargs)
        assert t.max_grad_norm is None

    def test_explicit_stored(self, base_kwargs):
        """显式开启：值被正确保存"""
        t = MAPPOTrainer(**base_kwargs, max_grad_norm=0.5)
        assert t.max_grad_norm == 0.5


class TestOptInWiring:
    def test_default_never_calls_clip(self, base_kwargs):
        """默认路径：clip_grad_norm_ 永不被调用（零行为改动）"""
        t = MAPPOTrainer(**base_kwargs)
        calls = []

        def _spy(*a, **k):
            calls.append((a, k))
            return 0.0

        orig = torch.nn.utils.clip_grad_norm_
        torch.nn.utils.clip_grad_norm_ = _spy
        try:
            _fill(t)
            t.train_step()
        finally:
            # 还原，避免污染其他测试
            torch.nn.utils.clip_grad_norm_ = orig
        assert calls == [], "默认 max_grad_norm=None 时不应调用裁剪"

    def test_optin_calls_clip_with_threshold(self, base_kwargs):
        """开启路径：actor 与 critic 各自调用裁剪，且 max_norm 等于配置阈值"""
        t = MAPPOTrainer(**base_kwargs, max_grad_norm=0.5)
        calls = []

        orig = torch.nn.utils.clip_grad_norm_
        def _spy(params, max_norm, *a, **k):
            p_list = list(params)
            calls.append({'params': p_list, 'max_norm': max_norm})
            return orig(p_list, max_norm, *a, **k)

        torch.nn.utils.clip_grad_norm_ = _spy
        try:
            _fill(t)
            t.train_step()
        finally:
            torch.nn.utils.clip_grad_norm_ = orig
        assert len(calls) >= 2, "至少 actor/critic 各裁剪一次"
        assert all(abs(c['max_norm'] - 0.5) < 1e-9 for c in calls)
        # actor 裁剪应作用于 agents 参数（参数数量与 agents 一致）
        assert any(len(c['params']) == len(list(t.agents.parameters())) for c in calls)


class TestClampCorrectness:
    def test_post_clip_norm_within_threshold(self, base_kwargs):
        """裁剪后 actor 参数梯度总范数严格 ≤ 阈值（含浮点容差）"""
        thr = 0.5
        t = MAPPOTrainer(**base_kwargs, max_grad_norm=thr)

        recorded = []
        orig_step = t.actor_opt.step          # 原始 bound method
        def _wrapped(self):
            # 此刻梯度已被裁剪：以 max_norm=inf 仅测量而不修改
            total = torch.nn.utils.clip_grad_norm_(
                list(t.agents.parameters()), float('inf'))
            recorded.append(float(total))
            orig_step()
        t.actor_opt.step = types.MethodType(_wrapped, t.actor_opt)

        _fill(t)
        t.train_step()

        assert recorded, "应至少记录一次 actor 梯度范数"
        for norm in recorded:
            assert 0.0 <= norm <= thr * (1 + 1e-5), f"裁剪后范数越界: {norm}"

    def test_training_still_finite_with_clip(self, base_kwargs):
        """开启裁剪后训练仍正常：返回有限损失且缓冲清空（on-policy 用完即弃）"""
        t = MAPPOTrainer(**base_kwargs, max_grad_norm=0.5)
        _fill(t)
        loss = t.train_step()
        assert loss is not None and np.isfinite(loss)
        assert len(t.buffer) == 0
