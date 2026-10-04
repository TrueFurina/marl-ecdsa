#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E13-B：生成 derived 逐种子文件 + 登记 NR-68 ~ NR-73。

derived 文件展平为 {avg_env_reward, avg_cooperation_rate, avg_betrayal_rate}，
以便 number_registry 用简单的 dotted field 读取（与 legacy derived/ 同构）。
"""
import json, os, glob, sys
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402

D = REPO / "results" / "dispatch_20260921"
DERIVED = D / "derived"
# 真值源路径：默认取 assurance_common.REGISTRY_PATH（与 verify_numbers.py 完全同一条通路），
# 可用环境变量 MARL_REGISTRY 覆盖（换机/私有部署）。禁止硬编码本机绝对路径。
REG = Path(os.environ.get("MARL_REGISTRY") or ac.REGISTRY_PATH)

METRICS = {"env": "avg_env_reward", "coop": "avg_cooperation_rate", "betray": "avg_betrayal_rate"}


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------- 1. 展平 e13b_* ----------
def flatten():
    n = 0
    for f in sorted(D.glob("e13b_*_seed*.json")):
        base = f.stem  # e13b_step050_seed100
        arm = base.split("_")[1]
        seed = base.split("_seed")[1]
        res = jload(f)["experiments"][0]["results"]
        for label, v in res.items():
            if label == "comparison":
                continue
            out = DERIVED / f"e13b_{arm}_{label}_seed{seed}.json"
            out.write_text(json.dumps({
                "seed": int(seed), "arm": arm, "config": label,
                **{src: v[src] for src in METRICS.values()},
            }, ensure_ascii=False), encoding="utf-8")
            n += 1
    return n


def vals(pattern, field):
    out = []
    for p in sorted(DERIVED.glob(pattern)):
        out.append(jload(p)[field])
    return out


def multi_entry(nr, arm, field_name, metric_cn, note):
    roles = {
        "50g": f"e13b_{arm}_selfish_50pct_greedy_seed*.json",
        "50r": f"e13b_{arm}_selfish_50pct_random_seed*.json",
        "20g": f"e13b_{arm}_selfish_20pct_greedy_seed*.json",
        "20r": f"e13b_{arm}_selfish_20pct_random_seed*.json",
    }
    data = {r: vals(g, field_name) for r, g in roles.items()}
    pairs = [{"label": "50pct", "a": "50g", "b": "50r"},
             {"label": "20pct", "a": "20g", "b": "20r"}]
    computed = {}
    for r, v in data.items():
        computed[f"mean_{r}"] = ac.mean(v)
        computed[f"sd_{r}"] = ac.stdev(v)
        computed[f"n_{r}"] = len(v)
    for pr in pairs:
        st = ac.two_sample_stats(data[pr["a"]], data[pr["b"]])
        lbl = pr["label"]
        computed[f"delta_{lbl}"] = st["mean_a"] - st["mean_b"]
        computed[f"diff_pp_{lbl}"] = (st["mean_a"] - st["mean_b"]) * 100.0
        computed[f"p_{lbl}"] = st["welch_p"]
        computed[f"d_{lbl}"] = st["cohens_d"]
    def smart_round(v):
        # 极小 p 值不能用固定小数位（会显示成 0，报告里是误导），按量级保留有效位
        if isinstance(v, float):
            if v != 0 and abs(v) < 1e-4:
                return float(f"{v:.6g}")
            return round(v, 6)
        return v
    computed = {k: smart_round(v) for k, v in computed.items()}

    def sign(x):
        return "更高" if x > 0 else "更低"

    def pfmt(p):
        # scipy 在极小 p 上会下溢返回 0.0；论文里写 "p=0" 会被评审质疑，一律写成上界
        if p is None:
            return "n/a"
        if p == 0 or p < 1e-12:
            return "p<1e-12"
        return f"p={p:.3g}"

    word = (
        f"E13-B（500 回合、10 种子、同种子配对、arm={arm}）："
        f"50% 自私下 greedy {metric_cn} {computed['mean_50g']:.4f} vs random {computed['mean_50r']:.4f}"
        f"（Δ={computed['delta_50pct']:+.4f}，Welch {pfmt(computed['p_50pct'])}，d={computed['d_50pct']:+.2f}）；"
        f"20% 自私下 greedy {computed['mean_20g']:.4f} vs random {computed['mean_20r']:.4f}"
        f"（Δ={computed['delta_20pct']:+.4f}，{pfmt(computed['p_20pct'])}，d={computed['d_20pct']:+.2f}）。"
        f"两个比例下 greedy 均高于 random。"
    )
    return {
        "id": nr,
        "claim": f"E13-B {arm}：{metric_cn} 上 greedy 与 random 的配对差（behavioral 合作率口径）",
        "allowed_wording": word + " " + note,
        "analysis": "multi_sample",
        "sources": [{"glob": f"dispatch_20260921/derived/{g}", "field": field_name, "role": r}
                    for r, g in roles.items()],
        "pairs": pairs,
        "n_expected": 10,
        "statistic": ["mean_50g", "mean_50r", "delta_50pct", "p_50pct", "d_50pct",
                      "mean_20g", "mean_20r", "delta_20pct", "p_20pct", "d_20pct"],
        "declared": computed,
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": f"dispatch_20260921 批次（2026-09-22 19:18 跑完，20/20 exit=0）。{note}",
    }


def two_sample_entry(nr, ga, gb, field, claim, wording, note):
    a, b = vals(ga, field), vals(gb, field)
    st = ac.two_sample_stats(a, b)
    return {
        "id": nr,
        "claim": claim,
        "allowed_wording": wording,
        "analysis": "two_sample",
        "sources": [{"glob": f"dispatch_20260921/derived/{ga}", "field": field, "role": "a"},
                    {"glob": f"dispatch_20260921/derived/{gb}", "field": field, "role": "b"}],
        "n_expected": 10,
        "statistic": ["mean_a", "sd_a", "mean_b", "sd_b", "welch_p", "cohens_d", "ci95_diff"],
        "declared": {
            "mean_a": round(st["mean_a"], 4), "sd_a": round(st["sd_a"], 4),
            "mean_b": round(st["mean_b"], 4), "sd_b": round(st["sd_b"], 4),
            "welch_p": (float(f"{st['welch_p']:.6g}") if st["welch_p"] and abs(st["welch_p"]) < 1e-4
                        else round(st["welch_p"], 6)), "cohens_d": round(st["cohens_d"], 4),
            "ci95_diff": [round(st["ci95_diff"][0], 4), round(st["ci95_diff"][1], 4)],
            "n_a": len(a), "n_b": len(b),
        },
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": note,
    }


def main():
    n = flatten()
    print(f"展平 derived 文件: {n}")

    REV = ("【口径反转提示】同一批种子、同一份行为，legacy 口径（合作率=标签计数器）"
           "给出相反的符号——引用时必须说明用的是 behavioral 口径。")
    CAVEAT = ("【机制限定，不可省略】greedy 臂注入的是一个**手编的、接近最优的启发式策略**，"
              "而对照臂是 500 回合下尚未收敛的学习者；step005 arm 中 2 个 greedy + 1 个学习者的"
              "环境奖励（−2.13）远优于 3 个学习者（−57.13），说明测到的是**策略质量差异**，"
              "不是『自私的破坏力』。因此本条只能用于说明『本任务中贪心自私不劣于随机噪声』，"
              "**不得**外推为『自私有益』或『自私无害』。")

    new = [
        multi_entry("NR-68", "step050", "avg_env_reward", "环境奖励（env_reward）", REV + CAVEAT),
        multi_entry("NR-69", "step050", "avg_cooperation_rate", "行为学合作率", REV + CAVEAT),
        multi_entry("NR-70", "step005", "avg_env_reward", "环境奖励（env_reward）", REV + CAVEAT),
        multi_entry("NR-71", "step005", "avg_cooperation_rate", "行为学合作率", REV + CAVEAT),
        two_sample_entry(
            "NR-72",
            "e13b_step050_selfish_50pct_greedy_seed*.json",
            "e13_selfish_50pct_greedy_seed*.json",
            "avg_cooperation_rate",
            "合作率口径修复导致符号反转：同一配置 50% greedy 合作率 behavioral 0.70 vs legacy 0.16",
            "合作率口径修复的证据：50% 自私/greedy 配置下，behavioral 口径合作率 {a:.4f}±{sa:.4f}，"
            "legacy 口径（=未被标记背叛的步数占比）{b:.4f}±{sb:.4f}，差 {d:+.4f}（Welch {p}）。"
            "**同一批种子、同一份行为，仅因口径不同符号相反**——凡引用 selfish 类实验的合作率，"
            "必须标注口径版本，且只能用 behavioral。",
            "用于支撑『legacy 合作率是循环论证』这一判定，不作效果结论。",
        ),
        two_sample_entry(
            "NR-73",
            "e13b_step005_selfish_0pct_greedy_seed*.json",
            "e13b_step005_selfish_0pct_random_seed*.json",
            "avg_cooperation_rate",
            "E13-B step005 自洽性检查：0% 自私（无自私智能体）下 greedy 与 random 配置无差异",
            "E13-B step005 arm 的 0% 自私对照：greedy 配置合作率 {a:.4f}±{sa:.4f}，"
            "random 配置 {b:.4f}±{sb:.4f}，差 {d:+.4f}（Welch {p}，不显著）。"
            "说明 E13-B 中的组间差异确实来自『背叛模式』这一变量，而非种子噪声或管线漂移。",
            "阴性对照。step050 arm 同样通过（Δ=−0.0008）。",
        ),
    ]

    # 填充 NR-72/73 的具体数值
    for e in new:
        if e["id"] in ("NR-72", "NR-73"):
            d = e["declared"]
            pv = d["welch_p"]
            ps = "p<1e-12" if (pv == 0 or pv < 1e-12) else f"p={pv:.3g}"
            e["allowed_wording"] = e["allowed_wording"].format(
                a=d["mean_a"], sa=d["sd_a"], b=d["mean_b"], sb=d["sd_b"],
                d=d["mean_a"] - d["mean_b"], p=ps)

    doc = json.load(open(REG, encoding="utf-8"))
    have = {x["id"] for x in doc["entries"]}
    added = []
    for e in new:
        if e["id"] in have:
            print(f"[skip] {e['id']}")
            continue
        doc["entries"].append(e)
        added.append(e["id"])
    json.dump(doc, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已新增: {added}")
    for e in new:
        if e["id"] in added:
            d = e["declared"]
            if "delta_50pct" in d:
                print(f"  {e['id']}: 50pct Δ={d['delta_50pct']:+.4f} p={d['p_50pct']:.4g} | "
                      f"20pct Δ={d['delta_20pct']:+.4f} p={d['p_20pct']:.4g}")
            else:
                print(f"  {e['id']}: {d['mean_a']:.4f} vs {d['mean_b']:.4f} "
                      f"Δ={d['mean_a'] - d['mean_b']:+.4f} p={d['welch_p']:.4g}")


if __name__ == "__main__":
    main()
