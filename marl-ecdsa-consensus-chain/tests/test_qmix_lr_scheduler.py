"""
QMIX 学习率调度自验收测试（自进化：backlog#8 衍生 — lr 调度，对齐 MAPPO 落地）
覆盖：opt-in 学习率调度的「默认零改动」与「开启后按调度衰减」两条路径。
与 test_mappo_lr_scheduler.py 同款验证思路，套用到 QMIXTrainer（公共 train_step 分发）。

设计原则（fail-closed，不影响已固化主结局 +6.54%）：
- 默认 lr_scheduler=None：train_step 与历史版本逐字一致，不创建/不调用调度器，lr 恒定。
- 显式开启：每个 train_step 完成一次更新后调用 scheduler.step() 一次，优化器 lr 按调度衰减。
通过标准：新增测试全过；既有 qmix 测试零回归。
"""
import logging

import numpy as np
import pytest

try:
    from marl.algorithms.qmix import QMIXTrainer  # PyTorch 分支定义
except ImportError as _exc:  # 无 torch：本文件锁的是 qmix 的 PyTorch 分支
    pytest.skip("QMIXTrainer 仅在 PyTorch 分支定义，当前环境不可用：%s" % _exc,
                allow_module_level=True)

logging.basicConfig(level=logging.CRITICAL)

N_AGENTS, OBS_DIM, STATE_DIM, N_ACTIONS = 3, 14, 18, 5


@pytest.fixture
def base_kwargs():
    return dict(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                n_actions=N_ACTIONS, hidden_dim=32, algorithm='iql')


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


def _fill(trainer, n_episodes=4):
    for _ in range(n_episodes):
        trainer.store_episode(_fake_episode())


class TestConfig:
    def test_default_is_none(self, base_kwargs):
        """默认关闭：lr_scheduler 必须为 None（保证历史行为不变）"""
        t = QMIXTrainer(**base_kwargs)
        assert t.lr_scheduler is None

    def test_explicit_factory_builds_scheduler(self, base_kwargs):
        """显式开启：工厂以优化器为参数构建出调度器实例"""
        t = QMIXTrainer(
            **base_kwargs,
            lr_scheduler=lambda opt: __import__('torch').optim.lr_scheduler.StepLR(opt, step_size=1, gamma=0.9),
        )
        assert t.lr_scheduler is not None


class TestOptInWiring:
    def test_default_never_steps_scheduler(self, base_kwargs):
        """默认路径：不创建调度器，lr 恒定且训练正常（零行为改动）"""
        t = QMIXTrainer(**base_kwargs)
        lr0 = t.optimizer.param_groups[0]['lr']
        _fill(t)
        loss = t.train_step(batch_size=8)
        lr1 = t.optimizer.param_groups[0]['lr']
        assert lr0 == lr1, "默认无调度器时 lr 不得变化"
        assert loss is not None and np.isfinite(loss)

    def test_optin_steps_scheduler_once_per_train_step(self, base_kwargs):
        """开启路径：每个 train_step 后 lr 按 StepLR(gamma=0.5, step_size=1) 衰减"""
        gamma = 0.5
        t = QMIXTrainer(
            **base_kwargs,
            lr_scheduler=lambda opt: __import__('torch').optim.lr_scheduler.StepLR(opt, step_size=1, gamma=gamma),
        )
        lr0 = t.optimizer.param_groups[0]['lr']
        _fill(t)
        t.train_step(batch_size=8)
        lr1 = t.optimizer.param_groups[0]['lr']
        assert abs(lr1 - lr0 * gamma) < 1e-9, f"一次 train_step 后 lr 应衰减为 {lr0 * gamma}，实际 {lr1}"
        # 第二次 train_step 继续衰减
        _fill(t)
        t.train_step(batch_size=8)
        lr2 = t.optimizer.param_groups[0]['lr']
        assert abs(lr2 - lr0 * gamma * gamma) < 1e-9

    def test_training_still_finite_with_scheduler(self, base_kwargs):
        """开启调度后训练仍正常：返回有限损失"""
        t = QMIXTrainer(
            **base_kwargs,
            lr_scheduler=lambda opt: __import__('torch').optim.lr_scheduler.StepLR(opt, step_size=1, gamma=0.9),
        )
        _fill(t)
        loss = t.train_step(batch_size=8)
        assert loss is not None and np.isfinite(loss)
