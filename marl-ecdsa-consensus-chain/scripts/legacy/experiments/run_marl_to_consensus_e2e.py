#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_marl_to_consensus_e2e.py — MARL 训练 → 共识权重 端到端链路（2026-09-19）

修补的断裂点
------------
原共识实验的「贡献度权重」来自手写常量文件
``results/consensus_comparison/bc_scores_for_weights.json``
（全仓库 grep 不到任何生成它的脚本），即：贡献度→权重这一段是**断的**。

本脚本把链路接通：
    真实 MARL 训练（train.MARLBlockchainTrainer）
        → trainer.bridge.get_bc_scores()            # 真实累计积分
        → 权重桥接 bc_integration._update_consensus_weights（生产链路，未改动）
            实际落地权重可从 trainer.bridge.cw_pbft.get_weights() 读回
        → 落盘 bc_scores_from_training_<seed>.json + bc_scores_index.json

**不伪造数据**：若 torch / 训练链路跑不通，脚本直接 fail-closed 退出并打印原因，
绝不回退到合成常量。

产出
----
1) ``results/consensus_comparison/bc_scores_from_training_<seed>.json``
   每个 seed 一个文件，内含 n_agents ∈ {4,10,16} 三份真实训练产物：
       - ``bc_scores``                  真实累计积分（get_bc_scores 原样）
       - ``bc_scores_normalized``       s / max(s) ∈ (0,1]
       - ``production_consensus_weights``  生产链路实际写入 CW-PBFT 的权重
                                        （w = 1.0 + 0.5 * weighted_score，见
                                         bc_integration.py:383-395）
       - ``provenance``                 seed / mode / n_episodes / n_agents /
                                        时间戳 / 生成脚本绝对路径 / torch 版本
2) ``results/consensus_comparison/bc_scores_index.json``
   汇总索引，供 run_weight_broadening_full.py --scores-index 消费；
   顶层同样带 provenance（含每个 n 的 R 值）。

用法
----
    python -X utf8 scripts/legacy/experiments/run_marl_to_consensus_e2e.py \
        --episodes 500 --n-agents 4,10,16
    # 冒烟
    python -X utf8 ... --episodes 20 --n-agents 4 --seeds 42
"""
import sys
import json
import time
import logging
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

OUT_DIR = _REPO_ROOT / "results" / "consensus_comparison"

SEEDS = [42, 123, 456, 789, 1024, 2026, 3141, 5926, 7777, 8888]


def _rratio(d):
    v = list(d.values())
    mn = min(v)
    return (max(v) / mn) if mn > 0 else float("inf")


def run_one_training(n_agents, n_episodes, seed, mode, n_landmarks):
    """真跑一次 MARL 训练，返回 (bc_scores, production_weights, summary)。"""
    from train import TrainingConfig, MARLBlockchainTrainer  # torch 依赖，延迟导入
    kw = dict(n_agents=n_agents, n_episodes=n_episodes, seed=seed, mode=mode)
    if n_landmarks:
        kw["n_landmarks"] = n_landmarks
    cfg = TrainingConfig(**kw)
    trainer = MARLBlockchainTrainer(cfg)
    stats = trainer.train()
    bc_scores = dict(trainer.bridge.get_bc_scores())
    prod_w = dict(trainer.bridge.cw_pbft.get_weights()) if trainer.bridge.cw_pbft else {}
    summary = stats.summary() if hasattr(stats, "summary") else {}
    return bc_scores, prod_w, summary


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    ap.add_argument("--n-agents", default="4,10,16")
    ap.add_argument("--episodes", type=int, default=500)
    ap.add_argument("--mode", default="bc_marl",
                    help="训练模式；bc_marl = MARL+区块链激励（项目主口径）")
    ap.add_argument("--landmarks", type=int, default=None,
                    help="None = 沿用 TrainingConfig 默认(3)，与 run_experiment.py 一致")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    for noisy in ("blockchain.consensus.cw_pbft", "blockchain.ledger.blockchain",
                  "marl.integration.bc_integration", "train"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    agent_counts = [int(x) for x in a.n_agents.split(",") if x.strip()]
    out_dir = Path(a.out_dir) if a.out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # 环境自检（fail-closed）
    try:
        import torch
        torch_ver = torch.__version__
    except Exception as e:  # pragma: no cover
        raise SystemExit(f"[FAIL-CLOSED] torch 不可用，禁止伪造贡献度数据：{e}")
    try:
        import train  # noqa: F401
    except Exception as e:
        raise SystemExit(f"[FAIL-CLOSED] 训练链路 import 失败，禁止伪造贡献度数据：{e}")

    # provenance 只记**仓库相对路径**，不落地本机绝对路径（避免数据成为身份指纹）
    try:
        script_rel = Path(__file__).resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:  # 脚本被复制到仓库外执行
        script_rel = Path(__file__).name
    t_global = time.time()
    index = {
        "meta": {
            "script": script_rel,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "torch": torch_ver,
            "python": sys.version.split()[0],
            "mode": a.mode,
            "n_episodes": a.episodes,
            "n_landmarks": a.landmarks if a.landmarks else "TrainingConfig default",
            "seeds": seeds,
            "n_agents_list": agent_counts,
            "bc_score_source": "MARLBlockchainTrainer.bridge.get_bc_scores()",
            "weight_source": "MARLBlockchainTrainer.bridge.cw_pbft.get_weights() "
                             "(由 bc_integration._update_consensus_weights 写入, w=1.0+0.5*weighted_score)",
            "note": "全部数值由真实训练产生；无任何手写/合成常量。",
        },
        "runs_by_n": {},
    }

    for seed in seeds:
        per_seed = {
            "provenance": {
                "seed": seed,
                "mode": a.mode,
                "n_episodes": a.episodes,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "generated_by": script_rel,
                "torch": torch_ver,
                "bc_score_source": "trainer.bridge.get_bc_scores()",
                "weight_source": "trainer.bridge.cw_pbft.get_weights()",
            },
            "runs_by_n": {},
        }
        for na in agent_counts:
            t0 = time.time()
            bc, pw, summ = run_one_training(na, a.episodes, seed, a.mode, a.landmarks)
            mx = max(bc.values()) if bc else 1.0
            rec = {
                "provenance": {
                    "seed": seed,
                    "n_agents": na,
                    "n_episodes": a.episodes,
                    "mode": a.mode,
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "generated_by": script_rel,
                    "elapsed_sec": round(time.time() - t0, 2),
                },
                "bc_scores": bc,
                "bc_scores_normalized": {k: v / mx for k, v in bc.items()},
                "production_consensus_weights": pw,
                "R_bc_scores": _rratio(bc),
                "R_production_weights": _rratio(pw) if pw else None,
                "training_summary": {
                    k: summ.get(k) for k in
                    ("total_episodes", "avg_reward", "avg_env_reward",
                     "avg_cooperation_rate", "avg_betrayal_rate")
                    if isinstance(summ, dict) and k in summ
                },
            }
            per_seed["runs_by_n"][str(na)] = rec
            index["runs_by_n"].setdefault(str(na), {})[str(seed)] = rec
            print(f"  seed={seed:<5} n_agents={na:<3} {rec['provenance']['elapsed_sec']:>6.1f}s  "
                  f"R_bc={rec['R_bc_scores']:.4f}  R_w={rec['R_production_weights']:.4f}  "
                  f"bc={ {k: round(v, 1) for k, v in list(bc.items())[:3]} }...")

        sp = out_dir / f"bc_scores_from_training_{seed}.json"
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(per_seed, f, indent=2, ensure_ascii=False)
        print(f"  [写入] {sp}")

    index["meta"]["elapsed_sec"] = round(time.time() - t_global, 1)
    idxp = out_dir / "bc_scores_index.json"
    with open(idxp, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"\n[写入] {idxp}  (总耗时 {index['meta']['elapsed_sec']}s)")


if __name__ == "__main__":
    main()
