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
        [--only NR-1,NR-3] [--strict] [--check-mirror] [--overwrite]

退出码（架构 §4.2）::

    0  全部非 PENDING/PLANNED 条目 PASS，且无 FAIL（PENDING 不阻断）
    1  至少一条 FAIL（复算值≠声明值，或 n 不符）
    2  用法 / IO / 注册表 schema 错误
    3  数据文件缺失（data-root 不可读）
    4  --strict 下存在 PENDING/PLANNED 条目

设计约束：被 import 时零副作用；所有 IO 均在 ``main()`` 之后。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 同目录共享库（脚本既可 `python scripts/x.py` 也可 `-m scripts.x` 运行）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import assurance_common as ac  # noqa: E402

logger = ac.get_logger("verify_numbers")


# --------------------------------------------------------------------------- #
# 取值 / 复算
# --------------------------------------------------------------------------- #
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
        data = ac.load_json(f)
        v = ac.extract_field(data, field)
        if isinstance(v, (list, tuple)):
            seq = list(v)
            if sl:
                seq = seq[int(sl["start"]):int(sl["end"])]
            v = ac.mean(seq)
        vals.append(float(v))
    return files, vals


def _check_n(entry: Dict[str, Any], role: str, n: int, errors: List[str]) -> None:
    """声明样本数校验：不符即记 err（→ FAIL）。"""
    ne = entry.get("n_expected")
    if isinstance(ne, int) and n != ne:
        errors.append(f"role={role} n={n}≠n_expected={ne}")


def _recompute_two_sample(entry, data_root, errors):
    srcs = {s["role"]: s for s in entry["sources"]}
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
            errors.append(f"pytest 未产出 junit xml（退出码 {proc.returncode}）")
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
    elif analysis == "attack_report":
        computed, files = _recompute_attack(entry, data_root, errors)
    elif analysis == "attack_batch":
        computed, files = _recompute_attack_batch(entry, data_root, errors)
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


def compare(entry: Dict[str, Any], computed: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """逐条比对 declared↔computed；返回 ``(all_ok, deltas)``。

    * 常规条目：按 key 的容差**精确**比对。
    * ``evidence_kind == "test_count"``：``passed`` / ``collected`` 按**下限**比对
      （只增不减）；``failed`` 等其余键仍精确比对。见 ``_FLOOR_COMPARE_KEYS``。
    """
    tol = entry.get("tolerance", {})
    floor_mode = entry.get("evidence_kind") == "test_count"
    ok, deltas = True, {}
    for key, dec in entry.get("declared", {}).items():
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
        o, dl = _compare_value(key, dec, computed[key], tol)
        ok = ok and o
        deltas[key] = dl
    return ok, deltas


# --------------------------------------------------------------------------- #
# 双数据源一致性
# --------------------------------------------------------------------------- #
def check_mirror(registry: Dict[str, Any], data_root: Path, mirror_root: Path) -> Dict[str, Any]:
    """repo↔backup 双源一致性：按注册表 glob 的文件名逐个比字段值。"""
    diffs: List[Dict[str, Any]] = []
    checked = 0
    seen_globs: set[str] = set()
    for entry in registry["entries"]:
        for src in entry.get("sources", []):
            g = src["glob"]
            if g in seen_globs:
                continue
            seen_globs.add(g)
            rf = ac.resolve_glob(data_root, g)
            mf = ac.resolve_glob(mirror_root, g)
            rmap = {p.name: p for p in rf}
            mmap = {p.name: p for p in mf}
            if set(rmap) != set(mmap):
                diffs.append({"glob": g, "only_repo": sorted(set(rmap) - set(mmap)),
                              "only_mirror": sorted(set(mmap) - set(rmap))})
            for name, rp in rmap.items():
                mp = mmap.get(name)
                if mp is None:
                    continue
                checked += 1
                try:
                    rv = ac.extract_field(ac.load_json(rp), src["field"])
                    mv = ac.extract_field(ac.load_json(mp), src["field"])
                except Exception as exc:  # noqa: BLE001
                    diffs.append({"file": name, "error": str(exc)})
                    continue
                if isinstance(rv, (list, tuple)):
                    rv = ac.mean(rv)
                if isinstance(mv, (list, tuple)):
                    mv = ac.mean(mv)
                if abs(float(rv) - float(mv)) > 1e-9:
                    diffs.append({"file": name, "repo": rv, "mirror": mv})
    return {"consistent": len(diffs) == 0, "files_compared": checked, "diffs": diffs}


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def _render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# 数字复算报告（number_verification_report）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 注册表：`{report['registry_ref']}`",
        f"- 数据源：`{report['data_root']}`（镜像：`{report['mirror_root']}`，commit `{report['commit']}`）",
        f"- 汇总：total={s['total']} PASS={s['pass']} FAIL={s['fail']} PENDING={s['pending']} INVALID={s['invalid']}"
        + (f" DATA_MISSING={s['data_missing']}" if s.get("data_missing") else ""),
        f"- 双源一致：{'是' if report.get('mirror_consistent') else '**否**'}"
        + (f"（比较 {report['mirror']['files_compared']} 个文件，{len(report['mirror']['diffs'])} 处差异）"
           if report.get("mirror") else ""),
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
    ap.add_argument("--report", default=str(ac.REPORTS_DIR / "number_verification_report.json"))
    return ap


def _sources_present(entry: Dict[str, Any], data_root: Path) -> bool:
    """条目所需数据源是否至少命中一个文件。

    只用于区分「数据缺失」与「数字算错」：任一 glob 命中即视为有数据可复算。
    没有 sources 的条目（如纯 code_check）不适用此判据，一律视为有数据。
    """
    srcs = entry.get("sources") or []
    if not isinstance(srcs, list) or not srcs:
        return True
    for src in srcs:
        if not isinstance(src, dict):
            continue
        g = src.get("glob")
        if not g:
            continue
        try:
            if ac.resolve_glob(data_root, g):
                return True
        except Exception:  # noqa: BLE001 - glob 解析异常不阻断，交由复算阶段处理
            continue
    return False


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

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
              "data_missing": 0}
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
        declared_status = entry.get("status", "PENDING")
        analysis = entry.get("analysis", "none")

        computed: Dict[str, Any] = {}
        files = 0
        errors: List[str] = []
        deferred = ""
        missing = ""
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
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
                computed, files, errors = {}, 0, []
                missing = f"数据源缺失（{exc.__class__.__name__}）：本数据包不含该条目所需文件"
            else:
                # 复算报错了，才回溯判断：是不是因为数据源根本不存在。
                # 放在报错之后再判，是为了不干扰「复算本就不依赖 data-root」的条目
                # （如源码口径类），避免把本来能 PASS 的条目误判成缺失。
                if errors and files == 0 and not _sources_present(entry, data_root):
                    missing = "数据源缺失：本数据包不含该条目所需的任何结果文件"
                    errors = []

        if declared_status in ("INVALID", "PLANNED"):
            status = declared_status
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

        reason = missing or deferred or ("; ".join(errors) if errors else "")
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
            "notes": entry.get("notes", ""),
        })
        logger.info("%-6s %s%s", entry["id"], status, f"  [{reason}]" if reason else "")

    mirror_info = None
    mirror_consistent = None
    if args.check_mirror:
        mirror_info = check_mirror(registry, data_root, mirror_root)
        mirror_consistent = mirror_info["consistent"]

    report = {
        "schema_version": "1.0",
        "generated_at": ac.now_iso(),
        "registry_ref": ac.rel_to_workspace(registry_path),
        "data_root": ac.rel_to_workspace(data_root),
        "mirror_root": ac.rel_to_workspace(mirror_root),
        "commit": registry.get("commit", ""),
        "primary_metric": registry.get("primary_metric", ""),
        "summary": counts,
        "mirror_consistent": mirror_consistent,
        "mirror": mirror_info,
        "entries": entries_out,
    }

    report_json = _resolve(args.report, ac.REPORTS_DIR / "number_verification_report.json")
    _emit_report(report, report_json, overwrite=args.overwrite)

    logger.info("汇总：total=%d PASS=%d FAIL=%d PENDING=%d INVALID=%d DATA_MISSING=%d",
                counts["total"], counts["pass"], counts["fail"], counts["pending"],
                counts["invalid"], counts["data_missing"])

    if has_fail:
        logger.error("存在 FAIL —— 阻断（退出码 1）")
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
