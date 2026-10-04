#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 E14 同批对照结果登记进 number_registry.json（NR-63 ~ NR-67），
并把 NR-58/59/60（跨批 E14）降级为"仅方向参考，不作显著性依据"。

所有 declared 数值均由 scripts/verify_numbers.py 同款统计（assurance_common.two_sample_stats）
从源文件复算得出，不是手抄。
"""
import json, os, sys, glob
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import assurance_common as ac  # noqa: E402

# 真值源与数据根均从 assurance_common 推导（与 verify_numbers.py 同一条通路），
# 可用 MARL_REGISTRY / MARL_DATA_ROOT 覆盖（换机/私有部署）。禁止硬编码本机绝对路径。
REG = Path(os.environ.get("MARL_REGISTRY") or ac.REGISTRY_PATH)
D = Path(os.environ.get("MARL_DATA_ROOT") or ac.RESULTS_DIR) / "dispatch_20260921"
FIELD = "summary.avg_env_reward_last_50"


def vals(tag, alg):
    out = []
    for p in sorted(D.glob(f"{tag}_{alg}_seed*.json")):
        out.append(json.load(open(p, encoding="utf-8"))["summary"]["avg_env_reward_last_50"])
    return out


def entry_for(nr, alg, tag_a="e14", tag_b="e14pure", label_a="bc_marl", label_b="pure_marl"):
    a, b = vals(tag_a, alg), vals(tag_b, alg)
    st = ac.two_sample_stats(a, b)
    delta = st["mean_a"] - st["mean_b"]
    verdict = {
        "iql": "不显著（方向为负）",
        "qmix": "方向为正、效应量中等偏大，但 n=10 检验力不足，未达 p<0.05",
        "vdn": "不显著（方向为负）",
        "mappo": "不显著（方向为负）",
    }[alg]
    return {
        "id": nr,
        "claim": f"E14 同批对照（n=10/组，seed100-109 同种子）{alg.upper()}：bc_marl 与 pure_marl 末50 env_reward 对比",
        "allowed_wording": (
            f"E14（3000 回合、λ=0.1、{alg.upper()}、n=10 同批同种子对照）："
            f"bc_marl 末50 环境奖励 {st['mean_a']:.2f}±{st['sd_a']:.2f}，"
            f"pure_marl {st['mean_b']:.2f}±{st['sd_b']:.2f}，Δ={delta:+.2f}；"
            f"Welch p={st['welch_p']:.4f}、Cohen d={st['cohens_d']:+.2f}、"
            f"95%CI [{st['ci95_diff'][0]:.2f},{st['ci95_diff'][1]:.2f}]。{verdict}。"
            f"**同批对照**（bc 与 pure 均为 seed100-109），可与非同批的 NR-58/59/60 互为稳健性参照。"
        ),
        "analysis": "two_sample",
        "sources": [
            {"glob": f"dispatch_20260921/{tag_a}_{alg}_seed*.json", "field": FIELD, "role": "a"},
            {"glob": f"dispatch_20260921/{tag_b}_{alg}_seed*.json", "field": FIELD, "role": "b"},
        ],
        "filter": {
            "config.n_episodes": 3000,
            "config.lambda_weight": 0.1,
            "config.algorithm": alg,
        },
        "n_expected": 10,
        "statistic": ["mean_a", "sd_a", "mean_b", "sd_b", "welch_p", "cohens_d", "ci95_diff"],
        "declared": {
            "mean_a": round(st["mean_a"], 4),
            "sd_a": round(st["sd_a"], 4),
            "mean_b": round(st["mean_b"], 4),
            "sd_b": round(st["sd_b"], 4),
            "welch_p": round(st["welch_p"], 5),
            "cohens_d": round(st["cohens_d"], 4),
            "ci95_diff": [round(st["ci95_diff"][0], 4), round(st["ci95_diff"][1], 4)],
            "n_a": len(a),
            "n_b": len(b),
        },
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": (
            "dispatch_20260921 批次（2026-09-22 补拉 e14pure_* 后首次同批配对）。"
            "此前 NR-58/59/60 因 e14pure 结果未拉回本地，被迫与 E1（seed1001-1030，n=30）跨批比较。"
            "2026-09-22 起：**同批对照优先**，跨批仅作方向参照。"
        ),
    }


def mappo_vs_qmix():
    """MAPPO vs QMIX（同批 bc_marl，n=10）—— 支撑'MAPPO 四者最差'的统计依据"""
    m, q = vals("e14", "mappo"), vals("e14", "qmix")
    st = ac.two_sample_stats(m, q)
    return {
        "id": "NR-67",
        "claim": "E14 同批：MAPPO 末50 env_reward 显著劣于 QMIX（四算法中最差，须如实报告）",
        "allowed_wording": (
            f"E14（3000 回合、λ=0.1、n=10 同批）MAPPO 末50 环境奖励 {st['mean_a']:.2f}±{st['sd_a']:.2f}，"
            f"QMIX {st['mean_b']:.2f}±{st['sd_b']:.2f}，Δ={st['mean_a'] - st['mean_b']:+.2f}；"
            f"Welch p={st['welch_p']:.5f}、d={st['cohens_d']:+.2f}。"
            f"四算法排序 iql ≫ qmix > vdn > mappo（env_reward 与合作率同序）。"
            f"**限定语（不可省略）**：MAPPO 使用与其余算法相同的接口与默认超参、仅 3000 回合；"
            f"MAPPO 为 on-policy，通常需更多样本与独立调参。"
            f"故只能表述为『在当前未调参的 3000 回合设定下最差』，**不得**表述为『MAPPO 不适合本任务』。"
        ),
        "analysis": "two_sample",
        "sources": [
            {"glob": "dispatch_20260921/e14_mappo_seed*.json", "field": FIELD, "role": "a"},
            {"glob": "dispatch_20260921/e14_qmix_seed*.json", "field": FIELD, "role": "b"},
        ],
        "filter": {"config.n_episodes": 3000, "config.lambda_weight": 0.1},
        "n_expected": 10,
        "statistic": ["mean_a", "sd_a", "mean_b", "sd_b", "welch_p", "cohens_d", "ci95_diff"],
        "declared": {
            "mean_a": round(st["mean_a"], 4),
            "sd_a": round(st["sd_a"], 4),
            "mean_b": round(st["mean_b"], 4),
            "sd_b": round(st["sd_b"], 4),
            "welch_p": round(st["welch_p"], 5),
            "cohens_d": round(st["cohens_d"], 4),
            "ci95_diff": [round(st["ci95_diff"][0], 4), round(st["ci95_diff"][1], 4)],
            "n_a": len(m),
            "n_b": len(q),
        },
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": (
            "加 MAPPO 的初衷是回应『算法老旧』批评，结果给出的是**不利证据**。"
            "诚实处置：如实写入 limitation；对『算法老旧』的正确回应是 **claim 重瞄**"
            "（从『我们用 QMIX+区块链』改为『激励机制在自私攻击下的稳健性、且跨算法成立』），"
            "而不是换一个更强的算法。E14 的跨算法负向事实对重瞄是有用材料。"
        ),
    }


def main():
    doc = json.load(open(REG, encoding="utf-8"))
    entries = doc["entries"]
    have = {e["id"] for e in entries}

    new = [entry_for("NR-63", "qmix"), entry_for("NR-64", "iql"),
           entry_for("NR-65", "vdn"), entry_for("NR-66", "mappo"), mappo_vs_qmix()]
    added = []
    for e in new:
        if e["id"] in have:
            print(f"[skip] {e['id']} 已存在")
            continue
        entries.append(e)
        added.append(e["id"])

    # 降级 NR-58/59/60（跨批）：显著性不得作为结论依据
    demote = {
        "NR-58": "同批权威结果见 NR-63（Δ=+6.14，p=0.0919，不显著）",
        "NR-59": "同批权威结果见 NR-64（Δ=-0.56，p=0.8233，不显著）",
        "NR-60": "同批权威结果见 NR-65（Δ=-1.77，p=0.3105，不显著）",
    }
    for e in entries:
        if e["id"] in demote:
            old = e.get("allowed_wording", "")
            e["allowed_wording"] = (
                old.replace("增益显著", "方向为正但系跨批比较，不得作为显著性依据")
                   .replace("无显著增益", "无显著增益；且系跨批比较，仅供方向参照")
                + f" 【2026-09-22 降级】本条为**跨批**比较（bc seed100-109 vs E1 pure seed1001-1030），"
                  f"同批对照已于 2026-09-22 补齐：{demote[e['id']]}。"
                  f"**论文中引用显著性时一律用同批条目，跨批只可作方向参照。**"
            )
            e["notes"] = (e.get("notes", "") +
                          " 2026-09-22 降级：跨批对照不作显著性依据（e14pure 已拉回，同批见 NR-63~66）。")
            print(f"[demote] {e['id']} 已标注降级")

    doc["entries"] = entries
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"\n已新增: {added}")
    for e in new:
        if e["id"] in added:
            d = e["declared"]
            print(f"  {e['id']}: Δ={d['mean_a'] - d['mean_b']:+.4f}  Welch p={d['welch_p']}  d={d['cohens_d']}")


if __name__ == "__main__":
    main()
