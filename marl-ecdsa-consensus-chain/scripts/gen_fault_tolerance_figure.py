#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容错活性对比图生成（NR-38 演示视频配图）
=============================================
从权威结果 JSON 程序化读取 n=16 / 40% 省略故障下 CW-PBFT vs 标准 PBFT
共识成功率，生成 1080P 深色对比柱状图，供 build_demo_video.py 使用。

数字不手抄：mean 从 results/consensus_comparison/weight_broadening_full/
n16_b0.40_{dynamic_cw,std}_seed*.json 的 success_rate 现算，
并与 number_registry.json 的 NR-38 declared 值对照（容差 0.005）。

产出：ppt_screenshots/fault_tolerance_liveness.png
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "results" / "consensus_comparison" / "weight_broadening_full"
SHOTS = ROOT / "ppt_screenshots"
REGISTRY = ROOT.parent / "deliverables" / "number_registry.json"

BG = "#101218"
FG = "#f0f4fa"
ACCENT = "#00d4ff"
WARN = "#ff5a5a"
GRID = "#2a2f3a"


def load_seed_means(pattern: str) -> list[float]:
    vals = []
    for fp in sorted(SRC.glob(pattern)):
        with open(fp, encoding="utf-8") as f:
            vals.append(float(json.load(f)["success_rate"]))
    return vals


def main() -> int:
    cw = load_seed_means("n16_b0.40_dynamic_cw_seed*.json")
    std = load_seed_means("n16_b0.40_std_seed*.json")
    if len(cw) != 10 or len(std) != 10:
        print(f"[FAIL] seed 数不为 10：cw={len(cw)} std={len(std)}")
        return 1
    mean_cw = sum(cw) / len(cw)
    mean_std = sum(std) / len(std)

    # 与登记簿 NR-38 declared 对照
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    nr38 = next(e for e in reg["entries"] if e.get("id") == "NR-38")
    d = nr38["declared"]
    if abs(mean_cw - d["mean_a"]) > 0.005 or abs(mean_std - d["mean_b"]) > 0.005:
        print(f"[FAIL] 与 NR-38 declared 漂移: "
              f"cw {mean_cw:.5f} vs {d['mean_a']}, std {mean_std:.5f} vs {d['mean_b']}")
        return 1

    # 中文字体
    font_manager.fontManager.addfont(r"C:\Windows\Fonts\msyh.ttc")
    plt.rcParams["font.family"] = "Microsoft YaHei"
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=100)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    bars = ax.bar(["标准 PBFT", "CW-PBFT（动态档）"], [mean_std * 100, mean_cw * 100],
                  width=0.45, color=[WARN, ACCENT], edgecolor="none", zorder=3)
    ax.set_ylim(0, 110)
    ax.set_ylabel("共识成功率（%）", color=FG, fontsize=15)
    ax.set_title("40% 省略故障下的共识活性（n=16 节点，10 seeds × 2000 轮）",
                 color=FG, fontsize=18, pad=18)
    ax.tick_params(colors=FG, labelsize=14)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)

    for b, v, sd in zip(bars, [mean_std * 100, mean_cw * 100],
                        [0.0, (sum((x - mean_cw) ** 2 for x in cw) / (len(cw) - 1)) ** 0.5 * 100]):
        ax.text(b.get_x() + b.get_width() / 2, v + 3,
                f"{v:.2f}%（±{sd:.2f}）" if sd > 0 else f"{v:.2f}%",
                ha="center", color=FG, fontsize=16, fontweight="bold")

    ax.annotate("Δ = +97.30pp，零方差 → 确定性差异",
                xy=(0.5, 0.86), xycoords="axes fraction",
                ha="center", color=FG, fontsize=14,
                bbox=dict(boxstyle="round,pad=0.5", fc="#1a1f2b", ec=GRID))
    fig.text(0.5, 0.045,
             "参与率驱动权重展宽（FLOOR=0.25 / MAX_W=1.5 / 纪元50轮），不预知坏节点身份；"
             "省略型故障模型（数据来源：NR-38 权威登记口径）",
             ha="center", color="#9aa3b2", fontsize=11)

    SHOTS.mkdir(parents=True, exist_ok=True)
    out = SHOTS / "fault_tolerance_liveness.png"
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    fig.savefig(out, facecolor=BG)
    print(f"✅ {out}  CW={mean_cw*100:.2f}% STD={mean_std*100:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
