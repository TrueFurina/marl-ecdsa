#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ML 路径盲区探针（判据预注册见 deliverables/ML路径盲区实验_20261016.md）

问题：自适应攻击者探针（_probe_adaptive_attacker.py）证明规则基
detect_cooperation 的盲区可被黑盒自适应攻击者利用（优势 +0.489）。
CooperationDetector 另有一条已实现但**未接线**的 ML 路径
（train_classifier/predict_ml 全仓零调用方——2026-10-16 全仓核验；
sklearn 可用性因环境而异：权威解释器 Python312 装有 lock 锁定的
1.9.0，10-16 自适应探针所报「两环境无 sklearn」仅覆盖其当时所用
两个 venv，不构成生产事实）。本探针度量：**若把 ML 路径接上，
自适应攻击者的成功率是否下降**——即 ML 路径对 MAGIC 论点的本地版本
「静态善意假设防不住自适应攻击者」是否提供稳健增量。

六臂设计（2 防御 × 3 攻击者层级，同种子同运动学）：
  rule × L1        全知（知道规则 ⇒ 直奔自身 landmark）        复现既有探针
  rule × L2_adaptive 黑盒自适应（v3 局部搜索，判定反馈学习）    复现既有探针
  rule × L2_random   随机游走                                  复现既有探针
  ml   × L1        白盒（Kerckhoffs：分类器参数公开 ⇒ 网格扫描
                   可信域后占领）——ML 臂的全知上界
  ml   × L2_adaptive 同一 v3 策略（不编码规则知识，纯判定反馈）
                   ⇒ 对 ML 臂是「迁移攻击」，未做针对性再演化
  ml   × L2_random  随机游走

良性训练协议（预注册，固定种子 101，与攻击种子独立）：
  - 20 回合 × 200 步 × 3 智能体，全部诚实：每步朝自身 landmark 移动，
    角度抖动 σ=0.35rad、速度因子 U(0.6,1.0)×V_MAX（OU 式徘徊，
    避免直线轨迹把特征共线性推到极限）
  - 标签 = 环境语义「到达自身 landmark」（dist_to_own<0.5），
    **不编码 min_dist_any 旁路**——否则 ML 只是重放规则基，
    实验退化为同义反复
  - 前 16 回合训练 / 后 4 回合留出（按回合划分防时序泄漏），
    报告留出准确率
  - 诊断量：良性数据中「攻击模式」样本（min_dist_any<0.5 且
    dist_to_own≥0.5）占比——记录共线性程度，ML 必须离线外推

判据（预注册决策表，见 decide()）：
  C0 仪表：rule L1 > 0.90（盲区可达且稳定）
  C1 非退化：random_rule < 0.95 且 random_ml < 0.95（盲区非全域）
  C2 复现：rule 臂自适应优势 > 0.05 且 ≥4/5 种子（复现 +0.489 结论；
     同时 |新-旧|<0.01 逐臂核对既有探针读数）
  C3 ML 仪表：ml L1（白盒）> 0.90 且留出准确率 ≥ 0.90
     ——L1 低 ⇒「无可占盲区」，此时低自适应率**不可解释为稳健**
       （可能是「谁都不信」的退化检测器），必须报仪表故障
  C4 主判据：Δ = adv_rule − adv_ml（各臂优势 = 自适应 − 随机）
     Δ > +0.10 且 ada_ml < ada_rule − 0.10 ⇒ ML 显著压低成功率
     Δ < −0.10                            ⇒ ML 反而扩大盲区
     其余                                 ⇒ 无显著稳健增量

口径纪律（与既有探针逐位一致）：
  - 观测切片 [4:4+2n] landmark 相对、[2:4] 自报位置；own_idx = i % n_lm
  - 攻击只谎报「自己在哪」，landmark 固定为真实值（共识层职责）
  - lm_rel 由自报位置推导；V_MAX=0.3/步运动学约束不放松
  - 速度不参与特征（特征 = [dist_to_own, min_dist_any, pos_x, pos_y]）

诚实边界（结论引用时必须携带）：
  1. ML 路径全仓零调用方（未接线）⇒ 本实验是「若接线」的反事实度量，
     **不是已交付能力**；不得据此宣称生产系统具备 ML 检测。
     防住该宣称的边界是「零调用方」这一代码级事实，不是 sklearn
     环境缺失（Python312 权威环境装有 lock 锁定的 1.9.0）
  2. v3 策略对 ML 臂是迁移攻击（未共演化再演化）⇒ 若 ML 显示稳健，
     结论限定为「未针对 ML 演化的攻击者下」；共演化实验是后续工作
  3. 良性数据为合成诚实策略，非真实 MARL rollout
  4. sklearn 版本决定树结构 ⇒ 记录版本，数字不跨版本比对
"""
import json
import math
import platform
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marl.integration.cooperation_detector import CooperationDetector

# ---- 固定参数（与 _probe_adaptive_attacker.py 逐位一致，防漂移）----
N_AGENTS = 3
N_LM = 3
THRESHOLD = 0.5
DT = 1.0
V_MAX = 0.3
N_STEPS = 200
SEEDS = [11, 23, 37, 41, 53]
LANDMARKS = [(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
START = (0.0, 0.0)
ATTACKER_ID = "attacker"

# ---- 良性训练协议参数（预注册）----
BENIGN_SEED = 101
BENIGN_EPISODES = 20
BENIGN_TRAIN_EPISODES = 16      # 前 16 训练 / 后 4 留出
BENIGN_JITTER = 0.35            # 角度抖动 σ（rad）
BENIGN_SPEED_LO = 0.6           # 速度因子下界
GRID_LO, GRID_HI, GRID_STEP = -0.5, 2.0, 0.05   # L1-ML 白盒扫描网格

# 既有探针已发布读数（adaptive_attacker_result.json，2026-10-16）
PRIOR = {"L1_omniscient": 0.9950, "L2_adaptive": 0.6730, "L2_random": 0.1840}

# 补充扩种（预注册后追加，样本阶梯纪律：5 → 20；仅作稳健性检查，
# 主判据仍以预注册 5 种子为准，扩种不得回头改主判据）
SEEDS_SWEEP = SEEDS + [61, 67, 71, 73, 79, 83, 89, 97, 101, 103,
                       107, 109, 113, 127, 131]


def build_obs(vx: float, vy: float, px: float, py: float) -> list:
    """观测向量：[vx, vy, px, py, lm_rel(2*N_LM)]。口径与生产切片一致。"""
    lm = []
    for lx, ly in LANDMARKS:
        lm.extend([lx - px, ly - py])
    return [vx, vy, px, py] + lm


def _dist_to_own(px: float, py: float, i: int) -> float:
    return math.hypot(LANDMARKS[i][0] - px, LANDMARKS[i][1] - py)


def _min_dist_any(px: float, py: float) -> float:
    return min(math.hypot(lx - px, ly - py) for lx, ly in LANDMARKS)


def benign_label(px: float, py: float, i: int) -> int:
    """良性数据标签（预注册协议）：1=到达自身 landmark（环境语义）。

    ⛔ 禁止改用 min_dist_any<THRESHOLD——那等于让 ML 重放规则基的第二判定
    （「靠近任意 landmark 即合作」），实验退化为同义反复。
    注意：良性诚实轨迹中两定义数值上巧合一致（off_manifold=0），
    **数据性质测试守不住这个变异**，只有直接测函数体才能守住
    （见 tests/test_ml_blindspot.py::TestBenignData::test_benign_label_function_semantics）。
    """
    return 1 if _dist_to_own(px, py, i) < THRESHOLD else 0


# ---------------------------------------------------------------------------
# 良性数据生成（合成诚实策略；标签只编码「到达自身 landmark」）
# ---------------------------------------------------------------------------
def gen_benign_episodes():
    """返回 (episodes, diag)：episodes = [(obs, labels, agent_ids), ...]"""
    rng = random.Random(BENIGN_SEED * 31 + 7)
    episodes = []
    off_manifold = 0
    total = 0
    for _ep in range(BENIGN_EPISODES):
        pos = [[0.0, 0.0] for _ in range(N_AGENTS)]
        ep_obs, ep_lab, ep_ids = [], [], []
        for _t in range(N_STEPS):
            new_pos = []
            for i in range(N_AGENTS):
                lx, ly = LANDMARKS[i]
                dx, dy = lx - pos[i][0], ly - pos[i][1]
                d = math.hypot(dx, dy) or 1.0
                ang = math.atan2(dy, dx) + rng.uniform(-BENIGN_JITTER, BENIGN_JITTER)
                speed = V_MAX * rng.uniform(BENIGN_SPEED_LO, 1.0)
                new_pos.append([pos[i][0] + speed * math.cos(ang),
                                pos[i][1] + speed * math.sin(ang)])
            pos = new_pos
            for i in range(N_AGENTS):
                ep_obs.append(build_obs(0.0, 0.0, pos[i][0], pos[i][1]))
                # 标签：环境语义，不含 min_dist_any 旁路（见 benign_label 文档字符串）
                ep_lab.append(benign_label(pos[i][0], pos[i][1], i))
                ep_ids.append(f"a{i}")
                total += 1
                if _min_dist_any(pos[i][0], pos[i][1]) < THRESHOLD and \
                        _dist_to_own(pos[i][0], pos[i][1], i) >= THRESHOLD:
                    off_manifold += 1
        episodes.append((ep_obs, ep_lab, ep_ids))
    diag = {
        "off_manifold_samples": off_manifold,
        "total_samples": total,
        "off_manifold_frac": round(off_manifold / max(1, total), 6),
        "label_positive_frac": round(
            sum(lab for _o, labs, _i in episodes for lab in labs) / max(1, total), 6),
    }
    return episodes, diag


def train_ml_defender():
    """训练 ML 防御者（一次部署一个模型；攻击种子不参与训练）。"""
    episodes, diag = gen_benign_episodes()
    tr_obs = [o for ep in episodes[:BENIGN_TRAIN_EPISODES] for o in ep[0]]
    tr_lab = [l for ep in episodes[:BENIGN_TRAIN_EPISODES] for l in ep[1]]
    tr_ids = [i for ep in episodes[:BENIGN_TRAIN_EPISODES] for i in ep[2]]
    ho_obs = [o for ep in episodes[BENIGN_TRAIN_EPISODES:] for o in ep[0]]
    ho_lab = [l for ep in episodes[BENIGN_TRAIN_EPISODES:] for l in ep[1]]
    ho_ids = [i for ep in episodes[BENIGN_TRAIN_EPISODES:] for i in ep[2]]

    det = CooperationDetector(n_agents=N_AGENTS, n_landmarks=N_LM)
    ok = det.train_classifier(tr_obs, tr_ids, tr_lab)
    heldout = det.get_ml_accuracy(ho_obs, ho_ids, ho_lab) if ok else None
    train_acc = det.get_ml_accuracy(tr_obs, tr_ids, tr_lab) if ok else None
    info = {
        "trained": bool(ok),
        "train_samples": len(tr_obs),
        "heldout_samples": len(ho_obs),
        "train_accuracy": train_acc,
        "heldout_accuracy": heldout,
        "classifier": det.get_stats().get("ml_classifier"),
        "benign_diag": diag,
        "versions": _versions(),
    }
    return det, info


def _versions() -> dict:
    import numpy
    import sklearn
    import scipy
    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "sklearn": sklearn.__version__,
        "scipy": scipy.__version__,
    }


# ---------------------------------------------------------------------------
# 判定入口
# ---------------------------------------------------------------------------
def judge_rule(obs: list):
    """生产 detect_cooperation；不传 selfish_flags ⇒ 纯距离判定。"""
    det = CooperationDetector(n_agents=N_AGENTS, n_landmarks=N_LM)
    st = det.detect_cooperation([obs], [ATTACKER_ID], cooperation_threshold=THRESHOLD)
    return st[ATTACKER_ID]


def make_judge_ml(ml_det: CooperationDetector):
    def _judge(obs: list):
        preds = ml_det.predict_ml([obs], [ATTACKER_ID])
        return preds.get(ATTACKER_ID)
    return _judge


# ---------------------------------------------------------------------------
# L1 全知（规则臂）：知道规则 ⇒ 直奔自身 landmark 阈值邻域（复现既有探针）
# ---------------------------------------------------------------------------
def run_omniscient_rule(seed: int) -> dict:
    p = list(START)
    coop = 0
    first_hit = None
    for t in range(N_STEPS):
        dx = LANDMARKS[0][0] - p[0]
        dy = LANDMARKS[0][1] - p[1]
        d = math.hypot(dx, dy) or 1.0
        vx, vy = V_MAX * dx / d, V_MAX * dy / d
        p[0] += vx * DT
        p[1] += vy * DT
        if judge_rule(build_obs(vx, vy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
    return {"seed": seed, "coop_rate": coop / N_STEPS, "first_hit_step": first_hit}


# ---------------------------------------------------------------------------
# L1 白盒（ML 臂）：Kerckhoffs——分类器参数公开 ⇒ 网格扫描可信域后占领
# ---------------------------------------------------------------------------
def map_trusted_region(judge_ml) -> list:
    n = int(round((GRID_HI - GRID_LO) / GRID_STEP)) + 1
    trusted = []
    for ix in range(n):
        for iy in range(n):
            x, y = GRID_LO + ix * GRID_STEP, GRID_LO + iy * GRID_STEP
            if judge_ml(build_obs(0.0, 0.0, x, y)) is True:
                trusted.append((x, y))
    return trusted


def run_omniscient_ml(seed: int, judge_ml, trusted: list) -> dict:
    if not trusted:
        return {"seed": seed, "coop_rate": 0.0, "first_hit_step": None,
                "note": "no trusted cell"}
    target = min(trusted, key=lambda c: (c[0] - START[0]) ** 2 + (c[1] - START[1]) ** 2)
    p = list(START)
    coop = 0
    first_hit = None
    for t in range(N_STEPS):
        d = math.hypot(target[0] - p[0], target[1] - p[1])
        if d > 0.02:
            step = min(V_MAX, d)          # 必须按剩余距离截断，否则在目标两侧振荡
            dx, dy = (target[0] - p[0]) / d * step, (target[1] - p[1]) / d * step
        else:
            dx = dy = 0.0
        p[0] += dx
        p[1] += dy
        if judge_ml(build_obs(dx, dy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
    return {"seed": seed, "coop_rate": coop / N_STEPS, "first_hit_step": first_hit,
            "target": list(target)}


# ---------------------------------------------------------------------------
# L2 实验组：自适应局部搜索（v3，与既有探针逐位同构；防御无关，纯判定反馈）
# ---------------------------------------------------------------------------
def run_adaptive(seed: int, judge_fn, track_best: bool = False) -> dict:
    """L2 自适应局部搜索（v3）。track_best=True 时附加终点诊断（默认关闭，
    保持 _probe_ml_blindspot 自身输出逐字节不变——供定向攻击探针复用）。"""
    rng = random.Random(seed * 7 + 1)
    p = list(START)
    best = None
    coop = 0
    first_hit = None
    for t in range(N_STEPS):
        if best is not None and rng.random() < 0.7:
            ang = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(0.0, 0.15)
            tx, ty = best[0] + r * math.cos(ang), best[1] + r * math.sin(ang)
        else:
            ang = rng.uniform(0, 2 * math.pi)
            tx, ty = p[0] + V_MAX * math.cos(ang), p[1] + V_MAX * math.sin(ang)
        dx, dy = tx - p[0], ty - p[1]
        d = math.hypot(dx, dy)
        if d > V_MAX:
            dx, dy = dx * V_MAX / d, dy * V_MAX / d
        p[0] += dx
        p[1] += dy
        if judge_fn(build_obs(dx, dy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
            best = [p[0], p[1]]
    out = {"seed": seed, "coop_rate": coop / N_STEPS, "first_hit_step": first_hit}
    if track_best:
        out["best_pos"] = [round(best[0], 4), round(best[1], 4)] if best else None
    return out


# ---------------------------------------------------------------------------
# L2 对照组：随机游走（同等步数、同等扰动幅度量级）
# ---------------------------------------------------------------------------
def run_random(seed: int, judge_fn) -> dict:
    rng = random.Random(seed * 13 + 5)
    p = list(START)
    coop = 0
    first_hit = None
    for t in range(N_STEPS):
        theta = rng.uniform(0, 2 * math.pi)
        rate = rng.uniform(0.1, V_MAX)
        vx, vy = rate * math.cos(theta), rate * math.sin(theta)
        p[0] += vx * DT
        p[1] += vy * DT
        if judge_fn(build_obs(vx, vy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
    return {"seed": seed, "coop_rate": coop / N_STEPS, "first_hit_step": first_hit}


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs):
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def sweep(judge_ml) -> dict:
    """补充扩种（预注册后）：20 种子 L2 四臂，仅作稳健性检查。"""
    arms = {
        "rule_L2_adaptive": lambda s: run_adaptive(s, judge_rule),
        "rule_L2_random": lambda s: run_random(s, judge_rule),
        "ml_L2_adaptive": lambda s: run_adaptive(s, judge_ml),
        "ml_L2_random": lambda s: run_random(s, judge_ml),
    }
    rates = {name: [fn(s)["coop_rate"] for s in SEEDS_SWEEP]
             for name, fn in arms.items()}
    out = {"n_seeds": len(SEEDS_SWEEP), "post_registration": True,
           "seeds": SEEDS_SWEEP, "rates": rates}
    for name, xs in rates.items():
        mu = _mean(xs)
        out[f"{name}_mean"] = round(mu, 4)
        out[f"{name}_se"] = round(_sd(xs) / max(1, len(xs)) ** 0.5, 4)
    ada_rule = [a - r for a, r in zip(rates["rule_L2_adaptive"], rates["rule_L2_random"])]
    ada_ml = [a - r for a, r in zip(rates["ml_L2_adaptive"], rates["ml_L2_random"])]
    paired = [a - b for a, b in zip(rates["rule_L2_adaptive"], rates["ml_L2_adaptive"])]
    out["paired_adaptive_drop"] = [round(x, 4) for x in paired]
    out["paired_adaptive_drop_mean"] = round(_mean(paired), 4)
    out["paired_adaptive_drop_se"] = round(_sd(paired) / max(1, len(paired)) ** 0.5, 4)
    out["adaptive_drop_wins"] = sum(1 for x in paired if x > 0)
    out["advantage_rule"] = round(_mean(ada_rule), 4)
    out["advantage_ml"] = round(_mean(ada_ml), 4)
    out["delta"] = round(_mean(ada_rule) - _mean(ada_ml), 4)
    return out


# ---------------------------------------------------------------------------
# 预注册决策表（纯函数，可单测；改边界=改判据，必须显式）
# ---------------------------------------------------------------------------
def decide(m: dict) -> dict:
    """
    :param m: 聚合指标 dict（键见 main）
    :return: {"checks": {...}, "advantage_rule", "advantage_ml", "delta",
              "verdict", "replication_ok"}
    """
    adv_rule = m["ada_rule"] - m["rnd_rule"]
    adv_ml = m["ada_ml"] - m["rnd_ml"]
    delta = adv_rule - adv_ml
    checks = {
        "C0_rule_l1_high": m["l1_rule"] > 0.90,
        "C1_random_not_full": m["rnd_rule"] < 0.95 and m["rnd_ml"] < 0.95,
        "C2_rule_replicates": adv_rule > 0.05 and m["wins_rule"] >= 4,
        "C3_ml_instrument": m["l1_ml"] > 0.90 and (m["ml_heldout"] or 0.0) >= 0.90,
    }
    replication_ok = (
        abs(m["l1_rule"] - PRIOR["L1_omniscient"]) < 0.01
        and abs(m["ada_rule"] - PRIOR["L2_adaptive"]) < 0.01
        and abs(m["rnd_rule"] - PRIOR["L2_random"]) < 0.01
    )
    if not checks["C0_rule_l1_high"]:
        verdict = "❌ 仪表故障：规则臂 L1 未达高位，判据失效"
    elif not checks["C1_random_not_full"]:
        verdict = "⚠️ 随机臂近全域可信 ⇒ 判定器无区分力（比自适应无效更严重）"
    elif not checks["C3_ml_instrument"]:
        verdict = ("❌ 仪表故障：ML 臂退化（白盒 L1≤0.90 或留出准确率<0.90）"
                   "⇒ 低自适应率不可解释为稳健（可能是「谁都不信」）")
    elif delta > 0.10 and m["ada_ml"] < m["ada_rule"] - 0.10:
        verdict = (f"✅ ML 路径显著压低自适应成功率（Δ={delta:+.4f}，"
                   f"adaptive {m['ada_rule']:.4f}→{m['ada_ml']:.4f}）"
                   "——限定：迁移攻击、未共演化")
    elif delta < -0.10:
        verdict = (f"❌ ML 路径反而扩大盲区（Δ={delta:+.4f}，"
                   f"adaptive {m['ada_rule']:.4f}→{m['ada_ml']:.4f}）")
    else:
        verdict = (f"🟡 ML 路径无显著稳健增量（Δ={delta:+.4f}）"
                   "⇒ MAGIC 论点从规则基扩展到 ML 路径")
    if not checks["C2_rule_replicates"]:
        verdict = "⚠️ 规则臂未复现既有结论（策略/仪表疑似回归）；" + verdict
    if not replication_ok:
        verdict = "⚠️ 与既有探针读数偏差 ≥0.01（环境/版本差异？）；" + verdict
    return {"checks": checks, "advantage_rule": adv_rule, "advantage_ml": adv_ml,
            "delta": delta, "verdict": verdict, "replication_ok": replication_ok}


def main() -> int:
    print("=" * 70)
    print("ML 路径盲区实验（rule vs ml × L1/L2，同种子同运动学）")
    print("=" * 70)
    print(f"场景: {N_AGENTS} agents / {N_LM} landmarks / threshold={THRESHOLD} / "
          f"v_max={V_MAX} / steps={N_STEPS} / seeds={len(SEEDS)}")
    print(f"landmarks={LANDMARKS}  start={START}")
    print(f"良性训练: seed={BENIGN_SEED} episodes={BENIGN_EPISODES} "
          f"(train {BENIGN_TRAIN_EPISODES}/heldout {BENIGN_EPISODES - BENIGN_TRAIN_EPISODES})")

    ml_det, ml_info = train_ml_defender()
    print(f"\nML 防御者: trained={ml_info['trained']} "
          f"classifier={ml_info['classifier']} "
          f"train_acc={ml_info['train_accuracy']} heldout_acc={ml_info['heldout_accuracy']}")
    print(f"  版本: {ml_info['versions']}")
    print(f"  良性诊断: {ml_info['benign_diag']}")
    if not ml_info["trained"]:
        print("❌ ML 训练失败（sklearn 缺失或样本不足）——ML 臂全部无效")
        return 1

    judge_ml = make_judge_ml(ml_det)
    trusted = map_trusted_region(judge_ml)
    near_any = sum(1 for x, y in trusted
                   if _min_dist_any(x, y) < THRESHOLD)
    near_own = sum(1 for x, y in trusted
                   if _dist_to_own(x, y, 0) < THRESHOLD)
    n_cells = (int(round((GRID_HI - GRID_LO) / GRID_STEP)) + 1) ** 2
    trusted_diag = {
        "trusted_cells": len(trusted),
        "total_cells": n_cells,
        "trusted_area_frac": round(len(trusted) / n_cells, 6),
        "trusted_near_any_landmark_frac": round(near_any / max(1, len(trusted)), 6),
        "trusted_near_own_landmark_frac": round(near_own / max(1, len(trusted)), 6),
    }
    print(f"\n可信域扫描: {trusted_diag}")

    arms = {
        "rule_L1": lambda s: run_omniscient_rule(s),
        "rule_L2_adaptive": lambda s: run_adaptive(s, judge_rule),
        "rule_L2_random": lambda s: run_random(s, judge_rule),
        "ml_L1": lambda s: run_omniscient_ml(s, judge_ml, trusted),
        "ml_L2_adaptive": lambda s: run_adaptive(s, judge_ml),
        "ml_L2_random": lambda s: run_random(s, judge_ml),
    }
    results = {}
    for name, fn in arms.items():
        runs = [fn(s) for s in SEEDS]
        results[name] = runs
        rates = [r["coop_rate"] for r in runs]
        hits = [r["first_hit_step"] for r in runs if r["first_hit_step"] is not None]
        print(f"{name:18s} coop_rate mean={_mean(rates):.4f}  "
              f"per-seed={[round(x, 3) for x in rates]}  "
              f"first_hit(mean)={_mean(hits) if hits else 'N/A'}")

    l1_rule = _mean([r["coop_rate"] for r in results["rule_L1"]])
    ada_rule = _mean([r["coop_rate"] for r in results["rule_L2_adaptive"]])
    rnd_rule = _mean([r["coop_rate"] for r in results["rule_L2_random"]])
    l1_ml = _mean([r["coop_rate"] for r in results["ml_L1"]])
    ada_ml = _mean([r["coop_rate"] for r in results["ml_L2_adaptive"]])
    rnd_ml = _mean([r["coop_rate"] for r in results["ml_L2_random"]])
    wins_rule = sum(1 for a, r in zip(results["rule_L2_adaptive"],
                                      results["rule_L2_random"])
                    if a["coop_rate"] - r["coop_rate"] > 0)
    wins_ml = sum(1 for a, r in zip(results["ml_L2_adaptive"],
                                    results["ml_L2_random"])
                  if a["coop_rate"] - r["coop_rate"] > 0)

    m = {
        "l1_rule": l1_rule, "ada_rule": ada_rule, "rnd_rule": rnd_rule,
        "l1_ml": l1_ml, "ada_ml": ada_ml, "rnd_ml": rnd_ml,
        "wins_rule": wins_rule, "wins_ml": wins_ml,
        "ml_heldout": ml_info["heldout_accuracy"] or 0.0,
    }
    d = decide(m)

    print("\n" + "-" * 70)
    print("判据（预注册决策表）：")
    for k, v in d["checks"].items():
        print(f"  {k:24s} {'✅' if v else '❌'}")
    print(f"  规则臂复现核对（ vs 既有探针 {PRIOR}）: "
          f"{'✅' if d['replication_ok'] else '⚠️ 偏差≥0.01'}")
    print(f"优势: rule={d['advantage_rule']:+.4f}  ml={d['advantage_ml']:+.4f}  "
          f"Δ={d['delta']:+.4f}  (wins rule {wins_rule}/5, ml {wins_ml}/5)")
    print(f"判定：{d['verdict']}")

    out = Path(__file__).resolve().parent / "ml_blindspot_result.json"
    out.write_text(json.dumps({
        "params": {
            "n_agents": N_AGENTS, "n_landmarks": N_LM, "threshold": THRESHOLD,
            "dt": DT, "v_max": V_MAX, "n_steps": N_STEPS, "seeds": SEEDS,
            "landmarks": LANDMARKS, "start": START,
            "benign_seed": BENIGN_SEED, "benign_episodes": BENIGN_EPISODES,
            "benign_train_episodes": BENIGN_TRAIN_EPISODES,
            "benign_jitter": BENIGN_JITTER,
            "grid": [GRID_LO, GRID_HI, GRID_STEP],
        },
        "ml_defender": ml_info,
        "trusted_region": trusted_diag,
        "runs": results,
        "aggregate": m,
        "checks": d["checks"],
        "advantage_rule": d["advantage_rule"],
        "advantage_ml": d["advantage_ml"],
        "delta": d["delta"],
        "wins": {"rule": wins_rule, "ml": wins_ml},
        "replication_ok": d["replication_ok"],
        "prior_readings": PRIOR,
        "verdict": d["verdict"],
        "supplementary_sweep": sweep(judge_ml),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    sw = json.loads(out.read_text(encoding="utf-8"))["supplementary_sweep"]
    print(f"\n补充扩种（n={sw['n_seeds']}，预注册后，主判据不变）：")
    print(f"  adaptive: rule={sw['rule_L2_adaptive_mean']:.4f}±{sw['rule_L2_adaptive_se']:.4f}"
          f"  ml={sw['ml_L2_adaptive_mean']:.4f}±{sw['ml_L2_adaptive_se']:.4f}")
    print(f"  random  : rule={sw['rule_L2_random_mean']:.4f}  ml={sw['ml_L2_random_mean']:.4f}")
    print(f"  逐种子自适应落差: mean={sw['paired_adaptive_drop_mean']:+.4f}"
          f"±{sw['paired_adaptive_drop_se']:.4f}  规则更高 {sw['adaptive_drop_wins']}/{sw['n_seeds']}")
    print(f"  Δ(20种子)={sw['delta']:+.4f}")
    print(f"\n结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
