#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ML 共演化环探针（对抗重训；判据预注册见 deliverables/ML共演化环实验_20261016.md）

问题链（前两个安全实验的遗留边界）：
  1. 盲区实验（_probe_ml_blindspot.py）：ML 路径若接线，自适应成功率
     0.6730→0.4870，但白盒 L1 0.9950——盲区未消失
  2. 定向攻击实验（_probe_ml_targeted_attack.py）：S2 模型窃取 0.9950=白盒
     天花板 ⇒ 0.4870 是 v3 搜索类上限；ML 抬高门槛（爬山→窃取模型）但不
     关闭盲区
  两者共同遗留：**固定防御单轮适应**——防御方不随攻击重训。本探针补上
  共演化环：
    R_r 模型 = train(良性 ∪ 攻击轨迹(R_0..R_{r-1})，语义真值标签)
    R_r 攻击 = 窃取 R_r 模型（Kerckhoffs：算法类公开 ⇒ 同族 ExtraTrees
              深度 8，8000 查询）→ 反演占领**离流形可信格**
  轮数预注册 6 轮（R0..R5）。

「利用」的操作定义（安全指标，非总体判定率）：
  exploit_rate = 被判合作**且**离流形（dist_to_own≥0.5，agent 0 视角）
  的步数占比。坐在自身 landmark 邻域是合法行为（规则基也判合作），不计
  利用；只有「远离自身 landmark 却被判合作」才是盲区剥削。

负载事实：ML 路径全仓零调用方 ⇒ 反事实度量，不是已交付能力。

训练集对齐（关键实现细节，E3 守卫）：
  _extract_features 用**列表索引** i%n_lm 决定 own landmark。良性集长度
  9600=3 的倍数，三元组（a0,a1,a2）视角正确。攻击观测（agent 0 视角）
  必须落在 ≡0 (mod 3) 槽位，否则 2/3 样本被错配 own_idx 并以错误标签
  污染「靠近 L1 ⇒ 合作」模式（那正是盲区本身）。故每个攻击位置以三槽位
  视角入队，标签按各视角语义标注：own=0 ⇒ 0（区分信号，闭盲区的来源）；
  own=1/2 ⇒ 语义正确值（靠近 L1 且自身=L1 ⇒ 1）。冲突诊断逐位核验。

判据（预注册决策表，见 decide()；先定判据后跑数）：
  E0 仪表（R0 复读盲区实验良性-only 模型）：
     trusted_cells==560｜heldout≥0.90｜代理一致率≥0.95 且目标被真实模型
     判信｜本地 exploit 导航在全可信集上与 BS.run_omniscient_ml 逐位一致
  E1 良性保全：所有回合 heldout≥0.90（否则「关闭盲区」的代价是摧毁合法
     检测——仍报告，判定加代价前缀）
  E2 初始可利用：R0 exploit_rate>0.80（否则实验对象不存在）
  E3 标签完整性：每回合冲突行数（与良性训练行特征全同而标签相反）==0
     （>0 ⇒ own_idx 对齐管线坏，共演化结论不可信）
  E4 主判据（末回合 + 轨迹）：
     exploit_final≤0.20 且离流形格==0   ⇒ ✅ 共演化重训关闭盲区（报 n*）
     exploit_final≤0.20 且残余 1~10 格  ⇒ ✅ 近似关闭（披露残余）
     exploit_final>0.80 且目标跨回合迁移 ⇒ 🔴 打地鼠（重训只搬迁盲区）
     exploit_final>0.80 且目标不迁移    ⇒ 🔴 重训无效（同区持续可占）
     其余                              ⇒ 🟡 部分压缩（报轨迹 + 残余）
  E5 代理仪表（每回合，不阻塞）：一致率≥0.95 且 target_real_trusted
  E6 确定性守卫：每回合 5 种子 exploit_rate 逐位相等（导航/代理无随机源；
     不等 ⇒ 随机源混入 ⇒ 仪表故障）

口径纪律：观测/运动学/网格/阈值逐位复用盲区探针（BS.*）；代理仪器复用
定向攻击探针（TA.train_surrogate，单一真源）；良性协议（种子 101、20 回合、
前 16 训练后 4 留出）与盲区实验逐位一致。

诚实边界（结论引用必须携带）：
  1. ML 路径零调用方 ⇒ 反事实；不得宣称生产具备 ML 检测或共演化能力
  2. 防御方标签=环境语义真值（oracle labeling）。生产只有自报位置时无标签，
     需主动学习/抽样人工审计，未测
  3. 攻击方每回合免费重窃取（Kerckhoffs）；防御方每回合仅新增一轮观测
     （等量对局下防御数据增长率 = 攻击观测率），代价不对称已尽量对称化
  4. 攻击类只含「占领最近离流形可信格」（S2 式）；v3 局部搜索/重启类未入环
  5. 5 种子导航确定且逐位相同（E6 守卫）⇒ 训练按**独特轨迹**计，避免同一
     轨迹 5 副本虚增防御方权重
  6. 合成良性数据；sklearn 版本决定树结构 ⇒ 数字不跨版本比对
     （本结果由 marl-ml venv：py3.13.14/sklearn1.9.1 产出）
"""
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load(name: str, filename: str):
    """按文件路径加载同目录探针模块（单一真源复用，防口径漂移）。"""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BS = _load("probe_ml_blindspot_shared", "_probe_ml_blindspot.py")
TA = _load("probe_ml_targeted_shared", "_probe_ml_targeted_attack.py")

from marl.integration.cooperation_detector import CooperationDetector

# ---- 预注册参数 ----
N_ROUNDS = 6                      # 共演化轮数（R0..R5）

# 良性-only 模型指纹（盲区实验已提交读数，复读基准；优先取 JSON）
_PRIOR_R0_FALLBACK = {"trusted_cells": 560, "heldout": 0.9879}


def load_prior_r0() -> dict:
    f = HERE / "ml_blindspot_result.json"
    if not f.exists():
        return dict(_PRIOR_R0_FALLBACK)
    d = json.loads(f.read_text(encoding="utf-8"))
    return {"trusted_cells": d["trusted_region"]["trusted_cells"],
            "heldout": d["ml_defender"]["heldout_accuracy"]}


PRIOR_R0 = load_prior_r0()


# ---------------------------------------------------------------------------
# 离流形判定与目标格标记
# ---------------------------------------------------------------------------
def _off_manifold(x: float, y: float) -> bool:
    """离流形 = 远离自身 landmark（agent 0 视角，index%3 口径）。"""
    return BS._dist_to_own(x, y, 0) >= BS.THRESHOLD


def _target_label(x: float, y: float) -> str:
    """目标格所在 landmark 邻域（打地鼠迁移诊断）。"""
    for idx, (lx, ly) in enumerate(BS.LANDMARKS):
        if math.hypot(lx - x, ly - y) < BS.THRESHOLD:
            return f"L{idx}"
    return "other"


# ---------------------------------------------------------------------------
# 良性数据切分（与盲区实验同协议：种子 101 / 20 回合 / 前 16 训练后 4 留出）
# ---------------------------------------------------------------------------
def gen_benign_split():
    episodes, diag = BS.gen_benign_episodes()
    tr_obs = [o for ep in episodes[:BS.BENIGN_TRAIN_EPISODES] for o in ep[0]]
    tr_lab = [l for ep in episodes[:BS.BENIGN_TRAIN_EPISODES] for l in ep[1]]
    tr_ids = [i for ep in episodes[:BS.BENIGN_TRAIN_EPISODES] for i in ep[2]]
    ho_obs = [o for ep in episodes[BS.BENIGN_TRAIN_EPISODES:] for o in ep[0]]
    ho_lab = [l for ep in episodes[BS.BENIGN_TRAIN_EPISODES:] for l in ep[1]]
    ho_ids = [i for ep in episodes[BS.BENIGN_TRAIN_EPISODES:] for i in ep[2]]
    return (tr_obs, tr_lab, tr_ids), (ho_obs, ho_lab, ho_ids), diag


def build_retrain_set(benign, attack_obs_cum):
    """攻击观测按三元组对齐入训练集（index%3 → own_idx；标签按槽位语义标注）。

    _extract_features 用**列表索引** i%n_lm 决定 own landmark：良性集长度
    9600=3 的倍数，三元组（a0,a1,a2）视角正确。攻击观测（agent 0 视角）
    必须落在 ≡0 (mod 3) 槽位，否则 2/3 样本被错配 own_idx 并以错误标签
    污染「靠近 L1 ⇒ 合作」模式（那正是盲区本身）。故每个攻击位置以三槽位
    视角入队：own=0 ⇒ 0（区分信号，闭盲区的来源）；own=1/2 ⇒ 语义正确值
    （靠近 L1 且自身=L1 ⇒ 1）。该构造不引入标签冲突（E3 逐位核验）。
    """
    tr_obs, tr_lab, tr_ids = list(benign[0]), list(benign[1]), list(benign[2])
    assert len(tr_obs) % BS.N_LM == 0, "良性训练集长度必须是 n_lm 倍数（三元组对齐前提）"
    for a in attack_obs_cum:
        px, py = a[2], a[3]
        for own in range(BS.N_LM):
            tr_obs.append(a)
            tr_lab.append(BS.benign_label(px, py, own))
            tr_ids.append("attacker")
    return tr_obs, tr_lab, tr_ids


def retrain_defender(benign, attack_obs_cum):
    """R_r 防御方：良性 ∪ 累计攻击轨迹重训；返回 (detector, 训练诊断)。"""
    tr_obs, tr_lab, tr_ids = build_retrain_set(benign, attack_obs_cum)
    det = CooperationDetector(n_agents=BS.N_AGENTS, n_landmarks=BS.N_LM)
    ok = det.train_classifier(tr_obs, tr_ids, tr_lab)
    # 标签冲突诊断：新增行与良性训练行特征全同而标签相反（E3）
    feats, _ = det._extract_features(tr_obs, tr_ids)
    n_benign = len(benign[0])
    benign_map = {}
    for f, l in zip(feats[:n_benign], tr_lab[:n_benign]):
        benign_map.setdefault(tuple(f), set()).add(int(l))
    conflicts = sum(
        1 for f, l in zip(feats[n_benign:], tr_lab[n_benign:])
        if int(l) not in benign_map.get(tuple(f), {int(l)}))
    info = {"trained": bool(ok), "train_rows": len(tr_obs),
            "attack_rows": len(tr_obs) - n_benign, "conflicts": conflicts}
    return det, info


# ---------------------------------------------------------------------------
# 攻击方：导航占领离流形可信格（复用盲区实验白盒 L1 同导航）
# ---------------------------------------------------------------------------
def run_exploit(seed: int, judge_fn, candidate_cells: list, record: bool = False) -> dict:
    """导航占领离流形可信格（步长按剩余距离截断，与 BS.run_omniscient_ml 同构）。

    攻击者行为（faithful）：从代理可信域按距 START 升序逐个试探，占领**第一个
    真实模型也判合作**的候选格（即代理误差格会被真实反馈剔除，不计入可利用）。
    这与定向攻击探针 S2 同构（S2 命中白盒天花板 0.9950）。若候选域无真实可信格
    ⇒ exploit=0（诚实：攻击者找不到可利用盲点）。

    额外回报 exploit_rate：被判合作**且**离流形的步数占比——真正的盲区剥削
    指标（坐在自身 landmark 邻域是合法行为，不计利用）。
    record=True 时回报轨迹观测（供防御方下一轮重训）。
    """
    if not candidate_cells:
        return {"seed": seed, "coop_rate": 0.0, "exploit_rate": 0.0,
                "first_hit_step": None, "target": None, "traj_obs": [],
                "note": "no candidate cell"}
    ordered = sorted(candidate_cells, key=lambda c: (c[0] - BS.START[0]) ** 2
                     + (c[1] - BS.START[1]) ** 2)
    # 预筛：仅保留真实模型判合作的候选（攻击者实际抵达后获真实反馈，等价）
    valid = [c for c in ordered
             if judge_fn(BS.build_obs(0.0, 0.0, c[0], c[1])) is True]
    if not valid:
        return {"seed": seed, "coop_rate": 0.0, "exploit_rate": 0.0,
                "first_hit_step": None, "target": None, "traj_obs": [],
                "note": "surrogate candidates all rejected by real model"}
    target = valid[0]
    p = list(BS.START)
    coop = exploit = 0
    first_hit = None
    traj = []
    for t in range(BS.N_STEPS):
        d = math.hypot(target[0] - p[0], target[1] - p[1])
        if d > 0.02:
            step = min(BS.V_MAX, d)      # 必须按剩余距离截断，否则目标两侧振荡
            dx, dy = (target[0] - p[0]) / d * step, (target[1] - p[1]) / d * step
        else:
            dx = dy = 0.0
        p[0] += dx
        p[1] += dy
        obs = BS.build_obs(dx, dy, p[0], p[1])
        if record:
            traj.append(obs)
        if judge_fn(obs) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
            if _off_manifold(p[0], p[1]):
                exploit += 1
    return {"seed": seed, "coop_rate": coop / BS.N_STEPS,
            "exploit_rate": exploit / BS.N_STEPS, "first_hit_step": first_hit,
            "target": list(target), "traj_obs": traj if record else None}


def run_random_exploit(seed: int, judge_fn) -> dict:
    """随机游走对照（与 BS.run_random 同 rng 同运动学）+ exploit 计数。"""
    rng = random.Random(seed * 13 + 5)
    p = list(BS.START)
    coop = exploit = 0
    first_hit = None
    for t in range(BS.N_STEPS):
        theta = rng.uniform(0, 2 * math.pi)
        rate = rng.uniform(0.1, BS.V_MAX)
        vx, vy = rate * math.cos(theta), rate * math.sin(theta)
        p[0] += vx * BS.DT
        p[1] += vy * BS.DT
        if judge_fn(BS.build_obs(vx, vy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
            if _off_manifold(p[0], p[1]):
                exploit += 1
    return {"seed": seed, "coop_rate": coop / BS.N_STEPS,
            "exploit_rate": exploit / BS.N_STEPS, "first_hit_step": first_hit}


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


# ---------------------------------------------------------------------------
# 预注册决策表（纯函数，可单测；改边界=改判据，必须显式）
# ---------------------------------------------------------------------------
def decide(rounds: list, prior: dict) -> dict:
    """:param rounds: 每回合指标列表（键见 main）；:param prior: R0 复读基准"""
    r0 = rounds[0]
    final = rounds[-1]
    checks = {
        "E0_r0_fingerprint": (
            r0["model"]["trusted_cells"] == prior["trusted_cells"]
            and (r0["model"]["heldout"] or 0.0) >= 0.90
            and r0["surrogate"]["agreement"] >= 0.95
            and r0["attack"]["target_real_trusted"] is True
            and r0["nav_consistency_ok"] is True),
        "E1_benign_preserved": all(
            (rd["model"]["heldout"] or 0.0) >= 0.90 for rd in rounds),
        "E2_initially_exploitable": r0["attack"]["exploit_rate"] > 0.80,
        "E3_no_label_conflict": all(rd["train"]["conflicts"] == 0 for rd in rounds),
        "E5_surrogate_instrument": all(
            rd["surrogate"]["agreement"] >= 0.95
            and rd["attack"]["target_real_trusted"] is True
            for rd in rounds if rd["attack"]["target"] is not None),
        "E6_determinism": all(
            len({round(x, 6) for x in rd["attack"]["exploit_rates"]}) <= 1
            for rd in rounds),
    }
    exploit_traj = [rd["attack"]["exploit_rate"] for rd in rounds]
    off_traj = [rd["model"]["off_cells"] for rd in rounds]
    active = [(rd["round"], rd["attack"]["target_label"])
              for rd in rounds if rd["attack"]["exploit_rate"] > 0.5]
    migrated = len({lab for _r, lab in active}) >= 2
    n_star = next((rd["round"] for rd in rounds
                   if rd["attack"]["exploit_rate"] <= 0.20), None)
    exploit_final = final["attack"]["exploit_rate"]
    off_final = final["model"]["off_cells"]

    if not checks["E0_r0_fingerprint"]:
        verdict = "❌ 仪表故障：R0 未复读盲区实验良性-only 模型（指纹/导航一致性不符）"
    elif not checks["E3_no_label_conflict"]:
        verdict = "❌ 标签冲突>0：own_idx 对齐管线坏，共演化结论不可信"
    elif not checks["E6_determinism"]:
        verdict = "❌ 确定性守卫失败：种子间 exploit 不等（随机源混入？）"
    elif not checks["E2_initially_exploitable"]:
        verdict = "⚠️ R0 盲区初始不可利用（exploit≤0.80）——实验对象不存在，需人工核查"
    elif exploit_final <= 0.20 and off_final == 0:
        verdict = (f"✅ 共演化重训关闭盲区（n*={n_star}；exploit 轨迹 "
                   f"{[round(x, 3) for x in exploit_traj]}；末回合离流形格 0）")
    elif exploit_final <= 0.20 and off_final <= 10:
        verdict = (f"✅ 近似关闭（残余 {off_final} 格；n*={n_star}；exploit 轨迹 "
                   f"{[round(x, 3) for x in exploit_traj]}）")
    elif exploit_final > 0.80 and migrated:
        verdict = (f"🔴 打地鼠：重训只搬迁盲区不关闭（exploit 轨迹 "
                   f"{[round(x, 3) for x in exploit_traj]}；目标迁移 {active}）")
    elif exploit_final > 0.80:
        verdict = (f"🔴 重训无效：同区持续可占（exploit 轨迹 "
                   f"{[round(x, 3) for x in exploit_traj]}；目标 {active}）")
    else:
        verdict = (f"🟡 部分压缩（exploit 轨迹 {[round(x, 3) for x in exploit_traj]}；"
                   f"残余离流形格 {off_final}；目标 {active}）")
    if not checks["E1_benign_preserved"]:
        verdict = ("⚠️ 良性检测被重训破坏（heldout<0.90）——关闭盲区的代价须同报；"
                   + verdict)
    if not checks["E5_surrogate_instrument"]:
        verdict = ("⚠️ 某回合代理仪表不良（一致率<0.95 或目标未被真实模型判信）"
                   "——该回合攻击结论不可信；" + verdict)
    return {"checks": checks, "exploit_trajectory": exploit_traj,
            "off_cells_trajectory": off_traj, "n_star": n_star,
            "migrated": migrated, "active_targets": active, "verdict": verdict}


def run_round(r: int, benign, held, attack_cum: list) -> tuple:
    """执行第 r 回合：防御方重训 → 指标 → 攻击方窃取+反演 → 回收轨迹。"""
    det, tr_info = retrain_defender(benign, attack_cum)
    if not tr_info["trained"]:
        raise RuntimeError(f"R{r} ML 训练失败")
    judge = BS.make_judge_ml(det)

    # 防御方指标（真实模型口径）
    trusted = BS.map_trusted_region(judge)
    off_cells = [c for c in trusted if _off_manifold(*c)]
    near = {f"L{i}": sum(1 for x, y in off_cells
                         if math.hypot(BS.LANDMARKS[i][0] - x,
                                       BS.LANDMARKS[i][1] - y) < BS.THRESHOLD)
            for i in range(BS.N_LM)}
    heldout = det.get_ml_accuracy(held[0], held[2], held[1])
    train_acc = det.get_ml_accuracy(benign[0], benign[2], benign[1])

    # 攻击方：窃取当前模型 → 反演离流形可信格 → 占领
    surr = TA.train_surrogate(judge)
    surr_off = [c for c in surr["trusted"] if _off_manifold(*c)]
    # 候选目标 = 代理离流形可信格全集；run_exploit 内部按距 START 升序试探，
    # 仅占领真实模型也判合作的格（代理误差格被真实反馈剔除，不计入可利用）。
    atk = [run_exploit(s, judge, surr_off, record=True) for s in BS.SEEDS]
    rnd = [run_random_exploit(s, judge) for s in BS.SEEDS]

    # 独特轨迹去重（5 种子导航确定；按独特 obs 序列计，防同轨迹 5 副本虚增权重）
    uniq, seen = [], set()
    for a in atk:
        key = tuple(tuple(o) for o in a["traj_obs"])
        if key not in seen:
            seen.add(key)
            uniq.extend(a["traj_obs"])

    target = atk[0]["target"]
    tlabel = _target_label(*target) if target else None
    treal = (bool(judge(BS.build_obs(0.0, 0.0, target[0], target[1])))
             if target else None)

    # R0 导航一致性：本地 exploit 导航 vs 盲区实验白盒导航（全可信集，逐位）
    nav_ok = None
    if r == 0:
        chk = [run_exploit(s, judge, trusted) for s in BS.SEEDS[:2]]
        ref = [BS.run_omniscient_ml(s, judge, trusted) for s in BS.SEEDS[:2]]
        nav_ok = all(a["coop_rate"] == b["coop_rate"]
                     and a["first_hit_step"] == b["first_hit_step"]
                     for a, b in zip(chk, ref))

    rd = {
        "round": r,
        "model": {"heldout": heldout, "train_acc": train_acc,
                  "trusted_cells": len(trusted), "off_cells": len(off_cells),
                  "off_frac": round(len(off_cells) / max(1, len(trusted)), 6),
                  "near": near},
        "attack": {"exploit_rate": _mean([a["exploit_rate"] for a in atk]),
                   "exploit_rates": [a["exploit_rate"] for a in atk],
                   "coop_rate": _mean([a["coop_rate"] for a in atk]),
                   "coop_rates": [a["coop_rate"] for a in atk],
                   "first_hit_step": atk[0]["first_hit_step"],
                   "target": target, "target_label": tlabel,
                   "target_real_trusted": treal,
                   "random_exploit_rate": _mean([a["exploit_rate"] for a in rnd]),
                   "random_coop_rate": _mean([a["coop_rate"] for a in rnd]),
                   "new_unique_obs": len(uniq)},
        "surrogate": {"agreement": surr["agreement"],
                      "trusted_cells": surr["trusted_cells"],
                      "off_cells": len(surr_off),
                      "target_fidelity": surr["target_fidelity"]},
        "train": tr_info,
        "nav_consistency_ok": nav_ok,
    }
    return rd, uniq


def main() -> int:
    print("=" * 70)
    print("ML 共演化环实验（防御方随攻击重训 × 攻击方每轮重窃取）")
    print("=" * 70)
    print(f"轮数: {N_ROUNDS}  种子: {BS.SEEDS}  复读基准: {PRIOR_R0}")
    benign, held, diag = gen_benign_split()
    print(f"良性: train {len(benign[0])} / heldout {len(held[0])}  diag={diag}")

    attack_cum = []
    rounds = []
    for r in range(N_ROUNDS):
        rd, uniq = run_round(r, benign, held, attack_cum)
        rounds.append(rd)
        attack_cum.extend(uniq)
        print(f"R{r}: model(heldout={rd['model']['heldout']} "
              f"trusted={rd['model']['trusted_cells']} "
              f"off={rd['model']['off_cells']} near={rd['model']['near']}) "
              f"attack(exploit={rd['attack']['exploit_rate']:.4f} "
              f"coop={rd['attack']['coop_rate']:.4f} "
              f"target={rd['attack']['target']} {rd['attack']['target_label']} "
              f"real={rd['attack']['target_real_trusted']} "
              f"rnd_exploit={rd['attack']['random_exploit_rate']:.4f}) "
              f"surr(agr={rd['surrogate']['agreement']:.4f} "
              f"off={rd['surrogate']['off_cells']}) "
              f"train(rows={rd['train']['train_rows']} "
              f"atk={rd['train']['attack_rows']} "
              f"conflicts={rd['train']['conflicts']})")

    d = decide(rounds, PRIOR_R0)
    print("\n" + "-" * 70)
    print("判据（预注册决策表）：")
    for k, v in d["checks"].items():
        print(f"  {k:28s} {'✅' if v else '❌'}")
    print(f"exploit 轨迹: {[round(x, 4) for x in d['exploit_trajectory']]}")
    print(f"离流形格轨迹: {d['off_cells_trajectory']}")
    print(f"n*={d['n_star']}  迁移={d['migrated']}  活跃目标={d['active_targets']}")
    print(f"判定：{d['verdict']}")

    out = HERE / "ml_coevolution_result.json"
    out.write_text(json.dumps({
        "params": {
            "n_rounds": N_ROUNDS, "seeds": BS.SEEDS,
            "n_agents": BS.N_AGENTS, "n_landmarks": BS.N_LM,
            "threshold": BS.THRESHOLD, "dt": BS.DT, "v_max": BS.V_MAX,
            "n_steps": BS.N_STEPS, "landmarks": BS.LANDMARKS, "start": BS.START,
            "benign_seed": BS.BENIGN_SEED, "benign_episodes": BS.BENIGN_EPISODES,
            "benign_train_episodes": BS.BENIGN_TRAIN_EPISODES,
            "grid": [BS.GRID_LO, BS.GRID_HI, BS.GRID_STEP],
            "surrogate_queries": TA.SURROGATE_QUERIES,
            "surrogate_max_depth": TA.SURROGATE_MAX_DEPTH,
        },
        "prior_r0": PRIOR_R0,
        "benign_diag": diag,
        "rounds": rounds,
        "trajectory": {"exploit_rates": d["exploit_trajectory"],
                       "off_cells": d["off_cells_trajectory"],
                       "targets": [rd["attack"]["target"] for rd in rounds],
                       "target_labels": [rd["attack"]["target_label"] for rd in rounds]},
        "n_star": d["n_star"], "migrated": d["migrated"],
        "active_targets": d["active_targets"],
        "checks": d["checks"], "verdict": d["verdict"],
        "versions": BS._versions(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
