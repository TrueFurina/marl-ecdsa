#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E13/E14 数据登记：派生 E13 摊平文件 + 追加 NR 条目 + 更新 NR-19。

背景：verify_numbers.py 的 navigate() 只支持点路径（不支持数组索引），
E13 源文件是 `experiments[0].results.<cfg>.<field>` 嵌套结构，故需派生
"每配置每 seed 一个摊平文件"，供 registry 用简单 glob+field 复算。

用法: python register_e13_e14_entries.py [--dry-run]
"""
import json
import glob
import os
import re
import sys
import argparse

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(BASE, "..", ".."))
ROOT = os.path.abspath(os.path.join(REPO, ".."))          # 项目根
DISPATCH = os.path.join(REPO, "results", "dispatch_20260921")
DERIVED = os.path.join(DISPATCH, "derived")
REGISTRY = os.path.join(ROOT, "deliverables", "number_registry.json")

E13_CONFIGS = [
    "selfish_0pct_random", "selfish_0pct_greedy",
    "selfish_20pct_random", "selfish_20pct_greedy",
    "selfish_50pct_random", "selfish_50pct_greedy",
]
E13_FIELDS = ["avg_env_reward", "avg_env_reward_last_50", "avg_cooperation_rate", "avg_betrayal_rate"]


def flatten_e13():
    """派生 results/dispatch_20260921/derived/e13_<cfg>_seed<NNN>.json（每文件一个 seed 的标量）。"""
    os.makedirs(DERIVED, exist_ok=True)
    n = 0
    for fp in sorted(glob.glob(os.path.join(DISPATCH, "e13_expb_seed*.json"))):
        seed = int(re.search(r"seed(\d+)", os.path.basename(fp)).group(1))
        d = json.load(open(fp, encoding="utf-8"))
        for exp in d.get("experiments", []):
            for cfg, r in exp.get("results", {}).items():
                if cfg not in E13_CONFIGS:
                    continue
                rec = {"seed": seed, "config": cfg}
                for fld in E13_FIELDS:
                    if fld in r:
                        rec[fld] = r[fld]
                outp = os.path.join(DERIVED, f"e13_{cfg}_seed{seed}.json")
                json.dump(rec, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                n += 1
    return n


def _src(glob_pat, field, role, label=None):
    s = {"glob": glob_pat, "field": field, "role": role}
    if label:
        s["label"] = label
    return s


def _entry(nid, claim, wording, analysis, sources, n_expected, declared, notes, status="PASS"):
    return {
        "id": nid, "claim": claim, "allowed_wording": wording, "analysis": analysis,
        "sources": sources, "n_expected": n_expected,
        "statistic": ["mean_a", "sd_a", "n_a", "mean_b", "sd_b", "n_b", "welch_p", "cohen_d"],
        "declared": declared, "tolerance": {"abs": 0.05, "p_abs": 0.02},
        "status": status, "pre_registered": False, "requires": [], "notes": notes,
    }


def build_entries():
    E = []
    # ---- E13：greedy vs random（env_reward 与合作率两指标同登记，避免单指标误读）----
    E.append(_entry(
        "NR-55",
        "E13 自私攻击强度（500ep/10seed）：50% 理性自私(greedy) env_reward −36.75±1.33 显著高于随机(random) −57.38±1.07",
        "E13（500 回合、10 种子）：50% 自私者中，理性自私(greedy) env_reward −36.75±1.33，随机噪声(random) −57.38±1.07，"
        "Welch p<0.001。**须与 NR-56 同报**——reward 与合作率指向相反方向，不得单独引用其一。",
        "two_sample",
        [_src("dispatch_20260921/derived/e13_selfish_50pct_greedy_seed*.json", "avg_env_reward", "a", "greedy"),
         _src("dispatch_20260921/derived/e13_selfish_50pct_random_seed*.json", "avg_env_reward", "b", "random")],
        10, {"mean_a": -36.75, "mean_b": -57.38}, "E13 服务器实跑（dispatch_20260921），派生自 e13_expb_seed100-109.json"))

    E.append(_entry(
        "NR-56",
        "E13：50% greedy 合作率 0.1606 显著低于 random 0.3838（Δ−0.2232）",
        "E13（500 回合、10 种子）：50% 自私者中，greedy 合作率 0.1606 vs random 0.3838（Δ−0.2232，Welch p<0.001），"
        "背叛率 0.667 vs 0.200。**与 NR-55 方向相反**：'理性自私伤害更大'只在合作率口径成立，reward 口径下不成立。",
        "two_sample",
        [_src("dispatch_20260921/derived/e13_selfish_50pct_greedy_seed*.json", "avg_cooperation_rate", "a", "greedy"),
         _src("dispatch_20260921/derived/e13_selfish_50pct_random_seed*.json", "avg_cooperation_rate", "b", "random")],
        10, {"mean_a": 0.1606, "mean_b": 0.3838}, "E13；本条目用于**修正 NR-23（旧 n=3 单指标结论）**"))

    E.append(_entry(
        "NR-57",
        "E13：20% greedy env_reward −46.80 高于 random −57.52（Δ+10.73）；合作率 0.317 低于 0.427",
        "E13（500 回合、10 种子）：20% 自私者中 greedy env_reward −46.80 vs random −57.52（Δ+10.73，p<0.001），"
        "合作率 0.317 vs 0.427（Δ−0.110，p<0.001）。剂量-效应：自私比例越高，greedy 的 reward 优势越大（20%→50%：+10.7→+20.6）。",
        "two_sample",
        [_src("dispatch_20260921/derived/e13_selfish_20pct_greedy_seed*.json", "avg_env_reward", "a", "greedy"),
         _src("dispatch_20260921/derived/e13_selfish_20pct_random_seed*.json", "avg_env_reward", "b", "random")],
        10, {"mean_a": -46.80, "mean_b": -57.52}, "E13；与 NR-55 同族（不同自私比例）"))

    # ---- E14：四算法 vs E1 pure（跨批，须标注）----
    for nid, algo, bc_last, pure_last, pval in [
        ("NR-58", "qmix", -48.94, -57.12, 0.0256),
        ("NR-59", "iql", -9.41, -8.43, 0.636),
        ("NR-60", "vdn", -68.77, -67.56, 0.375),
    ]:
        E.append(_entry(
            nid,
            f"E14 四算法（3000ep/10seed）：{algo.upper()} 下 bc_marl last50 {bc_last} vs pure(E1) {pure_last}",
            f"E14（3000 回合、10 种子）{algo.upper()}：bc_marl env_reward last50 {bc_last}，E1 pure {pure_last}，"
            f"Δ={round(bc_last-pure_last,2):+}，Welch p={pval}。**跨批比较**（bc seed100-109 vs pure seed1001-1030），"
            f"须标注非同批；{'增益显著' if pval<0.05 else '无显著增益'}。QMIX 为主线，MAPPO 仅作稳健性检验。",
            "two_sample",
            [_src(f"dispatch_20260921/e14_{algo}_seed*.json", "summary.avg_env_reward_last_50", "a", f"bc_{algo}"),
             _src(f"champion_20260919/e1_{algo}_pure_marl_seed*.json", "summary.avg_env_reward_last_50", "b", f"pure_{algo}")],
            None, {"mean_a": bc_last, "mean_b": pure_last},
            f"E14 服务器实跑；对照为 E1 批次（跨批）。建议后续同批重跑以消歧。"))

    # NR-61（MAPPO 单臂）不登记：无 pure 对照的孤值不构成可复算结论，
    # registry 原则是"每条可被脚本复算"，故 MAPPO 仅在报告内作定性描述（"四算法最差"）。
    return E


def update_nr19(reg):
    """NR-19 测试数 —— **下限式口径**（2026-09-23 改造）。

    对外材料一律写「1600+ 项自动化测试全部通过（0 失败）」；declared 保留精确值供复算。
    设计意图：测试数是构建产物，只要 passed ≥ 1600，其变化**不需要更新任何材料**
    （此前精确数硬编码进 ~43 处材料，每加一批测试就要全链更新一次）。

    ⚠️ 本函数是 registry 的**覆盖源**：任何人重跑本脚本都会把 NR-19 覆写为此处常量。
    改动口径必须同时改这里，只改 registry 会被下次执行冲掉。
    """
    for e in reg["entries"]:
        if e["id"] == "NR-19":
            e["claim"] = ("1600+ 项自动化测试全部通过（0 失败）—— 下限式表述，精确值见 declared")
            e["allowed_wording"] = (
                "工程可信度证据：**对外材料统一写「1600+ 项自动化测试全部通过（0 失败）」**。"
                "采用下限式表述的目的：**只要实测 passed ≥ 1600，测试数变化就不需要更新任何材料**。"
                "精确值见本条目 declared，仅供内部核对与门禁复算；须注明为测试数量而非正确性证明。")
            e["declared"] = {"passed": 1665, "skipped": 2, "failed": 0, "collected": 1667}
            e["notes"] = (
                e.get("notes", "") + " | 2026-09-23 口径改造：改为**下限式表述**（对外「1600+ 项」；"
                "declared 保留精确值）。下限阈值 1600，精确基线本机复跑 1665 passed / 2 skipped / "
                "0 failed（1667 collected）。历史精确值 1603/1624/1626/1632/1634 一律作废。")
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    n = flatten_e13()
    print(f"[派生] E13 摊平文件: {n} 个 → {os.path.relpath(DERIVED, REPO)}")

    reg = json.load(open(REGISTRY, encoding="utf-8"))
    existing = {e["id"] for e in reg["entries"]}
    new = [e for e in build_entries() if e["id"] not in existing]
    print(f"[登记] 新增 NR: {[e['id'] for e in new]}")

    if args.dry_run:
        print("[dry-run] 未写入")
        return 0

    reg["entries"].extend(new)
    updated = update_nr19(reg)
    print(f"[更新] NR-19: {'已更新' if updated else '未找到'}")
    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    print(f"[写入] {os.path.relpath(REGISTRY, ROOT)} 共 {len(reg['entries'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
