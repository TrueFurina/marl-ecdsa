# -*- coding: utf-8 -*-
"""
自适应攻击者实验守护测试（tests for scripts/security/_probe_adaptive_attacker.py）

守护的是「实验可信度」而非「结论方向」——负结果与正结果同理：
探针算错就会永久误导。判据预注册见
deliverables/自适应攻击者实验设计_20261016.md §2。

核心守护点：
  1. 口径与生产逐位一致（观测切片 / own_idx / threshold）
  2. L1 全知攻击者可达高合作率（盲区存在，仪表有上限）
  3. 随机组显著 <100%（盲区非全域，学习有信号空间）
  4. 自适应优势显著为正（核心发现； exploit 机制失效必须转红）
  5. 策略演进防回归：纯探索（exploit=0）必须打不过随机基线
"""
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from marl.integration.cooperation_detector import CooperationDetector

from scripts.security._probe_adaptive_attacker import (
    LANDMARKS, N_LM, START, THRESHOLD, V_MAX,
    build_obs, judge, run_adaptive, run_omniscient, run_random,
)

TEST_SEEDS = [11, 23, 37]          # 快速子集（探针用 5 个，测试取 3）


# ---------------------------------------------------------------------------
# 1. 口径守卫：探针用的切片/threshold 必须与生产一致
# ---------------------------------------------------------------------------
def test_observation_vector_matches_production_slicing():
    """obs[4:4+2n] 是 landmark 相对坐标、obs[2:4] 是自报位置——与
    cooperation_detector._extract_features 的切片口径逐位一致。"""
    obs = build_obs(0.1, 0.2, 0.3, 0.4)
    # F16：生产切片含 other_rel 块（单攻击者场景填 0）
    assert len(obs) == 4 + 2 * N_LM + 2 * (3 - 1)
    assert obs[4 + 2 * N_LM:] == [0.0] * (2 * (3 - 1))
    # landmark 相对坐标 = 真实 landmark - 自报位置
    for j, (lx, ly) in enumerate(LANDMARKS):
        assert obs[4 + 2 * j] == pytest.approx(lx - 0.3)
        assert obs[5 + 2 * j] == pytest.approx(ly - 0.4)
    # 自报位置透传
    assert obs[2:4] == [0.3, 0.4]


def test_threshold_matches_production_default():
    """cooperation_threshold 必须取 detect_cooperation 默认值 0.5。"""
    assert THRESHOLD == 0.5
    det = CooperationDetector(n_agents=3, n_landmarks=N_LM)
    # 站在 landmark 正上方 ⇒ 必然判合作（证明判定器在工作）
    obs = build_obs(0.0, 0.0, LANDMARKS[0][0], LANDMARKS[0][1])
    assert judge(det, obs) is True


def test_own_idx_matches_production_modulo():
    """own_idx = i % n_lm：agent 0 的目标 landmark 是 L0（探针口径）。"""
    det = CooperationDetector(n_agents=3, n_landmarks=N_LM)
    # 报在 L0 上 ⇒ dist_to_own≈0 ⇒ 合作
    obs = build_obs(0.0, 0.0, LANDMARKS[0][0], LANDMARKS[0][1])
    assert judge(det, obs) is True
    # 报在 L1 上：agent0 的 own 目标是 L0，但 min_dist_any<0.5 也判合作
    # （这正是 v3 的设计决策——靠近任意 landmark 算合作）
    obs = build_obs(0.0, 0.0, LANDMARKS[1][0], LANDMARKS[1][1])
    assert judge(det, obs) is True


# ---------------------------------------------------------------------------
# 2. L1 全知攻击者：盲区可达且稳定
# ---------------------------------------------------------------------------
def test_omniscient_attacker_reaches_high_cooperation():
    """全知攻击者（知道规则直奔盲区）合作率必须 >0.9——
    否则说明盲区不存在或判定器无区分力（仪表故障）。"""
    for seed in TEST_SEEDS:
        r = run_omniscient(seed)
        assert r["coop_rate"] > 0.9, f"seed={seed} 全知组仅 {r['coop_rate']:.3f}"
        assert r["first_hit_step"] is not None


# ---------------------------------------------------------------------------
# 3. 随机组：盲区非全域
# ---------------------------------------------------------------------------
def test_random_walker_stays_below_full_blind():
    """随机游走合作率必须显著 <1.0——否则盲区占满可行空间，
    「自适应优势」将恒等于 0，主判据退化为恒等式。"""
    rates = [run_random(s)["coop_rate"] for s in TEST_SEEDS]
    mean = sum(rates) / len(rates)
    assert mean < 0.95, f"随机组 {mean:.3f} 接近全域 ⇒ 判据退化"


# ---------------------------------------------------------------------------
# 4. 主判据：自适应优势为正（核心发现守护）
# ---------------------------------------------------------------------------
def test_adaptive_advantage_over_random():
    """自适应组平均合作率必须显著高于随机组。
    这是本实验的核心结论（MAGIC 论点本地成立）——
    若探针的 exploit 机制被破坏，本测试必须转红。"""
    ada = [run_adaptive(s)["coop_rate"] for s in TEST_SEEDS]
    rnd = [run_random(s)["coop_rate"] for s in TEST_SEEDS]
    adv = sum(ada) / len(ada) - sum(rnd) / len(rnd)
    assert adv > 0.05, f"自适应优势仅 {adv:+.3f}（ada={ada} rnd={rnd}）"


def test_adaptive_wins_majority_of_seeds():
    """逐种子多数胜出（容忍个别种子失败——实测 4/5，
    不允许 5/5 全胜的过强断言）。"""
    wins = sum(
        1 for s in TEST_SEEDS
        if run_adaptive(s)["coop_rate"] > run_random(s)["coop_rate"]
    )
    assert wins >= 2, f"仅 {wins}/{len(TEST_SEEDS)} 种子胜出"


# ---------------------------------------------------------------------------
# 5. 策略有效性：exploit 机制是优势来源（防回归）
# ---------------------------------------------------------------------------
def _adaptive_no_exploit(seed: int) -> float:
    """复现 run_adaptive 但强制纯探索（exploit 概率 0）——
    验证「优势来自 exploit 而非别的东西」。"""
    rng = random.Random(seed * 7 + 1)
    det = CooperationDetector(n_agents=3, n_landmarks=N_LM)
    p = list(START)
    coop = 0
    for _ in range(200):
        ang = rng.uniform(0, 2 * math.pi)
        tx, ty = p[0] + V_MAX * math.cos(ang), p[1] + V_MAX * math.sin(ang)
        dx, dy = tx - p[0], ty - p[1]
        d = math.hypot(dx, dy)
        if d > V_MAX:
            dx, dy = dx * V_MAX / d, dy * V_MAX / d
        p[0] += dx
        p[1] += dy
        if judge(det, build_obs(dx, dy, p[0], p[1])) is True:
            coop += 1
    return coop / 200


def test_advantage_comes_from_exploit_not_exploration():
    """把 exploit 关掉（纯探索=随机），优势必须消失。
    若本测试绿而 test_adaptive_advantage_over_random 红 ⇒ 口径漂移；
    若两者同红 ⇒ 探针实现与测试脱节。"""
    ada = [run_adaptive(s)["coop_rate"] for s in TEST_SEEDS]
    noexp = [_adaptive_no_exploit(s) for s in TEST_SEEDS]
    assert sum(ada) / len(ada) > sum(noexp) / len(noexp) + 0.05, (
        f"关掉 exploit 后未退化：ada={ada} no_exploit={noexp}"
    )


# ---------------------------------------------------------------------------
# 6. 伤害不恒 0（防「全判负」式坏仪表）
# ---------------------------------------------------------------------------
def test_blind_zone_is_nontrivial():
    """盲区必须是非空的有限区域：
    - 站在 L0 上 ⇒ True（盲区存在）
    - 站在远处 (5,5) ⇒ None（判定器有区分力）
    两者同时成立才说明测的是「边界」而非「恒真/恒假」。"""
    det = CooperationDetector(n_agents=3, n_landmarks=N_LM)
    assert judge(det, build_obs(0, 0, LANDMARKS[0][0], LANDMARKS[0][1])) is True
    far = build_obs(0, 0, 5.0, 5.0)
    assert judge(det, far) is None, "远处仍判 True ⇒ 判定器恒真，仪表坏"


def test_random_hits_are_nontrivial():
    """随机组必须偶有命中（>0）——全 0 说明场景设置让盲区不可达，
    此时 L1 也应失败；两者互为交叉验证。"""
    rates = [run_random(s)["coop_rate"] for s in TEST_SEEDS]
    assert max(rates) > 0.0, "随机组全零命中 ⇒ 场景不可达，检查 LANDMARKS/V_MAX"
