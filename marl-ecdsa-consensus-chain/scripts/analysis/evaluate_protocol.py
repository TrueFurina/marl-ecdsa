# -*- coding: utf-8 -*-
"""评估协议对齐（任务书结合点①④）—— Tian 2025 四指标 + 消融协议映射

产出（写入 --out 目录，默认 results/evaluation_protocol/）：
  evaluation_protocol.json   全部计算结果（机器可读）
  summary.md                 三线表摘要（人读）
  README.md                  数据字典（口径定义 / IC 声明 / 结算对齐声明 / 消融映射 / 噪声状态）

口径纪律：
  - 全部数字由本脚本从原始 JSON 程序化计算，禁手抄；
  - IC 指数为本项目口径（横截面 corr），不得宣称与 Tian 2025 逐值可比；
  - 噪声鲁棒性需冒烟重跑，未跑前如实标 PENDING。
"""
import argparse
import glob
import json
import os
from collections import defaultdict

import numpy as np
from scipy import stats as sps


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pearson(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    r, _ = sps.pearsonr(a, b)
    return float(r)


# ---------------------------------------------------------------- ① Social Welfare
def social_welfare(files_by_arm):
    """团队口径：各臂 summary.avg_env_reward 跨 seed 均值±std。

    说明：SimpleSpread 的 env_reward 即团队共享福利（单智能体分解不可得），
    故采用团队口径——已在数据字典声明。
    """
    out = {}
    for arm, files in sorted(files_by_arm.items()):
        vals = [load(f)["summary"]["avg_env_reward"] for f in files]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        out[arm] = {
            "n_seeds": len(vals),
            "mean": round(float(np.mean(vals)), 3),
            "std": round(float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0, 3),
            "per_seed": [round(v, 3) for v in sorted(vals)],
        }
    return out


# ---------------------------------------------------------------- ② Collusion Rate
def collusion_rate(files_by_arm, threshold=0.90):
    """行为向量 Pearson 相关 > 阈值 的 agent 对占比。

    行为向量 = 逐回合链上积分增量（bc_scores_history 的差分；ECDSA 签名存证的
    贡献流）。pure 臂无链上账本（增量为零/缺失）→ 如实标 N/A。
    """
    out = {}
    for arm, files in sorted(files_by_arm.items()):
        per_seed, na = [], 0
        for f in files:
            d = load(f)
            hist = d.get("bc_scores_history")
            if not hist:
                na += 1
                continue
            agents = sorted(hist[0].keys())
            inc = {a: np.diff([float(h[a]) for h in hist]) for a in agents}
            pairs, above = [], []
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    r = pearson(inc[agents[i]], inc[agents[j]])
                    if r is None:
                        continue
                    pairs.append(r)
                    above.append(abs(r) > threshold)
            if not pairs:
                na += 1
                continue
            per_seed.append({
                "rate": round(sum(above) / len(pairs), 4),
                "n_pairs": len(pairs),
                "pair_r": [round(p, 4) for p in pairs],
            })
        if per_seed:
            rates = [p["rate"] for p in per_seed]
            out[arm] = {
                "n_seeds": len(rates),
                "rate_mean": round(float(np.mean(rates)), 4),
                "per_seed": per_seed,
                "threshold": threshold,
                "note": "行为向量=逐回合链上积分增量；|r|>阈值 计为高关联对",
            }
        else:
            out[arm] = {"rate": "N/A", "note": "无链上账本数据（pure 臂），共 %d run" % na}
    return out


# ---------------------------------------------------------------- ① IC Index
def ic_index(files_by_arm):
    """Incentive Compatibility Index（本项目口径）：

    横截面 corr(终态贡献权重_i, 终态链上积分_i)——贡献度权重取共识层
    consensus_stats.weights（CW-PBFT 逐节点权重），激励取链上积分终值
    bc_scores_final。仅 bc 臂有链上数据；n_agents=3 的横截面，n 小，
    仅作方向性证据，不得与 Tian 逐值比较。
    """
    out = {}
    for arm, files in sorted(files_by_arm.items()):
        per_seed = []
        for f in files:
            d = load(f)
            w = (d.get("consensus_stats") or {}).get("weights")
            bf = d.get("bc_scores_final")
            if not w or not bf:
                continue
            agents = sorted(bf.keys())
            wv = [float(w[a]) for a in agents] if isinstance(w, dict) else [float(x) for x in w]
            if len(wv) != len(agents):
                continue
            r = pearson(wv, [float(bf[a]) for a in agents])
            if r is not None:
                per_seed.append(round(r, 4))
        if per_seed:
            out[arm] = {
                "n_seeds": len(per_seed),
                "ic_mean": round(float(np.mean(per_seed)), 4),
                "per_seed": per_seed,
                "note": "横截面 corr(贡献权重_i, 链上积分_i)，n_agents=3；本项目口径",
            }
    return out


# ---------------------------------------------------------------- ① 噪声鲁棒性
def noise_robustness(out_dir):
    """奖励噪声保持率（σ=0.3）。需冒烟重跑；未跑前如实标 PENDING。"""
    nd = os.path.join(out_dir, "noise")
    if os.path.isdir(nd) and glob.glob(os.path.join(nd, "*.json")):
        clean, noisy = [], []
        for f in glob.glob(os.path.join(nd, "clean_*.json")):
            clean.append(load(f)["summary"]["avg_env_reward"])
        for f in glob.glob(os.path.join(nd, "noisy_*.json")):
            noisy.append(load(f)["summary"]["avg_env_reward"])
        if clean and noisy:
            keep = float(np.mean(noisy)) / float(np.mean(clean)) if np.mean(clean) else None
            return {"status": "OK", "keep_rate": round(keep, 4) if keep else None,
                    "n_clean": len(clean), "n_noisy": len(noisy)}
    return {"status": "PENDING", "note": "冒烟重跑（3 seeds × 减半 episode，σ=0.3）未执行；"
                                          "执行后按 results/evaluation_protocol/noise/ 约定落盘即可重算"}


# ---------------------------------------------------------------- ④ 消融对齐
ABLATION_MAP = [
    # (本项目臂, 对应 Tian 2025 变体, 说明)
    ("baseline", "FBM（全量）", "完整栈：ECDSA + CW-PBFT + 激励合约"),
    ("security", "FBM − 去检测", "去 SecurityGuard/签名防护层 —— 对应 Tian 的统计检测移除（本项目检测为密码学攻击面）"),
    ("consensus", "（Tian 无对应：去 CW-PBFT）", "去贡献加权共识层——Tian 采用标准 PBFT，无共识消融维度，为本项目增量维度"),
    ("incentive", "FBM − 去激励重分配", "去 λ 链上激励结算 —— 对应 Tian 的激励重分配移除"),
]


def ablation_alignment(ablation_dir):
    arms = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(ablation_dir, "*.json"))):
        name = os.path.splitext(os.path.basename(f))[0]
        arm, _, seed = name.rpartition("_seed")
        if not arm:
            continue
        arms[arm].append((int(seed), f))
    out = {}
    for arm, runs in sorted(arms.items()):
        seeds = sorted(runs)
        vals, coop, used_key = [], [], None
        for _, f in seeds:
            s = load(f).get("summary", {})
            v = s.get("avg_env_reward_last_50", s.get("avg_env_reward"))
            if v is None:
                continue
            used_key = used_key or ("avg_env_reward_last_50" if "avg_env_reward_last_50" in s else "avg_env_reward")
            vals.append(v)
            coop.append(s.get("avg_cooperation_rate", 0.0))
        if not vals:
            continue
        out[arm] = {
            "seeds": [s for s, _ in seeds],
            "field": used_key,
            "env_last50_mean": round(float(np.mean(vals)), 3),
            "env_last50_std": round(float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0, 3),
            "coop_mean": round(float(np.mean(coop)), 4),
            "n": len(vals),
        }
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Tian 2025 评估协议对齐（任务书结合点①④）")
    ap.add_argument("--data-root", default="MARL-ECDSA_共识链_提交包/other/测试数据",
                    help="algorithm_comparison/ ablation/ 所在目录")
    ap.add_argument("--conv-dir", default="results/convergence_3000",
                    help="convergence_3000 目录（142 run，主口径）")
    ap.add_argument("--out", default="results/evaluation_protocol")
    args = ap.parse_args()

    ac = os.path.join(args.data_root, "algorithm_comparison")
    files_by_arm = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(ac, "*.json"))):
        name = os.path.splitext(os.path.basename(f))[0]
        if name == "comparison_report":
            continue
        arm = name.rsplit("_seed", 1)[0]
        files_by_arm[arm].append(f)

    os.makedirs(args.out, exist_ok=True)

    result = {
        "social_welfare": {
            "algorithm_comparison_3seeds": social_welfare(files_by_arm),
            "convergence_3000_n71": social_welfare({
                "iql_pure_marl": sorted(glob.glob(os.path.join(args.conv_dir, "pure_marl_seed*.json"))),
                "iql_bc_marl": sorted(glob.glob(os.path.join(args.conv_dir, "bc_marl_seed*.json"))),
            }),
        },
        "collusion_rate": collusion_rate(files_by_arm),
        "ic_index": ic_index(files_by_arm),
        "noise_robustness": noise_robustness(args.out),
        "ablation_alignment": ablation_alignment(os.path.join(args.data_root, "ablation")),
        "ablation_mapping": [{"arm": a, "tian_variant": t, "note": n} for a, t, n in ABLATION_MAP],
    }

    with open(os.path.join(args.out, "evaluation_protocol.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---- summary.md（三线表）----
    sw_a = result["social_welfare"]["algorithm_comparison_3seeds"]
    lines = ["# 评估协议对齐 — 摘要（Tian 2025 四指标）", "",
             "> 全部数字由 `scripts/analysis/evaluate_protocol.py` 程序化计算；IC 为本项目口径，不得宣称逐值可比。", ""]
    lines += ["## Social Welfare（团队 env_reward，均值±std）", "",
              "| 臂 | n | Social Welfare |", "|---|---|---|"]
    for arm, v in sw_a.items():
        lines.append(f"| {arm} | {v['n_seeds']} | {v['mean']:.3f} ± {v['std']:.3f} |")
    lines += ["", "## Collusion Rate（|Pearson|>0.90 的 agent 对占比）", "",
              "| 臂 | rate（3 seed 均值） | 说明 |", "|---|---|---|"]
    for arm, v in result["collusion_rate"].items():
        val = v.get("rate_mean", v.get("rate"))
        lines.append(f"| {arm} | {val} | {v.get('note','')} |")
    lines += ["", "## Incentive Compatibility Index（横截面 corr）", "",
              "| 臂 | IC（3 seed 均值） |", "|---|---|"]
    for arm, v in result["ic_index"].items():
        lines.append(f"| {arm} | {v['ic_mean']} |")
    lines += ["", "## Noise Robustness", "",
              json.dumps(result["noise_robustness"], ensure_ascii=False)]
    lines += ["", "## 消融协议对齐（④）", "",
              "| 臂 | n | env(last50) 均值±std | 合作率 | 对应 Tian 变体 |", "|---|---|---|---|---|"]
    mapping = {m["arm"]: (m["tian_variant"], m["note"]) for m in result["ablation_mapping"]}
    for arm, v in result["ablation_alignment"].items():
        tv = mapping.get(arm, ("", ""))[0]
        lines.append(f"| {arm} | {v['n']} | {v['env_last50_mean']:.3f} ± {v['env_last50_std']:.3f} | "
                     f"{v['coop_mean']:.4f} | {tv} |")
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("评估协议结果写入:", os.path.abspath(args.out))
    print("  Social Welfare 臂数:", len(sw_a), "| IC 臂数:", len(result["ic_index"]),
          "| 消融臂数:", len(result["ablation_alignment"]),
          "| 噪声:", result["noise_robustness"]["status"])


if __name__ == "__main__":
    main()
