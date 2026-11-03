#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试数据瘦身打包器（Slim Test-Data Packer）
=============================================
目的：把本地 results/ 下的**完整训练 JSON**（含逐回合曲线，单文件约 1MB）
     瘦身为**仅保留 config + summary** 的版本，写入提交包 other/测试数据/。

为什么需要：NR-86/87/116/118/129 等条目只读取 `summary.*` 标量字段，
评审复现同样只需 summary；逐回合数组占了 99% 体积（env_diversity 61 个
json 合计 58MB），全量进包会让 other.zip 失控。

保留字段：comparison_note / config / summary（复现 verify_numbers 的全部依据）
丢弃字段：episode_rewards / env_rewards / cooperation_rates / losses /
          betrayal_rates / bc_scores_history / bc_scores_final 等逐回合数组

用法：
    python scripts/pack_slim_testdata.py --dry-run   # 只看会写什么、多大
    python scripts/pack_slim_testdata.py --apply     # 实际写入
"""
import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SRC = BASE / "marl-ecdsa-consensus-chain" / "results"
DST = BASE / "MARL-ECDSA_共识链_提交包" / "other" / "测试数据"

KEEP_TOP = {"comparison_note", "config", "summary"}

# 目录 → 处理的 json 名模式（只处理 NR 引用到的）
TARGETS = [
    ("env_diversity", "moving*.json"),
    ("env_diversity_moving5_n20", "moving*.json"),
    ("e31_main_n101", "*.json"),
    ("e18_scale_w5x5", "*.json"),
    ("e20_qmix_w5x5", "*.json"),
]

_SCALAR = (int, float, str, bool, type(None))


def _keep_scalars(obj, depth=0):
    """递归保留标量；丢弃 list 与大 dict 内的数组。

    兼容两种结构：
      - 嵌套式（env_diversity / e31 / moving5）：comparison_note / config / summary
      - 扁平式（e18 / e20）：顶层直接是 avg_env_reward_last_50 等标量
    逐回合数组（episode_rewards / losses / cooperation_rates ...）一律丢弃。
    """
    out = {}
    for k, v in obj.items():
        if isinstance(v, _SCALAR):
            out[k] = v
        elif isinstance(v, dict) and depth < 3:
            sub = _keep_scalars(v, depth + 1)
            if sub:
                out[k] = sub
        # list 一律丢（逐回合曲线都在这里）
    return out


def slim(d: dict) -> dict:
    """优先保留复现所需 key；其余标量也保留（兼容扁平结构）。"""
    base = {k: v for k, v in d.items() if k in KEEP_TOP}
    extra = _keep_scalars({k: v for k, v in d.items() if k not in KEEP_TOP})
    # 合并：KEEP_TOP 内的标量子集 + 顶层其他标量
    out = _keep_scalars(base)
    for k, v in extra.items():
        out.setdefault(k, v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        print("请指定 --dry-run 或 --apply")
        return 1

    total_src = total_dst = 0
    n_files = 0
    plan = []
    for sub, pattern in TARGETS:
        src_dir = SRC / sub
        if not src_dir.is_dir():
            print(f"[SKIP] 本地无目录: {sub}")
            continue
        dst_dir = DST / sub
        for f in sorted(src_dir.glob(pattern)):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[WARN] 读取失败 {f.name}: {e}")
                continue
            s = slim(d)
            payload = json.dumps(s, ensure_ascii=False)
            src_sz = f.stat().st_size
            dst_sz = len(payload.encode("utf-8"))
            total_src += src_sz
            total_dst += dst_sz
            n_files += 1
            plan.append((sub, f.name, src_sz, dst_sz, payload))
            if not args.apply:
                continue
            dst_dir.mkdir(parents=True, exist_ok=True)
            (dst_dir / f.name).write_text(payload, encoding="utf-8")

    mode = "DRY-RUN" if not args.apply else "APPLIED"
    print(f"=== [{mode}] 瘦身打包计划 ===")
    print(f"  目录: {len(TARGETS)} 个 | 文件: {n_files} 个")
    print(f"  原始合计: {total_src/1024/1024:.1f} MB")
    print(f"  瘦身合计: {total_dst/1024/1024:.2f} MB  "
          f"(压缩至 {total_dst/max(1,total_src)*100:.1f}%)")
    print()
    for sub, name, ss, ds, _ in plan[:5]:
        print(f"    {sub}/{name}: {ss/1024:.0f}KB → {ds/1024:.1f}KB")
    if len(plan) > 5:
        print(f"    ... 另 {len(plan)-5} 个")
    if args.apply:
        print()
        print(f"✅ 已写入: {DST}")
        print("  复现依据 summary.* 已保留；verify_numbers 可正常复算。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
