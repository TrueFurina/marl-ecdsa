#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径数字对齐检查器 —— 以登记簿为真值源的**口径漂移体检**

用法：
    python scripts/pre-commit/caliber_check.py [--cached] [--strict] [文件列表...]
退出码：
    0 = 无「未豁免漂移」（默认行为；漂移仅打印为警示）
    1 = ``--strict`` 下存在未豁免漂移

--------------------------------------------------------------------------------
历史与定位（2026-09-28 重写，勿删这段说明）
--------------------------------------------------------------------------------
本脚本原名「口径数字对齐检查器 — pre-commit 门禁」，但复查发现它三重失效：

1. **死门禁**：``.git/hooks/pre-commit`` 的 5 步（密钥/诚实口径/作废令牌/结构守卫/
   测试文件禁改）与 ``.github/workflows/ci.yml`` **都没有调用它** —— 它从未真正跑过。
2. **正则瞎**：旧式样 ``n\\s*=\\s*(\\d+)\\s*(?:seeds|samples|runs|episodes)``
   **匹配不到** ``n=22/组``、``n=22 种子`` 这类中文写法，而这正是本项目作废口径的
   实际书写形式。
3. **无真值源**：旧实现只是把每处像指标的数字打印一遍（连 ``(\\d+(\\.\\d+)?)\\s*%``
   这种泛匹配都在内），一旦改为 fail-closed 会把**每一次提交**全拦死 ——
   所以它当年只能 ``return 0  # 警告而非拦截``。这不是懒，是结构上无法收紧。

现在改为**高精度、可机验、真值驱动**的体检，只查两类能对上权威真值的口径族：

* **样本量族** ``n=NN 种子 / seeds / 组 / group`` → 必须等于登记簿的 n；
* **测试数族** ``NN passed`` → 必须等于登记簿 NR-19 的下限式表述。

百分比族**不在此处**查：它已由 ``scripts/scan_void_tokens.py`` 的作废令牌
（``29.2`` / ``0.126`` 等，含 ``needs_review`` 降级机制）覆盖，重复实现只会
制造两套口径。真值一律从**权威登记簿**读，不手抄、不落第二份。

严重度：命中行若含「作废 / 历史快照 / 预警 / 旧口径 / 已被取代 …」等**口径豁免
标记**（与 ``scan_void_tokens`` 的 ``context_markers.mention`` 同源），
判为 ``[豁免]``，不计入 ``--strict`` 的失败。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# 真值源：权威登记簿（仓库外 deliverables/ 优先，仓库内镜像兜底）
# --------------------------------------------------------------------------- #
_REPO = Path(__file__).resolve().parents[2]
_WORKSPACE = _REPO.parent
REGISTRY_CANDIDATES = [
    _WORKSPACE / "deliverables" / "number_registry.json",   # 权威
    _REPO / "number_registry.json",                          # 入库镜像
]

#: 只检查这些扩展名（代码里的数字是真值源，不检）
DOC_EXT = {".md", ".txt", ".docx", ".pdf", ".html", ".htm", ".pptx"}

#: 样本量族：``n=71`` / ``n=22 种子`` / ``n=22/组`` / ``n=22 seeds/group``
_RE_SAMPLE = re.compile(
    r"n\s*=\s*(\d+)\s*(?:个)?\s*(?:种子|seeds?|组|groups?|samples?|runs?|episodes?|/"
    r"(?:组|group))", re.I)
#: 测试数族：``1624 passed`` / ``1624 个测试通过``
_RE_TESTS = re.compile(r"(\d{3,5})\s*(?:passed|个测试通过|个测试用例全部通过|tests passed)", re.I)

#: 口径豁免标记（与 scan_void_tokens 的 mention 同源；此处内联一份常量，
#: 避免本体检脚本依赖 scanning 运行时，缺失配置时仍可独立工作）
EXEMPT_MARKERS = (
    "作废", "历史快照", "预警", "旧口径", "口径混用", "口径错误", "已被取代", "取代",
    "勘误", "已修正", "曾写作", "原写作", "早期", "当时口径", "小样本估计", "无出处",
    "不得声称", "不得宣称", "不得表述为", "不可表述为", "排除", "未使用", "禁用",
    "禁止", "应改为", "所谓", "待核", "待补", "溯源档", "作废值", "非全量", "推算",
)


def load_registry() -> dict:
    """读取登记簿；两处都缺时返回空 dict（体检降级为「无真值」并明示）。"""
    for p in REGISTRY_CANDIDATES:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def _entry(reg: dict, nid: str):
    ents = reg.get("entries", reg) if isinstance(reg, dict) else reg
    if isinstance(ents, dict):
        return ents.get(nid)
    for e in ents or []:
        if isinstance(e, dict) and e.get("id") == nid:
            return e
    return None


def _dig(obj, *keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def authoritative_facts(reg: dict) -> dict:
    """从登记簿抽出可机验真值。

    * ``n_universe``：**全部**条目的样本量取值集合 —— 本项目并行存在多种合法样本量
      （NR-1 收敛=71 / E1·E3=30 / 消融=10 / NR-29=60 …），所以"样本量"的合法判据
      **不是「等于 71」**，而是**「落在登记簿出现过的取值集合内」**：落在集合外即
      无出处口径（已作废的 n=22 正属此列）。
    * ``tests_floor``：NR-19 下限式表述的阈值（``claim`` 里的 ``1600+``）；低于它即漂移。
    """
    ents = reg.get("entries", reg) if isinstance(reg, dict) else reg
    if isinstance(ents, dict):
        ents = list(ents.values())
    ents = [e for e in (ents or []) if isinstance(e, dict)]

    ns: set = set()
    for e in ents:
        v = e.get("n_expected")
        if isinstance(v, int):
            ns.add(v)
        dec = e.get("declared")
        if isinstance(dec, dict):
            for k in ("n", "n_a", "n_b", "n_seeds", "seeds"):
                if isinstance(dec.get(k), int):
                    ns.add(dec[k])

    floor = None
    for e in ents:
        if e.get("id") == "NR-19":
            m = re.search(r"(\d{3,5})\s*\+", str(e.get("claim", "")))
            floor = int(m.group(1)) if m else _dig(e, "declared", "passed")
            break
    return {"n_universe": ns, "tests_floor": floor, "registry_found": bool(ents)}


def is_exempt(line: str) -> bool:
    return any(mk in line for mk in EXEMPT_MARKERS)


def scan_text(text: str) -> list:
    """返回 ``[(行号, 口径族, 值, 是否豁免, 原行)]``。"""
    out = []
    for idx, line in enumerate(text.splitlines(), start=1):
        for m in _RE_SAMPLE.finditer(line):
            out.append((idx, "sample_size", int(m.group(1)), is_exempt(line), line.strip()))
        for m in _RE_TESTS.finditer(line):
            out.append((idx, "tests", int(m.group(1)), is_exempt(line), line.strip()))
    return out


def gather_files(args) -> list:
    if args.cached:
        import subprocess
        try:
            raw = subprocess.check_output(
                ["git", "diff", "--cached", "-z", "--name-only", "--diff-filter=ACM"],
                stderr=subprocess.DEVNULL)
            names = [f for f in raw.decode("utf-8", "replace").split("\x00") if f]
        except Exception:
            names = []
        files = [Path(x) for x in names]
    elif args.files:
        files = [Path(x) for x in args.files]
    else:
        files = [p for p in Path(".").rglob("*") if p.is_file()]
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
            ".mpl_cache", ".pytest_cache", "backup"}
    return [f for f in files
            if f.suffix.lower() in DOC_EXT and not (skip & set(f.parts))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="口径漂移体检（登记簿驱动）")
    ap.add_argument("--cached", action="store_true", help="只检查 git 暂存区文件")
    ap.add_argument("--strict", action="store_true",
                    help="存在未豁免漂移时 exit 1（默认仅警示，不阻断）")
    ap.add_argument("files", nargs="*", help="指定文件列表")
    args = ap.parse_args(argv)

    reg = load_registry()
    facts = authoritative_facts(reg)
    if not facts["registry_found"]:
        print("⚠️ 未找到登记簿（deliverables/number_registry.json 或仓库镜像）——"
              "本次体检无真值源，跳过漂移判定。")
    else:
        print(f"真值源：登记簿（合法样本量集合={sorted(facts['n_universe'])}，"
              f"测试数下限={facts['tests_floor']}）")

    drift, exempt = [], []
    for f in gather_files(args):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, family, value, ex, line in scan_text(text):
            if family == "sample_size":
                uni = facts["n_universe"]
                if not uni or value in uni:
                    continue
                shown = f"不在登记簿合法集合 {sorted(uni)} 内"
            else:
                floor = facts["tests_floor"]
                if floor is None or value >= floor:
                    continue
                shown = f"低于下限 {floor}"
            (exempt if ex else drift).append((f, lineno, family, value, shown, line[:120]))

    for f, lineno, family, value, auth, line in exempt:
        print(f"[豁免] {f}:{lineno}: {family}={value}（真值 {auth}） — {line}")
    for f, lineno, family, value, auth, line in drift:
        print(f"[漂移] {f}:{lineno}: {family}={value} ≠ 真值 {auth} — {line}")

    print(f"\n合计：未豁免漂移 {len(drift)} 条，已豁免 {len(exempt)} 条")
    if drift and args.strict:
        print("❌ --strict：存在未豁免口径漂移")
        return 1
    if drift:
        print("⚠️ 存在未豁免口径漂移（默认不阻断；如需阻断请加 --strict，"
              "或为该行补口径豁免标记）")
    else:
        print("✅ 口径体检通过（无未豁免漂移）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
