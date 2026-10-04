#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""torch 可用性契约：**装坏必须 fail-closed，不允许静默降级**。

背景
----
``marl/algorithms/qmix.py`` 与 ``mappo.py`` 各带两套实现（PyTorch 版 / NumPy 回退版），
由模块级常量 ``HAS_TORCH`` 选择。若用 ``except ImportError`` 兜住整个导入块，就会出现
一个危险误判：

* Windows 上 torch 装坏（典型：``c10.dll`` 缺失）抛的是
  ``ImportError: DLL load failed while importing _C`` —— 它**是** ``ImportError``；
* 于是被误判成「torch 未安装」→ ``HAS_TORCH=False`` → **算法被悄悄换成 NumPy 版**，
  实验照跑、结果照样"看起来正常"，但换台机器/重装环境就不可复现。

本测试用子进程 + 临时 ``sys.path`` 上的假 ``torch`` 包，分别模拟三种情形，
把这条契约钉死：

============  ==========================  ============================
情形           期望行为                     判据
============  ==========================  ============================
torch 不存在   允许回退                     ``HAS_TORCH=False``，退出码 0
torch 装坏     必须抛错（fail-closed）      退出码非 0
子模块缺失     必须抛错（fail-closed）      退出码非 0
============  ==========================  ============================

外加一条锚定：参考环境（本机有可用 torch 时）**必须**走 PyTorch 路径，因为论文全部数值
都产自该路径。

变异验证（证明本测试真的会咬人）：把 ``qmix.py``/``mappo.py`` 的
``except ModuleNotFoundError as exc:`` 改回 ``except ImportError:``，
``test_broken_torch_must_not_degrade_silently`` 必须 FAIL。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES = ["marl.algorithms.qmix", "marl.algorithms.mappo"]

_STUB_ABSENT = 'raise ModuleNotFoundError("No module named \'torch\'", name="torch")\n'
_STUB_BROKEN_DLL = (
    'raise ImportError("DLL load failed while importing _C: '
    'The specified module could not be found.")\n'
)
# torch 本体能导入、但里面没有 nn 子模块 → `import torch.nn` 抛
# ModuleNotFoundError(name='torch.nn')，与"torch 本身不存在"必须区分开
_STUB_NO_SUBMODULE = "__version__ = '0.0.0-stub'\n"


def _make_stub(tmp_path: Path, mode: str) -> Path:
    """在 tmp_path 下造一个假 ``torch`` 包，用于遮蔽真 torch。"""
    pkg = tmp_path / "torch"
    pkg.mkdir(parents=True, exist_ok=True)
    body = {
        "absent": _STUB_ABSENT,
        "broken_dll": _STUB_BROKEN_DLL,
        "no_submodule": _STUB_NO_SUBMODULE,
    }[mode]
    (pkg / "__init__.py").write_text(body, encoding="utf-8")
    return tmp_path


def _run_import(module: str, stub_dir: Path | None) -> tuple[int, str]:
    """在子进程里 ``import module``，返回 ``(returncode, 合并输出)``。

    假 torch 目录插在 ``sys.path[0]``，从而优先于 site-packages 里的真 torch。
    """
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONIOENCODING": "utf-8"}
    prelude = ["import sys", f"sys.path.insert(0, {str(REPO_ROOT)!r})"]
    if stub_dir is not None:
        prelude.insert(1, f"sys.path.insert(0, {str(stub_dir)!r})")
    code = textwrap.dedent(
        "\n".join(prelude) + f"\nimport {module} as m\nprint('HAS_TORCH=', m.HAS_TORCH)\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# --------------------------------------------------------------------------- #
# 1. torch 确实不存在 → 允许回退（这是唯一被允许的降级）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", MODULES)
def test_torch_absent_falls_back_to_numpy(module, tmp_path):
    rc, out = _run_import(module, _make_stub(tmp_path, "absent"))
    assert rc == 0, f"{module}：torch 缺失时应正常回退到 NumPy 实现，却失败了：\n{out}"
    assert "HAS_TORCH= False" in out, f"{module}：torch 缺失时 HAS_TORCH 应为 False：\n{out}"


# --------------------------------------------------------------------------- #
# 2. torch 装坏（DLL 加载失败）→ 必须 fail-closed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", MODULES)
def test_broken_torch_must_not_degrade_silently(module, tmp_path):
    rc, out = _run_import(module, _make_stub(tmp_path, "broken_dll"))
    assert rc != 0, (
        f"{module}：torch 装坏（DLL 加载失败）时**静默降级**了。\n"
        f"这意味着算法被悄悄替换成 NumPy 版，实验结论不再与论文口径一致。\n"
        f"必须 fail-closed（抛错），而不是回退。\n{out}"
    )


# --------------------------------------------------------------------------- #
# 3. torch 在、但子模块缺失 → 同样必须 fail-closed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", MODULES)
def test_torch_missing_submodule_must_not_degrade(module, tmp_path):
    rc, out = _run_import(module, _make_stub(tmp_path, "no_submodule"))
    assert rc != 0, (
        f"{module}：torch 存在但子模块缺失时静默降级了 —— 这属于「装坏」，不是「未安装」。\n"
        f"必须 fail-closed。\n{out}"
    )


# --------------------------------------------------------------------------- #
# 4. 锚定参考环境：有可用 torch 就必须走 PyTorch 路径
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", MODULES)
def test_reference_env_uses_pytorch_path(module):
    pytest.importorskip("torch", reason="本机无可用 PyTorch，无法锚定参考路径")
    rc, out = _run_import(module, None)
    assert rc == 0, f"{module}：参考环境下导入失败：\n{out}"
    assert "HAS_TORCH= True" in out, (
        f"{module}：本机 torch 可导入，但模块解析出的 HAS_TORCH 不是 True —— "
        f"说明有人在静默改写参考环境。\n{out}"
    )
