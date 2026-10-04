# -*- coding: utf-8 -*-
"""NR-64/65/66 扩种升级：n=10 → n=20 合并口径（seed100-119），双登记簿同步。"""
import json

STATS = json.load(open(
    r"E:/Program/MARL/【CCF】区块链AI协同：面向MARL的共识机制/"
    r"marl-ecdsa-consensus-chain/results/e14_expand_n20_20260930/summary_stats.json",
    encoding="utf-8"))

REG_PATHS = [
    r"E:/Program/MARL/【CCF】区块链AI协同：面向MARL的共识机制/deliverables/number_registry.json",
    r"E:/Program/MARL/【CCF】区块链AI协同：面向MARL的共识机制/marl-ecdsa-consensus-chain/number_registry.json",
]

R4 = lambda x: round(x, 4)
ALGOS = {
    "NR-64": ("iql", "IQL"),
    "NR-65": ("vdn", "VDN"),
    "NR-66": ("mappo", "MAPPO"),
}
OLD = {  # 旧批（seed100-109）数字，来自升级前 declared
    "NR-64": ("Δ=-0.56（p=0.8233）", "（如『IQL 方向为负』『BC 对 IQL 无益/有害』）"),
    "NR-65": ("Δ=-1.77（p=0.3105）", "（如『VDN 方向为负』『BC 对 VDN 无益/有害』）"),
    "NR-66": ("Δ=-0.91（p=0.6254）", "（如『MAPPO 方向为负』『BC 对 MAPPO 无益/有害』）"),
}

for path in REG_PATHS:
    d = json.load(open(path, encoding="utf-8"))
    for e in d["entries"]:
        if e["id"] not in ALGOS:
            continue
        key, disp = ALGOS[e["id"]]
        c = STATS[key]["comb"]; nw = STATS[key]["new"]
        delta = c["mean_a"] - c["mean_b"]
        pct = delta / abs(c["mean_b"]) * 100
        e["claim"] = (f"E14 同批对照（n=20/组，seed100-119 同种子）{disp}："
                      f"bc_marl 与 pure_marl 末50 env_reward 对比")
        e["n_expected"] = 20
        e["declared"] = {
            "mean_a": R4(c["mean_a"]), "sd_a": R4(c["sd_a"]),
            "mean_b": R4(c["mean_b"]), "sd_b": R4(c["sd_b"]),
            "welch_p": R4(c["welch_p"]), "cohens_d": R4(c["cohens_d"]),
            "ci95_diff": [R4(c["ci95_diff"][0]), R4(c["ci95_diff"][1])],
            "n_a": c["n_a"], "n_b": c["n_b"],
        }
        old_d, old_forbid = OLD[e["id"]]
        common = (
            f"E14 同批同种子对照（3000 回合、λ=0.1、{disp}、合并 n=20/组 seed100-119）："
            f"bc_marl 末50 环境奖励 {R4(c['mean_a'])}±{R4(c['sd_a'])}，"
            f"pure_marl {R4(c['mean_b'])}±{R4(c['sd_b'])}，Δ={delta:+.2f}（{pct:+.1f}%），"
            f"Welch p={c['welch_p']:.4f}、Cohen d={c['cohens_d']:+.2f}、"
            f"95%CI [{c['ci95_diff'][0]:.2f},{c['ci95_diff'][1]:.2f}]，**不显著**。"
            f"分批披露：旧批 seed100-109（n=10）{old_d}、"
            f"新批 seed110-119（n=10）Δ={nw['mean_a']-nw['mean_b']:+.2f}（p={nw['welch_p']:.4f}）"
            f"——**批间符号翻转**，n=10 批次方向不可判，合并后仍不显著。"
            f"结论限定：『未观察到显著增益』，**不得将其作为方向性结论**{old_forbid}。"
        )
        if e["id"] == "NR-64":
            common += (
                "⚠️ 一致性披露：主口径 NR-1 同为 IQL（n=71/组，Δ=+2.61，p=0.0095 显著为正），"
                "引用本条时必须同时提及 NR-1 的相反结果。"
            )
        e["allowed_wording"] = common
        e["notes"] = (
            "2026-09-30 扩种升级：seed110-119 补跑完成（scripts/run_e14_expand_n20.sh，"
            "ALL_DONE 11:52），条目由 n=10 升为 n=20 合并口径，旧批数字保留于分批披露。"
            "合并后 IQL/VDN/MAPPO 均不显著 → 『仅 QMIX 显著』（NR-63）为跨算法唯一稳定结论。"
        )
        print(f"[{path.split('/')[-2]}] {e['id']} upgraded -> n=20, p={e['declared']['welch_p']}")
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("BOTH REGISTRIES UPDATED")
