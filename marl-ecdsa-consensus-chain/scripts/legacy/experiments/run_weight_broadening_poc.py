#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_weight_broadening_poc.py — 路线C PoC：诚实权重展宽机制验证（2026-09-18）

背景（U9 诊断结论）：
  真实贡献度权重 R≈1.007 时 CW-PBFT 与标准 PBFT 完全等价（无增益，数学必然：
  M3 判据 b < n/(2R+1)，R≈1 ⇒ b < n/3 ≈ PBFT 的 n/3）。
  要产生增益需有效 R > 3（33% 容错）。

本 PoC 的机制（不预设谁是坏节点，只用链上可核验的参与行为）：
  1) 参与率信号：每轮统计 engine._votes['prepare'] 实际投票者 → 每节点滑动窗口参与率
  2) 纪元机制：每 EPOCH_ROUNDS=50 轮一个纪元，纪元内权重冻结（回应第2章"动态权重
     法定人数论证"缺口）；纪元末统一更新并延迟到下一纪元生效
  3) 权重更新：w ← clip(w * (FLOOR + (1-FLOOR)*participation), MIN, MAX)，再均值归一到 1
     - FLOOR=0.25：单纪元零参与最多衰减到 25%（温和，不瞬杀）
     - MAX=1.5 钳制：修复"无上界"缺陷（F 项）。注意（2026-09-19 更正）：MAX=1.5
       配 MIN=0.1 使权重带宽上界达 R=15，为 M3 安全带 R<7/6 的 12.8 倍，故该钳制
       **不构成 M3 判据意义下的安全守护**（M3 要求把 R 压小，与本机制"扩大 R"方向
       相反）；安全来自坏节点被实际压到低权重（实测坏节点权重占比 2.60%~4.27%），
       而非来自钳制本身
  4) 预期：省略故障节点参与率=0 → 权重逐纪元指数衰减至 MIN；诚实节点(95%参与)
     几乎不衰减且归一化回 ~1 → 有效 R 增长，诚实方权重占比越过 2/3 → 活性恢复

对照组：standard PBFT（同故障模型）；对照 CW-static（uniform 权重 = U9 的 R=1 基线）。

纯标准库。python3 直接跑。
"""
import sys, json, random, hashlib, time, statistics as st
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from blockchain.consensus.cw_pbft import CWPBFTConsensus, ConsensusState
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

HONEST_MSG_LOSS = 0.05
SEEDS = [42, 123, 456, 789, 1024]
EPOCH_ROUNDS = 50
FLOOR = 0.25
MIN_W = 0.1
MAX_W = 1.5


def simulate_dynamic(n_nodes, byz_ratio, n_rounds, seed):
    """CW-PBFT + 参与率驱动权重展宽（每 EPOCH_ROUNDS 轮更新一次，纪元内冻结）"""
    random.seed(seed)
    node_ids = [f"node_{i}" for i in range(n_nodes)]
    n_byz = int(n_nodes * byz_ratio)
    byz_ids = set(node_ids[:n_byz])
    engine = CWPBFTConsensus(node_id="node_0", consensus_nodes=node_ids)
    weights = {nid: 1.0 for nid in node_ids}
    for nid, w in weights.items():
        engine.update_weight(nid, w)
    # 滑动窗口参与计数（全窗口，够用且简单）
    part_total = {nid: 0 for nid in node_ids}
    part_rounds = 0
    succ = 0
    r_hist = []          # 每纪元末的有效 R = w_max/w_min
    honest_share = []    # 每纪元末诚实方权重占比

    for r in range(n_rounds):
        engine.reset()
        engine._state = ConsensusState.IDLE
        silent = set(byz_ids)
        for nid in node_ids:
            if nid not in byz_ids and random.random() < HONEST_MSG_LOSS:
                silent.add(nid)
        proposer = engine.get_primary(0)
        bh = hashlib.sha256(f"{seed}:{r}".encode()).hexdigest()
        if engine.simulated_consensus(bh, proposer, byzantine_nodes=silent):
            succ += 1
        # 记录本轮实际投票者（PREPARE 阶段投票表）
        part_rounds += 1
        for nid in engine._votes.get('prepare', {}):
            part_total[nid] += 1
        # 纪元末：参与率 → 权重更新（延迟到下一纪元生效 = 纪元内冻结）
        if (r + 1) % EPOCH_ROUNDS == 0 and (r + 1) < n_rounds:
            new_w = {}
            for nid in node_ids:
                p = part_total[nid] / max(part_rounds, 1)
                raw = weights[nid] * (FLOOR + (1 - FLOOR) * p)
                new_w[nid] = max(MIN_W, min(MAX_W, raw))
            mean = sum(new_w.values()) / len(new_w)
            weights = {nid: w / mean for nid, w in new_w.items()}
            for nid, w in weights.items():
                engine.update_weight(nid, w)
            vals = list(weights.values())
            r_hist.append(max(vals) / min(vals))
            honest_share.append(sum(weights[n] for n in node_ids if n not in byz_ids)
                                / sum(weights.values()))
            # 参与窗口滚动重置（近期行为主导，恢复也有机会）
            part_total = {nid: 0 for nid in node_ids}
            part_rounds = 0
    final_r = max(weights.values()) / min(weights.values())
    final_honest = sum(weights[n] for n in node_ids if n not in byz_ids) / sum(weights.values())
    return succ / n_rounds, weights, (r_hist[-1] if r_hist else 1.0), final_r, final_honest


def simulate_std(n_nodes, byz_ratio, n_rounds, seed):
    random.seed(seed)
    node_ids = [f"node_{i}" for i in range(n_nodes)]
    n_byz = int(n_nodes * byz_ratio)
    byz_ids = set(node_ids[:n_byz])
    engine = StandardPBFTConsensus(node_id="node_0", consensus_nodes=node_ids)
    succ = 0
    for r in range(n_rounds):
        engine.reset()
        engine._state = ConsensusState.IDLE
        silent = set(byz_ids)
        for nid in node_ids:
            if nid not in byz_ids and random.random() < HONEST_MSG_LOSS:
                silent.add(nid)
        proposer = engine.get_primary(0)
        bh = hashlib.sha256(f"{seed}:{r}".encode()).hexdigest()
        if engine.simulated_consensus(bh, proposer, byzantine_nodes=silent):
            succ += 1
    return succ / n_rounds


def run_config(n_nodes, byz_ratio, n_rounds):
    dyn, std = [], []
    finals = []
    for s in SEEDS:
        c, w, r_ep, r_fin, hs = simulate_dynamic(n_nodes, byz_ratio, n_rounds, s)
        dyn.append(c); finals.append({"R_epoch": r_ep, "R_final": r_fin, "honest_share": hs})
        std.append(simulate_std(n_nodes, byz_ratio, n_rounds, s))
    return {
        "n_nodes": n_nodes, "byzantine_ratio": byz_ratio, "n_seeds": len(SEEDS),
        "n_rounds": n_rounds, "epoch_rounds": EPOCH_ROUNDS, "floor": FLOOR,
        "min_w": MIN_W, "max_w": MAX_W,
        "cw_dyn_mean": st.mean(dyn), "cw_dyn_sd": st.pstdev(dyn), "cw_dyn_rates": dyn,
        "std_mean": st.mean(std), "std_sd": st.pstdev(std), "std_rates": std,
        "diff_mean": st.mean(dyn) - st.mean(std),
        "finals": finals,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2000)
    a = ap.parse_args()
    out = {"results": [], "meta": {"rounds": a.rounds, "seeds": SEEDS,
                                   "epoch_rounds": EPOCH_ROUNDS, "floor": FLOOR,
                                   "min_w": MIN_W, "max_w": MAX_W,
                                   "mechanism": "participation-driven decay, epoch-frozen, clipped"}}
    print(f"== 路线C PoC：参与率驱动权重展宽（{a.rounds} 轮 × {len(SEEDS)} 种子）==")
    for (n, r) in [(10, 0.33), (10, 0.4), (16, 0.33), (16, 0.4), (4, 0.33)]:
        res = run_config(n, r, a.rounds)
        out["results"].append(res)
        rf = st.mean([f["R_final"] for f in res["finals"]])
        hs = st.mean([f["honest_share"] for f in res["finals"]])
        print(f"  n={n:>3} byz={r*100:>3.0f}% | CW-dyn {res['cw_dyn_mean']*100:>5.1f}±{res['cw_dyn_sd']*100:.1f}%  "
              f"STD {res['std_mean']*100:>5.1f}±{res['std_sd']*100:.1f}%  diff {res['diff_mean']*100:+6.1f}%  "
              f"R_final={rf:.2f} honest_w={hs*100:.1f}%")
    op = Path(_REPO_ROOT) / "results" / "consensus_comparison" / "weight_broadening_poc_report.json"
    with open(op, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[报告写入] {op}")


if __name__ == "__main__":
    main()
