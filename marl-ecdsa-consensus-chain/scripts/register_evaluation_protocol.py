#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Tian2025 评估协议对齐（任务书①②③④）结果登记进 number_registry.json：
NR-96 Social Welfare｜NR-97 Collusion Rate（诚实 null）｜NR-98 IC 指数｜
NR-99 噪声鲁棒性（冒烟级）｜NR-100 合谋检测双通道 2×2。

口径与全项目铁律一致：
- 声明值**全部由源 JSON 复算**得出，非手抄；verify_numbers 可重验；
- IC 为本项目口径，**不得宣称与 Tian 逐值可比**（写入 allowed_wording）；
- 噪声为冒烟级（3 seeds × 1500ep，非正式 A/B），**不得写进主结论链**；
- Collusion Rate 全 0 为诚实 null（可信底座下未检出统计合谋），非缺数据；
- 双通道 n=3 seeds 冒烟级，499 拒收包数程序化取自 per_seed.rejected 之和。

注：消融对齐（④）数字与既有消融同源（other/测试数据/ablation/），仅映射表新增，
不单独建条目（映射随 NR-96 notes 与数据字典走）。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import assurance_common as ac  # noqa: E402

REG = Path(os.environ.get("MARL_REGISTRY") or ac.REGISTRY_PATH)
D = ac.RESULTS_DIR / "evaluation_protocol"


def _write_flat(ev: dict, dc: dict) -> Path:
    """生成顶层扁平化 JSON（先例：NR-95 的 deployment_distributed_flat.json）——
    verify_numbers 的 benchmark 分支只按顶层键名取数，不支持点路径。"""
    sw = ev["social_welfare"]
    n71_bc = sw["convergence_3000_n71"]["iql_bc_marl"]
    n71_pure = sw["convergence_3000_n71"]["iql_pure_marl"]
    flat: dict = {
        "n71_iql_bc_mean": n71_bc["mean"], "n71_iql_bc_std": n71_bc["std"],
        "n71_iql_pure_mean": n71_pure["mean"], "n71_iql_pure_std": n71_pure["std"],
    }
    for k, v in sw["algorithm_comparison_3seeds"].items():
        flat[f"ac3_{k}"] = round(v["mean"], 3)
    n_pairs = 0
    for k in ("iql_bc_marl", "qmix_bc_marl", "vdn_bc_marl"):
        flat[f"collusion_{k}"] = ev["collusion_rate"][k]["rate_mean"]
        flat[f"ic_{k}"] = ev["ic_index"][k]["ic_mean"]
        n_pairs += sum(s.get("n_pairs", 0) for s in ev["collusion_rate"][k]["per_seed"])
    flat["collusion_n_pairs_total"] = n_pairs
    nz = ev["noise_robustness"]
    flat["noise_keep_rate"] = nz["keep_rate"]
    flat["noise_n_clean"] = nz["n_clean"]
    flat["noise_n_noisy"] = nz["n_noisy"]
    cells = dc["cells"]
    for k in ("normal_single", "normal_dual", "forged_single", "forged_dual"):
        flat[f"dual_{k}"] = cells[k]["rate_mean"]
    flat["dual_forged_rejected_total"] = sum(
        s["verify"]["rejected"] for s in cells["forged_dual"]["per_seed"])
    out = D / "evaluation_protocol_flat.json"
    out.write_text(json.dumps(flat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def _src(fields: list) -> list:
    return [{"file": "evaluation_protocol/evaluation_protocol_flat.json",
             "field": ",".join(fields)}]


def entry_nr96(ev: dict) -> dict:
    sw = ev["social_welfare"]
    n71_bc = sw["convergence_3000_n71"]["iql_bc_marl"]
    n71_pure = sw["convergence_3000_n71"]["iql_pure_marl"]
    ac3 = sw["algorithm_comparison_3seeds"]
    six = {k: round(v["mean"], 3) for k, v in ac3.items()}
    return {
        "id": "NR-96",
        "claim": ("Tian2025 评估协议对齐 · Social Welfare（团队 env_reward）：IQL 主口径 n=71 收敛数据 + "
                  "六臂 500ep 批次（3 seeds）"),
        "allowed_wording": (
            f"按 Tian et al. (2025) 评估协议以团队 env_reward 计算 Social Welfare。**主口径（3000 回合收敛，"
            f"n=71/组）**：iql_bc_marl {n71_bc['mean']:.3f}±{n71_bc['std']:.3f}，iql_pure_marl "
            f"{n71_pure['mean']:.3f}±{n71_pure['std']:.3f}。**500ep 批次（3 seeds）六臂**：" +
            "、".join(f"{k} {v}" for k, v in six.items()) +
            "。口径说明：Tian 的 Social Welfare 定义为全部 agent 累计回报均值；本项目为团队级 env_reward，"
            "单智能体分解在 IQL 设定下不可得（数据字典声明）。**仅声明同一评估协议下口径可比，"
            "不得宣称与 Tian 逐值可比**。"),
        "analysis": "benchmark",
        "sources": _src(["n71_iql_bc_mean", "n71_iql_bc_std",
                          "n71_iql_pure_mean", "n71_iql_pure_std"] + 
                         [f"ac3_{k}" for k in ("iql_bc_marl","iql_pure_marl","qmix_bc_marl",
                                                "qmix_pure_marl","vdn_bc_marl","vdn_pure_marl")]),
        "n_expected": 71,
        "statistic": ["mean", "std"],
        "declared": {
            "n71_iql_bc_mean": n71_bc["mean"], "n71_iql_bc_std": n71_bc["std"],
            "n71_iql_pure_mean": n71_pure["mean"], "n71_iql_pure_std": n71_pure["std"],
            **{f"ac3_{k}": v for k, v in six.items()},
        },
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "benchmark",
        "notes": ("2026-10-04 任务书①（evaluate_protocol.py 程序化计算）。500ep 批次 3 seeds 为评估协议"
                  "对齐专用（algorithm_comparison 数据），与 n=71 收敛主口径并存、两口径均已声明。"),
    }


def entry_nr97(ev: dict) -> dict:
    cr = ev["collusion_rate"]
    zeros = {k: cr[k]["rate_mean"] for k in ("iql_bc_marl", "qmix_bc_marl", "vdn_bc_marl")}
    assert all(v == 0.0 for v in zeros.values()), f"Collusion Rate 预期全 0，实得 {zeros}"
    n_pairs = sum(s.get("n_pairs", 0) for k in zeros for s in cr[k]["per_seed"])
    return {
        "id": "NR-97",
        "claim": ("Tian2025 评估协议对齐 · Collusion Rate（|Pearson|>0.90 的 agent 对占比）："
                  "bc 三算法臂 3 seeds 均为 0.0（诚实 null）"),
        "allowed_wording": (
            "行为向量取逐回合链上积分增量（签名验证后的链上数据），|Pearson r|>0.90 计为高关联对。"
            "iql/qmix/vdn 三算法 bc 臂各 3 seeds × 3 对，共 27 对，检出高关联对 **0 对**（率 0.0）——"
            "**诚实 null：可信底座下未检出统计合谋**，是检测器在真实数据上的阴性结论，非缺数据。"
            "pure 臂无链上账本 → N/A 如实标注。threshold=0.90 与 Tian 一致。"),
        "analysis": "benchmark",
        "sources": _src(["collusion_iql_bc_marl", "collusion_qmix_bc_marl", "collusion_vdn_bc_marl",
                          "collusion_n_pairs_total"]),
        "n_expected": 3,
        "statistic": [],
        "declared": {"collusion_iql_bc_marl": 0.0, "collusion_qmix_bc_marl": 0.0,
                     "collusion_vdn_bc_marl": 0.0, "collusion_n_pairs_total": n_pairs},
        "tolerance": {"abs": 0.001, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "benchmark",
        "notes": ("2026-10-04 任务书①。null 结果按预注册惯例如实登记（防选择性报告）；"
                  "检测输入为链上账本数据（签名层产出），双通道增强见 NR-100。"),
    }


def entry_nr98(ev: dict) -> dict:
    ic = ev["ic_index"]
    vals = {k: ic[k]["ic_mean"] for k in ("iql_bc_marl", "qmix_bc_marl", "vdn_bc_marl")}
    return {
        "id": "NR-98",
        "claim": ("Tian2025 评估协议对齐 · Incentive Compatibility Index（横截面 corr(贡献权重_i, "
                  "链上积分_i)，3 seeds 均值）"),
        "allowed_wording": (
            f"IC 指数：iql {vals['iql_bc_marl']:.4f}、qmix {vals['qmix_bc_marl']:.4f}、"
            f"vdn {vals['vdn_bc_marl']:.2f}（各 3 seeds，n_agents=3）。**本项目口径**：与 Tian 的 IC 定义"
            "仅协议同构（其含诚实策略收益优势辅助口径，本项目未实现），**不得宣称与 Tian 逐值可比**。"
            "三算法方向不一致（iql 近零 / qmix 弱正 / vdn 正），如实报告，不做解释性拔高；"
            "n=3 小样本不构成统计结论，仅作口径演示与方向性参考。"),
        "analysis": "benchmark",
        "sources": _src(["ic_iql_bc_marl", "ic_qmix_bc_marl", "ic_vdn_bc_marl"]),
        "n_expected": 3,
        "statistic": [],
        "declared": {"ic_iql_bc_marl": vals["iql_bc_marl"], "ic_qmix_bc_marl": vals["qmix_bc_marl"],
                     "ic_vdn_bc_marl": vals["vdn_bc_marl"]},
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "benchmark",
        "notes": "2026-10-04 任务书①。方向不一致为诚实披露项，设计报告引用时必须带小样本+口径声明。",
    }


def entry_nr99(ev: dict) -> dict:
    nz = ev["noise_robustness"]
    return {
        "id": "NR-99",
        "claim": ("Tian2025 评估协议对齐 · 奖励噪声鲁棒性（σ=0.3 高斯注入）回报保持率 "
                  "keep_rate=0.9753（冒烟级）"),
        "allowed_wording": (
            f"奖励注入 σ=0.3 高斯噪声后回报保持率 {nz['keep_rate']:.4f}"
            f"（无噪 {nz['n_clean']} seeds × 有噪 {nz['n_noisy']} seeds，1500ep，seeds 2000-2002，"
            "train.py --reward-noise-sigma）。**冒烟级，非正式 A/B**——仅作噪声鲁棒性方向性证据，"
            "不得写进主结论链、不得与主口径实验混比。"),
        "analysis": "benchmark",
        "sources": _src(["noise_keep_rate", "noise_n_clean", "noise_n_noisy"]),
        "n_expected": 3,
        "statistic": [],
        "declared": {"noise_keep_rate": nz["keep_rate"], "noise_n_clean": nz["n_clean"],
                     "noise_n_noisy": nz["n_noisy"]},
        "tolerance": {"abs": 0.01, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "benchmark",
        "notes": ("2026-10-05 冒烟补跑（任务书①收尾）；--reward-noise-sigma 默认 0=零行为影响（f1a0ca0）。"
                  "原始 6 JSON 随包 other/测试数据/evaluation_protocol/noise/。"),
    }


def entry_nr100(dc: dict) -> dict:
    cells = dc["cells"]
    rates = {k: cells[k]["rate_mean"] for k in ("normal_single", "normal_dual",
                                                "forged_single", "forged_dual")}
    rej = sum(s["verify"]["rejected"] for s in cells["forged_dual"]["per_seed"])
    return {
        "id": "NR-100",
        "claim": ("合谋检测双通道 2×2 实验（任务书②）：{正常,伪造注入}×{单通道,双通道(ECDSA 验签门)}，"
                  "3 seeds"),
        "allowed_wording": (
            f"底料为真实链上积分增量；伪造=攻击者私钥签名的顶名 agent_0 包（流=agent_1×0.9+噪声）。"
            f"Collusion Rate：正常×单通道 {rates['normal_single']}｜正常×双通道 {rates['normal_dual']}"
            f"｜伪造×单通道 **{rates['forged_single']:.4f}（统计被投毒）**｜伪造×双通道 "
            f"**{rates['forged_dual']}（验签门拒收 {rej} 个伪造包后回到基线）**。结论：统计检测的"
            "**输入**经 ECDSA 验签后获得密码学不可抵赖性——检测输入可信性实证。n=3 seeds 冒烟级，"
            "如实呈现；与 NR-30（6 类攻击拦截）互补：NR-30 验证签名层拦截，本条验证检测层受益。"),
        "analysis": "benchmark",
        "sources": _src(["dual_normal_single", "dual_normal_dual",
                          "dual_forged_single", "dual_forged_dual",
                          "dual_forged_rejected_total"]),
        "n_expected": 3,
        "statistic": [],
        "declared": {f"dual_{k}": v for k, v in rates.items()} | {"dual_forged_rejected_total": rej},
        "tolerance": {"abs": 0.001, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "experiment",
        "notes": ("2026-10-05 任务书②（collusion_dual_channel_experiment.py，81aedee）。"
                  "阈值 0.90 与 Tian/NR-97 一致；底料为真实训练数据非合成。"),
    }


def main() -> int:
    ev = json.load(open(D / "evaluation_protocol.json", encoding="utf-8"))
    dc = json.load(open(D / "dual_channel" / "dual_channel.json", encoding="utf-8"))
    flat_path = _write_flat(ev, dc)
    print(f"[flat] {flat_path}")
    entries = [entry_nr96(ev), entry_nr97(ev), entry_nr98(ev), entry_nr99(ev), entry_nr100(dc)]

    reg = json.loads(REG.read_text(encoding="utf-8"))
    ents = reg["entries"]
    have = {e["id"] for e in ents}
    added = updated = 0
    for e in entries:
        if e["id"] in have:
            ents[:] = [x for x in ents if x["id"] != e["id"]]
            ents.append(e)
            updated += 1
            print(f"[update] {e['id']}")
            continue
        ents.append(e)
        added += 1
        print(f"[add] {e['id']}: {e['claim'][:50]}…")
    if added == 0 and updated == 0:
        print("无新增无更新，登记簿未改动")
        return 0
    reg["generated_at"] = ac.now_iso()
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n已写入 {REG}（新增 {added}，总条目 {len(ents)}）")
    print("⚠️ 记得同步仓库镜像：cp 权威 → marl-ecdsa-consensus-chain/number_registry.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
