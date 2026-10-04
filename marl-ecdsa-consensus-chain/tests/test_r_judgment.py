"""
E7 — R 判据边界验证测试（支撑 C3 改写）

验证安全条件 f_max = R/(R+2)（R = 诚实权重 / 拜占庭权重）：
- 已知解析值（R=1 → 1/3；R=1.007 → ≈n/3 无增益；R=15 → 15/17）
- 复现路线 C PoC（R≈15, n=10/40% → β<1/3, CW-PBFT 安全）
- 复现 EXP-3（R≈1.007 → 与标准 PBFT 等价，无增益）
- run() 自检全部通过
"""
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = str(
    Path(__file__).resolve().parent.parent / "scripts" / "legacy" / "analysis"
)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import r_judgment_verification as rj  # noqa: E402


def test_formula_known_values():
    assert abs(rj.max_byzantine_fraction(1.0) - 1 / 3) < 1e-9
    assert abs(rj.max_byzantine_fraction(1.007) - 1 / 3) < 0.01
    assert abs(rj.max_byzantine_fraction(15.0) - 15 / 17) < 1e-9


def test_poc_reproduction():
    # R=15, n=10, 40% byz → β<1/3, CW-PBFT 安全
    beta = rj.byzantine_weight_fraction(0.40, 15.0)
    assert beta < 1 / 3
    assert rj.cw_pbft_safe(10, 4, 15.0)


def test_exp3_no_gain():
    # R≈1.007 → f_max ≈ n/3，与标准 PBFT 无增益
    fmax = rj.max_byzantine_fraction(1.007)
    assert abs(fmax - 1 / 3) < 0.01


def test_run_self_checks_pass():
    rep = rj.run()
    assert rep["all_checks_pass"] is True
    assert len(rep["self_checks"]) >= 6
