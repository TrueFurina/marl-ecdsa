"""
E6 攻击扩类测试（3 → 6 类）+ 批量统计（≥50 次/类 + Wilson 95% CI）

覆盖新增 3 类攻击（Sybil / k 值重用 / 长程）的拦截语义，
以及对全部 6 类攻击的批量拦截率统计断言（有BC 模式应 100% 拦截）。
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPT_DIR = str(
    Path(__file__).resolve().parent.parent / "scripts" / "legacy" / "analysis"
)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import attack_defense_demo as demo  # noqa: E402

NEW_ATTACKS = {
    "sybil_attack": demo.demo_sybil_attack,
    "k_reuse_attack": demo.demo_k_reuse_attack,
    "long_range_attack": demo.demo_long_range_attack,
}


@pytest.mark.parametrize("name,fn", list(NEW_ATTACKS.items()))
def test_new_attack_blocked(name, fn):
    kd = tempfile.mkdtemp()
    try:
        res = fn(key_dir=kd)
    finally:
        shutil.rmtree(kd, ignore_errors=True)
    assert res["attack_type"] == name
    assert res["no_bc"]["attack_successful"] is True, "无BC 基线应被攻破"
    assert res["with_bc"]["attack_successful"] is False, "有BC 应拦截攻击"
    assert res["with_bc"].get("blocked") is True


def test_e6_batch_defense_rate_100pct():
    """E6 要求每类 ≥50 次 + Wilson CI；有BC 模式应 100% 拦截。"""
    stats = demo.run_attack_batch(n_trials=50)
    assert len(stats) == 6, "应覆盖全部 6 类攻击"
    for s in stats:
        assert s["trials"] == 50
        assert s["blocked"] == 50, f"{s['attack_type']} 拦截数应=50"
        assert s["defense_rate"] == 1.0
        lo, hi = s["wilson_ci_95"]
        assert lo <= 1.0 <= hi
        assert abs(hi - 1.0) < 1e-9  # 100% 上限


def test_wilson_ci_monotonic():
    """Wilson CI 下限应随拦截数增加而不低于 0.9（50/50 时）。"""
    lo, hi = demo._wilson_ci(50, 50)
    assert lo >= 0.90
    assert hi <= 1.0
