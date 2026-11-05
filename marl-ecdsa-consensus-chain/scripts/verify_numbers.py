#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_numbers.py —— 注册表驱动的数字复算器（P0-1）。

从 ``results/`` 原始 JSON 按 glob+field 复算 mean/SD/Welch p/Cohen d/95%CI/
提升率/检验力，逐条与 ``number_registry.json`` 的 ``declared`` 比对；并校验
repo 与 backup 双数据源一致性。**绝不粉饰**：注册表被改坏即 FAIL（见自证变异）。

用法::

    python -X utf8 scripts/verify_numbers.py \\
        --registry ../deliverables/number_registry.json \\
        --data-root results \\
        --mirror ../backup/pkg_old_src_20260917/results \\
        [--only NR-1,NR-3] [--strict] [--check-mirror] [--overwrite] \\
        [--self-test]

退出码（架构 §4.2）::

    0  全部非 PENDING/PLANNED 条目 PASS，且无 FAIL / UNVERIFIED（PENDING 不阻断）
    1  至少一条 FAIL（复算值≠声明值、n 不符、**或该条复算抛异常**）；或至少一条
       UNVERIFIED（登记声称已核验但 ``declared`` 为空 —— 零断言的 PASS 不算通过）
    2  用法 / IO / 注册表 schema 错误
    3  数据文件缺失（data-root 不可读 / 条目所需结果文件一个都没有）
    4  --strict 下存在 PENDING/PLANNED 条目

设计约束：被 import 时零副作用；所有 IO 均在 ``main()`` 之后。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 同目录共享库（脚本既可 `python scripts/x.py` 也可 `-m scripts.x` 运行）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import assurance_common as ac  # noqa: E402

logger = ac.get_logger("verify_numbers")


# --------------------------------------------------------------------------- #
# 取值 / 复算
# --------------------------------------------------------------------------- #
class SourceReadError(RuntimeError):
    """取数失败（文件读不出 / 字段取不到 / 取到的不是数）。

    为什么要专门一个异常类型：``_collect_source`` 里 ``ac.extract_field`` 会抛
    ``KeyError``、``float(v)`` 对 ``None`` 抛 ``TypeError``、``load_json`` 对半截
    JSON 抛 ``JSONDecodeError`` —— 这些都不是"数据缺失"，但都不是 ``OSError``，
    于是旧 ``main()`` 的 ``except (FileNotFoundError, ..., OSError)`` 一个都接不住：
    **整份报告消失**，读者只看到一段 traceback（实测见 ``_crash_reason``）。
    现在把每一处取值失败都包成带文件名与字段名的一句话，由 ``main()`` 的单条
    隔离分支判该条 FAIL，其余条目照常校验。
    """


def _source_patterns(src: Dict[str, Any]) -> List[str]:
    """取数模式：``globs``（多个，取并集）优先，否则单个 ``glob``。

    多 glob 是必要的：同一实验臂可能跨批次落盘（例：60 种子基线的前 30 个在
    ``e8_budget500_bc_marl_seed*``、后 30 个在 ``e9_b500_baseline_seed*``），
    只写一个 glob 会静默少算一半样本。
    """
    if src.get("globs"):
        return list(src["globs"])
    return [src["glob"]] if src.get("glob") else []


def _collect_source(data_root: Path, src: Dict[str, Any]) -> Tuple[List[Path], List[float]]:
    """按 glob/globs 读文件、抽取字段；支持 ``slice`` 时间窗，逐文件取均值。

    ``slice = {"start": int, "end": int}`` 作用于列表型字段（如 ``env_rewards``），
    先按回合窗切片再取均值——用于时间维度的分段统计（如 NR-27 的 ep500–1000 段）。
    """
    files: List[Path] = []
    for pat in _source_patterns(src):
        files.extend(ac.resolve_glob(data_root, pat))
    uniq: List[Path] = []
    seen: set[str] = set()
    for f in sorted(files):
        key = str(f)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    files = uniq

    field = src["field"]
    sl = src.get("slice")
    vals: List[float] = []
    for f in files:
        try:
            data = ac.load_json(f)
            v = ac.extract_field(data, field)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise SourceReadError(
                f"{f.name}: 字段 {field!r} 取不到（{exc.__class__.__name__}: {exc}）"
            ) from exc
        if isinstance(v, (list, tuple)):
            seq = list(v)
            if sl:
                seq = seq[int(sl["start"]):int(sl["end"])]
            v = ac.mean(seq)
        try:
            vals.append(float(v))
        except (TypeError, ValueError) as exc:
            raise SourceReadError(
                f"{f.name}: 字段 {field!r} 的值不是数值（{type(v).__name__}: {v!r}）"
            ) from exc
    return files, vals


def _check_n(entry: Dict[str, Any], role: str, n: int, errors: List[str]) -> None:
    """声明样本数校验：不符即记 err（→ FAIL）。"""
    ne = entry.get("n_expected")
    if isinstance(ne, int) and n != ne:
        errors.append(f"role={role} n={n}≠n_expected={ne}")


def _recompute_two_sample(entry, data_root, errors):
    # 登记完整性前置校验（2026-10-22）：sources 缺 role=a/b 时记 error 而非让
    # KeyError 抛出 —— 门禁必须 fail-closed（判该条 FAIL、脚本继续跑完其余条目），
    # 不得因一条登记不完整而整体崩溃、使全部条目失去校验。
    # 实测触发：NR-197~200 以 role=summary/raw 登记但 analysis 仍为 two_sample。
    srcs = {s["role"]: s for s in entry.get("sources", []) if isinstance(s, dict)}
    missing = [r for r in ("a", "b") if r not in srcs]
    if missing:
        errors.append(
            f"sources 缺 role={'/'.join(missing)}（现有 role: {sorted(srcs)}），"
            f"条目登记不完整，无法复算")
        return {}, 0
    fa, va = _collect_source(data_root, srcs["a"])
    fb, vb = _collect_source(data_root, srcs["b"])
    _check_n(entry, "a", len(va), errors)
    _check_n(entry, "b", len(vb), errors)
    if len(va) < 2 or len(vb) < 2:
        errors.append("样本不足（<2），拒绝产出结论")
        return {}, len(fa) + len(fb)
    st = ac.two_sample_stats(va, vb)
    # 双口径标准差：sd_* 为无偏样本 SD（ddof=1，报告口径）；
    # sd_pop_* 为总体 SD（ddof=0，numpy 默认口径）——显式区分，避免口径混淆。
    st["sd_pop_a"] = ac.variance(va, 0) ** 0.5
    st["sd_pop_b"] = ac.variance(vb, 0) ** 0.5
    # 绝对百分点差：mean_a-mean_b 换算为 pp，供"路线C 提升 X 个百分点"类主张复算。
    st["diff_pp"] = (st["mean_a"] - st["mean_b"]) * 100.0
    return st, len(fa) + len(fb)


def _recompute_multi_sample(entry, data_root, errors):
    """多臂复算：逐臂描述统计 + 配对效应量（delta / p / Cohen d / 绝对百分点差）。

    配对来源（可叠加）：
    1. 显式 ``pairs``: ``[{"label": str, "a": role, "b": role}]`` —— 支持任意标签，
       如 ``b500``（NR-28）、``eta0.02_vs_0``（NR-25）、``005_vs_000``（NR-24）。
    2. ``baseline_role``：自动为每个非基线臂生成一对；标签取该臂 source 的
       ``label``（缺省用 role），以便把 ``ablate_security`` 记成 ``security``。
    """
    data: Dict[str, List[float]] = {}
    labels: Dict[str, str] = {}
    total = 0
    for src in entry["sources"]:
        files, vals = _collect_source(data_root, src)
        total += len(files)
        role = src["role"]
        _check_n(entry, role, len(vals), errors)
        data[role] = vals
        labels[role] = src.get("label") or role

    computed: Dict[str, Any] = {}
    for role, vals in data.items():
        if not vals:
            continue
        computed["mean_" + role] = ac.mean(vals)
        computed["sd_" + role] = ac.stdev(vals)              # ddof=1（报告口径）
        computed["sd_pop_" + role] = ac.variance(vals, 0) ** 0.5  # ddof=0（numpy 口径）
        computed["n_" + role] = len(vals)

    counts = {len(v) for v in data.values() if v}
    if len(counts) == 1:
        computed["n"] = counts.pop()          # 各臂样本数一致时才给出整体 n

    base = entry.get("baseline_role")
    if base in data and data[base]:
        for role, vals in data.items():
            if role == base or not vals:
                continue
            computed["p_" + role] = ac.welch_ttest(data[base], vals)["p"]
            computed["improvement_pct_" + role] = ac.improvement_pct(
                ac.mean(vals), ac.mean(data[base])
            )

    pair_specs = list(entry.get("pairs") or [])
    if base and base in data:
        pair_specs.extend(
            {"label": labels[role], "a": role, "b": base}
            for role in data if role != base
        )
    for pair in pair_specs:
        a, b = data.get(pair["a"]), data.get(pair["b"])
        if not a or not b:
            errors.append(f"pair {pair.get('label')} 缺臂：{pair['a']}/{pair['b']}")
            continue
        st = ac.two_sample_stats(a, b)
        lbl = pair["label"]
        computed["delta_" + lbl] = st["mean_a"] - st["mean_b"]
        computed["diff_pp_" + lbl] = (st["mean_a"] - st["mean_b"]) * 100.0
        computed["p_" + lbl] = st["welch_p"]
        computed["d_" + lbl] = st["cohens_d"]
    return computed, total


def _recompute_delta(entry, data_root, errors):
    vals: Dict[str, List[float]] = {}
    total = 0
    for src in entry["sources"]:
        files, v = _collect_source(data_root, src)
        total += len(files)
        _check_n(entry, src["role"], len(v), errors)
        vals[src["role"]] = v
    computed: Dict[str, Any] = {}
    for pair in entry.get("pairs", []):
        a, b = vals.get(pair["a"], []), vals.get(pair["b"], [])
        if a and b:
            computed["delta_" + pair["label"]] = ac.mean(a) - ac.mean(b)
    return computed, total


def _consensus_rows(data_root: Path, rel: str) -> List[Dict[str, Any]]:
    return ac.load_json(Path(data_root) / rel).get("cw_pbft", []) or []


def _find_consensus(data_root: Path, entry: Dict[str, Any], match: Dict[str, Any]):
    p = Path(data_root) / entry["consensus_file"]
    doc = ac.load_json(p)
    out: Dict[str, Any] = {}
    ratio = match["byzantine_ratio"]
    for r in doc.get("cw_pbft", []):
        if r.get("n_nodes") == match["n_nodes"] and abs(r.get("byzantine_ratio", -1) - ratio) < 1e-9:
            out["cw_success_rate"] = r.get("success_rate")
            out["n_byzantine"] = r.get("n_byzantine")
            out["n_rounds"] = r.get("n_rounds")
            break
    for r in doc.get("standard_pbft", []):
        if r.get("n_nodes") == match["n_nodes"] and abs(r.get("byzantine_ratio", -1) - ratio) < 1e-9:
            out["std_success_rate"] = r.get("success_rate")
            break
    return out


def _recompute_consensus(entry, data_root, errors):
    if "matches" in entry:
        computed = {}
        for m in entry["matches"]:
            sub = _find_consensus(data_root, entry, m)
            if not sub:
                errors.append(f"未找到匹配行 {m}")
            computed[m["key"]] = sub
        return computed, len(entry["matches"])
    sub = _find_consensus(data_root, entry, entry["match"])
    if not sub:
        errors.append(f"未找到匹配行 {entry['match']}")
    return sub, 1


def _recompute_e2e_closing(entry, data_root, errors):
    """端到端共识收敛（NR-74）：读 e2e_consensus_closing_report.json 的 6 格阵列。

    报告结构为 ``{"meta": {...}, "results": [ {...} ]}``，不能直接被点路径取值，
    故需此聚合器把每格摊平成可比对键：``cw_mean_<key>`` / ``std_mean_<key>`` /
    ``diff_pct_<key>`` / ``welch_p_<key>`` / ``R_pw_<key>``（key = ``n<nodes>_b<ratio>``）。
    """
    src0 = (entry.get("sources") or [{}])[0]
    rel = src0.get("file") or src0.get("glob")
    if not rel:
        errors.append("e2e_closing: sources[0] 缺少 file/glob")
        return {}, 0
    p = Path(data_root) / rel
    if not p.exists():
        errors.append(f"e2e 收敛报告缺失: {rel}")
        return {}, 0
    doc = ac.load_json(p)
    rows = doc.get("results") or []
    if not rows:
        errors.append("e2e 收敛报告 results 为空")
        return {}, 0
    computed: Dict[str, Any] = {}
    for r in rows:
        key = f"n{r.get('n_nodes')}_b{r.get('byzantine_ratio')}"
        computed[f"cw_mean_{key}"] = r.get("cw_mean")
        computed[f"std_mean_{key}"] = r.get("std_mean")
        computed[f"diff_pct_{key}"] = r.get("diff_pct")
        computed[f"welch_p_{key}"] = r.get("welch_p")
        computed[f"R_pw_{key}"] = r.get("R_production_weights_mean")
    computed["n_cells"] = len(rows)
    return computed, 1


def _recompute_attack(entry, data_root, errors):
    doc = ac.load_json(Path(data_root) / "attack_defense_report.json")
    return {
        "defense_rate": doc["summary"]["defense_rate"],
        "n_attacks": len(doc.get("attacks", [])),
        "n_no_bc_success": doc["summary"].get("no_bc_success"),
    }, 1


def _recompute_code_check(entry, data_root, errors):
    computed: Dict[str, Any] = {}
    for chk in entry.get("checks", []):
        kind = chk["kind"]
        if kind in ("regex_capture", "regex_present"):
            path = ac.REPO_ROOT / chk["file"]
            if not path.exists():
                errors.append(f"代码文件缺失: {chk['file']}")
                continue
            m = re.search(chk["pattern"], ac.load_text(path))
            if kind == "regex_present":
                computed[chk["key"]] = bool(m)
            elif m:
                g = m.group(1)
                cast = chk.get("cast")
                if cast == "float":
                    computed[chk["key"]] = float(g)
                elif cast == "boolword":
                    computed[chk["key"]] = g.lower() == "true"
                else:
                    computed[chk["key"]] = g
            else:
                errors.append(f"未命中代码模式: {chk['key']}")
        elif kind == "json_nested_max":
            doc = ac.load_json(Path(data_root) / chk["data_file"])
            rows = ac.navigate(doc, chk["path"]) if chk.get("path") else doc
            mx: Optional[float] = None
            for r in rows:
                for v in (r.get(chk["subkey"], {}) or {}).values():
                    mx = v if mx is None else max(mx, v)
            computed[chk["key"]] = mx
        else:
            errors.append(f"未知 check kind: {kind}")
    return computed, 0


def _resolve_file(data_root: Path, rel: str) -> Path:
    """把注册表里的 ``file`` 解析为绝对路径（注册表以 workspace 为基准）。"""
    cand = Path(rel)
    if cand.is_absolute():
        return cand
    for root in (ac.WORKSPACE_ROOT, ac.REPO_ROOT, Path(data_root)):
        p = Path(root) / rel
        if p.exists():
            return p
    return ac.REPO_ROOT / rel


def _r_key(r: float) -> str:
    """R 值 → 键名后缀：1.0→``1``、1.007→``1007``、15.0→``15``。"""
    return ("%g" % float(r)).replace(".", "")


_PATH_AGG = ("mean", "min", "max", "n", "sum")


def _json_path_value(doc: Any, path: str) -> Tuple[Any, Optional[str]]:
    """按点路径从嵌套 JSON 取值，支持列表聚合与等值定位。

    语法（供 ``analysis == "benchmark"`` 的 ``sources[].paths`` 使用）::

        ml_defender.train_accuracy           # 嵌套字段
        runs.L1_omniscient[].coop_rate       # 列表逐项取字段，默认取均值
        runs.L1_omniscient[].coop_rate#min   # 指定聚合：mean/min/max/n/sum
        runs.L2_adaptive[seed=11].coop_rate  # 按字段等值定位唯一列表项

    返回 ``(value, err)``；路径不存在、定位命中数 ≠ 1、聚合对象为空时
    ``value=None`` 且给出 ``err``，由调用方记 error（→ FAIL）。**不静默当 0**：
    "取不到数"与"取到 0"是两件事，混同会让空断言重新变成安静通过。

    2026-11-06：此前 benchmark 类只能取**顶层**数值字段，NR-180~183 的数值在
    ``ml_defender.*`` 与 ``runs.*[].coop_rate`` 里取不到，于是这四条以
    ``declared={}`` 登记，门禁对它们零比对判 PASS（见 ``compare`` 的审计注释）。
    """
    agg = "mean"
    if "#" in path:
        path, _, agg_raw = path.partition("#")
        agg = agg_raw.strip().lower()
        if agg not in _PATH_AGG:
            return None, f"未知聚合 {agg_raw!r}（可用：{'/'.join(_PATH_AGG)}）"
    node: Any = doc
    for seg in path.split("."):
        name, sel = seg, None
        if seg.endswith("]"):
            name, _, rest = seg.partition("[")
            sel = rest[:-1]
        if isinstance(node, list):
            mapped = []
            for item in node:
                if not isinstance(item, dict) or name not in item:
                    return None, f"路径 {path}: 列表元素缺字段 {name!r}"
                mapped.append(item[name])
            node = mapped
        else:
            if not isinstance(node, dict):
                return None, f"路径 {path} 在 {name!r} 处遇到非对象"
            if name not in node:
                return None, f"路径 {path} 缺字段 {name!r}"
            node = node[name]
        if sel == "":
            if not isinstance(node, list):
                return None, f"路径 {path}: {name!r} 不是列表"
        elif sel is not None:
            if not isinstance(node, list):
                return None, f"路径 {path}: {name!r} 不是列表"
            key, _, want = sel.partition("=")
            hit = [it for it in node
                   if isinstance(it, dict) and str(it.get(key)) == want]
            if len(hit) != 1:
                return None, f"路径 {path}: [{sel}] 命中 {len(hit)} 项（须恰为 1）"
            node = hit[0]
    if isinstance(node, list):
        vals = [v for v in node if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not vals:
            return None, f"路径 {path}: 聚合对象为空或非数值"
        if agg == "n":
            return len(vals), None
        if agg == "min":
            return min(vals), None
        if agg == "max":
            return max(vals), None
        if agg == "sum":
            return sum(vals), None
        return ac.mean(vals), None
    return node, None


def _recompute_benchmark(entry, data_root, errors):
    """基准类：JSON 源取数值字段；``.py`` 源按正则取常量（如 ``DILITHIUM_AVAILABLE``）。"""
    computed: Dict[str, Any] = {}
    scanned = 0
    for src in entry.get("sources", []):
        rel = src.get("file") or src.get("glob")
        if not rel:
            continue
        p = _resolve_file(data_root, rel)
        if not p.exists():
            errors.append(f"基准文件缺失: {rel}")
            continue
        scanned += 1
        if p.suffix == ".py":
            text = ac.load_text(p)
            for key in (src.get("keys") or ["DILITHIUM_AVAILABLE"]):
                # 常量常见于 try/except 块内（有缩进），故允许行首空白
                m = re.search(rf"^[ \t]*{re.escape(key)}\s*=\s*(True|False)", text, re.M | re.I)
                if m:
                    computed[key.lower()] = m.group(1).lower() == "true"
                else:
                    errors.append(f"未在 {rel} 命中常量 {key}")
            continue
        doc = ac.load_json(p)
        if src.get("paths"):
            # 显式嵌套取数（2026-11-06）。与下面的「顶层数值字段全收」口径互斥：
            # paths 存在时只取列出的键，避免把整份报告的所有数值都拖进比对。
            for key, path in src["paths"].items():
                val, err = _json_path_value(doc, path)
                if err:
                    errors.append(f"{rel}: {err}")
                    continue
                computed[key] = val
            continue
        spec = src.get("field") or ""
        wanted = [f.strip() for f in spec.split(",") if f.strip()] if "/" not in spec else []
        for k, v in doc.items():
            if wanted and k not in wanted:
                continue
            if isinstance(v, bool) or isinstance(v, (int, float)):
                computed[k] = v
    return computed, scanned


def _recompute_attack_batch(entry, data_root, errors):
    """攻击批量统计：逐类 trials/blocked/rate/Wilson CI + 合计。"""
    rel = (entry.get("sources") or [{}])[0].get("file")
    p = _resolve_file(data_root, rel)
    if not p.exists():
        errors.append(f"攻击批量报告缺失: {rel}")
        return {}, 0
    doc = ac.load_json(p)
    rows = doc.get("per_attack") or []
    if not rows:
        errors.append("per_attack 为空")
        return {}, 0
    computed = {
        "n_attack_types": doc.get("n_attack_types", len(rows)),
        "total_trials": doc.get("total_trials", sum(r.get("trials", 0) for r in rows)),
        "total_blocked": sum(r.get("blocked", 0) for r in rows),
        "overall_defense_rate": doc.get("overall_defense_rate"),
        "per_class": {
            r["attack_type"]: [r.get("trials"), r.get("blocked"),
                               r.get("defense_rate"), r.get("wilson_ci_95")]
            for r in rows
        },
    }
    return computed, 1


# P0 加权法定人数（NR-197~200）：cell 选择器只允许数据里真实存在的定位键。
# 限定键集是为了让"选择器写错"变成可诊断错误，而不是静默匹配到 0 格后被误读成
# 数据缺失（后者会把登记缺陷伪装成"本数据包不含该结果"）。
_P0_SELECTOR_KEYS = ("profile", "n_nodes", "R_actual", "fault_ratio", "control")


def _p0_filter(cells, sel, where, errors):
    """按选择器过滤 cell；命中数必须恰为 1，否则记 error 并返回 None（fail-closed）。"""
    hits = []
    for c in cells:
        ok = True
        for k in _P0_SELECTOR_KEYS:
            if k not in sel:
                continue
            want, got = sel[k], c.get(k)
            if isinstance(want, (int, float)) and not isinstance(want, bool):
                if got is None or abs(float(got) - float(want)) > 1e-9:
                    ok = False
            elif got != want:
                ok = False
            if not ok:
                break
        if ok:
            hits.append(c)
    if len(hits) != 1:
        errors.append(f"{where}: 选择器 {sel} 命中 {len(hits)} 格（须恰为 1）")
        return None
    return hits[0]


def _recompute_p0_scores(spec, data_root, computed, errors):
    """Profile B 的贡献分离散度（真实 MARL 训练分）。

    🔴 口径必须与 ``scripts/p0_weighted_quorum/make_b_weights.py`` 逐字一致：
    先把同一 agent 跨种子求均值（消掉种子间波动），再对 agent 均值取**总体 SD**
    （ddof=0）。换成 ddof=1 或直接对全部 100 个值求 SD 都会得到不同数字
    （14.53 / 40.19 vs 13.78），因此这里显式钉住 ddof=0 并在 docstring 说明。
    """
    pat = spec.get("glob") or spec.get("file")
    n_agents = int(spec.get("n_agents") or 10)
    if not pat:
        errors.append("p0_summary.score_source 缺 glob")
        return
    files = ac.resolve_glob(data_root, pat)
    if not files:
        errors.append(f"贡献分文件缺失: {pat}")
        return
    per_agent: Dict[str, List[float]] = {}
    for f in files:
        doc = ac.load_json(f)
        runs = (doc.get("runs_by_n") or {}) if isinstance(doc, dict) else {}
        arm = runs.get(str(n_agents)) or runs.get(n_agents) or {}
        sc = arm.get("bc_scores") or {}
        if not sc:
            errors.append(f"{Path(f).name}: 缺 runs_by_n[{n_agents}].bc_scores")
            continue
        for a, v in sc.items():
            per_agent.setdefault(str(a), []).append(float(v))
    if not per_agent:
        errors.append("贡献分文件均未取到 bc_scores")
        return
    avg = [ac.mean(v) for v in per_agent.values()]
    mean = ac.mean(avg)
    computed["raw_score_mean"] = mean
    computed["raw_score_sigma"] = ac.variance(avg, 0) ** 0.5   # ddof=0（同 make_b_weights）
    computed["raw_score_span_pct"] = (max(avg) - min(avg)) / mean * 100.0 if mean else 0.0
    computed["raw_score_seeds"] = len(files)
    computed["raw_score_agents"] = len(avg)


def _recompute_p0_summary(entry, data_root, errors):
    """P0 加权法定人数汇总（NR-197~200）：从 ``p0_summary.json`` 的 cell 阵列复算。

    为什么不能只读汇总自报值：``p0_summary.json`` 是**派生文件**，一旦它与逐格
    原始结论脱钩（手工改过 / 换了算法但没重跑），材料里引用的 16/50、12/15 这类
    计数就变成无源数字。故本复算器一律从 cells 逐格重算 ``n_cells`` /
    ``holm_sig_total``，并把汇总自报值当**被核对对象**（不一致即报错），而不是
    当答案。

    输出键：
    - ``n_cells`` / ``holm_sig_total`` / ``n_rounds``：全局重算值
    - ``cw_<label>`` / ``std_<label>`` / ``diff_<label>`` / ``holm_<label>`` /
      ``R_actual_<label>``：``cell_selectors`` 逐格
    - ``holm_sig_<label>`` / ``holm_sig_<label>_total``：``aggregates`` 剖面聚合
      （显著格数 / 格数），label 命名与既有登记保持一致
    """
    src = (entry.get("sources") or [{}])[0]
    rel = src.get("file") or src.get("glob")
    if not rel:
        errors.append("p0_summary: sources[0] 缺少 file/glob")
        return {}, 0
    p = _resolve_file(data_root, rel)
    if not p.exists():
        errors.append(f"P0 汇总缺失: {rel}")
        return {}, 0
    doc = ac.load_json(p)
    if not isinstance(doc, dict):
        errors.append(f"P0 汇总结构异常（顶层非对象）: {rel}")
        return {}, 0
    cells = doc.get("cells") or []
    if not cells:
        errors.append("p0_summary: cells 为空")
        return {}, 0

    computed: Dict[str, Any] = {}

    # 全局重算 + 自报值交叉核对
    n_cells = len(cells)
    holm_sig = sum(1 for c in cells if c.get("holm_rejected_0.05") is True)
    computed["n_cells"] = n_cells
    computed["holm_sig_total"] = holm_sig
    for key, recomputed in (("n_cells", n_cells), ("n_holm_significant", holm_sig)):
        claimed = doc.get(key)
        if isinstance(claimed, (int, float)) and not isinstance(claimed, bool):
            if int(claimed) != int(recomputed):
                errors.append(
                    f"P0 汇总自报 {key}={claimed} ≠ 逐格重算 {recomputed}"
                    f"（汇总与原始结论脱钩）")

    rounds = {c.get("cw_pbft", {}).get("n_rounds") for c in cells}
    rounds.discard(None)
    if len(rounds) == 1:
        computed["n_rounds"] = rounds.pop()
    elif len(rounds) > 1:
        errors.append(f"P0 各格 n_rounds 不一致：{sorted(rounds)}")
    else:
        errors.append("P0 各格缺 cw_pbft.n_rounds")

    # 逐格自洽：success_rate 必须严格等于 successes/n_rounds。这是**全 50 格**的
    # 检查（不是只查被 selector 选中的格）——只查选中格会让未被引用的格静默腐坏，
    # 而 Holm 计数恰恰依赖全量格。
    for c in cells:
        where = (f"{c.get('profile')}/n{c.get('n_nodes')}/R{c.get('R_actual')}"
                 f"/f{c.get('fault_ratio')}/{c.get('control')}")
        for arm in ("cw_pbft", "standard_pbft"):
            blk = c.get(arm) or {}
            s, n = blk.get("successes"), blk.get("n_rounds")
            rate = blk.get("success_rate")
            if isinstance(s, int) and isinstance(n, int) and n > 0 and rate is not None:
                if abs(s / n - float(rate)) > 1e-9:
                    errors.append(
                        f"{where}/{arm}: success_rate={rate} ≠ {s}/{n}={s / n:.6f}")

    # 单格：读数
    for sel in entry.get("cell_selectors") or []:
        label = sel.get("label")
        if not label:
            errors.append("p0_summary: cell_selectors 项缺 label")
            continue
        cell = _p0_filter(cells, {k: v for k, v in sel.items() if k != "label"},
                          f"cell[{label}]", errors)
        if cell is None:
            continue
        cw = cell.get("cw_pbft") or {}
        std = cell.get("standard_pbft") or {}
        computed[f"cw_{label}"] = cw.get("success_rate")
        computed[f"std_{label}"] = std.get("success_rate")
        computed[f"diff_{label}"] = cell.get("success_rate_diff")
        computed[f"holm_{label}"] = bool(cell.get("holm_rejected_0.05"))
        computed[f"R_actual_{label}"] = cell.get("R_actual")

    # 剖面聚合：显著格数 / 格数
    for agg in entry.get("aggregates") or []:
        label = agg.get("label")
        if not label:
            errors.append("p0_summary: aggregates 项缺 label")
            continue
        pick = {k: v for k, v in agg.items() if k != "label"}
        hits = [c for c in cells if all(
            (abs(float(c.get(k)) - float(v)) <= 1e-9
             if isinstance(v, (int, float)) and not isinstance(v, bool)
             else c.get(k) == v)
            for k, v in pick.items())]
        if not hits:
            errors.append(f"agg[{label}]: 选择器 {pick} 命中 0 格")
            continue
        computed[f"holm_sig_{label}"] = sum(
            1 for c in hits if c.get("holm_rejected_0.05") is True)
        computed[f"holm_sig_{label}_total"] = len(hits)

    score = entry.get("score_source")
    if isinstance(score, dict):
        _recompute_p0_scores(score, data_root, computed, errors)

    return computed, 1


def _recompute_formula_verify(entry, data_root, errors):
    """判据类：从 ``r_scan``/``exp3_reproduction`` 复算 f_max(R)=R/(R+2) 边界与自检总状态。"""
    rel = (entry.get("sources") or [{}])[0].get("file")
    p = _resolve_file(data_root, rel)
    if not p.exists():
        errors.append(f"判据验证文件缺失: {rel}")
        return {}, 0
    doc = ac.load_json(p)
    computed: Dict[str, Any] = {}
    for row in doc.get("r_scan") or []:
        r = row.get("R_eff")
        if r is not None:
            computed[f"f_max_R{_r_key(r)}"] = row.get("f_max")
    for sub in (doc.get("exp3_reproduction") or {}).values():
        sub = sub or {}
        r, pct = sub.get("R_eff"), sub.get("f_max_pct")
        if r is not None and pct is not None:
            computed.setdefault(f"f_max_R{_r_key(r)}", round(float(pct) / 100.0, 4))
    checks = doc.get("self_checks") or []
    if checks:
        computed["all_checks_pass"] = all(bool(c.get("pass")) for c in checks)
    return computed, 1


def _recompute_pytest(entry, data_root, errors):
    """测试计数（NR-19）：真实复跑 pytest 并解析 junit xml。仅 ``--run-tests`` 时调用。"""
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    with tempfile.TemporaryDirectory() as td:
        xml = Path(td) / "junit.xml"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "pytest", "-q",
             "-p", "no:cacheprovider", "--junitxml", str(xml)],
            cwd=str(ac.REPO_ROOT), capture_output=True, text=True,
        )
        if not xml.exists():
            # 带 stderr 末行：解释器缺 pytest / 采集错误等一眼可诊断
            # （2026-10-17：PATH 上的 python 3.13 无 pytest，子进程秒败，
            #  没有这行 hint 时只能看到一句光秃秃的"未产出 junit xml"）。
            tail = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
            hint = f"；stderr 末行: {tail[-1][:200]}" if tail else ""
            errors.append(f"pytest 未产出 junit xml（退出码 {proc.returncode}{hint}）")
            return {}, 0
        root = ET.parse(xml).getroot()
        suites = [root] if root.tag == "testsuite" else list(root)
        total = failed = skipped = 0
        for s in suites:
            total += int(s.get("tests", 0))
            failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
            skipped += int(s.get("skipped", 0))
    return {"collected": total, "passed": total - failed - skipped,
            "failed": failed, "skipped": skipped}, 1


def _recompute_e41_longrun(entry, data_root, errors):
    """E41 端到端长跑一致性（NR-174）：读 e41_ledger_consistency.json 的 summary。

    产出键（与 declared 一一对应，全部为标量）：
      success_count / n_rounds / success_rate / n_divergence_checks /
      n_checks / latency_ms_mean / latency_ms_max / total_msg_sent
    ⚠ divergences 是 list，**不进 declared**（verify 的 _compare_value 对
    「declared 是 list 而 computed 无对应 key」直接判 False）；一致性结论
    由 n_divergence_checks == 0 表达。
    """
    src0 = (entry.get("sources") or [{}])[0]
    rel = src0.get("file") or src0.get("glob")
    if not rel:
        errors.append("e41_longrun: sources[0] 缺少 file/glob")
        return {}, 0
    p = Path(data_root) / rel
    if not p.exists():
        errors.append(f"E41 长跑报告缺失: {rel}")
        return {}, 0
    doc = ac.load_json(p)
    summ = doc.get("summary") or {}
    lat = summ.get("latency_ms") or {}
    computed = {
        "success_count": summ.get("success_count"),
        "n_rounds": summ.get("n_rounds"),
        "success_rate": summ.get("success_rate"),
        "n_checks": summ.get("n_checks"),
        "n_divergence_checks": summ.get("n_divergence_checks"),
        "latency_ms_mean": lat.get("mean"),
        "latency_ms_max": lat.get("max"),
        "total_msg_sent": summ.get("total_msg_sent"),
    }
    return computed, 1


def check_parameters(entry: Dict[str, Any], data_root: Path) -> List[str]:
    """E20 / REA #106：条目声明 ``parameters`` 时，逐文件核对 ``config.<key>``。

    为什么需要：数字对得上不等于**同配置**跑出来的。同一份结果目录里混入
    不同 λ / n_agents / algorithm 的批次时，均值可能仍落在容差内，但结论
    已经不可比。声明式核对把「这批文件确实是该参数的产物」变成可验证断言。

    纪律：
    - 只核对**声明过**的键；未声明不猜、不推断。
    - 文件里缺该键 → 记错（"配置里没有" 无法证实声明，不是"没关系"）。
    - 无匹配文件 → 返回空（数据缺失由 DATA_MISSING 通道处理，不重复报）。
    """
    params = entry.get("parameters")
    if not isinstance(params, dict) or not params:
        return []
    errors: List[str] = []
    seen = 0
    for src in entry.get("sources") or []:
        if not isinstance(src, dict):
            continue
        for pat in _source_patterns(src):
            for f in ac.resolve_glob(data_root, pat):
                seen += 1
                try:
                    doc = ac.load_json(f)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{Path(f).name}: 读取失败（{exc.__class__.__name__}），参数无法证实")
                    continue
                cfg = doc.get("config", {}) if isinstance(doc, dict) else {}
                if not isinstance(cfg, dict):
                    cfg = {}
                for key, want in params.items():
                    got = cfg.get(key, "<missing>")
                    if got != want:
                        errors.append(
                            f"{Path(f).name}: config.{key}={got!r} ≠ 声明 {want!r}")
    if seen == 0:
        return []
    return errors


def recompute(entry: Dict[str, Any], data_root: Path) -> Tuple[Dict[str, Any], int, List[str]]:
    """按 analysis 类型复算单条；返回 ``(computed, files_scanned, errors)``。"""
    analysis = entry.get("analysis")
    errors: List[str] = []
    if analysis == "two_sample":
        computed, files = _recompute_two_sample(entry, data_root, errors)
    elif analysis == "multi_sample":
        computed, files = _recompute_multi_sample(entry, data_root, errors)
    elif analysis == "delta_arms":
        computed, files = _recompute_delta(entry, data_root, errors)
    elif analysis in ("consensus_row", "consensus_rows"):
        computed, files = _recompute_consensus(entry, data_root, errors)
    elif analysis == "e2e_closing":
        computed, files = _recompute_e2e_closing(entry, data_root, errors)
    elif analysis == "e41_longrun":
        computed, files = _recompute_e41_longrun(entry, data_root, errors)
    elif analysis == "attack_report":
        computed, files = _recompute_attack(entry, data_root, errors)
    elif analysis == "attack_batch":
        computed, files = _recompute_attack_batch(entry, data_root, errors)
    elif analysis == "p0_summary":
        computed, files = _recompute_p0_summary(entry, data_root, errors)
    elif analysis == "formula_verify":
        computed, files = _recompute_formula_verify(entry, data_root, errors)
    elif analysis == "benchmark":
        computed, files = _recompute_benchmark(entry, data_root, errors)
    elif analysis == "pytest":
        computed, files = _recompute_pytest(entry, data_root, errors)
    elif analysis == "code_check":
        computed, files = _recompute_code_check(entry, data_root, errors)
    else:  # "none" / 缺失
        computed, files = {}, 0
    return computed, files, errors


# --------------------------------------------------------------------------- #
# 比对
# --------------------------------------------------------------------------- #
def _tol_for(key: str, tol: Dict[str, Any]) -> float:
    # 注意：百分比键形如 improvement_pct / improvement_pct_cars_010 / diff_pp_b500，
    # 故用 'pct'/'pp' 子串判定
    if "pct" in key or "pp" in key:
        return float(tol.get("pct_abs", 0.05))
    if "power" in key:
        return float(tol.get("power_abs", 0.02))
    # 配对检验的 p 值键形如 p_security / p_b500 / p_005_vs_000（前缀式），
    # 另有 welch_p / *_p（后缀式）
    if key == "welch_p" or key.endswith("_p") or key.startswith("p_") or key == "p_value":
        return float(tol.get("p_abs", 0.001))
    return float(tol.get("abs", 0.01))


def _compare_value(key: str, dec: Any, comp: Any, tol: Dict[str, Any]) -> Tuple[bool, Any]:
    if isinstance(dec, list):
        if not isinstance(comp, (list, tuple)) or len(dec) != len(comp):
            return False, None
        ok, deltas = True, []
        for d, c in zip(dec, comp):
            o, dl = _compare_value(key, d, c, tol)
            ok = ok and o
            deltas.append(dl)
        return ok, deltas
    if isinstance(dec, dict):
        if not isinstance(comp, dict):
            return False, None
        ok, dd = True, {}
        for k in dec:
            if k not in comp:
                return False, None
            o, dl = _compare_value(k, dec[k], comp[k], tol)
            ok = ok and o
            dd[k] = dl
        return ok, dd
    if isinstance(dec, bool) or isinstance(comp, bool):
        return dec == comp, None
    if isinstance(dec, str) or isinstance(comp, str):
        return str(dec) == str(comp), None
    try:
        delta = abs(float(dec) - float(comp))
    except (TypeError, ValueError):
        return False, None
    return delta <= _tol_for(key, tol), delta


# 「测试计数」类条目（当前仅 NR-19）的口径是**下限式**：对外只申报
# 「1600+ 项自动化测试全部通过（0 失败）」，`declared` 保留精确值仅供内部核对。
# 因此计数增长**不应**使校验失败 —— 否则每新增一批测试都会让 `--run-tests` 变红，
# 与下限式口径的动因（测试数是构建产物、不应触发全链更新）自相矛盾。
# 这里对计数键按下限比对：``computed >= declared`` 即通过。
# 注意 ``failed`` **不是**计数键，仍精确比对（必须为 0），回归照旧会被抓住。
_FLOOR_COMPARE_KEYS = frozenset({"passed", "collected"})

# test_count 类条目里，``skipped`` 同样是构建产物特性——哪些用例被 skip 随
# 环境/依赖漂移（如缺 torch 跳 GPU 用例、缺 sklearn 跳 ML 用例），既可能增
# 也可能减，下限/精确比对都不成立。故设为**信息键**：不计入判定，仅记录
# delta 供人读。（2026-10-17：declared skipped=8 vs 实测 2，精确比对使
# NR-19 无故 FAIL——与「测试数不应触发全链更新」的设计动因自相矛盾。）
_INFO_COMPARE_KEYS = frozenset({"skipped"})


def compare(entry: Dict[str, Any], computed: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """逐条比对 declared↔computed；返回 ``(all_ok, deltas)``。

    * 常规条目：按 key 的容差**精确**比对。
    * ``evidence_kind == "test_count"``：``passed`` / ``collected`` 按**下限**比对
      （只增不减）；``skipped`` 为**信息键**（环境相关、不计判定）；
      ``failed`` 等其余键仍精确比对。见 ``_FLOOR_COMPARE_KEYS`` / ``_INFO_COMPARE_KEYS``。
    * ``declared`` 为空：**一律不通过**（见下）。

    2026-11-06 审计缺陷（fail-open）：``declared`` 为空时旧实现的 ``for`` 循环体
    一次都不执行，``ok`` 保持初值 ``True`` ⇒ 判 PASS。实测：把 NR-121 的
    ``declared`` 留空、喂进一份「吞吐 1 pkg/s、拦截 0/999999」的**相反**数据，
    报告仍是 ``PASS``、``deltas={}``（零次比对）、退出码 0。同一形态在无任何
    数据时也让 NR-180~183 四条判 PASS（其余 187 条全是 DATA_MISSING）。
    「PASS 但一条数值都没断言」与「没检查」等价，而报告抬头把它计入 PASS 数，
    于是 ``PASS=184`` 里有 7 条是空断言 —— 必须 fail-closed。
    """
    declared = entry.get("declared")
    if not isinstance(declared, dict) or not declared:
        return False, {"__declared__": "declared 为空：该条目未声明任何可复算值"}
    tol = entry.get("tolerance", {})
    floor_mode = entry.get("evidence_kind") == "test_count"
    ok, deltas = True, {}
    for key, dec in declared.items():
        if key not in computed:
            ok = False
            deltas[key] = "MISSING"
            continue
        if floor_mode and key in _FLOOR_COMPARE_KEYS:
            try:
                good = float(computed[key]) >= float(dec)
            except (TypeError, ValueError):
                good = False
            ok = ok and good
            deltas[key] = ">= %s（下限式，实测 %s）" % (dec, computed[key])
            continue
        if floor_mode and key in _INFO_COMPARE_KEYS:
            # 信息键：环境相关的构建产物特性，不计入判定（见 _INFO_COMPARE_KEYS 注释）
            deltas[key] = "信息键（declared %s，实测 %s，不计判定）" % (dec, computed[key])
            continue
        o, dl = _compare_value(key, dec, computed[key], tol)
        ok = ok and o
        deltas[key] = dl
    return ok, deltas


# --------------------------------------------------------------------------- #
# 双数据源一致性
# --------------------------------------------------------------------------- #
#: 只有「纯点路径」形态的 ``field`` 才能两边各取一次再比数值。
#: 注册表里还有大量描述性 ``field``（如 ``"DILITHIUM_AVAILABLE / 签名长度常量"``、
#: ``"per_attack[].defense_rate / wilson_ci_95"``）—— 它们是给人读的口径说明，
#: 不是可机读路径。旧实现对这类源直接 ``extract_field`` 后由 ``except`` 记成
#: 「差异」，等于把「读不懂」报成「两边不一致」。
_PLAIN_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")


def _mirror_field_value(doc: Any, src: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """从一份数据文件里取出可比对的标量；取不到时返回 ``(None, 原因码)``。"""
    field = (src.get("field") or "").strip()
    if not field:
        return None, "no_field"
    if not _PLAIN_FIELD_RE.match(field):
        return None, "field_not_path"
    try:
        v = ac.extract_field(doc, field)
    except (KeyError, TypeError, AttributeError) as exc:
        return None, f"field_unreadable:{exc.__class__.__name__}"
    if isinstance(v, (list, tuple)):
        seq = list(v)
        if not seq:
            return None, "empty_sequence"
        v = ac.mean(seq)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, f"not_numeric:{type(v).__name__}"
    return v, None


def _mirror_file(mirror_path: Path, rel: str) -> Optional[Path]:
    """把注册表里的 ``file``（相对工作区）解析成镜像侧路径。

    两种基准都要试：镜像根本身就是 ``results/`` 目录，所以 ``results/x.json``
    对应 ``mirror/x.json``；而 ``deliverables/x.json`` 这类只能整体挂在镜像根下。
    猜不到就返回 ``None``（由调用方记 ``skipped``），**不回落到 repo 路径**——
    用同一份文件比两次永远"一致"。
    """
    cands = [mirror_path / rel]
    p = Path(rel)
    if p.parts and p.parts[0] == "results":
        cands.append(mirror_path / Path(*p.parts[1:]))
    for c in cands:
        if c.exists():
            return c
    return None


def check_mirror(registry: Dict[str, Any], data_root: Path, mirror_root: Path,
                 only: Optional[set] = None) -> Dict[str, Any]:
    """repo↔backup 双源一致性：按注册表的**全部**取数模式逐个比字段值。

    2026-11-06 审计：此项「repo↔backup 一致性」承诺自加入起**一次都没跑通**，
    三处缺陷，实测复现（真实注册表，第一条 NR-1 就崩）：

    1. ``src["glob"]`` 直接取键 ⇒ ``globs``（135 处，多批次并集）/ ``file``
       （31 处）/ 字符串式静态引用（NR-19 的 junit ``path#attr`` 三元组）全部
       抛异常 —— 前者 ``KeyError: 'glob'``，后者
       ``TypeError: string indices must be integers``。崩溃点在报告写出**之前**，
       所以 ``--check-mirror`` 的产物是一段 traceback，一份报告都没有。
    2. 只认单个 ``glob`` ⇒ 即便不崩，用 ``globs`` 登记的条目也只比了多批次并集
       的**前半截**，比较样本比声明少一截，而报告仍写"一致"。
    3. 零比较判「一致」：镜像根不存在 / glob 全不匹配时 ``diffs==0`` ⇒
       ``consistent=True``，报告抬头写「双源一致：是（比较 0 个文件）」。
       这与 ``declared`` 为空的 fail-open 同源 —— **未判定 ≠ 一致**。

    现在的返回值是三元结论：``True``（真比过且全同）/ ``False``（有差异）/
    ``None``（一次都没比成）。``reason`` 给可诊断的原因，``skipped`` 记录
    "有源但比不了"的每一处，避免它们静默消失。
    """
    diffs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    compared = 0
    sources_seen = 0
    seen_patterns: set[str] = set()
    mirror_path = Path(mirror_root)
    if not mirror_path.exists():
        return {
            "consistent": None, "files_compared": 0, "sources_checked": 0,
            "diffs": [], "skipped": [],
            "reason": (f"镜像根不存在（{mirror_path}）—— 双源一致性未判定"
                       "（未判定 ≠ 一致）"),
        }

    # 先把「两边各是哪份文件」配好，再统一比数值：这样 file 源（相对工作区解析）
    # 与 glob 源（相对 data-root 解析）不会各用一套规则、把配对悄悄错位。
    pairs: List[Tuple[str, str, Path, Path, Dict[str, Any]]] = []
    for entry in registry.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if only and entry.get("id") not in only:
            continue
        for src in entry.get("sources") or []:
            eid = entry.get("id")
            if isinstance(src, str):
                # NR-19 这类：sources 是 junit 的 "path#testsuite@attr" 引用，
                # 不是数据文件路径。没有可比的数值字段，显式记录而不是崩掉。
                skipped.append({"entry": eid, "reason": "static_ref",
                                "detail": src[:120]})
                continue
            if not isinstance(src, dict):
                skipped.append({"entry": eid, "reason": "not_an_object",
                                "detail": type(src).__name__})
                continue
            pats = _source_patterns(src)
            file_rel = (src.get("file") or "").strip()
            is_file_src = not pats and bool(file_rel)
            if is_file_src:
                pats = [file_rel]
            if not pats:
                skipped.append({"entry": eid, "reason": "no_pattern"})
                continue
            sources_seen += 1
            for g in pats:
                if g in seen_patterns:
                    continue
                seen_patterns.add(g)
                if is_file_src:
                    rp = _resolve_file(data_root, g)
                    try:
                        rp.resolve().relative_to(Path(data_root).resolve())
                        in_scope = True
                    except ValueError:
                        in_scope = False
                    if not in_scope:
                        # 双源镜像备的是 data-root 内的结果文件；deliverables/ 里的
                        # 派生物本来就不在镜像范围。报成「差异」会让 --check-mirror
                        # 永远红，报成「一致」又是假话 —— 记录原因后跳过。
                        skipped.append({"entry": eid, "reason": "outside_data_root",
                                        "detail": g})
                        continue
                    mp = _mirror_file(mirror_path, g)
                    have_r, have_m = rp.exists(), mp is not None
                    if have_r and have_m:
                        pairs.append((g, rp.name, rp, mp, src))  # type: ignore[arg-type]
                    elif have_r or have_m:
                        diffs.append({"glob": g,
                                      "only_repo": [g] if have_r else [],
                                      "only_mirror": [g] if have_m else []})
                    else:
                        skipped.append({"entry": eid, "reason": "file_not_found",
                                        "detail": g})
                    continue
                rmap = {p.name: p for p in ac.resolve_glob(data_root, g)}
                mmap = {p.name: p for p in ac.resolve_glob(mirror_path, g)}
                if set(rmap) != set(mmap):
                    diffs.append({"glob": g, "only_repo": sorted(set(rmap) - set(mmap)),
                                  "only_mirror": sorted(set(mmap) - set(rmap))})
                for name, rp in rmap.items():
                    mp = mmap.get(name)
                    if mp is not None:
                        pairs.append((g, name, rp, mp, src))

    for g, name, rp, mp, src in pairs:
        try:
            rdoc, mdoc = ac.load_json(rp), ac.load_json(mp)
        except (OSError, ValueError) as exc:
            diffs.append({"file": name, "glob": g,
                          "error": f"{exc.__class__.__name__}: {exc}"})
            continue
        rv, why = _mirror_field_value(rdoc, src)
        if why is None:
            mv, why = _mirror_field_value(mdoc, src)
        if why is not None:
            skipped.append({"file": name, "glob": g, "reason": why,
                            "detail": f"field={src.get('field')!r}"})
            continue
        compared += 1
        try:
            same = abs(float(rv) - float(mv)) <= 1e-9
        except (TypeError, ValueError):
            same = False
        if not same:
            diffs.append({"file": name, "glob": g, "repo": rv, "mirror": mv})

    if diffs:
        consistent: Optional[bool] = False
        reason = f"{len(diffs)} 处差异"
    elif compared == 0:
        consistent = None
        reason = ("零次比较：没有任何同名且可取数的文件（镜像侧缺文件 / 字段不可机读）"
                  f"—— 未判定 ≠ 一致；跳过 {len(skipped)} 处")
    else:
        consistent = True
        reason = ""
    return {"consistent": consistent, "files_compared": compared,
            "sources_checked": sources_seen, "diffs": diffs, "skipped": skipped,
            "reason": reason}


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def _git_head() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ac.REPO_ROOT,
                           capture_output=True, text=True, encoding="utf-8", timeout=10)
        out = r.stdout.strip()
        return out if r.returncode == 0 and len(out) == 40 else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _editorial_target(target: str) -> Dict[str, Any]:
    """编辑目标 pin（REA #126）：这份报告描述的是哪一批字节。

    target 为空 → sha="" / match=None，报告抬头显式写「未 pin」；
    给了但不是 40 位 SHA → ValueError（fail-closed，不猜、不截断、不比对缩写）。
    """
    target = (target or "").strip()
    head = _git_head()
    if not target:
        return {"sha": "", "current_head": head, "match": None}
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError(
            f"--target-sha 必须是 40 位小写十六进制 SHA，收到 {target!r}——"
            "缩写或大写无法与 HEAD 逐位比对，拒绝猜测")
    return {"sha": target, "current_head": head, "match": target == head}


def _render_mirror_line(report: Dict[str, Any]) -> str:
    """双源结论一行（四种状态必须互不混淆）。

    旧实现只有两态（"是" / "否" / 未启用），把「跑过但一次都没比成」和
    「没跑」都归到「未检查」；更糟的是零比较时 ``consistent=True`` 直接显示
    「是（比较 0 个文件）」。这里把 ``None`` 再分成两态：
    ``mirror is None`` ⇒ 未启用；``mirror`` 在但 ``consistent is None`` ⇒ 未判定。
    """
    mi = report.get("mirror")
    if mi is None:
        return "- 双源一致：**未检查**（未启用 --check-mirror；未检查 ≠ 一致）"
    compared = mi.get("files_compared", 0)
    reason = mi.get("reason") or ""
    state = report.get("mirror_consistent")
    if state is True:
        return f"- 双源一致：是（同名文件比较 {compared} 个，全部相同）"
    if state is False:
        return (f"- 双源一致：**否**（同名文件比较 {compared} 个，"
                f"差异 {len(mi.get('diffs') or [])} 处）")
    return f"- 双源一致：**未判定**（{reason or '一次都没比成'}）"


def _render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    et = report.get("editorial_target") or {}
    if et.get("sha"):
        pin = (f"`{et['sha']}`（当前 HEAD `{et.get('current_head', 'unknown')}`，"
               + ("一致" if et.get("match") else "**与当前 HEAD 不一致——报告描述的是拟提交版本，"
                  "复算时工作区已前进，引用前先确认**") + "）")
    else:
        pin = "**未 pin**（上传/答辩前用 `--target-sha <拟提交版本SHA>` 指定，否则无法证明报告对应哪批字节）"
    lines = [
        "# 数字复算报告（number_verification_report）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 编辑目标：{pin}",
        f"- 注册表：`{report['registry_ref']}`",
        f"- 数据源：`{report['data_root']}`（镜像：`{report['mirror_root']}`，commit `{report['commit']}`）",
        f"- 汇总：total={s['total']} PASS={s['pass']} FAIL={s['fail']} PENDING={s['pending']} INVALID={s['invalid']}"
        + (f" UNVERIFIED={s['unverified']}" if s.get("unverified") else "")
        + (f" DATA_MISSING={s['data_missing']}" if s.get("data_missing") else "")
        + (f" CRASHED={s['crashed']}" if s.get("crashed") else ""),
        _render_mirror_line(report),
        "",
        "| ID | 状态 | 复算值（摘要） | 差异 | 备注 |",
        "|---|---|---|---|---|",
    ]
    for e in report["entries"]:
        comp = e.get("computed", {})
        brief = ", ".join(
            f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
            for k, v in list(comp.items())[:4]
        )
        dmax = ""
        if isinstance(e.get("deltas"), dict):
            nums = [abs(v) for v in e["deltas"].values() if isinstance(v, (int, float))]
            if nums:
                dmax = f"max|Δ|={max(nums):.4g}"
        note = e.get("reason") or e.get("notes", "")
        lines.append(f"| {e['id']} | {e['status']} | {brief} | {dmax} | {note} |")
    lines.append("")
    return "\n".join(lines)


def _emit_report(report: Dict[str, Any], report_json: Path, overwrite: bool) -> None:
    pj = ac.safe_write_json(report, report_json, overwrite=overwrite)
    ac.safe_write_text(_render_markdown(report), pj.with_suffix(".md"), overwrite=overwrite)
    logger.info("报告已写出：%s", ac.rel_to_workspace(pj))
    logger.info("人读清单：%s", ac.rel_to_workspace(pj.with_suffix('.md')))


# --------------------------------------------------------------------------- #
# 自证（--self-test）
# --------------------------------------------------------------------------- #
#: 自证里复用的口径字段（与 NR-1 同口径，避免自证与真实登记各说各话）
_ST_FIELD = ac.PRIMARY_FIELD


def _st_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _st_arm(root: Path, prefix: str, arm: str, values: List[Any]) -> None:
    """在 ``root/prefix`` 下造 ``arm_seed*.json`` 批次（值可为 None，用来造坏数据）。"""
    for i, v in enumerate(values):
        _st_write_json(root / prefix / f"{arm}_seed{i}.json",
                       {"summary": {"avg_env_reward_last_50": v}})


def _st_two_sample(eid: str, prefix: str,
                   declared: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": eid, "analysis": "two_sample", "status": "PASS",
        "sources": [
            {"globs": [f"{prefix}/a_seed*.json"], "field": _ST_FIELD, "role": "a"},
            {"globs": [f"{prefix}/b_seed*.json"], "field": _ST_FIELD, "role": "b"},
        ],
        "declared": declared, "tolerance": {"abs": 0.01},
    }


def _st_ok_declared() -> Dict[str, Any]:
    """与 ``_st_arm(..., "a", [-7.0,-7.1,-6.9])`` / ``b=[-9.0,-9.1,-8.9]`` 对得上。"""
    return {"mean_a": -7.0, "mean_b": -9.0, "n_a": 3, "n_b": 3}


def _st_run(d: Path, entries: List[Dict[str, Any]], extra: Optional[List[str]] = None
            ) -> Tuple[int, Dict[str, Any], Path]:
    """跑一次 ``main()``，返回 ``(退出码, 报告, 数据根)``。"""
    data = d / "data"
    data.mkdir(parents=True, exist_ok=True)
    regp = d / "registry.json"
    _st_write_json(regp, {"version": 1, "commit": "self-test", "entries": entries})
    rep = d / "report.json"
    argv = ["--registry", str(regp), "--data-root", str(data),
            "--report", str(rep), "--overwrite"] + list(extra or [])
    rc = main(argv)
    doc = ac.load_json(rep) if rep.exists() else {}
    return rc, doc, data


def _st_by_id(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {e["id"]: e for e in doc.get("entries") or []}


def _self_test() -> int:
    """内置自证：用合成注册表/数据/镜像证明 2026-11-06 三处修复真的承重。

    为什么不只靠 pytest：``--check-mirror`` 从加入起就没跑通过（对真实注册表
    第一条 NR-1 就 ``KeyError: 'glob'``），而它不在任何 CI 步骤里 —— 一个从不
    执行的校验，红绿都是传说。这里把每处缺陷的**实测形态**写成用例，并让它
    能被 CI 直接跑（``python scripts/verify_numbers.py --self-test``）：
    修复被回退时用例立刻变红，而不是安静通过。

    不读仓库里的注册表 / results / 镜像；全部数据在临时目录里现造。
    """
    import tempfile

    cases: List[Tuple[str, Any]] = []

    def case(name: str):
        def deco(fn):
            cases.append((name, fn))
            return fn
        return deco

    # ---- 1. 崩溃隔离 ---------------------------------------------------- #
    @case("崩溃隔离：一条坏数据不让整份报告消失")
    def _(d: Path) -> None:
        bad = _st_two_sample("NR-T1", "bad", _st_ok_declared())
        good = _st_two_sample("NR-T2", "ok", _st_ok_declared())
        data = d / "data"
        data.mkdir(parents=True, exist_ok=True)
        _st_arm(data, "bad", "a", [None, -7.0, -7.0])   # ← 一次跑挂了写成 null
        _st_arm(data, "bad", "b", [-9.0, -9.0, -9.0])
        _st_arm(data, "ok", "a", [-7.0, -7.1, -6.9])
        _st_arm(data, "ok", "b", [-9.0, -9.1, -8.9])
        regp = d / "registry.json"
        _st_write_json(regp, {"version": 1, "commit": "self-test",
                              "entries": [bad, good]})
        rep = d / "report.json"
        rc = main(["--registry", str(regp), "--data-root", str(data),
                   "--report", str(rep), "--overwrite"])
        assert rep.exists(), "报告没产出：整跑被一条坏数据带崩了（旧缺陷回归）"
        doc = ac.load_json(rep)
        by = _st_by_id(doc)
        assert rc == ac.EXIT_FAIL, f"有 FAIL 却退出码 {rc}"
        assert by["NR-T1"]["status"] == "FAIL", by["NR-T1"]["status"]
        assert "复算抛异常" in by["NR-T1"]["reason"], by["NR-T1"]["reason"]
        assert by["NR-T1"]["crashed"] is True, "崩溃标记丢失"
        assert by["NR-T2"]["status"] == "PASS", \
            f"同批的干净条目被连坐：{by['NR-T2']['status']}"
        assert doc["summary"]["crashed"] == 1, doc["summary"]

    # ---- 2. 登记缺陷 ≠ 数据缺失 ----------------------------------------- #
    @case("登记缺 role 判 FAIL（不是「数据缺失」退出码 3）")
    def _(d: Path) -> None:
        data = d / "data"
        data.mkdir(parents=True, exist_ok=True)
        _st_arm(data, "p", "a", [-7.0, -7.1, -6.9])
        entry = _st_two_sample("NR-T3", "p", _st_ok_declared())
        entry["sources"] = [s for s in entry["sources"] if s["role"] == "a"]
        rc, doc, _ = _st_run(d, [entry])
        status = _st_by_id(doc)["NR-T3"]["status"]
        assert status == "FAIL", f"登记缺陷被报成 {status}（数据明明在盘上）"
        assert "缺 role=b" in _st_by_id(doc)["NR-T3"]["reason"], \
            _st_by_id(doc)["NR-T3"]["reason"]
        assert rc == ac.EXIT_FAIL, f"退出码 {rc}（3 = 被误诊成数据缺失）"

    # ---- 3. 双源校验：globs / file / 字符串引用都要能比 ------------------ #
    @case("双源：globs 与 file 源都能比（旧实现 KeyError）")
    def _(d: Path) -> None:
        repo, mir = d / "repo", d / "mirror"
        for root in (repo, mir):
            _st_arm(root, "p", "a", [-7.0, -7.1, -6.9])
            _st_write_json(root / "flat.json", {"sign_ms": 1.5})
        reg = {"entries": [
            {"id": "NR-T4", "sources": [
                {"globs": ["p/a_seed*.json"], "field": _ST_FIELD, "role": "a"},
                {"file": "flat.json", "field": "sign_ms"}]},
            {"id": "NR-T5", "sources": ["reports/junit.xml#testsuite@tests"]},
        ]}
        info = check_mirror(reg, repo, mir)
        assert info["files_compared"] == 4, info["files_compared"]
        assert info["consistent"] is True, info
        assert any(s.get("reason") == "static_ref" for s in info["skipped"]), \
            "字符串式静态引用必须留痕，不能静默消失"

    @case("双源：数值不同必须报差异")
    def _(d: Path) -> None:
        repo, mir = d / "repo", d / "mirror"
        _st_arm(repo, "p", "a", [-7.0, -7.1, -6.9])
        _st_arm(mir, "p", "a", [-7.0, -7.2, -6.9])
        reg = {"entries": [{"id": "NR-T6", "sources": [
            {"globs": ["p/a_seed*.json"], "field": _ST_FIELD, "role": "a"}]}]}
        info = check_mirror(reg, repo, mir)
        assert info["consistent"] is False, "数值不同却报「一致」"
        assert len(info["diffs"]) == 1, info["diffs"]

    @case("双源：镜像缺失/零比较判「未判定」，缺文件判差异")
    def _(d: Path) -> None:
        repo = d / "repo"
        _st_arm(repo, "p", "a", [-7.0])
        reg = {"entries": [{"id": "NR-T7", "sources": [
            {"globs": ["p/a_seed*.json"], "field": _ST_FIELD, "role": "a"}]}]}
        # (a) 镜像根不存在 ⇒ 未判定（不是「一致」）
        absent = check_mirror(reg, repo, d / "no_such_mirror")
        assert absent["consistent"] is None, absent
        assert "不存在" in absent["reason"], absent["reason"]
        # (b) 镜像根在但整份文件都没复制 ⇒ 这是**差异**，不是未判定
        empty = d / "empty"
        empty.mkdir()
        missing_files = check_mirror(reg, repo, empty)
        assert missing_files["consistent"] is False, missing_files
        assert missing_files["diffs"][0]["only_repo"] == ["a_seed0.json"], \
            missing_files["diffs"]
        # (c) 文件名对得上但字段不可机读 ⇒ 未判定（读不懂 ≠ 一致）
        unreadable = d / "unreadable"
        _st_arm(unreadable, "p", "a", [-7.0])
        vague = {"entries": [{"id": "NR-T7b", "sources": [
            {"globs": ["p/a_seed*.json"], "field": "签名长度常量 / 说明文字",
             "role": "a"}]}]}
        info = check_mirror(vague, repo, unreadable)
        assert info["files_compared"] == 0, info
        assert info["consistent"] is None, info
        assert info["skipped"], "不可机读的字段必须留痕"

    # ---- 4. 比对器本身不空转 -------------------------------------------- #
    @case("数值错得离谱必须 FAIL（证明比对器不空转）")
    def _(d: Path) -> None:
        data = d / "data"
        data.mkdir(parents=True, exist_ok=True)
        _st_arm(data, "p", "a", [-7.0, -7.1, -6.9])
        _st_arm(data, "p", "b", [-9.0, -9.1, -8.9])
        wrong = _st_ok_declared()
        wrong["mean_a"] = -3.0
        rc, doc, _ = _st_run(d, [_st_two_sample("NR-T8", "p", wrong)])
        assert _st_by_id(doc)["NR-T8"]["status"] == "FAIL", "错值被判 PASS"
        assert rc == ac.EXIT_FAIL, rc

    @case("真缺数据仍走 DATA_MISSING（不把缺数据读成算错）")
    def _(d: Path) -> None:
        rc, doc, _ = _st_run(d, [_st_two_sample("NR-T9", "nowhere", _st_ok_declared())])
        assert _st_by_id(doc)["NR-T9"]["status"] == "DATA_MISSING", \
            _st_by_id(doc)["NR-T9"]["status"]
        assert rc == ac.EXIT_DATA_MISSING, rc

    # ---- 5. --check-mirror 端到端（旧实现连报告都写不出来） ------------- #
    @case("--check-mirror 端到端：能出报告且结论为「未判定」")
    def _(d: Path) -> None:
        data = d / "data"
        data.mkdir(parents=True, exist_ok=True)
        _st_arm(data, "p", "a", [-7.0, -7.1, -6.9])
        _st_arm(data, "p", "b", [-9.0, -9.1, -8.9])
        rc, doc, _ = _st_run(d, [_st_two_sample("NR-T10", "p", _st_ok_declared())],
                             ["--check-mirror", "--mirror", str(d / "no_mirror")])
        assert doc, "没有报告：--check-mirror 又把主流程带崩了"
        assert doc["mirror_consistent"] is None, doc["mirror_consistent"]
        assert rc == ac.EXIT_OK, f"条目全 PASS 却退出码 {rc}"
        md = (d / "report.md").read_text(encoding="utf-8")
        assert "未判定" in md, "人读报告把「未判定」写成了别的结论"

    # ---- 执行 ---------------------------------------------------------- #
    prev_level = logger.level
    saved_sha = os.environ.pop("GITHUB_SHA", None)  # 自证必须与外部 CI 变量无关
    logger.setLevel("WARNING")
    failed = 0
    try:
        with tempfile.TemporaryDirectory(prefix="verify_numbers_selftest_") as td:
            print(f"verify_numbers --self-test：{len(cases)} 条用例")
            for idx, (name, fn) in enumerate(cases, 1):
                root = Path(td) / f"c{idx}"
                root.mkdir(parents=True, exist_ok=True)
                try:
                    fn(root)
                except AssertionError as exc:
                    failed += 1
                    print(f"  [{idx}/{len(cases)}] FAIL {name} —— {exc}")
                except Exception as exc:  # noqa: BLE001 - 用例自身抛错同样是失败
                    failed += 1
                    print(f"  [{idx}/{len(cases)}] FAIL {name} —— 用例自身抛 "
                          f"{exc.__class__.__name__}: {exc}")
                else:
                    print(f"  [{idx}/{len(cases)}] PASS {name}")
    finally:
        logger.setLevel(prev_level)
        if saved_sha is not None:
            os.environ["GITHUB_SHA"] = saved_sha
    if failed:
        print(f"自证失败 {failed}/{len(cases)} —— 门禁不承重，不得据此判仓库")
        return ac.EXIT_FAIL
    print(f"自证通过 {len(cases)}/{len(cases)}")
    return ac.EXIT_OK


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _resolve(p: str, default: Path) -> Path:
    if not p:
        return default
    cand = Path(p)
    if cand.is_absolute():
        return cand
    if cand.exists():
        return cand.resolve()
    return (ac.REPO_ROOT / cand).resolve()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="注册表驱动的数字复算器")
    ap.add_argument("--registry", default=str(ac.REGISTRY_PATH), help="注册表 JSON")
    ap.add_argument("--data-root", default=str(ac.RESULTS_DIR), help="原始数据根（repo results）")
    ap.add_argument("--mirror", default=str(ac.MIRROR_ROOT), help="镜像数据根（backup results）")
    ap.add_argument("--only", default="", help="仅校验指定条目，逗号分隔，如 NR-1,NR-3")
    ap.add_argument("--strict", action="store_true", help="存在 PENDING/PLANNED 即退出码 4")
    ap.add_argument("--check-mirror", action="store_true", help="执行 repo↔backup 双源一致性校验")
    ap.add_argument("--run-tests", action="store_true", help="复跑 pytest 核实测试数量（NR-19）")
    ap.add_argument("--code-check-only", action="store_true",
                    help="仅校验 code_check 类条目（架构审查 D4：把「口径 vs 代码」一致性"
                         "做成可独立跑的原子，供提交前门禁调用）")
    ap.add_argument("--overwrite", action="store_true", help="允许覆盖同名报告（默认防覆盖另存）")
    ap.add_argument("--target-sha", default="",
                    help="拟提交/编辑目标版本 SHA（40 位小写十六进制）；写入报告抬头 "
                         "editorial_target，证明报告对应哪批字节（不给则显式「未 pin」）")
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "number_verification_report.json"))
    ap.add_argument("--self-test", action="store_true",
                    help="跑内置自证用例（合成注册表/数据/镜像），证明本门禁不空转；"
                         "不读仓库数据，可与真实复算并存于 CI")
    return ap


def _sources_present(entry: Dict[str, Any], data_root: Path) -> bool:
    """条目所需数据源是否至少命中一个文件。

    只用于区分「数据缺失」与「数字算错」：任一取数模式命中即视为有数据可复算。
    没有 sources 的条目（如纯 code_check）不适用此判据，一律视为有数据。

    🔴 2026-11-06 审计缺陷（误诊）：旧实现只读 ``src.get("glob")``，而注册表里
    ``globs`` 有 135 处（多批次并集，如 NR-1 的 60 种子跨两个批次落盘）、
    ``file`` 有 31 处。用 ``globs`` 登记的条目**永远被判成「没有数据」**，于是
    「登记缺 role=b」这类**登记缺陷**被报成
    「数据源缺失：本数据包不含该条目所需的任何结果文件」并以退出码 3 结束 ——
    数据明明都在盘上（实测：只有角色 a 的 NR-1 被这么判）。这正是本模块反复
    警告的「把门禁失败伪装成数据缺失」，只不过这次伪装的是**登记错误**。
    现在与 ``_collect_source`` 用同一套模式解析（``_source_patterns`` + ``file``）。
    """
    srcs = entry.get("sources") or []
    if not isinstance(srcs, list) or not srcs:
        return True
    for src in srcs:
        if not isinstance(src, dict):
            continue
        for pat in _source_patterns(src):
            try:
                if ac.resolve_glob(data_root, pat):
                    return True
            except Exception:  # noqa: BLE001 - glob 解析异常不阻断，交由复算阶段处理
                continue
        rel = src.get("file")
        if rel:
            try:
                if _resolve_file(data_root, rel).exists():
                    return True
            except OSError:
                continue
    return False


def _crash_reason(exc: BaseException, fatal_read: bool = False) -> str:
    """把「未捕获异常」翻成一句可定位的 FAIL 原因（含出错文件:行号）。

    🔴 2026-11-06 审计缺陷（一条坏数据 = 全部 191 条失去校验）：

    主循环原来的 ``except (FileNotFoundError, NotADirectoryError,
    PermissionError, OSError)`` 只接文件系统错误。可 ``recompute`` 家族还会抛
    别的：``ac.extract_field`` 的 ``KeyError``（字段被改名/缺失）、
    ``float(None)`` 的 ``TypeError``（某次跑挂了把指标写成 null）、
    ``load_json`` 的 ``JSONDecodeError``（半截文件）、``_recompute_attack`` 的
    ``doc["summary"][...]``。这些一旦发生，异常穿透 ``main()``，而报告是在
    **循环之后**才写的 ⇒ 产物是一段 traceback，**一份报告都不产出**，
    其余条目连 PASS/FAIL 都没有 —— 门禁从「有一条红」退化成「没有门禁」。

    实测（本次修复前）：把 NR-1 的一份数据文件的
    ``summary.avg_env_reward_last_50`` 写成 ``null``，整跑输出
    ``TypeError: float() argument must be a string or a real number, not
    'NoneType'`` 后退出，``--report`` 指定的文件根本不存在。

    现在：异常只让**该条**判 FAIL，理由里带异常类型、消息和出错位置；
    其余条目照常复算。``fatal_read=True`` 用于「文件在盘上但读不出」——
    那也不是数据缺失，不能退化成退出码 3。
    """
    # 定位要指到**最初的**出错帧：``raise ... from exc`` 之后本异常的最后一帧
    # 永远是那行 raise，对排查没用；沿 __cause__ 链走到根因再取帧。
    root: BaseException = exc
    while isinstance(root.__cause__, BaseException):
        root = root.__cause__
    tb = traceback.extract_tb(root.__traceback__) or traceback.extract_tb(exc.__traceback__)
    where = ""
    if tb:
        frame = tb[-1]
        where = (f"；位置 {Path(frame.filename).name}:{frame.lineno}"
                 f" {(frame.line or '').strip()}")
    head = "读取失败（文件存在但读不出）" if fatal_read else "复算抛异常"
    return (f"{head}：{exc.__class__.__name__}: {exc}{where}"
            " —— 只判该条 FAIL，其余条目继续校验")


def _data_missing_applies(analysis: str, errors: List[str], files: int,
                          sources_present: bool) -> bool:
    """「数据源缺失」判定是否适用于本次复算失败。

    数据缺失 ≠ 数字错误：缺文件必须变成**可诊断的状态**（DATA_MISSING），
    既不能让复算器抛栈崩溃（评委照 REPRODUCE.md 跑会只看到 traceback），
    也绝不能计入 PASS 或伪装成 FAIL（避免"缺数据"被读成"数字算错了"）。

    🔴 **pytest 类条目（NR-19）永不适用**（2026-10-17 踩坑）：其复算不读
    data-root，而是子进程真实复跑 pytest；sources 只是历史 junit xml 的
    `file#testsuite@attr` 引用（无 glob 键）⇒ `_sources_present` 恒 False。
    若沿用通用判据，pytest 子进程的任何失败（如解释器缺 pytest、采集错误）
    都会被吞成误导性的「数据源缺失：本数据包不含该条目所需的任何结果文件」
    （exit 3）——把**门禁失败**伪装成**数据缺失**，正是最危险的误诊形态。
    此类错误必须带真实原因走 FAIL（exit 1）。
    """
    if analysis == "pytest":
        return False
    return bool(errors) and files == 0 and not sources_present


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()

    registry_path = _resolve(args.registry, ac.REGISTRY_PATH)
    data_root = _resolve(args.data_root, ac.RESULTS_DIR)
    mirror_root = _resolve(args.mirror, ac.MIRROR_ROOT)

    if not registry_path.exists():
        # 干净 checkout / CI / 实验服务器常无 deliverables/（权威副本在工作区），
        # 此时回退到仓库内镜像登记表（两者由 check_registry_mirror 保证同步）。
        _mirror = ac.REPO_ROOT / "number_registry.json"
        if _mirror.exists():
            registry_path = _mirror

    if not registry_path.exists():
        logger.error("注册表不存在：%s", registry_path)
        return ac.EXIT_USAGE
    try:
        registry = ac.load_json(registry_path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("注册表读取/schema 错误：%s", exc)
        return ac.EXIT_USAGE
    if not isinstance(registry.get("entries"), list):
        logger.error("注册表缺少 entries 列表（schema 错误）")
        return ac.EXIT_USAGE

    if not args.code_check_only and not data_root.exists():
        logger.error("data-root 不可读：%s", data_root)
        return ac.EXIT_DATA_MISSING

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    counts = {"total": 0, "pass": 0, "fail": 0, "pending": 0, "invalid": 0, "planned": 0,
              "data_missing": 0, "unverified": 0, "crashed": 0}
    entries_out: List[Dict[str, Any]] = []
    has_fail = False

    for entry in registry["entries"]:
        if only and entry["id"] not in only:
            continue
        # D4：--code-check-only 只跑「口径 vs 代码」一致性条目，作为门禁原子。
        # 其它分析类型（benchmark / attack_report / test_count）跳过，避免把
        # 慢的全量复算拖进提交前门禁，也把"代码漂移"和"数值漂移"解耦。
        if args.code_check_only and entry.get("analysis") != "code_check":
            continue
        counts["total"] += 1
        undetermined = ""
        declared_status = entry.get("status", "PENDING")
        analysis = entry.get("analysis", "none")
        has_declared = bool(entry.get("declared"))

        computed: Dict[str, Any] = {}
        files = 0
        errors: List[str] = []
        deferred = ""
        missing = ""
        crashed = ""
        if analysis == "pytest" and not args.run_tests:
            # 测试数量只能在真实复跑时核实；未加 --run-tests 时显式标 PENDING，
            # 既不伪绿也不阻断（PENDING 不产生退出码 1）。
            deferred = "测试计数须 --run-tests 真实复跑 pytest 后核实"
        elif analysis != "none":
            # 数据缺失 ≠ 数字错误。缺文件必须变成**可诊断的状态**（DATA_MISSING），
            # 既不能让整个复算器抛栈崩溃（评委照 REPRODUCE.md 跑会只看到 traceback），
            # 也绝不能计入 PASS 或伪装成 FAIL（避免"缺数据"被读成"数字算错了"）。
            try:
                computed, files, errors = recompute(entry, data_root)
            except (FileNotFoundError, NotADirectoryError) as exc:
                # 「这份文件不存在」是缺数据，不是门禁失败 —— 与旧行为一致，
                # 也是 DATA_MISSING 通道唯一该接的情形（实测：本机 191 条里
                # 174 条属于它，绝大多数是 results/ 不入库所致）。
                computed, files, errors = {}, 0, []
                missing = (f"数据源缺失（{exc.__class__.__name__}）："
                           "本数据包不含该条目所需文件")
            except OSError as exc:
                # 其余 OSError（权限 / 被占用 / 目录当文件）意味着「文件在，但读不出」：
                # 报成数据缺失会把门禁失败伪装成「本数据包没有」，故判 FAIL。
                computed, files, errors = {}, 0, []
                crashed = _crash_reason(exc, fatal_read=True)
            except Exception as exc:  # noqa: BLE001 —— 单条失败隔离，见 _crash_reason
                computed, files, errors = {}, 0, []
                crashed = _crash_reason(exc)
            else:
                # 复算报错了，才回溯判断：是不是因为数据源根本不存在。
                # 放在报错之后再判，是为了不干扰「复算本就不依赖 data-root」的条目
                # （如源码口径类），避免把本来能 PASS 的条目误判成缺失。
                # 🔴 pytest 类条目除外（_data_missing_applies）：子进程失败是门禁
                # 失败而非数据缺失，必须带真实原因走 FAIL（2026-10-17）。
                if _data_missing_applies(analysis, errors, files,
                                         _sources_present(entry, data_root)):
                    missing = "数据源缺失：本数据包不含该条目所需的任何结果文件"
                    errors = []
                # E20：数值在容差内 ≠ 同一配置跑出来的。声明了 parameters 才核对。
                if not missing and entry.get("parameters"):
                    errors.extend(check_parameters(entry, data_root))

        if declared_status in ("INVALID", "PLANNED"):
            status = declared_status
        elif crashed:
            # 崩溃 ≠ 缺数据：该条判 FAIL 并带上异常与出错位置（见 _crash_reason）。
            # 位置必须**先于** not has_declared：复算出不来是硬失败，不能因为
            # 「declared 待补登」就降级成 PENDING —— PENDING 不阻断，等于把崩溃放过。
            status = "FAIL"
        elif not has_declared:
            # 2026-11-06 审计缺陷：`declared` 为空 ⇒ 无可复算值 ⇒ `compare()` 旧实现
            # 零比对返回 True ⇒ 判 PASS。PASS 数里因此混进 7 条空断言
            # （NR-120/121/122/180/181/182/183）；无任何数据时 NR-180~183 也判 PASS，
            # 而其余 187 条全是 DATA_MISSING —— 这是最直白的证据。
            # 处置：登记为 PENDING 的（待补登）保持 PENDING（不阻断）；
            # 声称 PASS 的 → UNVERIFIED（阻断，退出码 1），因为"我核过了"是假话。
            if declared_status == "PENDING":
                status = "PENDING"
                undetermined = "declared 待补登：该条目尚无任何可复算值"
            else:
                status = "UNVERIFIED"
                undetermined = (
                    "declared 为空：该条目未声明任何可复算值"
                    f"（登记 status={declared_status}），PASS 无断言支撑")
        elif missing:
            status = "DATA_MISSING"
        elif deferred:
            status = "PENDING"
        elif analysis == "none" and declared_status == "PENDING":
            status = "PENDING"
        elif errors:
            status = "FAIL"
        else:
            ok, _ = compare(entry, computed)
            status = "PASS" if ok else "FAIL"

        _, deltas = compare(entry, computed) if computed else (False, {})

        if status == "FAIL":
            has_fail = True
            counts["fail"] += 1
            if crashed:
                counts["crashed"] += 1
        elif status == "UNVERIFIED":
            has_fail = True
            counts["unverified"] += 1
        elif status == "PENDING":
            counts["pending"] += 1
        elif status == "PLANNED":
            counts["planned"] += 1
        elif status == "INVALID":
            counts["invalid"] += 1
        elif status == "DATA_MISSING":
            counts["data_missing"] += 1
        else:
            counts["pass"] += 1

        reason = crashed or missing or deferred or undetermined or (
            "; ".join(errors) if errors else "")
        entries_out.append({
            "id": entry["id"],
            "status": status,
            "analysis": analysis,
            "computed": computed,
            "declared": entry.get("declared", {}),
            "deltas": deltas,
            "files_scanned": files,
            "n_expected": entry.get("n_expected"),
            "reason": reason,
            "crashed": bool(crashed),
            "notes": entry.get("notes", ""),
        })
        logger.info("%-6s %s%s", entry["id"], status, f"  [{reason}]" if reason else "")

    mirror_info = None
    mirror_consistent = None
    if args.check_mirror:
        # 与条目循环共用 --only 子集：否则「只校验 NR-1」仍会把 191 条全比一遍，
        # 报告里的双源结论与 entries 列表描述的不是同一批条目。
        mirror_info = check_mirror(registry, data_root, mirror_root, only=only)
        mirror_consistent = mirror_info["consistent"]

    try:
        ed_target = _editorial_target(getattr(args, "target_sha", "") or os.environ.get("GITHUB_SHA", ""))
    except ValueError as e:
        logger.error("%s", e)
        return 2

    report = {
        "schema_version": "1.0",
        "generated_at": ac.now_iso(),
        "registry_ref": ac.rel_to_workspace(registry_path),
        "data_root": ac.rel_to_workspace(data_root),
        "mirror_root": ac.rel_to_workspace(mirror_root),
        "commit": registry.get("commit", ""),
        "editorial_target": ed_target,
        "primary_metric": registry.get("primary_metric", ""),
        "summary": counts,
        "mirror_consistent": mirror_consistent,
        "mirror": mirror_info,
        "entries": entries_out,
    }

    report_json = _resolve(args.report, ac.REPORTS_DIR / "number_verification_report.json")
    _emit_report(report, report_json, overwrite=args.overwrite)

    logger.info("汇总：total=%d PASS=%d FAIL=%d UNVERIFIED=%d PENDING=%d INVALID=%d DATA_MISSING=%d%s",
                counts["total"], counts["pass"], counts["fail"], counts["unverified"],
                counts["pending"], counts["invalid"], counts["data_missing"],
                # CRASHED 是 FAIL 的子集，只在非零时追加（不改变既有汇总行前缀，
                # doctor.py 的正则仍按 total/PASS/FAIL 取数）
                f" CRASHED={counts['crashed']}" if counts["crashed"] else "")

    if has_fail:
        if counts["fail"]:
            logger.error("存在 FAIL —— 阻断（退出码 1）")
        if counts["unverified"]:
            logger.error(
                "存在 UNVERIFIED —— %d 条登记声称已核验但 declared 为空（零断言），"
                "不得计入 PASS —— 阻断（退出码 1）", counts["unverified"])
        return ac.EXIT_FAIL
    if counts["data_missing"]:
        logger.warning("存在数据源缺失条目 —— 未复算，非数字错误（退出码 3）")
        return ac.EXIT_DATA_MISSING
    if args.strict and (counts["pending"] or counts["planned"]):
        logger.warning("--strict 下存在 PENDING/PLANNED（退出码 4）")
        return ac.EXIT_STRICT_PENDING
    logger.info("通过（退出码 0）")
    return ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
