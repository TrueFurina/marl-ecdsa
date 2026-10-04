#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_weight_broadening_full.py — 路线C「参与率驱动权重展宽」全量实验（2026-09-19）

与 PoC（run_weight_broadening_poc.py）的关系：
    本脚本是 PoC 的**升格版**，展宽机制的数值与逻辑**逐字继承** PoC，不做任何调参：
        FLOOR=0.25   MIN_W=0.1   MAX_W=1.5   EPOCH_ROUNDS=50   HONEST_MSG_LOSS=0.05
    差异仅在规模与对照完整性：
        1) 种子 5 → 10（SEEDS 见下方常量）
        2) 四档权重对照同场跑：uniform / contribution / legacy / dynamic
        3) 配置网格 n∈{4,10,16} × byz∈{0.33,0.40}，每格 10 seed × 2000 轮
        4) 统计学补齐：Welch t / Cohen's d / 95%CI（复用 scripts/assurance_common.py，
           纯标准库，样本<2 时 fail-closed）

四档权重语义：
    uniform       全节点 w=1.0                  → R=1，CW-PBFT ≡ 标准 PBFT 的理论基线
    contribution  真实 MARL 训练产出的 bc_scores 归一化 → w=1.0+0.5*(s/max) ∈ [1.49,1.5]
                  （与 run_consensus_repeated.py 既有 contribution 口径一致，R≈1.007）
    legacy        拜占庭节点手工压到 w=0.2、诚实节点 1.0+0.3*(idx%3)
                  ⚠ 该档**预知坏节点身份**，属实验假象，仅作对照组，禁止作为创新点申报
                  → 输出带 is_artifact_control=true + warning
    dynamic       路线C：参与率驱动展宽 + 纪元冻结(50轮) + MAX_W=1.5 钳制 + FLOOR=0.25
                  初始权重默认 uniform（PoC 原样），可用 --dynamic-init contribution 切换

诚实红线：
    本脚本**不**为「结果好看」做任何调参。若某格扩到 10 seed 后效应消失或反转，
    原样输出并在 verdict 字段标注 "NO_GAIN" / "REVERSED"，不做任何抑制。

统计口径：
    ±SD 一律 sample SD（ddof=1）；Cohen's d 用 pooled SD（ddof=1）；
    Welch t 与 95%CI 用 assurance_common.welch_ttest / ci95_diff（Welch 自由度）。
    注：PoC 报告用的是 pstdev（ddof=0），故 5-seed 子集数值会有微小差异，属口径变更。

纯标准库（assurance_common 亦纯标准库），无需 torch/numpy。
"""
import sys
import json
import random
import hashlib
import time
import logging
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from blockchain.consensus.cw_pbft import CWPBFTConsensus, ConsensusState
from blockchain.consensus.standard_pbft import StandardPBFTConsensus

from assurance_common import welch_ttest, cohens_d, ci95_diff, mean, stdev  # 纯标准库


def pct2(v):
    """百分比 ROUND_HALF_UP 取 2 位小数（口径铁律：表格可手算复核）。"""
    return float(Decimal(str(v * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

# ── 机制参数（与 PoC 逐字一致，禁止调参）──
HONEST_MSG_LOSS = 0.05
EPOCH_ROUNDS = 50
FLOOR = 0.25
MIN_W = 0.1
MAX_W = 1.5

# ── 实验规模 ──
SEEDS = [42, 123, 456, 789, 1024, 2026, 3141, 5926, 7777, 8888]
NODE_COUNTS = [4, 10, 16]
BYZ_RATIOS = [0.33, 0.40]
MODES = ["uniform", "contribution", "legacy", "dynamic"]

ARTIFACT_WARNING = (
    "legacy 档在构造权重时直接读取 byzantine 身份集合（拜占庭 w=0.2、诚实 1.0+0.3*(idx%3)），"
    "等于协议事先知道谁是坏节点。该增益是实验假象，仅作对照组，禁止作为创新点申报。"
)


# ──────────────────────────────────────────────────────────────────────────────
# 权重构造
# ──────────────────────────────────────────────────────────────────────────────

def make_weights(mode, node_ids, byz_ids, scores):
    """构造初始权重映射。

    contribution 档：w = 1.0 + 0.5 * (s / max(s))，与 run_consensus_repeated.py:48 口径一致。
    scores 为空时调用方须先 fail-closed（见 load_scores）。
    """
    w = {}
    if mode == "uniform":
        for nid in node_ids:
            w[nid] = 1.0
    elif mode == "legacy":
        # ⚠ 实验假象对照组：此处读取 byz_ids 即"预知坏节点身份"，数值保持不变
        for nid in node_ids:
            if nid in byz_ids:
                w[nid] = 0.2
            else:
                idx = int(nid.split("_")[1])
                w[nid] = 1.0 + 0.3 * (idx % 3)
    elif mode == "contribution":
        if not scores:
            raise ValueError("contribution 档需要真实 bc_scores；未提供时禁止静默回退到合成数据")
        mx = max(scores.values())
        keys = sorted(scores.keys())
        for nid in node_ids:
            i = int(nid.split("_")[1])
            k = keys[i % len(keys)]
            w[nid] = 1.0 + 0.5 * (scores[k] / mx)
    elif mode == "dynamic":
        # 初值由 --dynamic-init 决定；此处返回 uniform，调用方按需覆盖
        for nid in node_ids:
            w[nid] = 1.0
    else:
        raise ValueError(f"未知权重档: {mode}")
    return w


def r_ratio(wmap):
    vals = list(wmap.values())
    mn = min(vals)
    if mn <= 0:
        return float("inf")
    return max(vals) / mn


def honest_weight_share(wmap, node_ids, byz_ids):
    tot = sum(wmap.values())
    if tot <= 0:
        return float("nan")
    return sum(wmap[n] for n in node_ids if n not in byz_ids) / tot


# ──────────────────────────────────────────────────────────────────────────────
# 模拟器
# ──────────────────────────────────────────────────────────────────────────────

def simulate_static(n_nodes, byz_ratio, n_rounds, seed, wmap, adversary_participation=False):
    """静态权重 CW-PBFT（uniform / contribution / legacy 三档共用）。

    adversary_participation: True 时坏节点照常投票（p=1.0）而非省略故障静默。
    """
    random.seed(seed)
    node_ids = [f"node_{i}" for i in range(n_nodes)]
    n_byz = int(n_nodes * byz_ratio)
    byz_ids = set(node_ids[:n_byz])
    engine = CWPBFTConsensus(node_id="node_0", consensus_nodes=node_ids)
    for nid, wv in wmap.items():
        engine.update_weight(nid, wv)
    succ = 0
    for r in range(n_rounds):
        engine.reset()
        engine._state = ConsensusState.IDLE
        silent = set()
        for nid in node_ids:
            if nid in byz_ids:
                if not adversary_participation:
                    silent.add(nid)            # 省略故障：坏节点静默
            else:
                if random.random() < HONEST_MSG_LOSS:
                    silent.add(nid)
        proposer = engine.get_primary(0)
        bh = hashlib.sha256(f"{seed}:{r}".encode()).hexdigest()
        if engine.simulated_consensus(bh, proposer, byzantine_nodes=silent):
            succ += 1
    return succ / n_rounds


def simulate_dynamic(n_nodes, byz_ratio, n_rounds, seed, init_weights=None,
                    adversary_participation=False):
    """路线C：参与率驱动权重展宽 + 纪元冻结 + 钳制（PoC 逻辑逐字继承）。

    adversary_participation: True 时坏节点照常投票（p=1.0），仅诚实方有 5% 丢失；
        用于实测「参与型对手」负面边界（评审必问）。
    返回 (成功率, 终态权重, 逐纪元诚实权重占比列表)。
    """
    random.seed(seed)
    node_ids = [f"node_{i}" for i in range(n_nodes)]
    n_byz = int(n_nodes * byz_ratio)
    byz_ids = set(node_ids[:n_byz])
    engine = CWPBFTConsensus(node_id="node_0", consensus_nodes=node_ids)
    weights = dict(init_weights) if init_weights else {nid: 1.0 for nid in node_ids}
    for nid, w in weights.items():
        engine.update_weight(nid, w)
    part_total = {nid: 0 for nid in node_ids}
    part_rounds = 0
    succ = 0
    epoch_shares = []          # 每个纪元末的诚实方权重占比

    for r in range(n_rounds):
        engine.reset()
        engine._state = ConsensusState.IDLE
        silent = set()
        for nid in node_ids:
            if nid in byz_ids:
                if not adversary_participation:
                    silent.add(nid)            # 省略故障：坏节点静默
            else:
                if random.random() < HONEST_MSG_LOSS:
                    silent.add(nid)
        proposer = engine.get_primary(0)
        bh = hashlib.sha256(f"{seed}:{r}".encode()).hexdigest()
        if engine.simulated_consensus(bh, proposer, byzantine_nodes=silent):
            succ += 1
        part_rounds += 1
        for nid in engine._votes.get('prepare', {}):
            part_total[nid] += 1
        if (r + 1) % EPOCH_ROUNDS == 0 and (r + 1) < n_rounds:
            new_w = {}
            for nid in node_ids:
                p = part_total[nid] / max(part_rounds, 1)
                raw = weights[nid] * (FLOOR + (1 - FLOOR) * p)
                new_w[nid] = max(MIN_W, min(MAX_W, raw))
            m = sum(new_w.values()) / len(new_w)
            weights = {nid: w / m for nid, w in new_w.items()}
            for nid, w in weights.items():
                engine.update_weight(nid, w)
            epoch_shares.append(honest_weight_share(weights, node_ids, byz_ids))
            part_total = {nid: 0 for nid in node_ids}
            part_rounds = 0
    return succ / n_rounds, weights, epoch_shares


def simulate_std(n_nodes, byz_ratio, n_rounds, seed):
    """标准 PBFT 基线（等权重、按节点数 2/3 阈值）"""
    random.seed(seed)
    node_ids = [f"node_{i}" for i in range(n_nodes)]
    n_byz = int(n_nodes * byz_ratio)
    byz_ids = set(node_ids[:n_byz])
    engine = StandardPBFTConsensus(node_id="node_0", consensus_nodes=node_ids)
    succ = 0
    for r in range(n_rounds):
        engine.reset()
        engine._state = ConsensusState.IDLE
        silent = set(byz_ids)
        for nid in node_ids:
            if nid not in byz_ids and random.random() < HONEST_MSG_LOSS:
                silent.add(nid)
        proposer = engine.get_primary(0)
        bh = hashlib.sha256(f"{seed}:{r}".encode()).hexdigest()
        if engine.simulated_consensus(bh, proposer, byzantine_nodes=silent):
            succ += 1
    return succ / n_rounds


# ──────────────────────────────────────────────────────────────────────────────
# 单格运行
# ──────────────────────────────────────────────────────────────────────────────

def run_cell(n_nodes, byz_ratio, n_rounds, scores_by_seed, dynamic_init, modes, per_seed_dir):
    """一格 = (n, byz)：10 seed × 指定权重档。STD 基线每 seed 只算一次，四档共用（配对比较）。"""
    node_ids = [f"node_{i}" for i in range(n_nodes)]
    n_byz = int(n_nodes * byz_ratio)
    byz_ids = set(node_ids[:n_byz])

    # STD 基线（与权重档无关，同 seed 结果完全一致）
    std_rates = [simulate_std(n_nodes, byz_ratio, n_rounds, s) for s in SEEDS]

    # 逐 seed 落盘：让 number_registry 的 two_sample 复算能真正回溯到「文件 + 字段」
    if per_seed_dir:
        per_seed_dir.mkdir(parents=True, exist_ok=True)
        for s, v in zip(SEEDS, std_rates):
            (per_seed_dir / f"n{n_nodes}_b{byz_ratio:.2f}_std_seed{s}.json").write_text(
                json.dumps({"n_nodes": n_nodes, "byzantine_ratio": byz_ratio,
                            "seed": s, "engine": "standard_pbft",
                            "success_rate": v}, ensure_ascii=False, indent=2),
                encoding="utf-8")

    out_rows = []
    for mode in modes:
        cw_rates, r_finals, honest_shares = [], [], []
        for s in SEEDS:
            scores = (scores_by_seed or {}).get(s)
            if mode == "dynamic":
                init = None
                if dynamic_init == "contribution":
                    init = make_weights("contribution", node_ids, byz_ids, scores)
                rate, final_w, _sh = simulate_dynamic(n_nodes, byz_ratio, n_rounds, s, init)
            else:
                wmap = make_weights(mode, node_ids, byz_ids, scores)
                rate = simulate_static(n_nodes, byz_ratio, n_rounds, s, wmap)
                final_w = wmap
            cw_rates.append(rate)
            r_finals.append(r_ratio(final_w))
            honest_shares.append(honest_weight_share(final_w, node_ids, byz_ids))

        # 四档全部落盘：uniform/legacy 同样需要可回溯（uniform 是 R=1 理论退化验证，
        # legacy 是假象对照组，均须带 is_artifact_control 标记供下游识别）
        if per_seed_dir:
            for s, v in zip(SEEDS, cw_rates):
                (per_seed_dir / f"n{n_nodes}_b{byz_ratio:.2f}_{mode}_cw_seed{s}.json").write_text(
                    json.dumps({"n_nodes": n_nodes, "byzantine_ratio": byz_ratio,
                                "seed": s, "engine": "cw_pbft", "weight_mode": mode,
                                "success_rate": v}, ensure_ascii=False, indent=2),
                    encoding="utf-8")

        wt = welch_ttest(cw_rates, std_rates)
        lo, hi, _df = ci95_diff(cw_rates, std_rates)
        cw_mean = mean(cw_rates)
        std_mean = mean(std_rates)
        cw_sd = stdev(cw_rates, ddof=1)
        std_sd = stdev(std_rates, ddof=1)
        # 口径铁律：百分比 ROUND_HALF_UP 2 位小数；Δ = 已舍入两均值之差
        cw_pct = pct2(cw_mean)
        std_pct = pct2(std_mean)
        diff_pct = round(cw_pct - std_pct, 2)
        # 零方差陷阱：任一组方差为 0 时 Welch 分母→0，p 无意义，禁止用于任何结论
        zero_var = (cw_sd == 0.0) or (std_sd == 0.0)
        row = {
            "n_nodes": n_nodes,
            "byzantine_ratio": byz_ratio,
            "weight_mode": mode,
            "n_seeds": len(SEEDS),
            "n_rounds": n_rounds,
            "cw_mean": cw_mean,
            "cw_sd": cw_sd,
            "std_mean": std_mean,
            "std_sd": std_sd,
            "diff_mean": cw_mean - std_mean,
            "cw_rates": cw_rates,
            "std_rates": std_rates,
            "cw_mean_pct": cw_pct,
            "std_mean_pct": std_pct,
            "diff_pct": diff_pct,
            "welch_p": wt["p"],
            "welch_t": wt["t"],
            "welch_df": wt["df"],
            "welch_p_applicable": (not zero_var),
            "zero_variance": zero_var,
            "cohens_d": cohens_d(cw_rates, std_rates),
            "ci95_diff": [lo, hi],
            "R_final_mean": mean(r_finals),
            "R_final_saturated": bool(mean(r_finals) >= MAX_W / MIN_W - 1e-6),
            "honest_weight_share_mean": mean(honest_shares),
            "is_artifact_control": mode == "legacy",
        }
        if mode == "legacy":
            row["warning"] = ARTIFACT_WARNING
        # 结论判定（不做任何抑制：无增益/反转照实标注）
        if row["welch_p_applicable"] and row["welch_p"] < 0.05 and row["diff_mean"] > 0:
            row["verdict"] = "GAIN_SIGNIFICANT"
        elif row["welch_p_applicable"] and row["diff_mean"] < 0 and row["welch_p"] < 0.05:
            row["verdict"] = "REVERSED"
        elif abs(row["diff_mean"]) < 1e-9:
            row["verdict"] = "IDENTICAL"
        elif zero_var and row["diff_mean"] > 0:
            row["verdict"] = "DETERMINISTIC_GAIN"   # 零方差 → 确定性差异，非统计显著性
        elif zero_var and row["diff_mean"] < 0:
            row["verdict"] = "DETERMINISTIC_LOSS"
        else:
            row["verdict"] = "NO_GAIN"
        out_rows.append(row)
    return out_rows


# ──────────────────────────────────────────────────────────────────────────────
# 参与型对手臂（评审必问的负面边界，必须实测）
# ──────────────────────────────────────────────────────────────────────────────

def run_adversary_arm(n_nodes, byz_ratio, n_rounds, per_seed_dir=None):
    """「参与型对手」：坏节点照常投票（p=1.0），仅诚实方有 5% 丢失。

    与省略故障（omission，坏节点静默）对照，实测路线C 展宽机制是否会塌缩。
    返回逐 seed 的 (CW动态成功率, STD同场景成功率, 逐纪元诚实权重占比)。

    ``per_seed_dir`` 非空时逐 seed 落盘 ``success_rate``（供 number_registry 的
    ``two_sample`` 复算回溯到「文件 + 字段」，与 ``run_cell`` 同约定）。
    """
    cw_rates, std_rates = [], []
    epoch_share_per_seed = []
    cw_traj_per_seed = []
    if per_seed_dir:
        per_seed_dir.mkdir(parents=True, exist_ok=True)
    for s in SEEDS:
        rate, _w, shares = simulate_dynamic(
            n_nodes, byz_ratio, n_rounds, s, None, adversary_participation=True)
        cw_rates.append(rate)
        epoch_share_per_seed.append(shares)
        # 同场景（坏节点参与、诚实 5% 丢失）的标准 PBFT 基线 —— 公平对照
        std_rate = simulate_static(
            n_nodes, byz_ratio, n_rounds, s, {f"node_{i}": 1.0 for i in range(n_nodes)},
            adversary_participation=True)
        std_rates.append(std_rate)
        if per_seed_dir:
            first_below = _first_below(shares, 2.0 / 3.0)
            cw_traj_per_seed.append({"seed": s, "epoch_shares": [
                None if v is None else round(v, 6) for v in shares]})
            common = {"n_nodes": n_nodes, "byzantine_ratio": byz_ratio, "seed": s,
                      "n_rounds": n_rounds, "adversary_participation": True,
                      "honest_msg_loss": HONEST_MSG_LOSS,
                      "epoch_honest_weight_share_traj": [
                          None if v is None else round(v, 6) for v in shares],
                      "first_below_2over3_epoch": first_below}
            (per_seed_dir / f"n{n_nodes}_b{byz_ratio:.2f}_adversary_cw_seed{s}.json").write_text(
                json.dumps({**common, "engine": "cw_pbft", "weight_mode": "dynamic",
                            "success_rate": rate, "final_honest_weight_share":
                                (round(shares[-1], 6) if shares else None)},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            (per_seed_dir / f"n{n_nodes}_b{byz_ratio:.2f}_adversary_std_seed{s}.json").write_text(
                json.dumps({**common, "engine": "standard_pbft", "success_rate": std_rate},
                           ensure_ascii=False, indent=2), encoding="utf-8")
    # 逐纪元诚实权重占比的轨迹（跨 seed 均值；不足一个纪元则留空）
    max_epochs = max((len(x) for x in epoch_share_per_seed), default=0)
    epoch_traj = []
    for e in range(max_epochs):
        col = [x[e] for x in epoch_share_per_seed if e < len(x)]
        epoch_traj.append(mean(col) if col else None)
    return {
        "n_nodes": n_nodes,
        "byzantine_ratio": byz_ratio,
        "n_seeds": len(SEEDS),
        "n_rounds": n_rounds,
        "cw_mean": mean(cw_rates),
        "cw_mean_pct": pct2(mean(cw_rates)),
        "cw_sd": stdev(cw_rates, ddof=1),
        "std_same_scenario_mean": mean(std_rates),
        "std_same_scenario_pct": pct2(mean(std_rates)),
        "std_same_scenario_sd": stdev(std_rates, ddof=1),
        "diff_pct": round(pct2(mean(cw_rates)) - pct2(mean(std_rates)), 2),
        "cw_rates": cw_rates,
        "std_same_scenario_rates": std_rates,
        "epoch_honest_weight_share_traj": epoch_traj,
        # 诚实方权重占比首次跌破 2/3 的纪元（未跌破则为 None）
        "first_below_2over3_epoch": _first_below(epoch_traj, 2.0 / 3.0),
        # 首/末/平台期（末 10 纪元均值）诚实权重占比 + 非空纪元数：
        # 供 number_registry 的 declared 直接引用（避免文档二次手抄漂移）
        "epoch_honest_weight_share_first": _first_not_none(epoch_traj),
        "epoch_honest_weight_share_last": _last_not_none(epoch_traj),
        "epoch_honest_weight_share_plateau_mean": _plateau_mean(epoch_traj, 10),
        "n_epochs": sum(1 for v in epoch_traj if v is not None),
        "per_seed_epoch_traj": cw_traj_per_seed,
    }


def _first_not_none(seq):
    return next((v for v in seq if v is not None), None)


def _last_not_none(seq):
    return next((v for v in reversed(seq) if v is not None), None)


def _plateau_mean(seq, tail_n):
    col = [v for v in seq[-tail_n:] if v is not None]
    return mean(col) if col else None


def _first_below(traj, thr):
    for i, v in enumerate(traj, start=1):
        if v is not None and v < thr:
            return i
    return None



# ──────────────────────────────────────────────────────────────────────────────
# 真实贡献度分数加载
# ──────────────────────────────────────────────────────────────────────────────

def load_scores(index_path, n_nodes, contrib_source):
    """从 e2e 产出的索引 JSON 加载 (n → seed → scores)。

    contrib_source:
        normalized_scores  → 原始 bc_scores（由调用方归一化，口径同既有 contribution 档）
        production_weights → 生产链路 cw_pbft 中真实落地的权重（w=1.0+0.5*weighted_score）
    """
    if not index_path:
        return None
    p = Path(index_path)
    if not p.exists():
        raise SystemExit(f"[FAIL-CLOSED] 贡献度索引不存在: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    runs = data["runs_by_n"].get(str(n_nodes))
    if not runs:
        raise SystemExit(f"[FAIL-CLOSED] 索引中缺少 n={n_nodes} 的真实训练分数: {p}")
    out = {}
    for s in SEEDS:
        rec = runs.get(str(s))
        if rec is None:
            raise SystemExit(f"[FAIL-CLOSED] 索引缺少 n={n_nodes} seed={s} 的真实训练分数")
        out[s] = rec["production_weights"] if contrib_source == "production_weights" else rec["bc_scores"]
    return out


# ──────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2000)
    ap.add_argument("--nodes", default="4,10,16")
    ap.add_argument("--ratios", default="0.33,0.40")
    ap.add_argument("--modes", default="uniform,contribution,legacy,dynamic")
    ap.add_argument("--dynamic-init", choices=["uniform", "contribution"], default="uniform")
    ap.add_argument("--contrib-source", choices=["normalized_scores", "production_weights"],
                    default="normalized_scores")
    ap.add_argument("--scores-index", default=None,
                    help="e2e 产出的 bc_scores_index.json；contribution/dynamic(contribution-init) 档必需")
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-seed-dir", default=None,
                    help="逐 seed 落盘目录（供 number_registry two_sample 复算）；"
                         "默认 results/consensus_comparison/weight_broadening_full/")
    ap.add_argument("--no-per-seed", action="store_true", help="不落逐 seed 文件")
    ap.add_argument("--adversary", action="store_true",
                    help="只跑『参与型对手』臂（n=10/33%% 与 n=16/33%%），实测负面边界，单独输出报告")
    ap.add_argument("--smoke", action="store_true", help="冒烟：1 seed / 200 轮 / 仅 n=4")
    a = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("blockchain.consensus.cw_pbft").setLevel(logging.ERROR)

    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    need_scores = ("contribution" in modes) or (a.dynamic_init == "contribution")

    if a.smoke:
        globals()["SEEDS"] = [42]
        nodes, ratios, rounds = [4], [0.33], 200
    else:
        nodes = [int(x) for x in a.nodes.split(",")]
        ratios = [float(x) for x in a.ratios.split(",")]
        rounds = a.rounds

    if a.no_per_seed:
        per_seed_dir = None
    elif a.per_seed_dir:
        per_seed_dir = Path(a.per_seed_dir)
    else:
        per_seed_dir = _REPO_ROOT / "results" / "consensus_comparison" / "weight_broadening_full"

    results = []
    t0 = time.time()

    # ── 参与型对手臂：独立报告 ──
    if a.adversary:
        if a.no_per_seed:
            adv_dir = None
        elif a.per_seed_dir:
            adv_dir = Path(a.per_seed_dir)
        else:
            adv_dir = (_REPO_ROOT / "results" / "consensus_comparison"
                       / "weight_broadening_adversary")
        adv = [run_adversary_arm(n, br, rounds if not a.smoke else 200, adv_dir)
               for (n, br) in [(10, 0.33), (16, 0.33)]]
        adv_out = {
            "meta": {
                "script": "scripts/legacy/experiments/run_weight_broadening_full.py --adversary",
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "seeds": SEEDS, "n_rounds": (200 if a.smoke else a.rounds),
                "epoch_rounds": EPOCH_ROUNDS, "floor": FLOOR, "min_w": MIN_W, "max_w": MAX_W,
                "honest_msg_loss": HONEST_MSG_LOSS,
                "per_seed_dir": (str(adv_dir.relative_to(_REPO_ROOT))
                                 if adv_dir else None),
                "model": "adversary_participation: 坏节点照常投票(p=1.0)，仅诚实方 5% 丢失",
                "model_limitation": "本模拟器只建模『省略故障下的配额可达性』（成功=非静默权重达到阈值），"
                                    "**不建模矛盾投票/equivocation**：拜占庭节点的投票计入有效参与。"
                                    "故本臂只能证明『增益是否依赖坏节点省略』，不能充当安全界证据。",
                "note": "对照同场景标准 PBFT（坏节点同样参与）。用于证明 98.6% 增益是"
                        "『省略故障下的活性恢复』，而非对任意 adversary 的安全界。",
            },
            "results": adv,
        }
        op = (_REPO_ROOT / "results" / "consensus_comparison"
              / "weight_broadening_adversary_report.json")
        with open(op, "w", encoding="utf-8") as f:
            json.dump(adv_out, f, indent=2, ensure_ascii=False)
        for r in adv:
            print(f"  n={r['n_nodes']:>3} byz={r['byzantine_ratio']*100:.0f}% | "
                  f"CW(参与型对手) {r['cw_mean_pct']}%  STD(同场景) {r['std_same_scenario_pct']}%  "
                  f"Δ {r['diff_pct']:+.2f}pp  "
                  f"诚实占比 首{r['epoch_honest_weight_share_first']:.4f}"
                  f"→末{r['epoch_honest_weight_share_last']:.4f}"
                  f"(平台{r['epoch_honest_weight_share_plateau_mean']:.4f})  "
                  f"跌破 2/3 于第 {r['first_below_2over3_epoch']} 纪元")
        print(f"\n[报告写入] {op}")
        if adv_dir:
            print(f"[逐 seed 写入] {adv_dir.relative_to(_REPO_ROOT)}"
                  f"（{len(list(adv_dir.glob('*_adversary_*_seed*.json')))} 个文件）")
        return

    for n in nodes:
        scores_by_seed = load_scores(a.scores_index, n, a.contrib_source) if need_scores else None
        for br in ratios:
            rows = run_cell(n, br, rounds, scores_by_seed, a.dynamic_init, modes, per_seed_dir)
            results.extend(rows)
            for r in rows:
                print(f"  n={n:>3} byz={br*100:>3.0f}% mode={r['weight_mode']:>12} | "
                      f"CW {r['cw_mean']*100:>5.1f}±{r['cw_sd']*100:.1f}%  "
                      f"STD {r['std_mean']*100:>5.1f}±{r['std_sd']*100:.1f}%  "
                      f"Δ {r['diff_mean']*100:+6.1f}%  p={r['welch_p']:.2e}  "
                      f"d={r['cohens_d']:+.2f}  R={r['R_final_mean']:.3f}  "
                      f"honest_w={r['honest_weight_share_mean']*100:.1f}%  {r['verdict']}")

    out = {
        "meta": {
            "script": "scripts/legacy/experiments/run_weight_broadening_full.py",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seeds": SEEDS,
            "n_rounds": rounds,
            "epoch_rounds": EPOCH_ROUNDS,
            "floor": FLOOR, "min_w": MIN_W, "max_w": MAX_W,
            "honest_msg_loss": HONEST_MSG_LOSS,
            "dynamic_init": a.dynamic_init,
            "contrib_source": a.contrib_source,
            "sd_ddof": 1,
            "cohens_d_ddof": 1,
            "stats_backend": "scripts/assurance_common.py (welch_ttest / cohens_d / ci95_diff, stdlib only)",
            "scores_index": a.scores_index,
            "per_seed_dir": str(per_seed_dir) if per_seed_dir else None,
            "smoke": bool(a.smoke),
            "elapsed_sec": round(time.time() - t0, 1),
            "mechanism": "participation-driven decay, epoch-frozen(50), clipped[0.1,1.5]",
            "poc_demotion": "5-seed 旧值(weight_broadening_poc_report.json) 仅作溯源档，对外一律引用本 10-seed 全量报告",
            "r_final_saturation_note": "R_final 恒≈15 = MAX_W/MIN_W(1.5/0.1)，说明机制已饱和到权重上下界；"
                                       "连续贡献度被退化为高/低二值区分（评审必问，已如实披露）",
            "zero_variance_note": "n=10/40% 与 n=16/40% 两格 STD 恒为 0（成功率为确定值），Welch p 分母→0 无意义；"
                                 "该两格改用『确定性差异/比例差』表述，p 值不用于任何结论",
            "gain_nature": "本质为『节点计数→权重计数』的活性改进，非安全界突破",
            "rounding": "百分比 ROUND_HALF_UP 取 2 位小数；Δ = 已舍入两均值之差（可手算复核）",
        },
        "results": results,
    }
    # ⚠ 破坏性副作用护栏：--smoke 只跑 1 seed / 200 轮 / n=4 的 4 行结果，
    # 若写入全量报告同名文件会静默把 24 行全量证据替换成冒烟数据（2026-09-20 实测踩坑）。
    # 冒烟默认改写到 _smoke 后缀文件；只有显式给出 --out 才允许覆盖指定路径。
    if a.out:
        op = Path(a.out)
    elif a.smoke:
        op = (_REPO_ROOT / "results" / "consensus_comparison"
              / "weight_broadening_full_report__smoke.json")
    else:
        op = (_REPO_ROOT / "results" / "consensus_comparison"
              / "weight_broadening_full_report.json")
    op.parent.mkdir(parents=True, exist_ok=True)
    with open(op, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n[报告写入] {op}  ({len(results)} 行, {out['meta']['elapsed_sec']}s)")


if __name__ == "__main__":
    main()
