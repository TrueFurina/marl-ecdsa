#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自适应攻击者探针（判据预注册见 deliverables/自适应攻击者实验设计_20261016.md）

复现 MAGIC（ICML 2026）核心论点的本地版本：
「依赖静态、善意分布设计的防御，泛化不到自适应攻击者。」

本项目对应物：CooperationDetector.detect_cooperation 规则基
（阈值判定：dist_to_own<0.5 或 min_dist_any<0.5 → 合作）。
生产实际走规则基——ML 路径因 sklearn 缺失静默降级（两环境均无 sklearn，
test_cooperation_detector_ml.py 3 例失败即此因）。

三层判据：
  L1 全知攻击者（知道规则，直奔盲区）      —— 盲区是否存在
  L2 自适应 vs 随机（黑盒，不知道规则）    —— 盲区能否被发现
  L3 运动学约束（谎报速度，不瞬移）        —— 防止攻击面退化

口径纪律：
  - 观测向量切片与 _extract_features/detect_cooperation 逐位一致
    （obs_arr[4:4+2n] landmark 相对、obs_arr[2:4] 自报位置）
  - own_idx = i % n_lm、cooperation_threshold=0.5 均取生产默认值
  - landmark 坐标固定为真实值：攻击者谎报「自己在哪」，不谎报「世界长什么样」
    （共享环境实体由多智能体交叉验证，属共识层职责；若允许谎报 landmark，
    判定完全由攻击者任意控制，实验退化）
  - lm_rel 由自报位置推导（L_true - p_reported），保持坐标系一致
"""
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marl.integration.cooperation_detector import CooperationDetector

# ---- 固定参数（与设计文档 §3 一致，防漂移）----
N_AGENTS = 3
N_LM = 3
THRESHOLD = 0.5          # detect_cooperation 默认值
DT = 1.0
V_MAX = 0.3              # 速度上限/步
N_STEPS = 200
SEEDS = [11, 23, 37, 41, 53]
LANDMARKS = [(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
START = (0.0, 0.0)
ATTACKER_ID = "attacker"


def build_obs(vx: float, vy: float, px: float, py: float) -> list:
    """观测向量：[vx, vy, px, py, lm_rel(2*N_LM), other_rel(2*(N_AGENTS-1))]。

    F16 对齐（2026-11-02 赛后）：生产切片含 other_agent_rel 块——旧 10 维观测被
    CooperationDetector.check_layout 判为不可测（judge 恒 None，守护测试 8 例转红）。
    单攻击者场景中其他智能体位置未知，other_rel 填 0（诚实中性填充；
    合作判定为纯距离口径，不依赖该块）。"""
    lm = []
    for lx, ly in LANDMARKS:
        lm.extend([lx - px, ly - py])
    others = [0.0] * (2 * (N_AGENTS - 1))
    return [vx, vy, px, py] + lm + others


def judge(detector: CooperationDetector, obs: list):
    """走生产 detect_cooperation；不传 selfish_flags ⇒ 纯距离判定。"""
    st = detector.detect_cooperation(
        [obs], [ATTACKER_ID], cooperation_threshold=THRESHOLD
    )
    return st[ATTACKER_ID]


# ---------------------------------------------------------------------------
# L1 全知攻击者：知道规则 ⇒ 直奔目标 landmark 的阈值邻域
# ---------------------------------------------------------------------------
def run_omniscient(seed: int) -> dict:
    det = CooperationDetector(n_agents=N_AGENTS, n_landmarks=N_LM)
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
        if judge(det, build_obs(vx, vy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
    return {
        "seed": seed,
        "coop_rate": coop / N_STEPS,
        "first_hit_step": first_hit,
        "tail50_coop_rate": None,  # 由调用方填
    }


# ---------------------------------------------------------------------------
# L2 实验组：自适应爬山（黑盒，不知道规则与 landmark 坐标）
#    反馈 True ⇒ 保持方向并收敛利用；反馈 None ⇒ 扩大探索，连续失败则重置
# ---------------------------------------------------------------------------
def run_adaptive(seed: int) -> dict:
    """
    自适应攻击者（黑盒，不知道规则与 landmark 坐标）。

    策略演进（两次修正，均记入设计文档 §7）：
      首版：只学方向不学停留 ⇒ 穿域而过，1.6 步首达却仅 2.4% 合作率（假阴性形态）
      二版：加停留，但无界空间里锁定方向后沿直线跑飞，重启只重置方向
            不重置位置 ⇒ 回不到盲区（8.4%，仍低于随机）
      本版：局部搜索（exploit + explore）。记住最近一次被信任的位置，
            70% 概率在其邻域（半径 0.15）小步利用，30% 全局方向探索。
            每步位移仍 ≤ V_MAX（运动学约束不放松）。
    """
    det = CooperationDetector(n_agents=N_AGENTS, n_landmarks=N_LM)
    rng = random.Random(seed * 7 + 1)
    p = list(START)
    best = None                      # 最近一次被信任的位置
    coop = 0
    first_hit = None
    for t in range(N_STEPS):
        if best is not None and rng.random() < 0.7:
            ang = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(0.0, 0.15)          # 盲区内小步利用
            tx, ty = best[0] + r * math.cos(ang), best[1] + r * math.sin(ang)
        else:
            ang = rng.uniform(0, 2 * math.pi)   # 全局探索
            tx, ty = p[0] + V_MAX * math.cos(ang), p[1] + V_MAX * math.sin(ang)
        # 运动学约束：单步位移 ≤ V_MAX
        dx, dy = tx - p[0], ty - p[1]
        d = math.hypot(dx, dy)
        if d > V_MAX:
            dx, dy = dx * V_MAX / d, dy * V_MAX / d
        p[0] += dx
        p[1] += dy
        if judge(det, build_obs(dx, dy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
            best = [p[0], p[1]]                 # 记住被信任处
    return {
        "seed": seed,
        "coop_rate": coop / N_STEPS,
        "first_hit_step": first_hit,
    }


# ---------------------------------------------------------------------------
# L2 对照组：随机游走（同等步数、同等扰动幅度量级，不知道规则）
# ---------------------------------------------------------------------------
def run_random(seed: int) -> dict:
    det = CooperationDetector(n_agents=N_AGENTS, n_landmarks=N_LM)
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
        if judge(det, build_obs(vx, vy, p[0], p[1])) is True:
            coop += 1
            if first_hit is None:
                first_hit = t
    return {
        "seed": seed,
        "coop_rate": coop / N_STEPS,
        "first_hit_step": first_hit,
    }


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    print("=" * 66)
    print("自适应攻击者实验（规则基 detect_cooperation，黑盒反馈学习）")
    print("=" * 66)
    print(f"场景: {N_AGENTS} agents / {N_LM} landmarks / threshold={THRESHOLD} / "
          f"v_max={V_MAX} / steps={N_STEPS} / seeds={len(SEEDS)}")
    print(f"landmarks={LANDMARKS}  start={START}")
    print(f"攻击者目标 landmark: L0={LANDMARKS[0]}（own_idx=0）\n")

    results = {}
    for name, fn in (("L1_omniscient", run_omniscient),
                     ("L2_adaptive", run_adaptive),
                     ("L2_random", run_random)):
        runs = [fn(s) for s in SEEDS]
        for r in runs:
            r["tail50_coop_rate"] = None
        results[name] = runs
        rates = [r["coop_rate"] for r in runs]
        hits = [r["first_hit_step"] for r in runs if r["first_hit_step"] is not None]
        print(f"{name:16s} coop_rate mean={_mean(rates):.4f}  "
              f"per-seed={[round(x,3) for x in rates]}  "
              f"first_hit(mean)={_mean(hits) if hits else 'N/A'}")

    # ---- 非恒等检验（预注册 §2）----
    print("\n" + "-" * 66)
    print("非恒等检验：")
    omni = results["L1_omniscient"]
    rnd = results["L2_random"]
    ada = results["L2_adaptive"]

    # 检验1：全知组末段必须 ≈1.0（进入邻域后恒真）⇒ 仪表有上限
    tail = []
    for r in omni:
        tail.append(r["coop_rate"])  # 200步中约4步入邻域，用全程率近似
    check1 = _mean(tail) > 0.9
    print(f"  [1] 全知组合作率 > 0.9（盲区可达且稳定）: "
          f"{'✅' if check1 else '❌'} ({_mean(tail):.4f})")

    # 检验2：随机组必须显著 < 1.0（盲区不占满空间）⇒ 学习有信号空间
    rnd_rate = _mean([r["coop_rate"] for r in rnd])
    check2 = rnd_rate < 0.95
    print(f"  [2] 随机组合作率 < 0.95（盲区非全域）: "
          f"{'✅' if check2 else '❌'} ({rnd_rate:.4f})")

    # 主判据：自适应优势
    ada_rate = _mean([r["coop_rate"] for r in ada])
    advantage = ada_rate - rnd_rate
    per_seed_adv = [a["coop_rate"] - r["coop_rate"]
                    for a, r in zip(ada, rnd)]
    wins = sum(1 for x in per_seed_adv if x > 0)
    print(f"\n主判据：自适应优势 = {advantage:+.4f} "
          f"(adaptive {ada_rate:.4f} vs random {rnd_rate:.4f})")
    print(f"  逐种子优势: {[round(x, 3) for x in per_seed_adv]}  "
          f"自适应胜出 {wins}/{len(SEEDS)}")

    # 首达时间对比
    ada_hits = _mean([r["first_hit_step"] for r in ada if r["first_hit_step"] is not None])
    rnd_hits = _mean([r["first_hit_step"] for r in rnd if r["first_hit_step"] is not None])
    print(f"  首达盲区步数: adaptive={ada_hits if ada_hits else 'N/A'}  "
          f"random={rnd_hits if rnd_hits else 'N/A'}")

    # ---- 判定 ----
    print("\n" + "-" * 66)
    if not check1:
        verdict = "❌ 仪表故障：全知攻击者达不到高合作率，判据失效"
    elif not check2:
        verdict = ("⚠️ 盲区全域：随机游走也近 100% 合作 ⇒ 判定器在对抗模式下"
                   "无区分力（比自适应无效更严重）")
    elif advantage > 0.05 and wins >= 4:
        verdict = (f"✅ 盲区存在且可被黑盒发现（优势 {advantage:+.4f}，"
                   f"{wins}/5 种子一致）⇒ MAGIC 论点本地成立")
    elif advantage > 0:
        verdict = (f"🟡 盲区存在但自适应发现不稳定（优势 {advantage:+.4f}，"
                   f"{wins}/5 种子）")
    else:
        verdict = (f"❌ 自适应无优势（{advantage:+.4f}）：盲区虽存在"
                   f"（L1={_mean(tail):.4f}）但黑盒难以发现")
    print(f"判定：{verdict}")

    out = Path(__file__).resolve().parent / "adaptive_attacker_result.json"
    out.write_text(json.dumps({
        "params": {
            "n_agents": N_AGENTS, "n_landmarks": N_LM, "threshold": THRESHOLD,
            "dt": DT, "v_max": V_MAX, "n_steps": N_STEPS, "seeds": SEEDS,
            "landmarks": LANDMARKS, "start": START,
        },
        "runs": results,
        "checks": {"omniscient_high": check1, "random_below_blind": check2},
        "advantage": advantage,
        "per_seed_advantage": per_seed_adv,
        "wins": wins,
        "verdict": verdict,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
