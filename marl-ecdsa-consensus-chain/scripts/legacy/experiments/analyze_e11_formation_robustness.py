#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E11 — 形成机制跨算法稳健性分析。

验证旗舰结论「BC 是协作形成加速器（formation accelerator），而非稳态性能提升器」是否跨底层算法稳健。
数据：E1 已存在的 IQL/VDN/QMIX × bc/pure × 30 种子（3000 回合），无需新跑服务器。

两个互补检验：
  (A) 分段 Welch：把 3000 回合按 WINDOWS 分段，逐段做 bc vs pure 的 Welch（env_reward 与 cooperation_rate），
      复刻 NR-27 的「倒 U」时序图，并扩展到 VDN/QMIX。
  (B) 加速器直接检验（每算法内 paired 对比）：
       formation_adv_i = bc[500:2000].mean() - pure[500:2000].mean()   （形成期 BC 优势）
       conv_adv_i     = bc[2000:3000].mean() - pure[2000:3000].mean()  （收敛期 BC 优势）
       Welch(formation_adv, conv_adv)：若显著为正 → BC 优势集中在形成期、收敛后衰减 = 加速器证据。

口径铁律：p 值一律 scipy t 分布（与 number_registry 统一）；env_reward 为主指标（不含 BC 激励）。
"""
import argparse
import glob
import json
import math
import os

import numpy as np
from scipy import stats as sp

WINDOWS = [(0, 100), (100, 500), (500, 1000), (1000, 2000), (2000, 3000)]
FORM_LO, FORM_HI = 500, 2000
CONV_LO, CONV_HI = 2000, 3000
ALGOS = ("iql", "vdn", "qmix")


def load_series(pattern, key, data_dir):
    files = sorted(glob.glob(os.path.join(data_dir, pattern)))
    arr = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        a = d.get(key)
        if a and len(a) > 0:
            arr.append(np.array(a, dtype=float))
    return np.array(arr)  # (n_seed, n_ep)


def welch(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    na, nb = len(a), len(b)
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(ddof=1), b.var(ddof=1)
    diff = ma - mb
    se = math.sqrt(va / na + vb / nb)
    t = diff / se if se > 0 else 0.0
    df_num = (va / na + vb / nb) ** 2
    df_den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = df_num / df_den if df_den > 0 else (na + nb - 2)
    p = 2 * (1 - sp.t.cdf(abs(t), df))
    pooled_sd = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)) if (na + nb - 2) > 0 else 0.0
    d = diff / pooled_sd if pooled_sd > 0 else 0.0
    return float(t), float(p), float(d)


def windowed_table(bc, pure, key):
    rows = []
    for lo, hi in WINDOWS:
        a_win = bc[:, lo:hi].mean(axis=1)   # per-seed window mean
        b_win = pure[:, lo:hi].mean(axis=1)
        t, p, d = welch(a_win, b_win)
        rows.append({
            "window": f"ep{lo}-{hi}",
            "bc_mean": round(float(a_win.mean()), 4),
            "pure_mean": round(float(b_win.mean()), 4),
            "delta": round(float(a_win.mean() - b_win.mean()), 4),
            "welch_p": round(p, 5),
            "cohen_d": round(d, 4),
            "n_bc": int(len(a_win)),
            "n_pure": int(len(b_win)),
        })
    return rows


def accelerator_test(bc, pure):
    form_adv = (bc[:, FORM_LO:FORM_HI].mean(axis=1) - pure[:, FORM_LO:FORM_HI].mean(axis=1))
    conv_adv = (bc[:, CONV_LO:CONV_HI].mean(axis=1) - pure[:, CONV_LO:CONV_HI].mean(axis=1))
    t, p, d = welch(form_adv, conv_adv)
    return {
        "formation_adv_mean": round(float(form_adv.mean()), 4),
        "conv_adv_mean": round(float(conv_adv.mean()), 4),
        "delta_form_minus_conv": round(float(form_adv.mean() - conv_adv.mean()), 4),
        "welch_p": round(p, 5),
        "cohen_d": round(d, 4),
        "n": int(len(form_adv)),
    }


def endpoint(bc, pure):
    return {
        "bc_full_mean": round(float(bc.mean()), 4),
        "pure_full_mean": round(float(pure.mean()), 4),
        "bc_last50_mean": round(float(bc[:, -50:].mean()), 4),
        "pure_last50_mean": round(float(pure[:, -50:].mean()), 4),
        "full_delta": round(float(bc.mean() - pure.mean()), 4),
        "last50_delta": round(float(bc[:, -50:].mean() - pure[:, -50:].mean()), 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/champion_20260919")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    report = {"meta": {"windows": [f"ep{lo}-{hi}" for lo, hi in WINDOWS],
                       "formation_phase": f"ep{FORM_LO}-{FORM_HI}",
                       "convergence_phase": f"ep{CONV_LO}-{CONV_HI}"},
              "algorithms": {}}

    for algo in ALGOS:
        bc_env = load_series(f"e1_{algo}_bc_marl_seed*.json", "env_rewards", a.dir)
        pure_env = load_series(f"e1_{algo}_pure_marl_seed*.json", "env_rewards", a.dir)
        bc_coop = load_series(f"e1_{algo}_bc_marl_seed*.json", "cooperation_rates", a.dir)
        pure_coop = load_series(f"e1_{algo}_pure_marl_seed*.json", "cooperation_rates", a.dir)
        if bc_env.shape[0] == 0 or pure_env.shape[0] == 0:
            print(f"[skip] {algo}: missing data")
            continue
        report["algorithms"][algo] = {
            "n_bc": int(bc_env.shape[0]),
            "n_pure": int(pure_env.shape[0]),
            "windows_env": windowed_table(bc_env, pure_env, "env_rewards"),
            "windows_coop": windowed_table(bc_coop, pure_coop, "cooperation_rates"),
            "accelerator_env": accelerator_test(bc_env, pure_env),
            "accelerator_coop": accelerator_test(bc_coop, pure_coop),
            "endpoint_env": endpoint(bc_env, pure_env),
            "endpoint_coop": endpoint(bc_coop, pure_coop),
        }
        print(f"\n=== {algo.upper()} (n_bc={bc_env.shape[0]}, n_pure={pure_env.shape[0]}) ===")
        print("  env_reward 分段 Δ / p / d:")
        for r in report["algorithms"][algo]["windows_env"]:
            flag = " ***" if r["welch_p"] < 0.05 else (" *" if r["welch_p"] < 0.1 else "")
            print(f"    {r['window']:>11}: Δ={r['delta']:+.4f} p={r['welch_p']:.4f} d={r['cohen_d']:+.4f}{flag}")
        ae = report["algorithms"][algo]["accelerator_env"]
        print(f"  加速器检验(env): 形成期优势={ae['formation_adv_mean']:+.4f} 收敛期优势={ae['conv_adv_mean']:+.4f} "
              f"Δ={ae['delta_form_minus_conv']:+.4f} p={ae['welch_p']:.4f} d={ae['cohen_d']:+.4f}")

    out = a.out or os.path.join(a.dir, "e11_formation_robustness_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n已写出: {out}")

    # markdown summary
    md = ["# E11 — 形成机制跨算法稳健性", "",
          "检验：BC 的边际优势是否集中在形成期（ep500–2000）、收敛后（ep2000–3000）衰减。",
          "", "| 算法 | 形成期 env Δ | 收敛期 env Δ | 加速器 Δ(形−收) | p | d |",
          "|------|------|------|------|------|------|"]
    for algo in ALGOS:
        if algo not in report["algorithms"]:
            continue
        r = report["algorithms"][algo]
        we = {w["window"]: w for w in r["windows_env"]}
        ae = r["accelerator_env"]
        md.append(f"| {algo.upper()} | {we['ep500-1000']['delta']:+.4f} / {we['ep1000-2000']['delta']:+.4f} "
                  f"| {we['ep2000-3000']['delta']:+.4f} | {ae['delta_form_minus_conv']:+.4f} | {ae['welch_p']:.4f} | {ae['cohen_d']:+.4f} |")
    md.append("")
    md.append("* 加速器 Δ 显著为正 ⇒ BC 优势集中在形成期、收敛后衰减（支持「形成加速器」解读）。")
    md.append("* env_reward 为主指标（不含 BC 激励）；p 值 scipy t 分布。")
    with open(out.replace(".json", ".md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"已写出: {out.replace('.json', '.md')}")


if __name__ == "__main__":
    main()
