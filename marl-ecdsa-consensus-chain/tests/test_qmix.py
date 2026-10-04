"""
QMIX / VDN 算法模块测试
覆盖 ReplayBuffer、VDNMixer、QMIXTrainer 的基础行为
（多算法值分解：IQL / VDN / QMIX，MARL-ECDSA 共识链）
"""
import pytest

from marl.algorithms.qmix import ReplayBuffer, VDNMixer, QMIXTrainer


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
