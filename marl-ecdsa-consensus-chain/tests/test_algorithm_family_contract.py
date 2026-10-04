"""IQL / VDN / QMIX 三算法的实现契约与行为回归（架构审查 F9）。

背景：论文第 4/6 章与 E13/E14 的**核心对比就是 IQL vs VDN vs QMIX**，而三者在实现上
共用同一个 ``QMIXTrainer`` 类与同一条网络构造路径（``self.agents`` / optimizer 装配）。
既有测试仅做"能构造出来"的冒烟，对三条分支**零行为断言**——任何"改动一个算法却意外
影响另两个"的基线耦合都会静默通过。

本文件把三者**可观测的实现差异**固化为契约。设计原则：
    只做只读断言，**不改任何实现**——改动 VDN 的计算路径即便数学等价，也会因浮点求和
    顺序变化而破坏已有实验结果的精确复现（本项目铁律：数据文件+字段+统计检验三件套）。

发现记录（供后续决策，本测试只固化现状）：
    ``_train_step_vdn`` **不使用** ``self.mixer``，而是手工 ``torch.stack(...).sum(0)``；
    ``VDNMixer`` 因此是"装配但不参与计算"的装饰性属性，且其 ``forward`` 只收 1 个参数，
    而 ``_train_step_qmix`` 调用 ``self.mixer(agent_qs, state)``（2 个参数）。
    → 见 ``test_vdn_and_qmix_mixer_signatures_differ``：该断言的作用是**阻止**未来任何
      "统一调用签名"的重构把 VDN 打断。
"""
import inspect
import random

import numpy as np
import pytest

from marl.algorithms.qmix import QMIXMixer, QMIXTrainer, VDNMixer


N_AGENTS, OBS_DIM, STATE_DIM, N_ACTIONS = 3, 8, 12, 4
ALGOS = ("iql", "vdn", "qmix")


def _make_trainer(algo, **kw):
    return QMIXTrainer(
        n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
        n_actions=N_ACTIONS, algorithm=algo, **kw
    )


def _fill(trainer, n=64, seed=0):
    """灌入 n 条完整的 transition（含三条分支各自需要的字段）。"""
    rng = np.random.RandomState(seed)
    for _ in range(n):
        trainer.store_transition({
            "obs_n": [rng.randn(OBS_DIM).astype(np.float32) for _ in range(N_AGENTS)],
            "actions_n": [int(rng.randint(N_ACTIONS)) for _ in range(N_AGENTS)],
            "rewards_n": [float(rng.randn()) for _ in range(N_AGENTS)],
            "next_obs_n": [rng.randn(OBS_DIM).astype(np.float32) for _ in range(N_AGENTS)],
            "state": rng.randn(STATE_DIM).astype(np.float32),
            "next_state": rng.randn(STATE_DIM).astype(np.float32),
            "done": False,
        })


# ---------------------------------------------------------------- 结构契约

class TestMixerWiring:
    """三个算法各自装配什么 mixer —— 这是"值分解家族"最本质的差异。"""

    @pytest.mark.parametrize("algo,expected", [
        ("iql", None),
        ("vdn", VDNMixer),
        ("qmix", QMIXMixer),
    ])
    def test_mixer_type_matches_algorithm(self, algo, expected):
        t = _make_trainer(algo)
        if expected is None:
            assert t.mixer is None, f"{algo} 不应有 mixer（独立 Q 学习）"
        else:
            assert isinstance(t.mixer, expected), f"{algo} 的 mixer 类型应为 {expected.__name__}"

    def test_qmix_has_more_trainable_params_than_iql(self):
        """qmix 的优化器须包含 mixer 参数，iql 不含 —— 否则 mixer 不参与训练。"""
        n_iql = sum(len(g["params"]) for g in _make_trainer("iql").optimizer.param_groups)
        n_qmix = sum(len(g["params"]) for g in _make_trainer("qmix").optimizer.param_groups)
        assert n_qmix > n_iql, "qmix 的优化器参数应多于 iql（多出 mixer 参数）"

    def test_vdn_has_no_extra_trainable_params(self):
        """VDN 的 mixer 无参数（Q_total = sum(Q_i)），故优化器参数数应与 iql 相同。"""
        n_iql = sum(len(g["params"]) for g in _make_trainer("iql").optimizer.param_groups)
        n_vdn = sum(len(g["params"]) for g in _make_trainer("vdn").optimizer.param_groups)
        assert n_vdn == n_iql, "VDNMixer 无参数，优化器参数数不应多于 iql"


# ---------------------------------------------------------------- 行为契约

class TestMixerSemantics:
    """mixer 的数学语义 —— 值分解的 IGM 条件是论文论证的基础。"""

    def test_vdn_mixer_is_exact_sum(self):
        import torch
        mixer = VDNMixer()
        qs = torch.tensor([[1.0, 2.0, 3.0], [0.5, 0.5, 1.0], [-1.0, 2.0, 0.0]])
        out = mixer.forward(qs)
        assert out.shape == (3, 1)
        assert torch.allclose(out.squeeze(-1), qs.sum(dim=-1)), "VDN 必须是精确求和"

    def test_vdn_mixer_output_independent_of_agent_order(self):
        """求和与 agent 顺序无关（VDN 的可交换性）。"""
        import torch
        mixer = VDNMixer()
        qs = torch.tensor([[1.0, 2.0, 3.0]])
        perm = torch.tensor([[3.0, 1.0, 2.0]])
        assert torch.allclose(mixer.forward(qs), mixer.forward(perm)), \
            "VDN 求和应与 agent 顺序无关"

    def test_qmix_mixer_depends_on_state(self):
        """QMIX 用超网络生成混合权重 → 同一组 agent_q 配不同 state 必须给出不同输出。"""
        import torch
        torch.manual_seed(0)
        mixer = QMIXMixer(N_AGENTS, STATE_DIM)
        qs = torch.tensor([[1.0, 2.0, 3.0]])
        s1 = torch.zeros(1, STATE_DIM)
        s2 = torch.ones(1, STATE_DIM)
        assert not torch.allclose(mixer(qs, s1), mixer(qs, s2)), \
            "QMIX 输出必须依赖 state（否则退化为 VDN）"

    def test_qmix_mixer_monotonic_in_each_agent_q(self):
        """IGM 条件：单个 agent_q 增大，Q_total 不得减小（torch.abs 保证的单调性）。"""
        import torch
        torch.manual_seed(0)
        mixer = QMIXMixer(N_AGENTS, STATE_DIM)
        state = torch.randn(1, STATE_DIM)
        base = torch.tensor([[0.0, 0.0, 0.0]])
        prev = mixer(base, state).item()
        for i in range(N_AGENTS):
            bumped = base.clone()
            bumped[0, i] = 1.0
            cur = mixer(bumped, state).item()
            assert cur >= prev - 1e-6, f"第 {i} 个 agent_q 增大时 Q_total 反而减小，违反单调性"


# ---------------------------------------------------------------- 接口契约（防重构）

class TestMixerInterfaceContract:
    """固化一个**已知的不一致**，防止未来"统一签名"的重构把 VDN 打断。

    ``_train_step_vdn`` 不走 mixer（手工 sum），因此 ``VDNMixer.forward(qs)`` 单参数
    并不报错；但 ``_train_step_qmix`` 调 ``self.mixer(qs, state)`` 双参数。若有人为了
    "统一接口"把两者都改成双参数（或都改成单参数）而不改调用点，VDN 或 QMIX 会立刻崩。
    """

    def test_vdn_and_qmix_mixer_signatures_differ(self):
        def n_pos(fn):
            return len([p for p in inspect.signature(fn).parameters if p != "self"])
        assert n_pos(VDNMixer.forward) == 1, "VDNMixer.forward 现状为单参数（agent_qs）"
        assert n_pos(QMIXMixer.forward) == 2, "QMIXMixer.forward 现状为双参数（agent_qs, state）"

    def test_vdn_training_path_does_not_call_mixer(self):
        """VDN 分支手工求和，不调 self.mixer —— 该事实被固化，改动它需同步重跑 VDN 实验。"""
        src = inspect.getsource(QMIXTrainer._train_step_vdn)
        assert "self.mixer" not in src, \
            "VDN 分支若开始使用 self.mixer，计算路径改变 → 必须重跑并重新登记 VDN 实验"


# ---------------------------------------------------------------- 行为回归（核心）

class TestAlgorithmPathsAreDistinct:
    """最关键：证明三者不是"同一条路径换个名字"。"""

    @pytest.mark.parametrize("algo", ALGOS)
    def test_train_step_runs_and_returns_finite_loss(self, algo):
        import torch
        torch.manual_seed(0)
        random.seed(0)
        t = _make_trainer(algo)
        _fill(t, n=64, seed=1)
        loss = t.train_step(batch_size=32)
        assert loss is not None, f"{algo}: buffer 已够，train_step 不应返回 None"
        assert np.isfinite(loss), f"{algo}: loss 必须是有限数，实得 {loss}"

    def test_three_algorithms_produce_different_losses(self):
        """同 seed / 同数据 / 同采样顺序下，三者的 loss 不应完全相同。

        若三者 loss 一致，说明 algorithm 分发未生效（三者跑了同一条路径）——
        这正是架构审查 F9 担心的"实验基线耦合"。本断言是该风险的守门人。
        """
        import torch
        losses = {}
        for algo in ALGOS:
            torch.manual_seed(4242)
            np.random.seed(4242)
            random.seed(4242)
            t = _make_trainer(algo)
            _fill(t, n=64, seed=99)
            torch.manual_seed(31337)
            random.seed(31337)           # 固定采样顺序 → batch 内容一致
            losses[algo] = float(t.train_step(batch_size=32))

        assert all(np.isfinite(v) for v in losses.values()), f"出现非有限 loss: {losses}"
        uniq = {round(v, 8) for v in losses.values()}
        assert len(uniq) >= 2, (
            f"三种算法的 loss 完全相同 {losses} —— algorithm 分发可能失效（基线耦合）"
        )

    def test_qmix_updates_mixer_params_but_iql_has_none(self):
        """qmix 训练一步后 mixer 参数应发生变化（证明 mixer 真的参与计算）。"""
        import torch
        torch.manual_seed(0)
        random.seed(0)
        t = _make_trainer("qmix")
        _fill(t, n=64, seed=3)
        before = [p.detach().clone() for p in t.mixer.parameters()]
        t.train_step(batch_size=32)
        after = list(t.mixer.parameters())
        assert any(not torch.equal(b, a) for b, a in zip(before, after)), \
            "qmix 训练后 mixer 参数未变化，说明 mixer 未参与梯度更新"
        assert t.__class__ and _make_trainer("iql").mixer is None


# ---------------------------------------------------------------- 遗留入口优先级

class TestLegacyEntryPrecedence:
    """``qmix.py:191-198`` 的三入口优先级：algorithm > use_vdn > use_iql。"""

    def test_algorithm_wins_over_use_iql(self):
        t = _make_trainer("vdn", use_iql=True)
        assert t.algorithm == "vdn", "显式 algorithm 应优先于 use_iql"

    def test_algorithm_wins_over_use_vdn(self):
        t = _make_trainer("qmix", use_vdn=True)
        assert t.algorithm == "qmix", "显式 algorithm 应优先于 use_vdn"

    def test_use_vdn_maps_to_vdn(self):
        t = QMIXTrainer(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                        n_actions=N_ACTIONS, use_vdn=True)
        assert t.algorithm == "vdn"

    def test_use_vdn_false_maps_to_iql(self):
        t = QMIXTrainer(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                        n_actions=N_ACTIONS, use_vdn=False)
        assert t.algorithm == "iql"

    def test_default_is_iql(self):
        t = QMIXTrainer(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                        n_actions=N_ACTIONS)
        assert t.algorithm == "iql", "默认算法应为 iql（use_iql=True）"

    def test_use_iql_false_maps_to_qmix(self):
        t = QMIXTrainer(n_agents=N_AGENTS, obs_dim=OBS_DIM, state_dim=STATE_DIM,
                        n_actions=N_ACTIONS, use_iql=False)
        assert t.algorithm == "qmix"
