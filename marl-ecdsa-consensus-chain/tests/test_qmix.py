"""
QMIX / VDN 算法模块测试
覆盖 ReplayBuffer、VDNMixer、QMIXTrainer 的基础行为
（多算法值分解：IQL / VDN / QMIX，MARL-ECDSA 共识链）

2026-11-04：本文件的 import 是**收集期**依赖。``ReplayBuffer`` / ``VDNMixer``
只在 ``marl/algorithms/qmix.py`` 的 PyTorch 分支（``if HAS_TORCH:``）里定义，
NumPy 回退分支**刻意不提供**这两个名字（回退实现是纯 Q 表的 IQL，没有回放缓存、
也没有混合器）。因此在无 torch 的机器上 ``from ... import ReplayBuffer`` 直接
抛 ImportError —— pytest 把它记成**收集期错误**，导致整个 ``pytest tests/``
一条都不执行（实测 ``Interrupted: 2 errors during collection``，2259 条全灭）。

不伪造桩来让 import 成功：那会让本文件在回退路径上"绿"得毫无意义，正属于本项目
明令禁止的假通过。改为缺失时整模块 skip，理由写进报告；torch 可用时行为不变。
"""
import pytest

try:
    from marl.algorithms.qmix import ReplayBuffer, VDNMixer, QMIXTrainer
except ImportError as _exc:  # 无 torch：三个名字里的 ReplayBuffer/VDNMixer 不存在
    pytest.skip(
        "本文件锁的是 qmix 的 PyTorch 分支（ReplayBuffer / VDNMixer 只在该分支定义，"
        "NumPy 回退分支按设计不提供它们）；当前环境不可用：%s" % _exc,
        allow_module_level=True,
    )


class TestReplayBuffer:
    def test_add_and_len(self):
        rb = ReplayBuffer(capacity=100)
        assert len(rb) == 0
        rb.add({"obs": [0.1], "action": 1, "reward": 1.0})
        assert len(rb) == 1

    def test_capacity_eviction(self):
        rb = ReplayBuffer(capacity=10)
        for i in range(20):
            rb.add({"obs": [float(i)], "action": 0, "reward": 0.0})
        assert len(rb) == 10  # 超容量后 FIFO 淘汰

    def test_sample_batch(self):
        rb = ReplayBuffer(capacity=100)
        for i in range(50):
            rb.add({"obs": [float(i)], "action": 0, "reward": float(i)})
        batch = rb.sample(10)
        assert len(batch) == 10
        # 采样元素来自 buffer
        assert all(t in rb.buffer for t in batch)

    def test_sample_larger_than_buffer(self):
        rb = ReplayBuffer(capacity=100)
        rb.add({"obs": [1.0], "action": 0, "reward": 0.0})
        batch = rb.sample(50)
        assert len(batch) == 1  # 采样数不超过 buffer 大小


class TestVDNMixer:
    def test_vdn_sum(self):
        import torch
        mixer = VDNMixer()
        agent_qs = torch.tensor([[1.0, 2.0, 3.0], [0.5, 0.5, 1.0]])
        q_total = mixer.forward(agent_qs)
        assert q_total.shape == (2, 1)
        assert q_total[0, 0].item() == pytest.approx(6.0)
        assert q_total[1, 0].item() == pytest.approx(2.0)


class TestQMIXTrainerBasics:
    def test_trainer_init(self):
        trainer = QMIXTrainer(
            n_agents=3, obs_dim=14, state_dim=18, n_actions=5,
        )
        assert trainer is not None
        assert hasattr(trainer, "train_step") or hasattr(trainer, "update")

    def test_trainer_algorithm_modes(self):
        for algo in ["iql", "vdn", "qmix"]:
            trainer = QMIXTrainer(
                n_agents=3, obs_dim=14, state_dim=18, n_actions=5,
                algorithm=algo,
            )
            assert trainer is not None
