"""QMIX NumPy 回退的状态离散化必须跨进程确定（2026-11-02）。

旧实现用内建 `hash(str(obs))`，它按 `PYTHONHASHSEED` 随机加盐：同一观测在不同
进程会落到不同 Q 表行，导致同一 seed/config 复跑结果不一致。项目在
`visualization/dashboard._demo_hash` 已因同款问题改掉内建 hash()，但 qmix 的
NumPy 回退漏了。

**本测只对「没有 torch」时的 NumPy 回退路径有效**（2026-11-03 补）：
`_state_index` 是回退实现 `IQLEstimator` 的方法；torch 可用时 `IQLEstimator` 指向
torch 版 `QMIXAgent`，它根本没有这个方法，`HAS_TORCH` 为真时整模块 skip。
覆盖分工是刻意的：
  * 本文件 —— CI 的 `安全不变量` 门（只装 numpy + cryptography，**无 torch**）
    走的正是回退路径，由它覆盖；
  * 全量 `pytest tests/`（装了 torch）—— 回退路径不生效，跳过而不是假通过。
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent

try:
    from marl.algorithms.qmix import HAS_TORCH as _HAS_TORCH
except Exception:          # 导入不了就让下面的用例自己报错，不在这里吞掉
    _HAS_TORCH = False

pytestmark = pytest.mark.skipif(
    _HAS_TORCH,
    reason="本测锁的是 QMIX 的 NumPy 回退路径；torch 可用时该路径不生效"
           "（IQLEstimator 指向 torch 实现，没有 _state_index）。"
           "回退路径由 CI 的『安全不变量』门（只装 numpy+cryptography）覆盖。",
)

_CODE = (
    "import numpy as np;"
    "from marl.algorithms.qmix import IQLEstimator;"
    "e = IQLEstimator(3, 4);"
    "print(e._state_index(np.array([1.0, 2.0, 3.0])))"
)


def _run_with_hashseed(seed: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT))
    return subprocess.check_output(
        [sys.executable, "-c", _CODE], env=env, cwd=str(ROOT), text=True
    ).strip()


def test_state_index_is_stable_across_pythonhashseed():
    """不同 PYTHONHASHSEED 的进程必须给出同一个状态索引。"""
    a = _run_with_hashseed("0")
    b = _run_with_hashseed("1")
    assert a == b, f"状态索引随 PYTHONHASHSEED 变化：{a} != {b}"


def test_state_index_in_range_and_deterministic():
    from marl.algorithms.qmix import IQLEstimator

    e = IQLEstimator(3, 4, hidden_dim=64)
    obs = np.array([1.0, 2.0, 3.0])
    idx1 = e._state_index(obs)
    idx2 = e._state_index(obs)
    assert idx1 == idx2
    assert 0 <= idx1 < 64
