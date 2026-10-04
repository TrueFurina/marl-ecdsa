#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""F1 边界实证：CW-PBFT 容错边界随 n 与 R(权重比) 的映射。

模型：omission / DoS（被标记节点静默不投票，对应 cw_pbft.simulated_consensus 的 byzantine_nodes）。
安全判据（实现层）：honest_weight >= 2/3 · total_weight ⇔ 共识达成。

本实验回答三个问题：
  (a) CW≡STD 等价性：共识达成是否只取决于「诚实权重占比」，而与权重分布 R 无关？
  (b) 最坏情形（最重节点作恶）下可容忍的作恶节点数 b_max_worst；
      最好情形（最轻节点作恶）下可容忍的作恶节点数 b_max_best；
      二者差异即 R 对「按节点数计」容错的真实影响（R 大 → 最坏情形容错下降、最好情形上升）。
  (c) R 硬上界：MAX_WEIGHT=1.5 / MIN_WEIGHT=0.1 ⇒ R = w_max/w_min ≤ 15（权重演化的饱和点）。

⚠️ 披露纪律（对应项目 C3）：
  - 本实验为 omission-故障（静默）下的活性 / 结构性边界，**不是**任意敌手安全性证明；
    严禁据此声称「抵御了参与型对手」。
  - 98.6% 类数字若出现在他处，仅指 omission 故障活性恢复，非任意敌手安全界。
  - 本结果不入 number_registry 作为安全性保证，仅作结构性实证映射。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blockchain.consensus.cw_pbft import CWPBFTConsensus


def make_weights(n, R):
    """线性权重分布：从 1.0 到 R，使 w_max / w_min = R（min=1.0, max=R）。"""
    if n <= 1:
        return {f"node_{i}": 1.0 for i in range(n)}
    return {f"node_{i}": 1.0 + (i / (n - 1)) * (R - 1.0) for i in range(n)}


def run_once(weights, byz):
    nodes = list(weights.keys())
    cw = CWPBFTConsensus(nodes[0], nodes)
    cw._weights = dict(weights)
    cw._total_weight = sum(weights.values())
    cw.consensus_success_count = 0
    cw.consensus_fail_count = 0
    bh = "x" * 16
    return bool(cw.simulated_consensus(bh, nodes[0], byzantine_nodes=set(byz)))


def scan(n, R):
    weights = make_weights(n, R)
    nodes = list(weights.keys())
    total = sum(weights.values())

    order_worst = sorted(nodes, key=lambda x: weights[x], reverse=True)  # 重节点优先作恶
    order_best = sorted(nodes, key=lambda x: weights[x])                # 轻节点优先作恶

    rows = []
    for b in range(0, n + 1):
        byz = set(order_worst[:b])
        honest_w = total - sum(weights[x] for x in byz)
        frac = honest_w / total
        ok = run_once(weights, byz)
        rows.append({
            "b": b,
            "byz_weight_frac": round(1 - frac, 4),
            "honest_weight_frac": round(frac, 4),
            "success": ok,
            "matches_2_3": bool(honest_w >= (2.0 / 3.0) * total - 1e-9),
        })
    b_max_worst = max([r["b"] for r in rows if r["success"]], default=0)

    b_max_best = 0
    for b in range(0, n + 1):
        byz = set(order_best[:b])
        honest_w = total - sum(weights[x] for x in byz)
        if honest_w >= (2.0 / 3.0) * total - 1e-9 and run_once(weights, byz):
            b_max_best = b

    return {
        "n": n,
        "R": R,
        "total_weight": round(total, 3),
        "b_max_worst": b_max_worst,      # 最坏（重节点作恶）可容忍作恶数
        "b_max_best": b_max_best,        # 最好（轻节点作恶）可容忍作恶数
        "std_pbft_bmax": (n - 1) // 3,   # 标准 PBFT（等权）容错数
        "rows": rows,
    }


def main():
    results = []
    for n in [10, 20, 30, 50]:
        for R in [1, 2, 5, 10, 15]:
            results.append(scan(n, R))

    # CW≡STD 检验：success 是否完全由 honest_weight_frac>=2/3 决定（跨所有 n,R 配置）
    mismatches = []
    for res in results:
        for r in res["rows"]:
            if r["success"] != r["matches_2_3"]:
                mismatches.append((res["n"], res["R"], r["b"], r["success"], r["matches_2_3"]))

    out = {
        "R_hard_cap": 15,   # MAX_WEIGHT/MIN_WEIGHT
        "cw_equiv_std_mismatch_count": len(mismatches),
        "mismatches_sample": mismatches[:10],
        "results": results,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    # 结果数据落在库内 experiments/ （仓库根不平铺：结构守卫禁止根级 json）
    _out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments")
    os.makedirs(_out_dir, exist_ok=True)
    _out_path = os.path.join(_out_dir, "f1_boundary_result.json")
    with open(_out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"[落盘] {_out_path}")


if __name__ == "__main__":
    main()
