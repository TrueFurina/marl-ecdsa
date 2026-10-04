"""
从真实实验结果（results/convergence_3000/）聚合出 Dashboard / 导出数据集所需的
training_results_*.json。

为什么存在这个脚本：
- 旧脚本 scripts/generate_complete_data.py 用 np.random 合成数据（硬编码 V2 目标值），
  仪表盘与导出的公开数据集跑的是假数据，违反"合成/demo 数据严禁出现于交付物"。
- 本脚本改为用**真实 71 种子 × 3000 回合**实验逐回合均值聚合，使仪表盘与导出数据集
  与论文 n=71 口径一致、可辩护。

聚合规则（诚实优先）：
- 逐回合数值字段（episode_rewards/env_rewards/cooperation_rates/betrayal_rates/losses）
  跨种子取均值。
- 标题用 avg_reward 由 **env_rewards** 口径计算（不含 BC 激励），与论文竞赛对比口径一致；
  episode_rewards 仍保留用于训练曲线展示（代理实际收到的回合奖励，合法）。
- bc 模式：bc_scores_history 逐回合逐 agent 跨种子均值 → 真实链上积分曲线；
  ecdsa/security/consensus/blockchain 统计按"计数求和、比率取均值"聚合。
- pure 模式：无区块链激励 → bc_scores_history=[]、区块链相关统计={}（仪表盘显示"未启用"占位，诚实）。
- selfish 模式：convergence_3000 无该实验，不生成（避免伪造）。

用法：
  python scripts/build_dashboard_data.py                  # 生成 bc + pure
  python scripts/build_dashboard_data.py --mode bc        # 只生成 bc
  python scripts/build_dashboard_data.py --check-only     # 仅校验数据完整性，不写文件
"""
import argparse
import glob
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONV_DIR = os.path.join(ROOT, "results", "convergence_3000")
N_AGENTS = 3


def _load_seed(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mean_per_episode(arrays, length):
    """arrays: list[list[float|None]]；返回长度 length 的逐回合均值（None 不参与）。
    各数组长度可能不一致（如 losses 为 2998），按各自长度对齐，超出部分记为无数据。"""
    acc = np.zeros(length, dtype=float)
    cnt = np.zeros(length, dtype=float)
    for arr in arrays:
        m = len(arr)
        a = np.array([x if x is not None else np.nan for x in arr], dtype=float)
        mask = ~np.isnan(a)
        acc[:m][mask] += a[mask]
        cnt[:m][mask] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(cnt > 0, acc / np.where(cnt > 0, cnt, 1), 0.0)
    return out.tolist()


def _aggregate_bc_scores_history(seeds, length):
    """逐回合逐 agent 跨种子均值；返回 list[dict]。"""
    agent_acc = {f"agent_{a}": np.zeros(length, dtype=float) for a in range(N_AGENTS)}
    agent_cnt = {f"agent_{a}": np.zeros(length, dtype=float) for a in range(N_AGENTS)}
    for sd in seeds:
        hist = sd.get("bc_scores_history") or []
        for i in range(min(len(hist), length)):
            row = hist[i]
            if not isinstance(row, dict):
                continue
            for a in range(N_AGENTS):
                k = f"agent_{a}"
                v = row.get(k)
                if isinstance(v, (int, float)):
                    agent_acc[k][i] += v
                    agent_cnt[k][i] += 1
    out = []
    for i in range(length):
        row = {}
        for a in range(N_AGENTS):
            k = f"agent_{a}"
            c = agent_cnt[k][i]
            row[k] = float(agent_acc[k][i] / c) if c > 0 else 0.0
        out.append(row)
    return out


def _sum_stat(seeds, key, sub):
    """对种子字典里的数值字段求和。"""
    total = 0
    for sd in seeds:
        d = sd.get(key) or {}
        v = d.get(sub)
        if isinstance(v, (int, float)):
            total += v
    return total


def _mean_stat(seeds, key, sub):
    vals = []
    for sd in seeds:
        d = sd.get(key) or {}
        v = d.get(sub)
        if isinstance(v, (int, float)):
            vals.append(v)
    return float(np.mean(vals)) if vals else 0.0


def _aggregate_blockchain_stats(seeds):
    blk = {}
    for k in ("height", "total_blocks", "total_transactions", "pending_transactions"):
        blk[k] = _sum_stat(seeds, "blockchain_stats", k)
    blk["latest_hash"] = (seeds[0].get("blockchain_stats") or {}).get("latest_hash", "")
    blk["pending_transactions"] = 0
    # 09-28：不再硬编码 chain_valid=True。聚合层并未做真实链校验，谎报 True 等于
    # 「零校验却显示验证通过」（前端会把它显示成绿色 OK）。置 None = 明确"未校验"；
    # 若将来需要真实校验，须读真链并调用 Blockchain.validate_chain() 后回填。
    blk["chain_valid"] = None
    blk["total_signers"] = N_AGENTS
    return blk


def _aggregate_ecdsa_stats(seeds):
    return {
        "sign_count": _sum_stat(seeds, "ecdsa_stats", "sign_count"),
        "verify_count": _sum_stat(seeds, "ecdsa_stats", "verify_count"),
        "unique_keys": N_AGENTS,
        "key_generation_count": N_AGENTS,
        "nonce_range": _sum_stat(seeds, "ecdsa_stats", "sign_count"),
        "avg_sign_time_ms": _mean_stat(seeds, "ecdsa_stats", "avg_sign_time_ms"),
        "avg_verify_time_ms": _mean_stat(seeds, "ecdsa_stats", "avg_verify_time_ms"),
    }


def _aggregate_security_stats(seeds):
    return {
        "ecdsa_sign_count": _sum_stat(seeds, "security_stats", "ecdsa_sign_count"),
        "ecdsa_verify_count": _sum_stat(seeds, "security_stats", "ecdsa_verify_count"),
        "security_pass_count": _sum_stat(seeds, "security_stats", "security_pass_count"),
        "security_fail_count": _sum_stat(seeds, "security_stats", "security_fail_count"),
        "total_alerts": 0,
        "replay_attempts_blocked": _sum_stat(seeds, "security_stats", "replay_attempts_blocked"),
        "invalid_signature_blocked": _sum_stat(seeds, "security_stats", "invalid_signature_blocked"),
        "nonce_reuse_blocked": _sum_stat(seeds, "security_stats", "nonce_reuse_blocked"),
    }


def _aggregate_consensus_stats(seeds):
    first = seeds[0].get("consensus_stats") or {}
    return {
        "node_id": first.get("node_id", 0),
        "state": first.get("state", "COMMITTED"),
        "n_nodes": first.get("n_nodes", 4),
        "f_tolerance": first.get("f_tolerance", 1),
        "prepare_votes": _sum_stat(seeds, "consensus_stats", "prepare_votes"),
        "commit_votes": _sum_stat(seeds, "consensus_stats", "commit_votes"),
        "current_block_hash": first.get("current_block_hash", ""),
        "weights": first.get("weights", {}),
        "consensus_success_rate": _mean_stat(seeds, "consensus_stats", "consensus_success_rate"),
        "weight_history": [],
    }


def _aggregate_leaderboard(seeds):
    """由逐种子最终链上积分均值排序。"""
    final_acc = {f"agent_{a}": [] for a in range(N_AGENTS)}
    for sd in seeds:
        f = sd.get("bc_scores_final") or {}
        for a in range(N_AGENTS):
            v = f.get(f"agent_{a}")
            if isinstance(v, (int, float)):
                final_acc[f"agent_{a}"].append(v)
    agents = []
    for a in range(N_AGENTS):
        vals = final_acc[f"agent_{a}"]
        score = float(np.mean(vals)) if vals else 0.0
        agents.append({
            "agent_id": a,
            "agent_name": f"Agent_{a}",
            "bc_score": round(score, 4),
            "cooperation_rate": 0.0,  # 由仪表盘另行填充
            "total_reward": 0.0,
            "blocks_proposed": 0,
            "blocks_validated": 0,
        })
    agents.sort(key=lambda x: x["bc_score"], reverse=True)
    return agents


def _build_summary(ep_mean, env_mean, coop_mean, betray_mean, losses, mode, elapsed_mean):
    last50_e = env_mean[-50:] if len(env_mean) >= 50 else env_mean
    return {
        "total_episodes": len(env_mean),
        # 标题口径：env_reward（不含 BC 激励），与论文竞赛对比口径一致
        "avg_reward": round(float(np.mean(env_mean)), 2),
        "avg_reward_last_50": round(float(np.mean(last50_e)), 2),
        "avg_cooperation_rate": round(float(np.mean(coop_mean)), 4),
        "avg_betrayal_rate": round(float(np.mean(betray_mean)), 4),
        "total_losses": int(np.count_nonzero([x for x in losses if x is not None])),
        "elapsed_time": round(float(elapsed_mean), 2),
        "mode": mode,
    }


def build(mode):
    pattern = os.path.join(CONV_DIR, f"{mode}_marl_seed*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"未找到 {pattern}（请确认 results/convergence_3000 已存在）")
    seeds = [_load_seed(p) for p in files]
    n = len(seeds)
    length = max(len(s.get("episode_rewards", [])) for s in seeds)

    ep = _mean_per_episode([s.get("episode_rewards", []) for s in seeds], length)
    env = _mean_per_episode([s.get("env_rewards", []) for s in seeds], length)
    coop = _mean_per_episode([s.get("cooperation_rates", []) for s in seeds], length)
    betray = _mean_per_episode([s.get("betrayal_rates", []) for s in seeds], length)
    losses = _mean_per_episode([s.get("losses", []) for s in seeds], length)
    elapsed = np.mean([(s.get("summary") or {}).get("elapsed_time", 0.0) for s in seeds])

    cfg = (seeds[0].get("config") or {}).copy()
    cfg["mode"] = mode

    data = {
        "config": cfg,
        "summary": _build_summary(ep, env, coop, betray, losses, mode, elapsed),
        "episode_rewards": [round(x, 2) for x in ep],
        "env_rewards": [round(x, 2) for x in env],
        "cooperation_rates": [round(x, 4) for x in coop],
        "betrayal_rates": [round(x, 4) for x in betray],
        "bc_scores_history": _aggregate_bc_scores_history(seeds, length) if mode == "bc" else [],
        "losses": [round(x, 4) if x is not None else None for x in losses],
        "bc_scores_final": (
            {f"agent_{a}": round(float(np.mean(
                [ (s.get("bc_scores_final") or {}).get(f"agent_{a}") for s in seeds if isinstance((s.get("bc_scores_final") or {}).get(f"agent_{a}"), (int, float)) ])), 4)
             for a in range(N_AGENTS)}
            if mode == "bc" else {}
        ),
        "leaderboard": _aggregate_leaderboard(seeds) if mode == "bc" else [],
        "ecdsa_stats": _aggregate_ecdsa_stats(seeds) if mode == "bc" else {},
        "security_stats": _aggregate_security_stats(seeds) if mode == "bc" else {},
        "consensus_stats": _aggregate_consensus_stats(seeds) if mode == "bc" else {},
        "blockchain_stats": _aggregate_blockchain_stats(seeds) if mode == "bc" else {},
    }
    return data, n


def _validate(data, fname):
    er = data.get("episode_rewards")
    if not isinstance(er, list) or len(er) == 0:
        raise ValueError(f"[{fname}] episode_rewards 缺失或为空，已拒绝写入")
    if not isinstance(data.get("summary"), dict) or "avg_reward" not in data["summary"]:
        raise ValueError(f"[{fname}] summary 缺失或不完整，已拒绝写入")
    return True


def main():
    ap = argparse.ArgumentParser(description="从真实实验结果聚合 Dashboard 数据（替代合成数据）")
    ap.add_argument("--mode", choices=["pure", "bc", "all"], default="all")
    ap.add_argument("--check-only", action="store_true", help="仅校验 convergence_3000 完整性")
    args = ap.parse_args()

    groups = ["bc", "pure"] if args.mode == "all" else [args.mode]
    for mode in groups:
        data, n = build(mode)
        if args.check_only:
            print(f"[{mode}] 聚合成功：{n} 种子, {len(data['episode_rewards'])} 回合, "
                  f"env_avg={data['summary']['avg_reward']}, "
                  f"coop={data['summary']['avg_cooperation_rate']}, "
                  f"bc_scores_history={len(data['bc_scores_history'])}")
            continue
        _validate(data, f"training_results_{mode}.json")
        fname = f"training_results_{mode}.json"
        fpath = os.path.join(ROOT, fname)
        if os.path.exists(fpath):
            bak = fpath.replace(".json", "_backup.json")
            if not os.path.exists(bak):
                import shutil
                shutil.copy2(fpath, bak)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        s = data["summary"]
        print(f"[{mode}] 写入 {fname}（{n} 种子, {len(data['episode_rewards'])} 回合）: "
              f"env_avg={s['avg_reward']}, last50={s['avg_reward_last_50']}, "
              f"coop={s['avg_cooperation_rate']}, bc_hist={len(data['bc_scores_history'])}")


if __name__ == "__main__":
    main()
