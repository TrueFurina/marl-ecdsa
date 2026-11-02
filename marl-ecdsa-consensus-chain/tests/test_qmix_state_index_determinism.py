"""QMIX NumPy 回退的状态离散化必须跨进程确定（2026-11-02）。

旧实现用内建 `hash(str(obs))`，它按 `PYTHONHASHSEED` 随机加盐：同一观测在不同
进程会落到不同 Q 表行，导致同一 seed/config 复跑结果不一致。项目在
`visualization/dashboard._demo_hash` 已因同款问题改掉内建 hash()，但 qmix 的
NumPy 回退漏了。
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent

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
