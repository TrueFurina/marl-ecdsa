#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_e2e_consensus_closing.py — 端到端链路收尾（2026-09-22）

把 run_marl_to_consensus_e2e.py 真跑训练导出的**生产权重**
（production_consensus_weights，由 bc_integration._update_consensus_weights 写入，
 w = 1.0 + 0.5 * weighted_score）真正灌进 CW-PBFT 并跑出共识成功率，
让链路从「训练 → 贡献度」延长到「贡献度 → 权重 → 共识成功率」。

这是创新链断裂点的彻底闭合：此前共识实验从未接上训练循环，贡献度权重来自手写常量。
本脚本证明：用真实 MARL 训练导出的生产权重，CW-PBFT 在省略故障下 ≈ 标准 PBFT（零增益），
即真实贡献度权重不足以区分拜占庭/诚实节点 —— 这是论文必须保留的诚实负结果。

权重来源：results/consensus_comparison/bc_scores_index.json（每个 n × seed 一份 production_consensus_weights）
模拟器：复用 run_weight_broadening_full.simulate_static / CWPBFTConsensus（与生产链路同口径）

不伪造数据：production_consensus_weights 缺失时 fail-closed 退出。
"""
import sys
import json
import time
import logging
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
for p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from run_weight_broadening_full import (  # 复用模拟器与生产链路同口径
    simulate_static, simulate_std, SEEDS, NODE_COUNTS, BYZ_RATIOS,
    r_ratio, pct2, mean, stdev, welch_ttest,
)

OUT_DIR = _REPO_ROOT / "results" / "consensus_comparison"
INDEX = OUT_DIR / "bc_scores_index.json"


def load_production_weights():
    if not INDEX.exists():
        raise SystemExit(f"[FAIL-CLOSED] 找不到 {INDEX}；请先跑 run_marl_to_consensus_e2e.py")
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    # runs_by_n[n][seed] -> production_consensus_weights (agent_i -> w)
    return idx


def main():
    logging.basicConfig(level=logging.ERROR)
    idx = load_production_weights()
    runs = idx["runs_by_n"]

    results = []
    t0 = time.time()
    for n in NODE_COUNTS:
        for br in BYZ_RATIOS:
            node_ids = [f"node_{i}" for i in range(n)]
            n_byz = int(n * br)
            byz_ids = set(node_ids[:n_byz])

            cw_rates, std_rates = [], []
            r_pw_list, honest_share_list = [], []
            for s in SEEDS:
                rec = runs.get(str(n), {}).get(str(s))
                if not rec or "production_consensus_weights" not in rec:
                    raise SystemExit(f"[FAIL-CLOSED] n={n} seed={s} 缺少 production_consensus_weights")
                pw = rec["production_consensus_weights"]
                # agent_i -> node_i（共识模拟器用 node_i 命名）
                wmap = {f"node_{i}": float(pw[f"agent_{i}"]) for i in range(n)}
                r_pw_list.append(r_ratio(wmap))
                honest_share_list.append(
                    sum(wmap[nid] for nid in node_ids if nid not in byz_ids) / sum(wmap.values())
                )
                cw = simulate_static(n, br, 2000, s, wmap)
                std = simulate_std(n, br, 2000, s)
                cw_rates.append(cw)
                std_rates.append(std)

            row = {
                "n_nodes": n,
                "byzantine_ratio": br,
                "weight_mode": "production_e2e",
                "n_seeds": len(SEEDS),
                "n_rounds": 2000,
                "cw_mean": mean(cw_rates),
                "cw_sd": stdev(cw_rates, ddof=1),
                "std_mean": mean(std_rates),
                "std_sd": stdev(std_rates, ddof=1),
                "diff_mean": mean(cw_rates) - mean(std_rates),
                "cw_mean_pct": pct2(mean(cw_rates)),
                "std_mean_pct": pct2(mean(std_rates)),
                "diff_pct": pct2(mean(cw_rates)) - pct2(mean(std_rates)),
                "welch_p": welch_ttest(cw_rates, std_rates)["p"],
                "R_production_weights_mean": mean(r_pw_list),
                "honest_weight_share_mean": mean(honest_share_list),
                "cw_rates": [round(x, 4) for x in cw_rates],
                "std_rates": [round(x, 4) for x in std_rates],
                "provenance": {
                    "weight_source": "bc_scores_index.json -> runs_by_n[n][seed].production_consensus_weights",
                    "weight_formula": "w = 1.0 + 0.5 * weighted_score (bc_integration._update_consensus_weights)",
                    "index_generated_at": idx["meta"].get("generated_at"),
                    "torch": idx["meta"].get("torch"),
                    "n_episodes": idx["meta"].get("n_episodes"),
                    "train_mode": idx["meta"].get("mode"),
                },
                "verdict": "NO_GAIN" if abs(mean(cw_rates) - mean(std_rates)) < 1e-9 else "GAIN",
            }
            # 逐 seed 落盘（供 verify_numbers.py 回溯，命名沿用 weight_broadening_full 约定）
            ps_dir = OUT_DIR / "e2e_closing"
            ps_dir.mkdir(parents=True, exist_ok=True)
            for k, (s, cwr, stdr, rpw, hs) in enumerate(
                zip(SEEDS, cw_rates, std_rates, r_pw_list, honest_share_list)
            ):
                (ps_dir / f"n{n}_b{br}_prod_cw_seed{s}.json").write_text(
                    json.dumps({"success_rate": cwr, "R_production_weights": rpw,
                                "honest_weight_share": hs}, ensure_ascii=False),
                    encoding="utf-8")
                (ps_dir / f"n{n}_b{br}_std_seed{s}.json").write_text(
                    json.dumps({"success_rate": stdr}, ensure_ascii=False),
                    encoding="utf-8")
            results.append(row)
            print(f"  n={n} byz={br}: CW={row['cw_mean_pct']}%  STD={row['std_mean_pct']}%  "
                  f"Δ={row['diff_pct']:+}pp  R_pw={row['R_production_weights_mean']:.3f}  "
                  f"honest_share={row['honest_weight_share_mean']:.3f}  -> {row['verdict']}")

    report = {
        "meta": {
            "script": "scripts/legacy/experiments/run_e2e_consensus_closing.py",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seeds": SEEDS,
            "n_rounds": 2000,
            "note": "真实 MARL 训练导出生产权重灌入 CW-PBFT；诚实负结果：R_pw≈1.13 下 CW≈STD（零增益）",
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "results": results,
    }
    outp = OUT_DIR / "e2e_consensus_closing_report.json"
    outp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[写入] {outp}")


if __name__ == "__main__":
    main()
