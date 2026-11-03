#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ML 定向自适应攻击探针 v2（判据预注册见 deliverables/ML定向自适应攻击实验_20261016.md）

问题：ML 盲区实验（_probe_ml_blindspot.py）证明 v3 局部搜索对 ML 判定器
成功率 0.4870（规则基 0.6730）。但 0.4870 是 **ML 防御的稳健性，还是 v3
这个搜索类的上限**？本探针用两类标准更强黑盒攻击者回答：

  S1 算力扩展：best-of-4 重启（4 条独立 200 步轨迹取最优，同种子族）
     ——攻击者跨回合记忆「什么奏效」，模型「自适应」的字面含义
  S2 模型窃取：8000 次随机位置查询拟合代理分类器（Kerckhoffs：算法类
     公开 ⇒ 用同族 ExtraTrees；攻击者算力扩展：深度 5→8，超出防御方
     部署超参 = 本攻击类的算力上界），网格扫描代理可信域后导航占领
     ——标准模型提取+反演攻击；导航复用盲区实验白盒 L1 同函数

首版设计缺陷留痕（v1 已跑并作废，证据存于结果 JSON 的 design_flaw 段）：
v1 试图区分「迁移（rule 反馈）vs 定向（ml 反馈）」，但 v3 搜索是**判定
无关**的——run_adaptive(seed, judge_ml) 的反馈源本就是 ML。实测 mm≡rm、
mr≡rr 逐位相等（recovery 恒 0.0000，20/20 种子），由 C2 闸门捕获。
⇒ 修正认知：盲区实验的 ml_L2_adaptive 臂**已经是在线适应 ML 判定**的，
「迁移」的真实含义是「搜索类在规则基上调参、未针对 ML 换更强搜索类」。
v2 因此直接测更强搜索类，并把 mm/mr 双臂留作**判定不变量**守护
（mm≡rm 且 mr≡rr 必须逐位成立，否则 run_adaptive 被植入规则知识）。

臂（5 种子，同运动学，仪表全部复用盲区探针）：
  rr   rule 反馈→rule 评测（诊断；≡ mr 预期）
  rm   rule 反馈→ml 评测 = S0 基线（复读 0.4870）
  mm   ml 反馈→ml 评测（≡ rm 预期——判定不变量）
  mr   ml 反馈→rule 评测（≡ rr 预期——判定不变量）
  S1   best-of-4 重启 vs ml
  S2   代理窃取 vs ml
  S3   白盒 L1 vs ml（复读 0.9950，上界）
  random_rule / random_ml 随机基线（复读 0.1840 / 0.1320）

判据（预注册决策表，见 decide()）：
  D0 仪表：|rm−0.4870|<0.01；|S3−0.9950|<0.01；mm≡rm 且 mr≡rr 逐位；
     ML 模型指纹一致（分类器+留出<0.001+可信域格点相等）
  D1 非退化：rnd_ml<0.95 且 rnd_rule<0.95
  D2 攻击能力闸门（防假阴性）：adv(S1)=S1−rnd_ml>0.10 且 wins≥3/5；
     adv(S2)=S2−rnd_ml>0.10 且 wins≥3/5；代理仪表：surrogate 与 ML 判定
     一致率≥0.95 且 S2 导航目标被真实 ML 判信——不满足 ⇒ 低成功率不可
     解释为 ML 稳健（死攻击者/坏仪表证明不了防御）
     （wins 阈值取 3 而非 4：ML 臂基线胜率本就是 3/5，见盲区实验）
  D3 主判据：best_strong = max(S1, S2) 对 S0：
     best_strong > S0+0.10 ⇒ 🔴 更强攻击类恢复利用 ⇒ 0.487 是 v3 搜索类
                               上限而非 ML 稳健性
     best_strong ≤ S0+0.10 ⇒ ✅ ML 对两类更强攻击者稳健（限定见下）
     best_strong < S0−0.10 ⇒ 🟡 异常分支，需人工核查
  D4 反迁移警告（不阻塞）：mr > rr+0.05 ⇒ ⚠️ 前缀

口径纪律：全部参数/观测切片/运动学逐位复用盲区探针（BS.*），防漂移；
S1 重启种子族 seed*1000+k*97+13（与 S0 的 seed*7+1 独立，披露）；
S2 代理查询 seed=707、2000 训练 + 2000 校验、网格步长 0.05。

诚实边界（结论引用时必须携带）：
  1. ML 路径全仓零调用方（未接线）⇒ 反事实度量，不是已交付能力
  2. S2 代理用**同族同超参**分类器（Kerckhoffs 上界）；异族代理
     （kNN/浅树/MLP）是更弱攻击者，未测——S2 是本类的强上界
  3. S1 重启模型「跨回合记忆」；若威胁模型限定单回合且无记忆，S1 不适用
  4. 仍是固定防御单轮适应；防御方随攻击重训的共演化环未测（后续工作）
  5. 合成良性数据；sklearn 版本决定树结构 ⇒ 数字不跨版本比对
     （本结果由 marl-ml venv：py3.13.14/sklearn1.9.1 产出）
"""
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.resolve().parents[1]))


def _load_blindspot():
    """复用盲区探针仪表（单一真源）。"""
    spec = importlib.util.spec_from_file_location(
        "probe_ml_blindspot_shared", HERE / "_probe_ml_blindspot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BS = _load_blindspot()

# 盲区实验已提交读数（复读基准；优先取 JSON，缺失时用已发布常量）
_PRIOR_FALLBACK = {"adaptive_rule": 0.6730, "adaptive_ml": 0.4870,
                   "random_rule": 0.1840, "random_ml": 0.1320, "l1_ml": 0.9950,
                   "heldout": 0.9879, "trusted_cells": 560,
                   "classifier": "ExtraTreesClassifier"}


def load_prior() -> dict:
    f = HERE / "ml_blindspot_result.json"
    if not f.exists():
        return dict(_PRIOR_FALLBACK)
    d = json.loads(f.read_text(encoding="utf-8"))
    agg, ml, tr = d["aggregate"], d["ml_defender"], d["trusted_region"]
    return {
        "adaptive_rule": agg["ada_rule"], "adaptive_ml": agg["ada_ml"],
        "random_rule": agg["rnd_rule"], "random_ml": agg["rnd_ml"],
        "l1_ml": agg["l1_ml"],
        "heldout": ml["heldout_accuracy"], "trusted_cells": tr["trusted_cells"],
        "classifier": ml["classifier"],
    }


PRIOR = load_prior()

# S1 / S2 参数（预注册）
S1_RESTARTS = 4
SURROGATE_SEED = 707
SURROGATE_QUERIES = 8000        # 首版 2000 被 D2 闸门拦（一致率 0.9230<0.95），
SURROGATE_VAL_QUERIES = 2000    # 按先例修仪表（查询量×4）而非放松判据
SURROGATE_MAX_DEPTH = 8         # 攻击者算力扩展（防御方部署为 depth=5）

# v1 设计缺陷作废证据（mm≡rm、mr≡rr 逐位相等；recovery 恒 0）
DESIGN_FLAW_V1 = {
    "claim": "v1 试图区分迁移(rule 反馈) vs 定向(ml 反馈)——空区分",
    "reason": "run_adaptive 判定无关：反馈源即 judge_fn，mm 与 rm 同函数同参数",
    "evidence": "mm≡rm、mr≡rr 逐位相等（5 种子 + 20 扩种，recovery 恒 0.0000）",
    "caught_by": "预注册 C2 能力闸门（死攻击者证明不了防御）",
    "correction": "盲区实验 ml_L2_adaptive 臂已是在线适应 ML；真实问题是搜索类上限",
}


# ---------------------------------------------------------------------------
# 诊断臂（判定不变量守护）
# ---------------------------------------------------------------------------
def arm_rr(seed: int) -> dict:
    return BS.run_adaptive(seed, BS.judge_rule, track_best=True)


def arm_rm(seed: int, judge_ml) -> dict:      # = S0 基线
    return BS.run_adaptive(seed, judge_ml, track_best=True)


def arm_mm(seed: int, judge_ml) -> dict:
    return BS.run_adaptive(seed, judge_ml, track_best=True)


def arm_mr(seed: int) -> dict:
    return BS.run_adaptive(seed, BS.judge_rule, track_best=True)


# ---------------------------------------------------------------------------
# S1：算力扩展（best-of-4 重启）
# ---------------------------------------------------------------------------
def arm_s1(seed: int, judge_ml, restarts: int = S1_RESTARTS) -> dict:
    rseeds = [seed * 1000 + k * 97 + 13 for k in range(restarts)]
    runs = [BS.run_adaptive(rs, judge_ml, track_best=True) for rs in rseeds]
    best = max(runs, key=lambda r: r["coop_rate"])
    hits = [r["first_hit_step"] for r in runs if r["first_hit_step"] is not None]
    return {"seed": seed, "coop_rate": best["coop_rate"],
            "first_hit_step": min(hits) if hits else None,
            "restart_seeds": rseeds,
            "restart_coop_rates": [r["coop_rate"] for r in runs]}


# ---------------------------------------------------------------------------
# S2：模型窃取（代理提取 + 反演）
# ---------------------------------------------------------------------------
def train_surrogate(judge_ml) -> dict:
    """随机查询 → 同族 ExtraTrees 代理 → 网格可信域 + 校验一致率。"""
    import numpy as np
    from sklearn.ensemble import ExtraTreesClassifier

    rng = random.Random(SURROGATE_SEED)

    def sample(n):
        obs = []
        for _ in range(n):
            x = rng.uniform(BS.GRID_LO, BS.GRID_HI)
            y = rng.uniform(BS.GRID_LO, BS.GRID_HI)
            obs.append(BS.build_obs(0.0, 0.0, x, y))
        return obs

    tr_obs = sample(SURROGATE_QUERIES)
    tr_lab = [1 if judge_ml(o) is True else 0 for o in tr_obs]
    clf = ExtraTreesClassifier(n_estimators=50, max_depth=SURROGATE_MAX_DEPTH,
                               max_features="sqrt", random_state=42)
    clf.fit(tr_obs, tr_lab)

    val_obs = sample(SURROGATE_VAL_QUERIES)
    val_lab = [1 if judge_ml(o) is True else 0 for o in val_obs]
    agreement = float((clf.predict(val_obs) == np.array(val_lab)).mean())

    # 网格扫描代理可信域（与白盒 L1 同网格口径）
    trusted = []
    n = int(round((BS.GRID_HI - BS.GRID_LO) / BS.GRID_STEP)) + 1
    for ix in range(n):
        for iy in range(n):
            x, y = BS.GRID_LO + ix * BS.GRID_STEP, BS.GRID_LO + iy * BS.GRID_STEP
            if clf.predict([BS.build_obs(0.0, 0.0, x, y)])[0] == 1:
                trusted.append((x, y))
    # 目标保真：代理可信格中被真实 ML 判信的占比
    fidelity = (sum(1 for c in trusted if judge_ml(BS.build_obs(0, 0, c[0], c[1])) is True)
                / max(1, len(trusted)))
    target = (min(trusted, key=lambda c: (c[0] - BS.START[0]) ** 2
                  + (c[1] - BS.START[1]) ** 2) if trusted else None)
    return {"classifier": "ExtraTreesClassifier(surrogate)",
            "max_depth": SURROGATE_MAX_DEPTH,
            "train_queries": SURROGATE_QUERIES,
            "train_positive_frac": round(sum(tr_lab) / len(tr_lab), 6),
            "val_queries": SURROGATE_VAL_QUERIES,
            "agreement": round(agreement, 6),
            "trusted_cells": len(trusted),
            "target_fidelity": round(fidelity, 6),
            "target": list(target) if target else None,
            "target_real_trusted": (bool(judge_ml(BS.build_obs(0, 0, target[0], target[1])))
                                    if target else None),
            "trusted": trusted}


def arm_s2(seed: int, judge_ml, surrogate: dict) -> dict:
    """导航占领代理可信域（复用白盒 L1 同函数；评测用真实 ML）。"""
    return BS.run_omniscient_ml(seed, judge_ml, surrogate["trusted"])


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs):
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


# ---------------------------------------------------------------------------
# 预注册决策表（纯函数，可单测；改边界=改判据，必须显式）
# ---------------------------------------------------------------------------
def decide(m: dict) -> dict:
    """:param m: 聚合指标 dict（键见 main）"""
    adv_s1 = m["s1"] - m["rnd_ml"]
    adv_s2 = m["s2"] - m["rnd_ml"]
    best_strong = max(m["s1"], m["s2"])
    checks = {
        "D0_instrument": (
            abs(m["ada_rm"] - m["prior_adaptive_ml"]) < 0.01
            and abs(m["s3"] - m["prior_l1_ml"]) < 0.01
            and bool(m["model_fp_ok"])),
        "D1_random_not_full": m["rnd_rule"] < 0.95 and m["rnd_ml"] < 0.95,
        "D2_capability": (adv_s1 > 0.10 and m["wins_s1"] >= 3
                          and adv_s2 > 0.10 and m["wins_s2"] >= 3
                          and m["surrogate_agreement"] >= 0.95
                          and m["surrogate_target_real_trusted"] is True),
    }
    if not checks["D0_instrument"]:
        verdict = "❌ 仪表故障：基线/白盒未复读盲区读数或模型指纹不符（harness/版本漂移）"
    elif not checks["D1_random_not_full"]:
        verdict = "⚠️ 随机臂近全域可信 ⇒ 判定器无区分力（比自适应无效更严重）"
    elif not checks["D2_capability"]:
        verdict = (f"❌ 更强攻击类未建立优势或代理仪表不良（adv_S1={adv_s1:+.4f} "
                   f"wins={m['wins_s1']}/5；adv_S2={adv_s2:+.4f} wins={m['wins_s2']}/5；"
                   f"代理一致率={m['surrogate_agreement']:.4f}）"
                   "⇒ 低成功率不可解释为 ML 稳健（死攻击者/坏仪表证明不了防御）")
    elif best_strong > m["ada_rm"] + 0.10:
        verdict = (f"🔴 更强攻击类恢复利用（S1={m['s1']:.4f} / S2={m['s2']:.4f} "
                   f"vs S0={m['ada_rm']:.4f}）⇒ 0.4870 是 v3 搜索类上限而非 ML 稳健性")
    elif best_strong < m["ada_rm"] - 0.10:
        verdict = (f"🟡 更强攻击类反而更差（S1={m['s1']:.4f} / S2={m['s2']:.4f} "
                   f"vs S0={m['ada_rm']:.4f}）——异常分支，需人工核查")
    else:
        verdict = (f"✅ ML 对两类更强攻击者稳健（S1={m['s1']:.4f} / S2={m['s2']:.4f} "
                   f"vs S0={m['ada_rm']:.4f}）——限定：未见攻击者类、固定防御单轮适应、"
                   "反事实未接线")
    if m["ada_mr"] > m["ada_rr"] + 0.05:
        verdict = (f"⚠️ 反迁移策略在规则基更强（{m['ada_mr']:.4f} > "
                   f"{m['ada_rr']:.4f}+0.05），解释需谨慎；") + verdict
    return {"checks": checks, "advantage_s1": adv_s1, "advantage_s2": adv_s2,
            "best_strong": best_strong, "verdict": verdict}


def sweep(judge_ml, surrogate: dict) -> dict:
    """补充扩种（预注册后追加，样本阶梯纪律 5→20；主判据仍以 5 种子为准）。"""
    arms = {
        "rm_adaptive": lambda s: arm_rm(s, judge_ml),
        "s1_restarts": lambda s: arm_s1(s, judge_ml),
        "s2_surrogate": lambda s: arm_s2(s, judge_ml, surrogate),
        "random_ml": lambda s: BS.run_random(s, judge_ml),
    }
    seeds = BS.SEEDS_SWEEP
    rates = {name: [fn(s)["coop_rate"] for s in seeds] for name, fn in arms.items()}
    out = {"n_seeds": len(seeds), "post_registration": True, "seeds": seeds,
           "rates": rates}
    for name, xs in rates.items():
        out[f"{name}_mean"] = round(_mean(xs), 4)
        out[f"{name}_se"] = round(_sd(xs) / max(1, len(xs)) ** 0.5, 4)
    for tag, arm in (("s1", "s1_restarts"), ("s2", "s2_surrogate")):
        paired = [a - b for a, b in zip(rates[arm], rates["rm_adaptive"])]
        out[f"paired_{tag}_gain"] = [round(x, 4) for x in paired]
        out[f"paired_{tag}_gain_mean"] = round(_mean(paired), 4)
        out[f"paired_{tag}_gain_se"] = round(_sd(paired) / max(1, len(paired)) ** 0.5, 4)
        out[f"{tag}_gain_wins"] = sum(1 for x in paired if x > 0)
    return out


def main() -> int:
    print("=" * 70)
    print("ML 定向自适应攻击实验 v2（更强黑盒攻击类 vs ML 防御）")
    print("=" * 70)
    print(f"场景: {BS.N_AGENTS} agents / {BS.N_LM} landmarks / "
          f"threshold={BS.THRESHOLD} / v_max={BS.V_MAX} / steps={BS.N_STEPS} / "
          f"seeds={BS.SEEDS}")
    print(f"复读基准（盲区实验已提交）: {PRIOR}")

    ml_det, ml_info = BS.train_ml_defender()
    print(f"\nML 防御者: trained={ml_info['trained']} "
          f"classifier={ml_info['classifier']} heldout={ml_info['heldout_accuracy']}")
    print(f"  版本: {ml_info['versions']}")
    if not ml_info["trained"]:
        print("❌ ML 训练失败（sklearn 缺失或样本不足）——ml 臂全部无效")
        return 1

    judge_ml = BS.make_judge_ml(ml_det)
    trusted = BS.map_trusted_region(judge_ml)
    model_fp_ok = (
        ml_info["classifier"] == PRIOR["classifier"]
        and abs((ml_info["heldout_accuracy"] or 0.0) - (PRIOR["heldout"] or 0.0)) < 0.001
        and len(trusted) == PRIOR["trusted_cells"])
    print(f"  可信域: {len(trusted)} 格（复读基准 {PRIOR['trusted_cells']}）"
          f" 模型指纹一致={model_fp_ok}")
    if not model_fp_ok:
        print("⚠️ 模型指纹与盲区实验不符——若为 sklearn 版本差异属预期"
              "（数字不跨版本比对），D0 将判仪表故障")

    print("\n[S2] 训练代理模型（模型窃取）...")
    surrogate = train_surrogate(judge_ml)
    print(f"  代理: agreement={surrogate['agreement']:.4f} "
          f"trusted_cells={surrogate['trusted_cells']} "
          f"target_fidelity={surrogate['target_fidelity']:.4f} "
          f"target={surrogate['target']} "
          f"target_real_trusted={surrogate['target_real_trusted']}")

    arms = {
        "rr_adaptive": lambda s: arm_rr(s),
        "rm_adaptive": lambda s: arm_rm(s, judge_ml),
        "mm_adaptive": lambda s: arm_mm(s, judge_ml),
        "mr_adaptive": lambda s: arm_mr(s),
        "s1_restarts": lambda s: arm_s1(s, judge_ml),
        "s2_surrogate": lambda s: arm_s2(s, judge_ml, surrogate),
        "s3_whitebox": lambda s: BS.run_omniscient_ml(s, judge_ml, trusted),
        "random_rule": lambda s: BS.run_random(s, BS.judge_rule),
        "random_ml": lambda s: BS.run_random(s, judge_ml),
    }
    results = {}
    for name, fn in arms.items():
        runs = [fn(s) for s in BS.SEEDS]
        results[name] = runs
        rates = [r["coop_rate"] for r in runs]
        hits = [r["first_hit_step"] for r in runs if r["first_hit_step"] is not None]
        print(f"{name:14s} coop_rate mean={_mean(rates):.4f}  "
              f"per-seed={[round(x, 3) for x in rates]}  "
              f"first_hit(mean)={_mean(hits) if hits else 'N/A'}")

    # 判定不变量：mm≡rm 且 mr≡rr 必须逐位成立
    inv_mm = all(a["coop_rate"] == b["coop_rate"] and a["first_hit_step"] == b["first_hit_step"]
                 for a, b in zip(results["mm_adaptive"], results["rm_adaptive"]))
    inv_mr = all(a["coop_rate"] == b["coop_rate"] and a["first_hit_step"] == b["first_hit_step"]
                 for a, b in zip(results["mr_adaptive"], results["rr_adaptive"]))
    print(f"\n判定不变量: mm≡rm {inv_mm}  mr≡rr {inv_mr}"
          f"（v3 搜索判定无关；不成立 ⇒ run_adaptive 被植入规则知识）")

    m = {
        "ada_rr": _mean([r["coop_rate"] for r in results["rr_adaptive"]]),
        "ada_rm": _mean([r["coop_rate"] for r in results["rm_adaptive"]]),
        "ada_mm": _mean([r["coop_rate"] for r in results["mm_adaptive"]]),
        "ada_mr": _mean([r["coop_rate"] for r in results["mr_adaptive"]]),
        "s1": _mean([r["coop_rate"] for r in results["s1_restarts"]]),
        "s2": _mean([r["coop_rate"] for r in results["s2_surrogate"]]),
        "s3": _mean([r["coop_rate"] for r in results["s3_whitebox"]]),
        "rnd_rule": _mean([r["coop_rate"] for r in results["random_rule"]]),
        "rnd_ml": _mean([r["coop_rate"] for r in results["random_ml"]]),
        "wins_s1": sum(1 for a, r in zip(results["s1_restarts"],
                                         results["random_ml"])
                       if a["coop_rate"] - r["coop_rate"] > 0),
        "wins_s2": sum(1 for a, r in zip(results["s2_surrogate"],
                                         results["random_ml"])
                       if a["coop_rate"] - r["coop_rate"] > 0),
        "prior_adaptive_ml": PRIOR["adaptive_ml"],
        "prior_l1_ml": PRIOR["l1_ml"],
        "model_fp_ok": model_fp_ok,
        "surrogate_agreement": surrogate["agreement"],
        "surrogate_target_real_trusted": surrogate["target_real_trusted"],
    }
    d = decide(m)

    print("\n" + "-" * 70)
    print("判据（预注册决策表）：")
    for k, v in d["checks"].items():
        print(f"  {k:24s} {'✅' if v else '❌'}")
    print(f"S0={m['ada_rm']:.4f}  S1={m['s1']:.4f}  S2={m['s2']:.4f}  "
          f"S3={m['s3']:.4f}  best_strong={d['best_strong']:.4f}")
    print(f"判定：{d['verdict']}")

    out = HERE / "ml_targeted_attack_result.json"
    out.write_text(json.dumps({
        "params": {
            "n_agents": BS.N_AGENTS, "n_landmarks": BS.N_LM,
            "threshold": BS.THRESHOLD, "dt": BS.DT, "v_max": BS.V_MAX,
            "n_steps": BS.N_STEPS, "seeds": BS.SEEDS,
            "landmarks": BS.LANDMARKS, "start": BS.START,
            "s1_restarts": S1_RESTARTS,
            "surrogate_seed": SURROGATE_SEED,
            "surrogate_queries": SURROGATE_QUERIES,
            "surrogate_val_queries": SURROGATE_VAL_QUERIES,
            "surrogate_max_depth": SURROGATE_MAX_DEPTH,
            "grid": [BS.GRID_LO, BS.GRID_HI, BS.GRID_STEP],
        },
        "design_flaw_v1": DESIGN_FLAW_V1,
        "prior_readings": PRIOR,
        "model_fingerprint_ok": model_fp_ok,
        "ml_defender": ml_info,
        "trusted_cells": len(trusted),
        "surrogate": {k: v for k, v in surrogate.items() if k != "trusted"},
        "runs": results,
        "invariants": {"mm_equiv_rm": inv_mm, "mr_equiv_rr": inv_mr},
        "aggregate": m,
        "checks": d["checks"],
        "advantage_s1": d["advantage_s1"],
        "advantage_s2": d["advantage_s2"],
        "best_strong": d["best_strong"],
        "verdict": d["verdict"],
        "supplementary_sweep": sweep(judge_ml, surrogate),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    sw = json.loads(out.read_text(encoding="utf-8"))["supplementary_sweep"]
    print(f"\n补充扩种（n={sw['n_seeds']}，预注册后，主判据不变）：")
    print(f"  S0(rm)={sw['rm_adaptive_mean']:.4f}±{sw['rm_adaptive_se']:.4f}  "
          f"S1={sw['s1_restarts_mean']:.4f}±{sw['s1_restarts_se']:.4f}  "
          f"S2={sw['s2_surrogate_mean']:.4f}±{sw['s2_surrogate_se']:.4f}")
    print(f"  逐种子增益 S1−S0: {sw['paired_s1_gain_mean']:+.4f}"
          f"±{sw['paired_s1_gain_se']:.4f}（S1 更高 {sw['s1_gain_wins']}/{sw['n_seeds']}）")
    print(f"  逐种子增益 S2−S0: {sw['paired_s2_gain_mean']:+.4f}"
          f"±{sw['paired_s2_gain_se']:.4f}（S2 更高 {sw['s2_gain_wins']}/{sw['n_seeds']}）")
    print(f"\n结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
