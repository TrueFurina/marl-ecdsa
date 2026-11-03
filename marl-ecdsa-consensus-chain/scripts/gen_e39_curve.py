#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_e39_curve.py — E39 容错活性「故障比例谱」曲线图（2026-10-15）
=================================================================
纪律：数字**不手抄**，全部从 results/e39_fault_ratio_sweep/e39_fault_ratio_sweep.json
现算；与 number_registry.json 的 declared 交叉对照（容差 0.005，不一致即报错）。

用途：设计报告（Word，白底）/ PPT。**不用于**演示视频（视频沿用深色版
gen_fault_tolerance_figure.py 的单点对照图）。

产出：
    ppt_screenshots/e39_fault_ratio_curve_n16.png   主曲线（n=16）
    ppt_screenshots/e39_fault_ratio_curve_multi.png 多规模对照（n=10/16/22）
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "results" / "e39_fault_ratio_sweep" / "e39_fault_ratio_sweep.json"
REGISTRY = ROOT.parent / "deliverables" / "number_registry.json"
OUT = ROOT / "ppt_screenshots"

FG = "#1a1a1a"
CW_COLOR = "#c0392b"      # CW-PBFT（红）
STD_COLOR = "#3d7ab8"     # 标准 PBFT（蓝）
GRID = "#dcdcdc"


def pct2(v):
    return float(Decimal(str(v * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def setup_font():
    for name in ("Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC", "Arial Unicode MS"):
        try:
            fp = font_manager.findfont(font_manager.FontProperties(family=name),
                                       fallback_to_default=False)
            if fp:
                plt.rcParams["font.family"] = name
                return name
        except Exception:
            continue
    return plt.rcParams["font.family"]


def load():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    return d


def declared_check(nr: str, key: str, value: float, tol: float = 0.005) -> None:
    """与 registry declared 交叉对照（数字不手抄的第二道保险）。"""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for e in reg["entries"]:
        if e["id"] == nr:
            dec = e["declared"].get(key)
            if dec is None:
                print(f"   [skip] {nr}.{key} 未登记（零方差条目按设计不含该键）")
                return
            if abs(float(dec) - value) > tol:
                raise SystemExit(f"[FATAL] {nr}.{key} 图值={value} 登记值={dec} 超出容差")
            print(f"   [ok] {nr}.{key} = {dec}")
            return
    print(f"   [warn] {nr} 未在 registry 中找到")


def curve_n16(d):
    rows = [r for r in d["results"] if r["n_nodes"] == 16 and r["weight_mode"] == "dynamic"]
    rows.sort(key=lambda r: r["byzantine_ratio"])
    xs = [r["byzantine_ratio"] * 100 for r in rows]
    cw = [pct2(r["cw_mean"]) for r in rows]
    std = [pct2(r["std_mean"]) for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    ax.plot(xs, cw, "-o", color=CW_COLOR, lw=2.4, ms=7,
            label="CW-PBFT（路线C 参与率驱动权重展宽）")
    ax.plot(xs, std, "-s", color=STD_COLOR, lw=2.4, ms=7, label="标准 PBFT（等权重 2/3 阈值）")
    ax.fill_between(xs, std, cw, color=CW_COLOR, alpha=0.10)

    for x, y in zip(xs, cw):
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=9, color=CW_COLOR)
    for x, y in zip(xs, std):
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, -16),
                    ha="center", fontsize=9, color=STD_COLOR)

    ax.set_xlabel("故障节点比例（省略型故障，%）", fontsize=12, color=FG)
    ax.set_ylabel("共识成功率（%）", fontsize=12, color=FG)
    ax.set_title("容错活性故障比例谱：n=16，10 seed × 2000 轮/场",
                 fontsize=13, color=FG, pad=14)
    ax.set_ylim(-4, 106)
    ax.set_xticks(xs)
    ax.grid(True, color=GRID, lw=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    ax.legend(loc="lower left", fontsize=10.5, framealpha=0.95)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#999999")

    fig.text(0.012, 0.015,
             "省略型（omission）故障模型：坏节点全程静默不投票，诚实节点另有 5% 随机消息丢失；"
             "非任意拜占庭行为，不据此宣称突破 1/3 拜占庭容错。",
             fontsize=8.2, color="#555555")
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    OUT.mkdir(parents=True, exist_ok=True)
    op = OUT / "e39_fault_ratio_curve_n16.png"
    fig.savefig(op, facecolor="white")
    plt.close(fig)
    print(f"[产出] {op}")
    return rows


def curve_multi(d):
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    styles = {10: ("-o", "#7f8c9a"), 16: ("-o", CW_COLOR), 22: ("-^", "#d68910")}
    for n, (ls, col) in styles.items():
        rows = [r for r in d["results"] if r["n_nodes"] == n and r["weight_mode"] == "dynamic"]
        rows.sort(key=lambda r: r["byzantine_ratio"])
        xs = [r["byzantine_ratio"] * 100 for r in rows]
        ys = [pct2(r["cw_mean"]) for r in rows]
        ax.plot(xs, ys, ls, color=col, lw=2.2, ms=6, label=f"CW-PBFT n={n}")
    # 标准 PBFT 基线（n 无关性：40%/50% 恒为 0，33% 已跌至 56%）
    rows16 = sorted([r for r in d["results"] if r["n_nodes"] == 16
                     and r["weight_mode"] == "dynamic"], key=lambda r: r["byzantine_ratio"])
    ax.plot([r["byzantine_ratio"] * 100 for r in rows16],
            [pct2(r["std_mean"]) for r in rows16], "--s", color=STD_COLOR, lw=2.2, ms=6,
            label="标准 PBFT（n=16 基线，40%/50% 恒为 0）")

    ax.set_xlabel("故障节点比例（省略型故障，%）", fontsize=12, color=FG)
    ax.set_ylabel("CW-PBFT 共识成功率（%）", fontsize=12, color=FG)
    ax.set_title("跨规模容错活性：CW-PBFT 在不同节点规模下的故障比例谱",
                 fontsize=13, color=FG, pad=14)
    ax.set_ylim(-4, 106)
    ax.grid(True, color=GRID, lw=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.95)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.012, 0.015,
             "n=4 在 5%/10%/20% 三格因 int(4×b)=0 未注入故障节点，CW 与 STD 恒等，"
             "故未纳入本图；40%/50% 档标准 PBFT 组恒为 0（零方差，p 不适用）。",
             fontsize=8.2, color="#555555")
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    op = OUT / "e39_fault_ratio_curve_multi.png"
    fig.savefig(op, facecolor="white")
    plt.close(fig)
    print(f"[产出] {op}")


def main():
    font = setup_font()
    print(f"[字体] {font}")
    d = load()
    print("[交叉对照] 图值与 registry declared：")
    rows = curve_n16(d)
    # n=16 各格点对应 NR-147~154
    for i, r in enumerate(rows):
        declared_check(f"NR-{147+i}", "mean_a", r["cw_mean"])
    curve_multi(d)
    meta = d["meta"]
    print(f"\n[自校验] hard={len(meta['self_verify_hard_mismatch'])} "
          f"soft={len(meta['self_verify_soft_mismatch'])} "
          f"(比对 {meta['self_verify_checks']} 个既有格点文件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
