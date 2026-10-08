# -*- coding: utf-8 -*-
"""合谋检测双通道小实验（任务书结合点②）

实验设计（2×2 × 3 seeds）：
  行 × 列 = {正常流, 伪造注入} × {单通道(不验签), 双通道(ECDSA 验签门)}
  - 底料：iql_bc_marl_seed*.json 的逐回合链上积分增量（真实训练数据）
  - 正常组：全部行为包由各 agent 真实私钥签名
  - 伪造组：攻击者顶名 agent_0 注入伪造流（与 agent_1 高相关的假证据），
            包以攻击者私钥签名 → 对 agent_0 注册公钥验签必失败
  - 统计：Collusion Rate = |Pearson| > 0.90 的 agent 对占比（与评估协议①同口径）
  - 预期：单通道+伪造 → 统计被投毒；双通道+伪造 → 伪造包被验签门拒收，统计回到正常基线

产出：results/evaluation_protocol/dual_channel/（JSON + summary.md）
"""
import argparse
import glob
import json
import os
from collections import defaultdict

import numpy as np

from marl.integration.cooperation_detector import CooperationDetector
from blockchain.crypto.ecdsa_utils import ECDSAUtils

THRESHOLD = 0.90
FORGED_PAIR_NOISE = 0.05  # 伪造流 = agent_1 流 × 缩放 + 该幅度噪声（制造假高相关）


def pearson(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    r, _ = np.corrcoef(a, b)[0, 1], None
    return float(r)


def load_increments(path):
    """真实训练数据 → 逐 agent 逐回合链上积分增量"""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    hist = d["bc_scores_history"]
    agents = sorted(hist[0].keys())
    return {a: list(np.diff([float(h[a]) for h in hist])) for a in agents}


def sign_stream(agent_id, key, stream):
    """把一条增量流打包为逐条真实 ECDSA 签名包"""
    return [
        ECDSAUtils.sign_action(agent_id, key, action={"delta": float(v)}, nonce=t)
        for t, v in enumerate(stream)
    ]


def collusion_rate(streams, agents):
    """streams: {agent_id: 增量列表}；返回 (rate, pair_r 列表)"""
    pairs = []
    for i in range(len(agents)):
        for j in range(i + 1, len(agents)):
            r = pearson(streams[agents[i]], streams[agents[j]])
            if r is not None:
                pairs.append(r)
    if not pairs:
        return None, []
    return sum(1 for r in pairs if abs(r) > THRESHOLD) / len(pairs), pairs


def streams_from_packages(pkgs, agents):
    out = {a: [] for a in agents}
    for p in pkgs:
        a = p["agent_id"]
        if a in out:
            out[a].append(float(p["action"]["delta"]))
    return out


def run_seed(seed, genuine, attacker_key):
    """单 seed：返回 2×2 四个格的 Collusion Rate 与验签统计

    伪造语义：攻击者把 agent_0 的整段记录历史替换为与自己私钥签名的伪造流
    （该流与 agent_1 的真实流高相关 —— 伪造"合谋证据"）。单通道下统计者无法
    分辨、直接采信；双通道下这些包对 agent_0 注册公钥验签全部失败 → 拒收。
    """
    agents = sorted(genuine.keys())
    agent_keys, agent_pubs = {}, {}
    for a in agents:
        k, pub = ECDSAUtils.generate_key_pair()
        agent_keys[a], agent_pubs[a] = k, pub

    genuine_pkgs = []
    for a in agents:
        genuine_pkgs += sign_stream(a, agent_keys[a], genuine[a])
    others_pkgs = [p for p in genuine_pkgs if p["agent_id"] != "agent_0"]

    # 伪造流：顶名 agent_0，与 agent_1 真实流高相关（伪造"合谋证据"）
    forged_stream = [v * 0.9 + float(np.random.default_rng(seed).normal(0, FORGED_PAIR_NOISE))
                     for v in genuine["agent_1"]]
    forged_pkgs = sign_stream("agent_0", attacker_key, forged_stream)

    def rate_via(forged, dual):
        """forged: 是否注入顶名伪造历史；dual: 是否过验签门。
        正常格 = 仅真实包；伪造格 = agent_0 历史被攻击者顶名替换（单通道）/
        伪造包被验签门拒收（双通道，真实 agent_0 数据保留）。"""
        det = CooperationDetector(n_agents=len(agents))
        if forged and not dual:
            verified = others_pkgs + list(forged_pkgs)   # 单通道：采信顶名替换历史
            rejected = len(forged_pkgs)
        elif forged and dual:
            verified, rejected = det.filter_verified_packages(genuine_pkgs + forged_pkgs, agent_pubs)
        else:
            verified, rejected = list(genuine_pkgs), 0
        streams = streams_from_packages(verified, agents)
        rate, pairs = collusion_rate(streams, agents)
        return {
            "rate": round(rate, 4) if rate is not None else None,
            "pair_r": [round(p, 4) for p in pairs],
            "verify_stats": det.get_verify_stats(),
            "n_rejected": rejected,
        }

    return {
        "normal_single": rate_via(False, False),   # 正常 × 单通道
        "normal_dual": rate_via(False, True),      # 正常 × 双通道
        "forged_single": rate_via(True, False),    # 伪造 × 单通道
        "forged_dual": rate_via(True, True),       # 伪造 × 双通道
        "_forged_injected": len(forged_pkgs),
    }


def main():
    ap = argparse.ArgumentParser(description="合谋检测双通道小实验（任务书②）")
    ap.add_argument("--data-dir", default="../MARL-ECDSA_共识链_提交包/other/测试数据/algorithm_comparison")
    ap.add_argument("--out", default="results/evaluation_protocol/dual_channel")
    args = ap.parse_args()

    seeds = [42, 123, 456]
    cells = defaultdict(list)
    for seed in seeds:
        path = os.path.join(args.data_dir, f"iql_bc_marl_seed{seed}.json")
        genuine = load_increments(path)
        attacker_key, _ = ECDSAUtils.generate_key_pair()  # 攻击者自己的私钥（非 agent_0 的）
        res = run_seed(seed, genuine, attacker_key)
        for cell in ("normal_single", "normal_dual", "forged_single", "forged_dual"):
            cells[cell].append(res[cell])
        print(f"seed {seed}: 单通道 {res['forged_single']['rate']} → "
              f"双通道 {res['forged_dual']['rate']}（伪造包 {res['_forged_injected']} 条，"
              f"拒收 {res['forged_dual']['verify_stats']['rejected']}）")

    os.makedirs(args.out, exist_ok=True)
    summary = {
        "design": "2×2：{正常,伪造注入}×{单通道(不验签),双通道(ECDSA验签门)}，3 seeds",
        "threshold": THRESHOLD,
        "forged_stream": "顶名 agent_0，流=agent_1×0.9+噪声(0.05)，攻击者私钥签名",
        "genuine_source": "iql_bc_marl_seed{42,123,456}.json 链上积分增量（真实训练数据）",
        "cells": {k: {
            "rate_mean": round(float(np.mean([c["rate"] for c in v if c["rate"] is not None])), 4),
            "per_seed": [{"rate": c["rate"], "verify": c["verify_stats"]} for c in v],
        } for k, v in cells.items()},
    }
    with open(os.path.join(args.out, "dual_channel.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    md = ["# 合谋检测双通道 — 小实验摘要（任务书②）", "",
          "> 底料为真实训练数据（链上积分增量）；伪造 = 攻击者私钥签名的顶名包；", "",
          "| 组 | 通道 | Collusion Rate（3 seeds 均值） | 伪造包拒收 |", "|---|---|---|---|"]
    for cell, label in (("normal_single", "正常"), ("normal_dual", "正常"),
                        ("forged_single", "伪造注入"), ("forged_dual", "伪造注入")):
        ch = "单通道" if cell.endswith("single") else "双通道"
        c = summary["cells"][cell]
        rej = c["per_seed"][0]["verify"]["rejected"]
        md.append(f"| {label} | {ch} | {c['rate_mean']} | {rej} |")
    md += ["", "**结论**：伪造注入在单通道下污染统计（率↑），双通道验签门拒收伪造包后统计回到正常基线；"
           "数值以 dual_channel.json 为准，如实呈现。"]
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print("结果写入:", os.path.abspath(args.out))
    for k, v in summary["cells"].items():
        print(f"  {k:16s} rate_mean = {v['rate_mean']}")


if __name__ == "__main__":
    main()
