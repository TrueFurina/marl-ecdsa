#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E14 QMIX 同批（n=30）**合作率**分段复算器（NR-102 的复算脚本）。

背景
----
设计报告 §4.6.2 曾写「合作率呈同向模式（late 段 Δ=+0.039，p=0.0094）」，
该数值在 number_registry.json 中**无出处**：它实为
``results/dispatch_20260921/e14_qmix_temporal_report.json`` 里 **n=20 扩种前**
那一批的 ``windows_coop.late``（delta=0.0386 / welch_p=0.00943），
2026-10-03 数据扩种到 n=30 后该报告未同步重跑，材料却沿用了旧值。

本脚本用**扩种后的 n=30 同批数据**（e14_qmix_seed*.json / e14pure_qmix_seed*.json，
各 30 个文件、seed 100–129 对齐）重新计算合作率分段统计，
为登记簿新条目 NR-102 提供可复算的 declared 值。

口径（与 NR-85 完全一致，仅把字段 env_rewards 换成 cooperation_rates）
------------------------------------------------------------------
* 字段：``cooperation_rates``（长度 3000 的逐回合序列）
* 窗口：early[0:1000] / mid[1000:2000] / late[2000:3000]
* 逐 seed 先在窗口内取均值 → 再做 bc vs pure 的 Welch 检验（assurance_common，标准库实现）
* 统计量与 NR-85 同源同法：``assurance_common.two_sample_stats``

自证（fail-closed）
------------------
脚本先复算 **env_rewards** 三个窗口，逐条比对 NR-85 的 declared；
任一条不吻合即打印 [FAIL] 并以退出码 1 结束——**不复现 NR-85 就不产出合作率结论**，
防止用错口径的数据冒充。

产物
----
``results/dispatch_20260921/e14_qmix_coop_windows_n30_report.json``
（经 ``assurance_common.safe_write_json`` 写出，**默认绝不覆盖**，
同名已存在则另存 ``<stem>_<时间戳>.json``）。

用法
----
    python -X utf8 scripts/legacy/experiments/analyze_e14_qmix_coop_windows_n30.py
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
REPO = HERE.parents[2]                       # marl-ecdsa-consensus-chain/
sys.path.insert(0, str(REPO / "scripts"))    # assurance_common
import assurance_common as ac                # noqa: E402

DISPATCH = REPO / "results" / "dispatch_20260921"
OUT_PATH = DISPATCH / "e14_qmix_coop_windows_n30_report.json"

#: 与 NR-85 / analyze_e14_qmix_temporal.py 相同的窗口定义
WINDOWS: dict[str, tuple[int, int]] = {
    "early": (0, 1000),
    "mid": (1000, 2000),
    "late": (2000, 3000),
}

#: NR-85 declared（env_rewards，n=30 扩种后）—— 用来自证本脚本口径正确
NR85_DECLARED: dict[str, tuple[float, float, float]] = {
    "early": (0.1612, 0.75249, 0.0818),
    "mid": (1.3101, 0.18221, 0.3491),
    "late": (4.5056, 0.00309, 0.7998),
}

#: 复算容差（与 NR-85 条目 tolerance 一致量级）
TOL_ABS = 0.01
TOL_P = 0.001


def _load(tag: str, algo: str = "qmix") -> list[dict]:
    """按 tag 读取该臂全部 seed 结果（排序，确定性）。"""
    fs = sorted(glob.glob(str(DISPATCH / f"{tag}_{algo}_seed*.json")))
    return [json.load(open(f, encoding="utf-8")) for f in fs]


def _per_seed_mean(records: list[dict], field: str, lo: int, hi: int) -> list[float]:
    """逐 seed 在窗口 [lo, hi) 内取均值（与 NR-27/NR-85 的 slice 口径一致）。"""
    return [st.mean(r[field][lo:hi]) for r in records]


def _window_stats(bc: list[dict], pu: list[dict], field: str) -> dict[str, dict]:
    """计算全部窗口的两样本统计量。"""
    out: dict[str, dict] = {}
    for name, (lo, hi) in WINDOWS.items():
        a = _per_seed_mean(bc, field, lo, hi)
        b = _per_seed_mean(pu, field, lo, hi)
        s = ac.two_sample_stats(a, b)
        out[name] = {
            "window": f"{name}[{lo}:{hi}]",
            "bc_mean": round(s["mean_a"], 6),
            "pure_mean": round(s["mean_b"], 6),
            "sd_bc": round(s["sd_a"], 6),
            "sd_pure": round(s["sd_b"], 6),
            "n_bc": s["n_a"],
            "n_pure": s["n_b"],
            "delta": round(s["mean_a"] - s["mean_b"], 6),
            "welch_p": round(s["welch_p"], 6),
            "cohens_d": round(s["cohens_d"], 6),
        }
    return out


def _selfcheck_env(bc: list[dict], pu: list[dict]) -> list[str]:
    """复算 env_rewards 窗口并比对 NR-85 declared；返回问题列表（空 = 通过）。"""
    env = _window_stats(bc, pu, "env_rewards")
    problems: list[str] = []
    print("[自检] 复算 env_rewards 窗口，与 NR-85 declared 比对：")
    for name, (d_dec, p_dec, dd_dec) in NR85_DECLARED.items():
        got = env[name]
        dd, dp, ddd = (abs(got["delta"] - d_dec), abs(got["welch_p"] - p_dec),
                       abs(got["cohens_d"] - dd_dec))
        ok = dd <= TOL_ABS and dp <= TOL_P and ddd <= TOL_ABS
        print(f"       {name:5s} Δ={got['delta']:+.4f}（登记 {d_dec:+.4f}, 差 {dd:.4f}）  "
              f"p={got['welch_p']:.5f}（登记 {p_dec:.5f}, 差 {dp:.5f}）  "
              f"d={got['cohens_d']:.4f}（登记 {dd_dec:.4f}, 差 {ddd:.4f}）  "
              f"{'OK' if ok else 'MISMATCH'}")
        if not ok:
            problems.append(f"env {name} 与 NR-85 declared 不符")
    return problems


def main() -> int:
    bc = _load("e14")
    pu = _load("e14pure")
    print(f"E14 QMIX 同批：bc n={len(bc)}  pure n={len(pu)}")
    if len(bc) != 30 or len(pu) != 30:
        print("[FAIL] 样本数不是 30/30——拒绝产出结论（fail-closed）。")
        return 1

    problems = _selfcheck_env(bc, pu)
    if problems:
        print("[FAIL] 自检未通过，不产出合作率结论：")
        for p in problems:
            print(f"       - {p}")
        return 1
    print("[ok ] 自检通过：本脚本口径与 NR-85 完全一致。")

    coop = _window_stats(bc, pu, "cooperation_rates")
    print()
    print("[结果] cooperation_rates 分段（n=30 同批，Welch bc vs pure）：")
    for name in WINDOWS:
        r = coop[name]
        print(f"       {name:5s} bc={r['bc_mean']:.4f} pure={r['pure_mean']:.4f} "
              f"Δ={r['delta']:+.4f}  p={r['welch_p']:.5f}  d={r['cohens_d']:.4f}  "
              f"n={r['n_bc']}/{r['n_pure']}")

    report = {
        "algo": "qmix",
        "experiment": "E14",
        "field": "cooperation_rates",
        "n_bc": len(bc),
        "n_pure": len(pu),
        "seeds": "100-129（同批同种子，bc 与 pure 一一对应）",
        "method": "逐 seed 窗口内取均值 → assurance_common.two_sample_stats（Welch, Cohen d）",
        "windows_coop": [coop[n] for n in WINDOWS],
        "env_selfcheck": "env_rewards 三窗口与 NR-85 declared 全部吻合（容差 Δ≤0.01 / p≤0.001 / d≤0.01）",
        "note": ("替代 e14_qmix_temporal_report.json 中 n=20 扩种前的合作率旧值 "
                 "(late Δ=0.0386 / p=0.00943)：扩种后重算为 late Δ=0.0332 / p=0.00371。"),
    }
    written = ac.safe_write_json(report, OUT_PATH, overwrite=False)
    print()
    print(f"[saved] {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
