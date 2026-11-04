#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""QMIX 双路径契约：**同一段调用代码必须能驱动两套实现**。

背景
----
``marl/algorithms/qmix.py`` 是**一个模块、两套实现**，由模块级 ``HAS_TORCH`` 选择：

    if HAS_TORCH:   QMIXAgent / QMIXMixer / ReplayBuffer / VDNMixer / QMIXTrainer
    else:           IQLEstimator / QMIXMixer（占位） / QMIXTrainer（IQL 实现）

问题在于**覆盖被环境劈成两半**：
  * CI 跑 ``ubuntu-latest``，装了 torch → 只执行 PyTorch 分支，回退分支一行都不跑；
  * 开发机常无 torch → 只执行回退分支，PyTorch 分支一行都不跑。

于是回退实现里的任何回归，**CI 全绿也发现不了**，只有在某台无 torch 的机器上才炸。
``tests/test_torch_import_contract.py`` 已经用 stub 验证过「回退分支能被 import」，
但**没有验证它真的能干活** —— import 成功 ≠ 可被驱动。

本文件补的就是这一步：用同一个假 ``torch`` 包（``raise ModuleNotFoundError``）
把真 torch 遮蔽掉，在**任何环境**（包括 CI）都能强制走回退分支，然后跑一遍真实
训练动作。契约字段（动作个数 / 取值范围 / 是否产出损失）两边必须逐项相同。

不比较数值：模块自身警告「结果口径与 PyTorch 版不同，禁止跨实现混比」。
本文件锁的是**调用契约**，不是训练效果。

变异验证：把回退分支的 ``QMIXTrainer.train_step`` 改成永远返回 ``None``，
``test_numpy_fallback_is_drivable_by_the_shared_call_contract`` 必须 FAIL；
把 ``QMIXAgent = IQLEstimator`` 这行兼容别名删掉，``has_qmix_agent`` 契约必须 FAIL。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE = "marl.algorithms.qmix"

_STUB_ABSENT = 'raise ModuleNotFoundError("No module named \'torch\'", name="torch")\n'

# 探针正文：两套实现共用。刻意只用两边都有的入口，且
#   * 用 ``batch_size=`` 关键字调用（回退版是 **kwargs，位置传参会 TypeError）
#   * 存 2 个 episode（回退版要求 len(replay_buffer) >= 2 才训练，PyTorch 版按条数）
_PROBE = """
import json
from marl.algorithms.qmix import HAS_TORCH, QMIXTrainer

N_AG, OBS, ST, ACT = 2, 4, 8, 3
obs = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]

tr = QMIXTrainer(n_agents=N_AG, obs_dim=OBS, state_dim=ST, n_actions=ACT,
                 lr=1e-3, gamma=0.9)
hidden = tr.init_hidden()
acts, hidden2 = tr.get_actions(obs, hidden)

episode = {
    "observations": [[obs[0], obs[1]] for _ in range(4)],
    "actions": [[0, 1] for _ in range(4)],
    "rewards": [[1.0, 1.0] for _ in range(4)],
    "next_observations": [[obs[0], obs[1]] for _ in range(4)],
    "state_list": [[0.0] * ST for _ in range(4)],
    "done": False,
}
for _ in range(2):
    tr.store_episode(episode)

loss = tr.train_step(batch_size=4)

import marl.algorithms.qmix as m
print("@@RESULT@@" + json.dumps({
    "has_torch": HAS_TORCH,
    "n_actions_out": len(acts),
    "actions_are_ints": all(isinstance(a, int) or hasattr(a, "item") for a in acts),
    "in_range": all(0 <= int(a) < ACT for a in acts),
    "loss_is_none": loss is None,
    "has_qmix_agent": hasattr(m, "QMIXAgent"),
    "has_qmix_mixer": hasattr(m, "QMIXMixer"),
    "has_qmix_trainer": hasattr(m, "QMIXTrainer"),
}))
"""


def _make_absent_stub(tmp_path: Path) -> Path:
    """造一个会抛 ModuleNotFoundError 的假 torch 包，遮蔽真 torch。"""
    pkg = tmp_path / "torch"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(_STUB_ABSENT, encoding="utf-8")
    return tmp_path


def _probe(stub_dir: Path | None) -> dict:
    """在子进程里跑探针，返回解析后的契约字段。"""
    prelude = ["import sys", f"sys.path.insert(0, {str(REPO_ROOT)!r})"]
    if stub_dir is not None:
        prelude.insert(1, f"sys.path.insert(0, {str(stub_dir)!r})")
    code = "\n".join(prelude) + "\n" + textwrap.dedent(_PROBE)

    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"探针失败（rc={r.returncode}）：\n{out}"
    marker = "@@RESULT@@"
    assert marker in out, f"探针未产出结果标记：\n{out}"
    payload = out.split(marker, 1)[1].strip().splitlines()[0]
    return json.loads(payload)


# 两套实现必须逐项相同的契约字段。**不含数值类**（口径不同，禁止跨实现混比）。
_CONTRACT_KEYS = (
    "n_actions_out", "actions_are_ints", "in_range",
    "loss_is_none", "has_qmix_agent", "has_qmix_mixer", "has_qmix_trainer",
)


def _assert_contract(data: dict, label: str):
    """单侧契约：这段代码必须真的把训练器驱动起来，而不是"跑通就算过"。"""
    problems = []
    if data["n_actions_out"] != 2:
        problems.append("动作个数 %s ≠ n_agents(2)" % data["n_actions_out"])
    if not data["actions_are_ints"]:
        problems.append("动作不是整数（调用方会拿去做 list 下标）")
    if not data["in_range"]:
        problems.append("动作越界：必须在 [0, n_actions)")
    if data["loss_is_none"]:
        problems.append("train_step 返回 None —— 数据已足够，说明训练逻辑没被执行")
    for key in ("has_qmix_agent", "has_qmix_mixer", "has_qmix_trainer"):
        if not data[key]:
            problems.append("缺少公开名字 %s" % key[len("has_"):])
    assert not problems, "%s 未满足调用契约：\n%s\n原始结果：%s" % (
        label, "\n".join("  - " + p for p in problems), data)


# --------------------------------------------------------------------------- #
# 1. 回退分支：任何环境都必须被强制走一遍（CI 上这一步才真正补齐覆盖）
# --------------------------------------------------------------------------- #
def test_numpy_fallback_is_drivable_by_the_shared_call_contract(tmp_path):
    data = _probe(_make_absent_stub(tmp_path))
    assert data["has_torch"] is False, (
        "假 torch 没生效 —— 本测试的价值就在于**强制**走回退分支；"
        "若这里拿到 True，说明它在重复测 PyTorch 路径，回退分支仍然零覆盖。\n%s" % data)
    _assert_contract(data, "NumPy 回退分支")


# --------------------------------------------------------------------------- #
# 2. PyTorch 分支：可用时必须同样被驱动
# --------------------------------------------------------------------------- #
def test_pytorch_path_is_drivable_by_the_shared_call_contract():
    pytest.importorskip("torch", reason="本机无可用 PyTorch，无法驱动该分支")
    data = _probe(None)
    assert data["has_torch"] is True, (
        "torch 可导入，但模块解析出 HAS_TORCH=False —— 参考环境被静默改写。\n%s" % data)
    _assert_contract(data, "PyTorch 分支")


# --------------------------------------------------------------------------- #
# 3. 两条路径逐项对齐（这是"给出同样结论"的可判定形态）
# --------------------------------------------------------------------------- #
def test_the_two_paths_agree_on_every_contract_field(tmp_path):
    pytest.importorskip("torch", reason="本机无 torch：双向对齐需在有 torch 的环境（CI）完成")

    fallback = _probe(_make_absent_stub(tmp_path))
    pytorch = _probe(None)

    # 先证明这一步真的把两套实现都执行了（否则下面的字段比对是在拿自己比自己）
    assert {fallback["has_torch"], pytorch["has_torch"]} == {False, True}, (
        "本次没有同时驱动两条路径（has_torch 取值 %r / %r）—— "
        "字段比对会退化成「同一份实现自己比自己」"
        % (fallback["has_torch"], pytorch["has_torch"]))

    diffs = {k: (fallback.get(k), pytorch.get(k))
             for k in _CONTRACT_KEYS if fallback.get(k) != pytorch.get(k)}
    assert not diffs, (
        "两条路径的调用契约不一致（字段: (回退, PyTorch)）：\n%s\n"
        "注意：这里只比契约，不比数值 —— 口径本就不同。"
        % "\n".join("  - %s: %r" % (k, v) for k, v in sorted(diffs.items())))


# --------------------------------------------------------------------------- #
# 4. 自检：上面的契约断言必须真的会咬人（否则等于没有断言）
# --------------------------------------------------------------------------- #
_COMPLIANT = {
    "has_torch": False,
    "n_actions_out": 2,
    "actions_are_ints": True,
    "in_range": True,
    "loss_is_none": False,
    "has_qmix_agent": True,
    "has_qmix_mixer": True,
    "has_qmix_trainer": True,
}

_VIOLATIONS = [
    ("train_step 永远返回 None（训练逻辑没执行）", {"loss_is_none": True}),
    ("动作个数与 n_agents 不符", {"n_actions_out": 3}),
    ("动作越界", {"in_range": False}),
    ("动作不是整数", {"actions_are_ints": False}),
    ("兼容别名 QMIXAgent 被删", {"has_qmix_agent": False}),
    ("QMIXMixer 被删", {"has_qmix_mixer": False}),
    ("QMIXTrainer 被删", {"has_qmix_trainer": False}),
]


def test_contract_assertion_actually_rejects_violations():
    """逐项注入违规，每一处都必须被 `_assert_contract` 拦下。

    没有这条，`_assert_contract` 可能被改成恒真而无人察觉 ——
    那么前面三条测试即使全绿，也不代表两套实现真的被驱动。
    """
    # 负对照：合规输入必须通过（证明它不是"见谁都报错"）
    _assert_contract(dict(_COMPLIANT), "自检-合规基线")

    missed = []
    for label, patch in _VIOLATIONS:
        data = dict(_COMPLIANT, **patch)
        try:
            _assert_contract(data, "自检")
        except AssertionError:
            continue
        missed.append(label)

    assert not missed, (
        "以下违规没有被契约断言拦下（断言已退化为恒真）：\n%s"
        % "\n".join("  - " + m for m in missed))


