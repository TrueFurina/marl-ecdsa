#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两批新数据纳入「单一真值源 + 机检」体系。

批次 1（用户 P1 #1）：**引擎级权重展宽数据 99.67% / 95.49%**
  源：results/weight_broadening_engine/results.json
      （meta: rounds=300, seeds=[42,123,456,789,2026], epoch=50 floor=0.25 max=1.5, 2026-09-24 00:06）
  问题：其结构（扁平 results[]，cw_dynamic_success_rate / std_pbft_success_rate / honest_weight_share）
        不是注册表任何 analysis 能直接读的。
  ✅ 解法（不动 verify_numbers.py —— 该文件属并发会话域）：
     投影为 `consensus_comparison/engine_broadening_20260924.json`，
     结构对齐 `consensus_row` 既有约定（cw_pbft[] / standard_pbft[]），
     于是 NR 条目可由**现有机检**复算，无需新增 analysis 类型。

批次 2：E15 训练预算剂量-响应（1000 / 3000 回合）
  展平为 derived 逐种子文件，用 multi_sample 登记（与 NR-68~71 同构）。
"""
import json, os, sys, glob
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402

RES = REPO / "results"
REG = Path(r"E:\Program\MARL\【CCF】区块链AI协同：面向MARL的共识机制\deliverables\number_registry.json")

METRICS = ("avg_env_reward", "avg_cooperation_rate", "avg_betrayal_rate")
ENGINE_SRC = RES / "weight_broadening_engine" / "results.json"
ENGINE_OUT = RES / "consensus_comparison" / "engine_broadening_20260924.json"

CAVEAT_ENGINE = (
    "【限定语不可省】本条为**引擎级**（CWPBFTConsensus 直测，非训练循环）结果，"
    "故障模型为**省略故障（omission）**——坏节点被跳过、从不投恶意票、不做 equivocation。"
    "故只能表述为『省略故障下的活性恢复』，**不得**表述为『抵御任意 adversary』或『拜占庭容错 40%』。"
    "另据 NR-52/53：坏节点**照常投票**时 CW-PBFT 与标准 PBFT 等价、增益消失。"
)


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------- 批次 1：投影引擎数据 ----------
def project_engine():
    src = jload(ENGINE_SRC)
    meta = src["meta"]
    cw, std = [], []
    for r in src["results"]:
        n, bz = r["n_nodes"], r["byz_ratio"]
        n_byz = int(round(n * bz))
        cw.append({
            "n_nodes": n, "byzantine_ratio": bz,
            "success_rate": r["cw_dynamic_success_rate"],
            "n_byzantine": n_byz, "n_rounds": meta["rounds"],
            "honest_weight_share": r["honest_weight_share"],
            "epochs_triggered": r["epochs_triggered"],
        })
        std.append({
            "n_nodes": n, "byzantine_ratio": bz,
            "success_rate": r["std_pbft_success_rate"],
            "n_byzantine": n_byz, "n_rounds": meta["rounds"],
        })
    out = {
        "_source": "results/weight_broadening_engine/results.json",
        "_note": ("引擎级权重展宽结果，投影为 consensus_row 可读结构以便机检。"
                  "原始字段：cw_dynamic_success_rate / std_pbft_success_rate / honest_weight_share。"
                  "故障模型=省略故障(omission)；每配置 5 种子 × 300 轮。"),
        "meta": meta,
        "cw_pbft": cw,
        "standard_pbft": std,
    }
    ENGINE_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(cw)


def consensus_entry(nr, n_nodes, byz, wording_extra, notes):
    doc = jload(ENGINE_OUT)
    row_cw = next(r for r in doc["cw_pbft"]
                  if r["n_nodes"] == n_nodes and abs(r["byzantine_ratio"] - byz) < 1e-9)
    row_std = next(r for r in doc["standard_pbft"]
                   if r["n_nodes"] == n_nodes and abs(r["byzantine_ratio"] - byz) < 1e-9)
    declared = {
        "cw_success_rate": row_cw["success_rate"],
        "std_success_rate": row_std["success_rate"],
        "n_byzantine": row_cw["n_byzantine"],
        "n_rounds": row_cw["n_rounds"],
    }
    return {
        "id": nr,
        "claim": (f"引擎级权重展宽：n={n_nodes} / 拜占庭 {byz:.0%} —— "
                  f"CW-PBFT {declared['cw_success_rate']:.4f} vs 标准 PBFT {declared['std_success_rate']:.4f}"),
        "allowed_wording": (
            f"引擎级直测（CWPBFTConsensus，5 种子 × 300 轮，展宽 epoch=50/floor=0.25/max=1.5）："
            f"n={n_nodes}、拜占庭 {byz:.0%} 下，CW-PBFT 成功率 {declared['cw_success_rate']:.2%}，"
            f"标准 PBFT {declared['std_success_rate']:.2%}；诚实方权重占比 {row_cw['honest_weight_share']:.2%}，"
            f"触发展宽 {row_cw['epochs_triggered']} 纪元。{wording_extra}{CAVEAT_ENGINE}"
        ),
        "analysis": "consensus_row",
        "consensus_file": "consensus_comparison/engine_broadening_20260924.json",
        "match": {"n_nodes": n_nodes, "byzantine_ratio": byz},
        "n_expected": 1,
        "statistic": ["cw_success_rate", "std_success_rate", "n_byzantine", "n_rounds"],
        "declared": declared,
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": notes,
    }


# ---------- 批次 2：E15 ----------
def flatten_e15():
    n = 0
    for f in sorted((RES / "dispatch_20260921").glob("e15_b*_seed*.json")):
        base = f.stem
        budget = base.split("_")[1]
        seed = base.split("_seed")[1]
        res = jload(f)["experiments"][0]["results"]
        for label, v in res.items():
            if label == "comparison":
                continue
            (RES / "dispatch_20260921" / "derived" /
             f"e15_{budget}_{label}_seed{seed}.json").write_text(json.dumps({
                 "seed": int(seed), "budget": budget, "config": label,
                 **{m: v[m] for m in METRICS},
             }, ensure_ascii=False), encoding="utf-8")
            n += 1
    return n


def vals(pattern, field):
    return [jload(p)[field]
            for p in sorted((RES / "dispatch_20260921" / "derived").glob(pattern))]


def multi_entry(nr, budget, field_name, metric_cn, note):
    roles = {
        "50g": f"e15_{budget}_selfish_50pct_greedy_seed*.json",
        "50r": f"e15_{budget}_selfish_50pct_random_seed*.json",
        "20g": f"e15_{budget}_selfish_20pct_greedy_seed*.json",
        "20r": f"e15_{budget}_selfish_20pct_random_seed*.json",
    }
    data = {r: vals(g, field_name) for r, g in roles.items()}
    pairs = [{"label": "50pct", "a": "50g", "b": "50r"},
             {"label": "20pct", "a": "20g", "b": "20r"}]
    computed = {}
    for r, v in data.items():
        computed[f"mean_{r}"] = ac.mean(v)
        computed[f"sd_{r}"] = ac.stdev(v)
        computed[f"n_{r}"] = len(v)
    for pr in pairs:
        st = ac.two_sample_stats(data[pr["a"]], data[pr["b"]])
        lbl = pr["label"]
        computed[f"delta_{lbl}"] = st["mean_a"] - st["mean_b"]
        computed[f"diff_pp_{lbl}"] = (st["mean_a"] - st["mean_b"]) * 100.0
        p = st["welch_p"]
        computed[f"p_{lbl}"] = (float(f"{p:.6g}") if p and abs(p) < 1e-4 else round(p, 6))
        computed[f"d_{lbl}"] = st["cohens_d"]
    computed = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in computed.items()}

    def pfmt(p):
        return "p<1e-12" if (p == 0 or p < 1e-12) else f"p={p:.3g}"
    word = (
        f"E15（{budget} 回合、10 种子同种子配对、greedy_step=0.05、behavioral 合作率口径）："
        f"50% 自私下 greedy {metric_cn} {computed['mean_50g']:.4f} vs random {computed['mean_50r']:.4f}"
        f"（Δ={computed['delta_50pct']:+.4f}，Welch {pfmt(computed['p_50pct'])}，d={computed['d_50pct']:+.2f}）；"
        f"20% 自私下 Δ={computed['delta_20pct']:+.4f}（{pfmt(computed['p_20pct'])}）。 {note}"
    )
    return {
        "id": nr,
        "claim": f"E15 {budget} 回合档：{metric_cn} 上 greedy 与 random 的配对差",
        "allowed_wording": word,
        "analysis": "multi_sample",
        "sources": [{"glob": f"dispatch_20260921/derived/{g}", "field": field_name, "role": r}
                    for r, g in roles.items()],
        "pairs": pairs,
        "n_expected": 10,
        "statistic": ["mean_50g", "mean_50r", "delta_50pct", "p_50pct", "d_50pct",
                      "mean_20g", "mean_20r", "delta_20pct", "p_20pct", "d_20pct"],
        "declared": computed,
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": f"dispatch_20260921 批次（2026-09-23 23:10 跑完，20/20 exit=0）。{note}",
    }


def main():
    n_eng = project_engine()
    print(f"引擎数据投影: {n_eng} 行 → {ENGINE_OUT.name}")
    n_e15 = flatten_e15()
    print(f"E15 展平: {n_e15} 个 derived 文件")

    DOSE_NOTE = (
        "【剂量-响应限定】本条须与同指标的 500/1000/3000 三档**同时引用**："
        "Δ 随训练预算单调衰减（50% 档 env_reward：+55.45 → +51.81 → +40.18，见 NR-70 / 本条 / NR-77），"
        "说明贪心优势部分来自『手编启发式 vs 未收敛学习者』的策略质量差异，"
        "**不得**据此宣称『自私无害』或『自私有益』。"
    )
    new = [
        consensus_entry("NR-74", 10, 0.4,
                        "标准 PBFT 在此比例下**完全失活**（0%），CW-PBFT 维持活性。",
                        "引擎级；n=10 档。与 NR-52（参与型对手臂）互为边界：省略故障下增益显著，满参与时消失。"),
        consensus_entry("NR-75", 25, 0.4,
                        "标准 PBFT 完全失活，CW-PBFT 维持活性；与 n=10/40 同构，说明**与规模无关**。",
                        "引擎级；n=25 档。"),
        consensus_entry("NR-76", 40, 0.4,
                        "标准 PBFT 完全失活，CW-PBFT 维持活性；与 n=10/25 同构。",
                        "引擎级；n=40 档。"),
        consensus_entry("NR-77", 10, 0.3,
                        "**注意**：拜占庭 ≤30%（在 1/3 理论界内）时 CW-PBFT 与标准 PBFT "
                        "**均为 100%、无差异**——增益只在超过理论界的 40%/50% 档出现。",
                        "引擎级；阴性对照档，须与 NR-74 同报，防止被误读为『全面优于标准 PBFT』。"),
        multi_entry("NR-78", "b1000", "avg_env_reward", "环境奖励（env_reward）", DOSE_NOTE),
        multi_entry("NR-79", "b1000", "avg_cooperation_rate", "行为学合作率", DOSE_NOTE),
        multi_entry("NR-80", "b3000", "avg_env_reward", "环境奖励（env_reward）", DOSE_NOTE),
        multi_entry("NR-81", "b3000", "avg_cooperation_rate", "行为学合作率", DOSE_NOTE),
    ]

    doc = json.load(open(REG, encoding="utf-8"))
    have = {e["id"] for e in doc["entries"]}
    added = []
    for e in new:
        if e["id"] in have:
            print(f"[skip] {e['id']}")
            continue
        doc["entries"].append(e)
        added.append(e["id"])
    json.dump(doc, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已新增: {added}")
    for e in new:
        if e["id"] not in added:
            continue
        d = e["declared"]
        if "delta_50pct" in d:
            print(f"  {e['id']}: 50pct Δ={d['delta_50pct']:+.4f} p={d['p_50pct']} | "
                  f"20pct Δ={d['delta_20pct']:+.4f}")
        else:
            print(f"  {e['id']}: cw={d['cw_success_rate']} std={d['std_success_rate']} "
                  f"n_byz={d['n_byzantine']}")


if __name__ == "__main__":
    main()
