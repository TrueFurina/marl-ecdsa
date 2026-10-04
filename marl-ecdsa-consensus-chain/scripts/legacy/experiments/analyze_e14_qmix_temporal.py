#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E14 QMIX 时间维度确认（n=20 同批受控，λ=0.1，3000 回合）。

目的：把 NR-63（QMIX 同批末50 env_reward 显著正增益 Δ=+5.83, p=0.035）做时间维度展开，
检验 NR-54 的「BC 对价值分解类算法的增益随训练单调放大」假设是否在受控同批数据上复现。

口径纪律（与主 registry 一致）：
- 主指标 env_reward（不含 BC 激励）；统一 scipy Welch t 检验（与 verify_numbers.py 同口径）。
- 分段：early[0:1000], mid[1000:2000], late[2000:3000]；另给 formation[500:2000] vs convergence[2000:3000]。
- 仅做描述 + Welch 显著性，不跨配置混比。
- 本脚本只读数据，产出独立报告，不直接写 number_registry.json（登记由主会话统一执行）。
"""
import json
import glob
import os
import statistics as st
from scipy import stats as sps

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(BASE, "..", "..", ".."))
DISPATCH = os.path.join(REPO, "results", "dispatch_20260921")


def _load(tag, algo):
    fs = sorted(glob.glob(os.path.join(DISPATCH, f"{tag}_{algo}_seed*.json")))
    return [json.load(open(f, encoding="utf-8")) for f in fs]


def _welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    t, p = sps.ttest_ind(a, b, equal_var=False)
    return {"t": round(t, 4), "p": round(p, 5)}


def _cohens(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    va, vb = st.variance(a), st.variance(b)
    sp = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
    sp = sp ** 0.5
    if sp == 0:
        return None
    return round((st.mean(a) - st.mean(b)) / sp, 4)


def main():
    algo = "qmix"
    bc = _load("e14", algo)
    pu = _load("e14pure", algo)
    print(f"QMIX E14: bc n={len(bc)} pure n={len(pu)}")

    # 取 env_rewards 与 cooperation_rates 序列
    bc_env = [d["env_rewards"] for d in bc]
    pu_env = [d["env_rewards"] for d in pu]
    bc_coop = [d["cooperation_rates"] for d in bc]
    pu_coop = [d["cooperation_rates"] for d in pu]

    windows = {
        "early[0:1000]": (0, 1000),
        "mid[1000:2000]": (1000, 2000),
        "late[2000:3000]": (2000, 3000),
        "formation[500:2000]": (500, 2000),
        "convergence[2000:3000]": (2000, 3000),
    }

    out = {"algo": algo, "n_bc": len(bc), "n_pure": len(pu), "windows_env": [], "windows_coop": []}

    for name, (lo, hi) in windows.items():
        bc_w = [st.mean(s[lo:hi]) for s in bc_env]
        pu_w = [st.mean(s[lo:hi]) for s in pu_env]
        w = _welch(bc_w, pu_w)
        d = _cohens(bc_w, pu_w)
        rec = {
            "window": name,
            "bc_mean": round(st.mean(bc_w), 4),
            "pure_mean": round(st.mean(pu_w), 4),
            "delta": round(st.mean(bc_w) - st.mean(pu_w), 4),
            "welch_p": (w["p"] if w else None),
            "cohens_d": d,
        }
        out["windows_env"].append(rec)
        print(f"  env {name:22s} Δ={rec['delta']:+8.4f}  p={rec['welch_p']}  d={rec['cohens_d']}")

    for name, (lo, hi) in windows.items():
        bc_w = [st.mean(s[lo:hi]) for s in bc_coop]
        pu_w = [st.mean(s[lo:hi]) for s in pu_coop]
        w = _welch(bc_w, pu_w)
        d = _cohens(bc_w, pu_w)
        rec = {
            "window": name,
            "bc_mean": round(st.mean(bc_w), 4),
            "pure_mean": round(st.mean(pu_w), 4),
            "delta": round(st.mean(bc_w) - st.mean(pu_w), 4),
            "welch_p": (w["p"] if w else None),
            "cohens_d": d,
        }
        out["windows_coop"].append(rec)
        print(f"  coop {name:22s} Δ={rec['delta']:+8.4f}  p={rec['welch_p']}  d={rec['cohens_d']}")

    # endpoint 末50（与 NR-63 对照）
    bc_last50 = [d["summary"]["avg_env_reward_last_50"] for d in bc]
    pu_last50 = [d["summary"]["avg_env_reward_last_50"] for d in pu]
    w = _welch(bc_last50, pu_last50)
    out["endpoint_env_last50"] = {
        "bc_mean": round(st.mean(bc_last50), 4),
        "pure_mean": round(st.mean(pu_last50), 4),
        "delta": round(st.mean(bc_last50) - st.mean(pu_last50), 4),
        "welch_p": (w["p"] if w else None),
        "cohens_d": _cohens(bc_last50, pu_last50),
    }
    print("\n  endpoint 末50 env:",
          json.dumps(out["endpoint_env_last50"], ensure_ascii=False))

    # 单调放大假设：late_delta > early_delta 且 late 显著 / early 不显著
    we = {r["window"]: r for r in out["windows_env"]}
    monotonic = (we["late[2000:3000]"]["delta"] > we["early[0:1000]"]["delta"]
                 and (we["late[2000:3000]"]["welch_p"] or 1) < 0.05
                 and (we["early[0:1000]"]["welch_p"] or 0) >= 0.05)
    out["hypothesis_monotonic_growth"] = bool(monotonic)
    print(f"\n  [假设] BC 增益随训练单调放大（late>early 且 late 显著/early 不显著）: {monotonic}")

    op = os.path.join(DISPATCH, "e14_qmix_temporal_report.json")
    with open(op, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n[saved] {op}")


if __name__ == "__main__":
    main()
