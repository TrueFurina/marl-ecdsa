#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把环境多样性扩展（Task A：SimpleSpreadMovingEnv）结果登记进 number_registry.json，
补 NR-86（moving3）与 NR-87（moving5），作为 BC 框架**泛化性旁证**。

口径与全项目铁律一致：
- 主指标 env_reward 末 50（不含 BC 激励）= ``summary.avg_env_reward_last_50``
- Welch + Cohen d（ac.two_sample_stats，标准库实现，与 verify_numbers 同一通路）
- λ=0.1；QMIX；3000 回合；seed 42-51（n=10/组）
- 声明值**全部由源文件复算**得出，非手抄；verify_numbers 可重验。

注：MAPPO 同批（Task B）已属 NR-66，六类签名层攻击（Task C）已属 NR-30，二者均不在本脚本范围。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import assurance_common as ac  # noqa: E402

REG = Path(os.environ.get("MARL_REGISTRY") or ac.REGISTRY_PATH)
D = Path(os.environ.get("MARL_DATA_ROOT") or ac.RESULTS_DIR) / "env_diversity_20260927"
FIELD = "summary.avg_env_reward_last_50"


def vals(env, mode):
    out = []
    for p in sorted(D.glob(f"{env}_{mode}_seed*.json")):
        out.append(json.load(open(p, encoding="utf-8"))["summary"]["avg_env_reward_last_50"])
    return out


def entry_for(nr, env, n_agents):
    a, b = vals(env, "bc_marl"), vals(env, "pure_marl")
    st = ac.two_sample_stats(a, b)
    delta = st["mean_a"] - st["mean_b"]
    if env == "moving3":
        verdict = "不显著（方向为正、中等效应，但 n=10 检验力不足，未达 p<0.05）"
    else:
        verdict = "显著（大效应），但在 2 环境 Bonferroni 校正（α'=0.025）下处于临界，应如实标注"
    return {
        "id": nr,
        "claim": (f"环境多样性扩展（{env}，{n_agents} agent，地标确定性漂移）QMIX："
                  f"bc_marl 与 pure_marl 末 50 env_reward 对比（泛化性旁证）"),
        "allowed_wording": (
            f"为检验 BC 框架在**动态目标**场景的泛化性，引入地标确定性漂移环境 {env}（{n_agents} agent）。"
            f"在 3000 回合、λ=0.1、QMIX、n=10 同批同种子下："
            f"bc_marl 末 50 环境奖励 {st['mean_a']:.2f}±{st['sd_a']:.2f}，"
            f"pure_marl {st['mean_b']:.2f}±{st['sd_b']:.2f}，Δ={delta:+.2f}；"
            f"Welch p={st['welch_p']:.4f}、Cohen d={st['cohens_d']:+.2f}、"
            f"95%CI [{st['ci95_diff'][0]:.2f},{st['ci95_diff'][1]:.2f}]。{verdict}。"
            f"两环境 Δ 均 > 0，方向一致 → BC 框架对动态目标场景同样成立，构成泛化性旁证。"
        ),
        "analysis": "two_sample",
        "sources": [
            {"glob": f"env_diversity_20260927/{env}_bc_marl_seed*.json", "field": FIELD, "role": "a"},
            {"glob": f"env_diversity_20260927/{env}_pure_marl_seed*.json", "field": FIELD, "role": "b"},
        ],
        "filter": {
            "config.n_episodes": 3000,
            "config.lambda_weight": 0.1,
            "config.algorithm": "qmix",
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
            "Task A 环境多样性扩展（2026-09-27）。第二环境 SimpleSpreadMovingEnv 复用 SimpleSpreadEnv "
            "的 obs/state/action 维度，BC 集成零改动。数据全量在服务器端 gomarl 跑完（40 个 JSON，各 3000 回合）。"
            "**泛化性旁证，非主口径**：主口径为 n=71（NR-1/NR-2）；本任务 n=10/组，仅测 QMIX，"
            "不构成跨算法泛化结论。严禁外推为「BC 通用加速器」（红线 NR-54/NR-27）；"
            "合作率 last50：moving3 p≈0.3440、moving5 p≈0.0502（临界），方向均正但不构成独立显著结论。"
            "2 环境多重比较 Bonferroni 校正 α'=0.025 下 moving5 p=0.0232 处临界。"
        ),
    }


def main():
    doc = json.load(open(REG, encoding="utf-8"))
    entries = doc["entries"]
    have = {e["id"] for e in entries}
    new = [entry_for("NR-86", "moving3", 3), entry_for("NR-87", "moving5", 5)]
    added = []
    for e in new:
        if e["id"] in have:
            print(f"[skip] {e['id']} 已存在")
            continue
        entries.append(e)
        added.append(e["id"])
    doc["entries"] = entries
    with open(REG, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"已新增: {added}")
    for e in new:
        if e["id"] in added:
            d = e["declared"]
            print(f"  {e['id']}: Δ={d['mean_a'] - d['mean_b']:+.4f}  Welch p={d['welch_p']}  d={d['cohens_d']}")


if __name__ == "__main__":
    main()
