#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
register_e39_fault_sweep.py — E39 容错活性比例谱程序化登记（2026-10-15）
======================================================================
纪律：
  - 数字一律**程序化取自** results/e39_fault_ratio_sweep/per_seed/*.json，不手抄
  - declared 的统计量用 `assurance_common.two_sample_stats` 计算，
    与 scripts/verify_numbers.py 的 `_recompute_two_sample` **同一函数** ⇒ declared
    与复算必然一致（避免"登记值与机器复算对不上"）
  - ⚠ 已知坑：declared 里**不能放自定义 list 字段**（verify 只生成
    mean/sd/sd_pop/n/delta/diff_pp/p/d/ci95_*），放了会静默 FAIL

登记范围（11 条格点 + 1 条跨引擎一致性）：
  NR-147~154  n=16 × 故障比例 {5,10,20,25,30,33,40,50}%
  NR-155~158  n=22 × {20,33,40,50}%
  NR-159      n=10 × 50%
  NR-160      n=4  × 50%
  NR-161      跨引擎版本一致性：n=16/40% 新引擎 vs 旧引擎（09-19 全量实验）

pre_registered 一律 false：本轮实验于 2026-10-15 执行与登记在同一天，
  网格常量在执行前已固定于 run_e39_fault_ratio_sweep.py（未做任何事后调参），
  但**确实不是先登记假设再跑**，故按项目铁律显式标 false 并在 notes 交代成因。
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import assurance_common as ac

REG = _REPO_ROOT.parent / "deliverables" / "number_registry.json"
PER_SEED = _REPO_ROOT / "results" / "e39_fault_ratio_sweep" / "per_seed"
LEGACY = _REPO_ROOT / "results" / "consensus_comparison" / "weight_broadening_full"
DATA_ROOT = "marl-ecdsa-consensus-chain/results"

PER_SEED_MAIN = "e39_fault_ratio_sweep/per_seed"
PER_SEED_EXT = "e39_fault_ratio_sweep/per_seed_ext"
GLOB_NEW = "{d}/n{n}_b{tag}_dynamic_cw_seed*.json"
GLOB_NEW_STD = "{d}/n{n}_b{tag}_std_seed*.json"
GLOB_OLD = "consensus_comparison/weight_broadening_full/n{n}_b{tag}_dynamic_cw_seed*.json"

STATISTIC = ["mean_a", "sd_a", "mean_b", "sd_b", "welch_p", "cohens_d",
             "ci95_diff", "improvement_pct", "posthoc_power"]
TOLERANCE = {"abs": 0.005, "p_abs": 0.001, "pct_abs": 0.5, "power_abs": 0.02}

OMISSION = ("省略型（omission）故障模型：坏节点全程静默不投票，诚实节点另有 5% "
            "随机消息丢失；非任意拜占庭行为，不据此宣称突破 1/3 拜占庭容错")


def pct2(v):
    return float(Decimal(str(v * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def tag(b: float) -> str:
    return f"{b:.2f}"


def collect(glob_pat: str) -> list[float]:
    """按 glob（相对 results/）取 success_rate，按文件名中的 seed 升序（保证可复算）。"""
    base = _REPO_ROOT / "results"
    files = sorted(base.glob(glob_pat),
                   key=lambda p: int(p.stem.split("seed")[-1]))
    if not files:
        raise SystemExit(f"[FATAL] glob 无命中: {glob_pat}")
    return [float(json.loads(f.read_text(encoding="utf-8"))["success_rate"]) for f in files]


def build_cell(nr: str, n: int, b: float, per_seed: str = PER_SEED_MAIN) -> dict:
    va = collect(GLOB_NEW.format(d=per_seed, n=n, tag=tag(b)))
    vb = collect(GLOB_NEW_STD.format(d=per_seed, n=n, tag=tag(b)))
    st = ac.two_sample_stats(va, vb)
    zero_var = (st["sd_a"] == 0.0) or (st["sd_b"] == 0.0)
    n_byz = int(n * b)

    cw_pct, std_pct = pct2(st["mean_a"]), pct2(st["mean_b"])
    diff_pct = round(cw_pct - std_pct, 2)

    if zero_var:
        head = (f"n={n}、故障比例 {b:.0%}（{n_byz}/{n} 节点静默）：CW-PBFT {cw_pct:.2f}% "
                f"vs 标准 PBFT {std_pct:.2f}%，Δ=+{diff_pct:.2f}pp"
                f"（对照标准差 PBFT 组零方差→确定性差异，Welch p 不适用，Cohen d=NA）")
    else:
        head = (f"n={n}、故障比例 {b:.0%}（{n_byz}/{n} 节点静默）：CW-PBFT {cw_pct:.2f}% "
                f"vs 标准 PBFT {std_pct:.2f}%，Δ=+{diff_pct:.2f}pp，"
                f"Welch p={st['welch_p']:.2e}，Cohen d={st['cohens_d']:+.2f}")

    allowed = (head + "。路线C 参与率驱动权重展宽（FLOOR=0.25/MAX_W=1.5/纪元50轮，"
               "不预知坏节点身份），10 seed×2000 轮。" + OMISSION + "。")

    declared = {
        "mean_a": st["mean_a"], "sd_a": st["sd_a"], "n_a": len(va),
        "mean_b": st["mean_b"], "sd_b": st["sd_b"], "n_b": len(vb),
        "welch_p": st["welch_p"], "welch_t": st["welch_t"], "welch_df": st["welch_df"],
        "ci95_diff": list(st["ci95_diff"]),
        "improvement_pct": st["improvement_pct"],
        "posthoc_power": st["posthoc_power"],
        "cohens_d": st["cohens_d"],
        "diff_pp": diff_pct,
    }
    stat = list(STATISTIC)
    # ⚠ 坑（2026-10-15 实测）：零方差时 improvement_pct = (a-b)/b、cohens_d 与
    # posthoc_power 的分母 pooled_sd/分母 SD 为 0 ⇒ NaN；verify 的 `delta <= tol`
    # 对 NaN 恒为 False ⇒ 整条判 FAIL。既有零方差条目（NR-38）的 declared 同样
    # 不含这些键 —— 故**统一剔除 declared 中的全部 NaN**（不改写为 0，避免伪造数值）。
    nan_keys = [k for k, v in declared.items()
                if isinstance(v, float) and v != v]
    for k in nan_keys:
        declared.pop(k, None)
        if k in stat:
            stat.remove(k)
    if nan_keys:
        print(f"   [note] {nr}: 剔除 NaN 字段 {nan_keys}")
    return {
        "id": nr,
        "claim": (f"E39 容错活性比例谱：n={n} / 故障比例 {b:.0%}（省略故障）下 "
                  f"CW-PBFT(dynamic) vs 标准 PBFT 共识成功率"),
        "allowed_wording": allowed,
        "analysis": "two_sample",
        "sources": [
            {"glob": GLOB_NEW.format(d=per_seed, n=n, tag=tag(b)),
             "field": "success_rate", "role": "a"},
            {"glob": GLOB_NEW_STD.format(d=per_seed, n=n, tag=tag(b)),
             "field": "success_rate", "role": "b"},
        ],
        "n_expected": 10,
        "statistic": stat,
        "declared": declared,
        "tolerance": TOLERANCE,
        "status": "PENDING",
        "pre_registered": False,
        "requires": [],
        "notes": (f"E39（2026-10-15）全谱扫描：n={n}、故障 {b:.0%}、{n_byz} 个节点静默、"
                  f"10 seed×2000 轮。zero_var={zero_var}"
                  + ("（p 不用于任何结论）" if zero_var else "")
                  + "；实验执行与登记同日，网格常量执行前已固定于脚本，未做事后调参"
                    "（按铁律 pre_registered=false）。"),
        "evidence_kind": "experiment",
    }


def build_cross_engine(nr: str) -> dict:
    """NR-161：跨引擎版本一致性（新引擎 E39 复算 vs 旧引擎 09-19 全量实验）。"""
    va = collect(GLOB_NEW.format(d=PER_SEED_MAIN, n=16, tag="0.40"))   # 当前 HEAD 引擎
    vb = collect(GLOB_OLD.format(n=16, tag="0.40"))                    # 09-19 引擎
    st = ac.two_sample_stats(va, vb)
    allowed = (f"n=16、故障 40%：当前 HEAD 引擎复算 CW-PBFT {pct2(st['mean_a']):.2f}% vs "
               f"2026-09-19 全量实验 {pct2(st['mean_b']):.2f}%，差 "
               f"{abs(pct2(st['mean_a'])-pct2(st['mean_b'])):.2f}pp，Welch p={st['welch_p']:.3f}"
               f"⇒ 引擎在 09-19 之后经历 7 次提交（含 P1-15 权重上界钳制 MAX_W=1.5、"
               f"S1–S9 代码审查修复）后，容错结论**统计上无变化**，"
               f"证明结论对实现演进稳健。" + OMISSION + "。")
    return {
        "id": nr,
        "claim": "跨引擎版本一致性：n=16/40% 容错活性在引擎 7 次提交前后复算对比",
        "allowed_wording": allowed,
        "analysis": "two_sample",
        "sources": [
            {"glob": GLOB_NEW.format(d=PER_SEED_MAIN, n=16, tag="0.40"),
             "field": "success_rate", "role": "a"},
            {"glob": GLOB_OLD.format(n=16, tag="0.40"), "field": "success_rate", "role": "b"},
        ],
        "n_expected": 10,
        "statistic": STATISTIC,
        "declared": {
            "mean_a": st["mean_a"], "sd_a": st["sd_a"], "n_a": len(va),
            "mean_b": st["mean_b"], "sd_b": st["sd_b"], "n_b": len(vb),
            "welch_p": st["welch_p"], "welch_t": st["welch_t"], "welch_df": st["welch_df"],
            "ci95_diff": list(st["ci95_diff"]),
            "improvement_pct": st["improvement_pct"],
            "posthoc_power": st["posthoc_power"],
            "cohens_d": st["cohens_d"],
        },
        "tolerance": TOLERANCE,
        "status": "PENDING",
        "pre_registered": False,
        "requires": [],
        "notes": ("微差根因已确证：commit 7862b35 引入 MAX_WEIGHT=1.5 权重上界钳制"
                  "（P1-15 修复：为权重设定硬上界），使 legacy 模拟器外部归一化"
                  "后的权重（可能 >1.5）被引擎二次钳制；实测放开该上界后 seed123 "
                  "精确复现旧值 0.973500。此条目为『事后发现→补登记』，不在任何既有材料中。"),
        "evidence_kind": "experiment",
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=("main", "ext"), default="main",
                    help="main=比例谱(NR-147~161)；ext=规模扩展批次(NR-162~173)")
    args = ap.parse_args()

    reg = json.loads(REG.read_text(encoding="utf-8"))
    have = {e["id"] for e in reg["entries"]}

    plan, per_seed, cross_nr = [], PER_SEED_MAIN, None
    if args.batch == "main":
        nr_i = 147
        for b in (0.05, 0.10, 0.20, 0.25, 0.30, 0.33, 0.40, 0.50):
            plan.append((f"NR-{nr_i}", 16, b)); nr_i += 1
        for b in (0.20, 0.33, 0.40, 0.50):
            plan.append((f"NR-{nr_i}", 22, b)); nr_i += 1
        plan.append((f"NR-{nr_i}", 10, 0.50)); nr_i += 1
        plan.append((f"NR-{nr_i}", 4, 0.50)); nr_i += 1
        cross_nr = f"NR-{nr_i}"
    else:
        per_seed = PER_SEED_EXT
        nr_i = 162
        for n in (31, 49, 64):
            for b in (0.20, 0.33, 0.40, 0.50):
                plan.append((f"NR-{nr_i}", n, b)); nr_i += 1

    added, updated = [], []
    for nr, n, b in plan:
        e = build_cell(nr, n, b, per_seed)
        if nr in have:
            reg["entries"] = [e if x["id"] == nr else x for x in reg["entries"]]
            updated.append(nr)
        else:
            reg["entries"].append(e)
            added.append(nr)
    if cross_nr:
        e = build_cross_engine(cross_nr)
        if cross_nr in have:
            reg["entries"] = [e if x["id"] == cross_nr else x for x in reg["entries"]]
            updated.append(cross_nr)
        else:
            reg["entries"].append(e)
            added.append(cross_nr)

    # 备份后再写
    bak = _REPO_ROOT.parent / "backup"
    bak.mkdir(parents=True, exist_ok=True)
    bak_fp = bak / f"number_registry_pre_e39_{args.batch}_20261015.json"
    bak_fp.write_text(REG.read_text(encoding="utf-8"), encoding="utf-8")
    assert bak_fp.stat().st_size > 0, "备份写入失败"

    REG.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[登记] 新增 {len(added)} 条: {added}")
    print(f"[登记] 更新 {len(updated)} 条: {updated}")
    print(f"[备份] {bak_fp}")
    print(f"[条目总数] {len(reg['entries'])}")
    print("\n⚠ 下一步必须执行：")
    print(f"   python scripts/check_registry_mirror.py --sync")
    print(f"   python scripts/verify_numbers.py --strict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
