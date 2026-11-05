#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_evidence_closure.py —— 实验证据闭合门禁（fail-closed）
=================================================================

为什么要有这个脚本（仓库侧根因）
--------------------------------
仓库已有的两道数字治理各管一段，但**都不管"没跑完的算不算通过"**：

* ``verify_numbers.py`` —— 管"声明值是否算得对"（复算 declared vs computed）；
  它假定结果文件本身是完整的。若某臂只跑了 100/500 回合，复算依然自洽，
  于是"没跑完"可以一路绿灯通过复算。
* ``check_registry_mirror.py`` —— 管"权威源与镜像是否一致"。

缺口因此是：**完成度（closure）没有任何自动化门禁**。这与 2026-10-18
REA 源码对账中发现的规约同源——``docs/reconstruction-readiness.md``：

    fail / unknown / unsupported / truncated / skipped **永不聚合成 pass**

本脚本把这条规约落到本仓库的结果文件上，只做一件事：**证明"通过"是有证据的**。

五类判定（status 沿用 REA 词汇）
--------------------------------
======== ==================== ==================================================
status   reason_code          触发条件
======== ==================== ==================================================
pass     ``closed``           回合数组长度 == 声明回合数，且数值非退化
truncated ``length_mismatch`` 声明 500 回合、数组只有 100 → **截断**，不是通过
fail     ``zero_filled``     summary 指标 == 0 而底层数组缺失/为空 → 用 0 冒充未知
unknown  ``no_evidence``      声明了回合数但没有任何回合数组 → 无证据，不算通过
unknown  ``degenerate``      整列恒定（典型：8000 回合合作率全是 0.0）→ 疑似指标未接
unknown  ``invalid_declaration`` 声明了回合数却读不成正整数（``0`` / ``"abc"`` / 对象）→ 读不懂 ≠ 没声明
unknown  ``malformed_column`` 某列存在但不是数值数组（字符串 / null / 嵌套）→ 有东西但读不懂
unknown  ``not_an_object``   JSON 顶层不是对象（数组 / 标量）→ 无法判断闭合
n/a      ``not_a_run``       汇总/报告类文件（无 config 回合声明、无回合数组）
n/a      ``summary_only``    仅 ``--require-trace`` 下：只有汇总、无逐回合证据
======== ==================== ==================================================

2026-11-06 补的四条，都是同一族缺陷——**读不懂的东西被当成"没有"**：

* ``n_episodes`` 只认 ``int``：``500.0``（numpy 除法产物）与 ``"500"``（序列化
  常见）当场退化成"没声明"，于是 100/500 的截断以 ``pass: undeclared`` 出线；
* 非数值列被 ``if arr`` 静默丢出 ``usable``：函数注释写着"宁可 unknown，不猜"，
  实际行为是"当作这列不存在"；
* 空数组同样被丢掉：声明 500 却给 ``[]`` 是 0/500，属**截断**而非"缺这列"；
* ``scan_root`` 对顶层非对象的 JSON 直接 ``continue``：文件既不计数也不留记录，
  输出里的"扫描 N 个 JSON"从此不再等于目录里的文件数。

``not_applicable`` **不计入分母**——2026-10-18 实测：results/ 5878 个 JSON 里
3592 个是汇总报告，若一并算 unknown，"没跑完"的真实信号（195 条）会被淹没。

**聚合规则（本脚本的核心）**：``complete = (适用样本 > 0 and fail == 0
and truncated == 0 and unknown == 0)``。任何一个 unknown 都把 ``complete``
按死为 False——不允许"大部分通过所以算通过"。

偏序比较（不输出总分）
----------------------
``--compare`` 不复用"算一个总分排名"的做法。做法是：

1. 按文件名剥 ``_seed<数字>`` 得到臂名（arm），种子取 ``config.seed``；
2. 仅在两臂**共有种子**上做逐种子配对，数 wins / losses / ties；
3. 种子集不齐时整对标 ``incomparable``，并列出缺失种子；
4. 输出里 ``total_score`` 恒为 ``None``，``ranking_emitted`` 恒为 ``False``。

理由：臂 A 跑了 60 个种子、臂 B 只跑 3 个，任何"总分"都是把不等样本量
压成一个标量，等于用全序掩盖偏序。宁可报"不可比"。

用法
----
::

    python -X utf8 scripts/check_evidence_closure.py                    # 扫 results/
    python -X utf8 scripts/check_evidence_closure.py --root results/ablation
    python -X utf8 scripts/check_evidence_closure.py --strict           # unknown 也判失败
    python -X utf8 scripts/check_evidence_closure.py --compare 'results/ablation/*.json'
    python -X utf8 scripts/check_evidence_closure.py --self-test        # 自证非空洞
    python -X utf8 scripts/check_evidence_closure.py --json-out ../deliverables/closure_ledger.json

退出码（与 assurance_common 一致）
----------------------------------
    0  全部 pass（``complete = True``）
    1  存在 fail / truncated（禁止作为"通过"引用）
    2  用法 / 参数错误
    3  --root 不可读或无 JSON；``--compare`` 一条都没比对到
    4  --strict 下存在 unknown

设计约束：被 import 时零副作用；所有 IO 均在 ``main()`` 之后。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# 同目录共享库（脚本既可 `python scripts/x.py` 也可 `-m scripts.x` 运行）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import assurance_common as ac  # noqa: E402

logger = ac.get_logger("check_evidence_closure")

# --------------------------------------------------------------------------- #
# 契约常量（改这里 = 改契约，必须同步 tests/test_check_evidence_closure.py）
# --------------------------------------------------------------------------- #

#: 回合级数组：长度必须严格等于声明回合数。
EPISODE_ARRAYS: Tuple[str, ...] = (
    "episode_rewards",
    "env_rewards",
    "cooperation_rates",
    "betrayal_rates",
    "lambda_history",
)

#: summary 指标 → 其证据数组。summary 为 0 而数组缺失/为空 = 零填充。
SUMMARY_BINDINGS: Dict[str, Tuple[str, ...]] = {
    "avg_reward": ("episode_rewards",),
    "avg_env_reward": ("env_rewards",),
    "avg_cooperation_rate": ("cooperation_rates",),
    "avg_betrayal_rate": ("betrayal_rates",),
}

#: 声明回合数的候选字段（先 config 后 summary）。
DECLARED_KEYS: Tuple[str, ...] = ("n_episodes", "total_episodes")

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_TRUNCATED = "truncated"
STATUS_UNKNOWN = "unknown"
#: 报告/汇总类文件：既没声明回合数也没有回合数组——不是"没跑完"，是"不适用"。
#: 单列一类并从分母中排除，否则 3000+ 个汇总文件会把真实信号淹掉（2026-10-18 实测教训）。
STATUS_NA = "not_applicable"

#: 退化判定：整列取值种类 <= 1 且长度 >= 该阈值，才值得报（短数组噪声大）。
#: 哪些"恒列"属结构性（见 ``_structurally_constant``）在此阈值之上仍需豁免。
DEGENERATE_MIN_LEN = 100

_SEED_RE = re.compile(r"^(?P<arm>.+?)[_-]seed(?P<seed>\d+)$")
_DECLARED_NUM_RE = re.compile(r"^\s*\+?(\d+)\s*$")


def _as_episode_count(value: Any) -> Optional[int]:
    """把声明值读成正整数；读不出返回 ``None``。

    2026-11-06 实测：只认 ``int`` 会让 ``500.0``（numpy 除法 / ``/`` 的产物）与
    ``"500"``（配置被序列化成字符串）**当场变成"没有声明"**，再被第 2 条判成
    ``pass: undeclared`` —— 100/500 的截断就这么通过了。数字就是数字，
    写法不同不改变它是不是一条声明；写成 ``0`` / ``"abc"`` / ``{}`` 才是真的读不懂。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        match = _DECLARED_NUM_RE.match(value)
        if match:
            parsed = int(match.group(1))
            return parsed if parsed > 0 else None
    return None


def _rel(path: Path, root: Path) -> str:
    """尽量输出相对路径；跨盘 / 越界时退回绝对路径。"""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def _declared_episodes(doc: Dict[str, Any]) -> Tuple[Optional[int], str, List[str]]:
    """取声明回合数、出处，以及"写了但读不懂"的声明。

    出处很重要：``config.n_episodes`` 是"这次运行打算跑多少"，属强声明；
    根级 ``n_episodes`` 常见于汇总报告（只是转述别人的回合数），属弱声明。

    第三项 ``problems`` 记录**字段存在、值不为 null、却解析不成正整数**的项。
    旧实现把这些字段当"没声明"，等于把读不懂的声明改写成"无需闭合"，再交给
    ``undeclared`` 放行——读不懂与没写是两件事，不能互相顶替。
    ``null`` 仍按"没写"处理（JSON 里的 null 就是没有值）。
    """
    problems: List[str] = []
    for holder in ("config", "summary"):
        block = doc.get(holder)
        if not isinstance(block, dict):
            continue
        for key in DECLARED_KEYS:
            if key not in block or block[key] is None:
                continue
            value = _as_episode_count(block[key])
            if value is None:
                problems.append(f"{holder}.{key}={block[key]!r}")
                # 强声明读不懂就到此为止：退到低优先级字段等于换一个数字凑出处。
                return None, holder, problems
            return value, holder, problems
    for key in DECLARED_KEYS:
        if key not in doc or doc[key] is None:
            continue
        value = _as_episode_count(doc[key])
        if value is None:
            problems.append(f"根级 {key}={doc[key]!r}")
            return None, "root", problems
        return value, "root", problems
    return None, "", problems


def _numeric_list(value: Any) -> Optional[List[float]]:
    """数组里若混入非数值就整列不认（宁可 unknown，不猜）。"""
    if not isinstance(value, list):
        return None
    out: List[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        out.append(float(item))
    return out


def _structurally_constant(doc: Dict[str, Any], array_name: str) -> bool:
    """该列恒定是否由配置决定（而非指标没接上）。

    两条实测依据（2026-10-18，results/ 全量扫描）：

    * ``betrayal_rates``：``selfish_ratio=0`` 的臂不可能出现背叛，恒 0 是定义使然；
    * ``lambda_history``：自适应 λ 只在 ``bc_marl`` 布线上更新，``pure_marl``
      臂即使 ``adaptive_lambda=true`` 也保持初值 0.1（配置与行为不一致，但
      不属于"缺指标"）。
    """
    config = doc.get("config") if isinstance(doc.get("config"), dict) else {}
    if array_name == "betrayal_rates":
        return "selfish_ratio" in config and not config["selfish_ratio"]
    if array_name == "lambda_history":
        if config.get("mode") not in (None, "bc_marl"):
            return True
        # 消融臂显式把 λ 压到 0（如 e2_lam0.00_*）：恒 0 是实验设计，不是缺指标。
        if "lambda_weight" in config and not config["lambda_weight"]:
            return True
        if config.get("adaptive_lambda") is False:
            return True
    return False


def inspect_document(doc: Dict[str, Any], require_trace: bool = False) -> Dict[str, Any]:
    """对单个结果文档出判定。纯函数，便于单测直接调用。

    :param require_trace: 为 True 时，只有汇总没有逐回合数组的文件记 ``unknown``
        （审计口径）；默认记 ``not_applicable``（不纳入闭合分母）。
    :returns: ``{status, reason_code, detail, declared, actual}``
    """
    declared, source, problems = _declared_episodes(doc)
    present = {name: _numeric_list(doc.get(name)) for name in EPISODE_ARRAYS}
    # 三种"列状态"必须分开，混为一谈就是这次修的缺陷：
    #   arrays   —— 键在、值是数值数组（**含空数组**，空数组要参与长度核对）；
    #   nonempty —— 非空数值数组（零填充/退化判定只看它）；
    #   malformed—— 键在、但读不成数值数组（字符串 / null / 嵌套）。这是"有东西
    #               却读不懂"，与"这列不存在"是两件事，后者才算 no_evidence。
    arrays = {name: arr for name, arr in present.items() if arr is not None}
    nonempty = {name: arr for name, arr in arrays.items() if arr}
    malformed = [name for name in EPISODE_ARRAYS
                 if doc.get(name) is not None and present[name] is None]
    has_any_array = bool(arrays) or bool(malformed)

    # 0) 声明写了但读不懂：无法闭合。只在"这确实是个运行文件"（config 有强声明
    #    或带回合数组）时判 unknown；纯汇总报告里的怪值不该把整棵树按死。
    if problems and (source == "config" or has_any_array):
        return _verdict(STATUS_UNKNOWN, "invalid_declaration",
                        "回合数声明读不成正整数：" + "，".join(problems),
                        None, {k: len(v) for k, v in arrays.items()})

    # 1) 不是"带轨迹的运行文件"：config 未声明回合数，且无任何回合数组。
    if not (source == "config" or has_any_array):
        if require_trace and declared is not None:
            return _verdict(STATUS_UNKNOWN, "summary_only",
                            f"仅 {source} 级声明 {declared} 回合，无逐回合证据", declared, {})
        return _verdict(STATUS_NA, "not_a_run",
                        f"汇总/汇总型记录（{source + ' 级' if source else '未声明'}回合数），无逐回合数组",
                        declared, {})

    # 2) 没有声明回合数：无法闭合，但也不冤判——交给 verify_numbers 的 n 校验。
    if declared is None:
        return _verdict(STATUS_PASS, "undeclared", "有回合数组但未声明回合数；仅记录不判罚", None,
                        {k: len(v) for k, v in nonempty.items()})

    # 3) 列在、读不懂 → unknown（"unsupported 永不聚合成 pass"），不是"缺列"。
    if malformed:
        return _verdict(STATUS_UNKNOWN, "malformed_column",
                        f"声明 {declared} 回合，但 {'/'.join(malformed)} 不是数值数组"
                        "（列存在却读不出数）",
                        declared, {k: len(v) for k, v in arrays.items()})

    # 4) 声明了但没有任何回合数组 → unknown，不是 pass。
    if not arrays:
        return _verdict(STATUS_UNKNOWN, "no_evidence",
                        f"config 声明 {declared} 回合，但无任何回合数组", declared, {})

    # 5) 零填充：summary 指标恰为 0，而对应数组缺失/为空。
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    for metric, bound in SUMMARY_BINDINGS.items():
        value = summary.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if float(value) != 0.0:
            continue
        if any(nonempty.get(name) for name in bound):
            continue  # 有数组支撑，0 是真实测量值
        return _verdict(STATUS_FAIL, "zero_filled",
                        f"summary.{metric}=0 但 {'/'.join(bound)} 缺失或为空",
                        declared, {name: (len(present[name]) if present[name] is not None else None)
                                   for name in bound})

    # 6) 截断：任一回合数组长度 != 声明。空数组也算——声明 500 给 [] 是 0/500。
    mismatched = {name: len(arr) for name, arr in arrays.items() if len(arr) != declared}
    if mismatched:
        return _verdict(STATUS_TRUNCATED, "length_mismatch",
                        f"声明 {declared} 回合，实际 {mismatched}", declared, mismatched)

    # 7) 退化：整列恒定（典型是 8000 回合合作率全 0）。
    #    例外：由配置决定的恒列（见 _structurally_constant）不算退化。
    structural: List[str] = []
    for name, arr in nonempty.items():
        if len(arr) < DEGENERATE_MIN_LEN or len(set(arr)) > 1:
            continue
        if _structurally_constant(doc, name):
            structural.append(f"{name} 恒为 {arr[0]!r}（结构性）")
            continue
        return _verdict(STATUS_UNKNOWN, "degenerate",
                        f"{name} 全列恒为 {arr[0]!r}（{len(arr)} 回合）——疑似指标未接入",
                        declared, {name: len(arr)})

    detail = f"{len(arrays)} 个回合数组长度均 == {declared}"
    if structural:
        detail += "；" + "；".join(structural)
    return _verdict(STATUS_PASS, "closed", detail, declared,
                    {k: len(v) for k, v in arrays.items()})


def _verdict(status: str, reason: str, detail: str,
             declared: Optional[int], actual: Any) -> Dict[str, Any]:
    return {"status": status, "reason_code": reason, "detail": detail,
            "declared_episodes": declared, "actual": actual}


def scan_root(root: Path, require_trace: bool = False) -> List[Dict[str, Any]]:
    """遍历 ``root`` 下全部 JSON，出逐文件判定。"""
    records: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            records.append({"file": _rel(path, root), "status": STATUS_UNKNOWN,
                            "reason_code": "unreadable", "detail": str(exc)[:200],
                            "declared_episodes": None, "actual": None})
            continue
        if not isinstance(doc, dict):
            # 顶层是数组/标量：读得懂，但不是本门禁能判的形态。旧实现直接 continue，
            # 文件既不计入分母也不留记录——"扫描 N 个 JSON"从此不等于文件数。
            records.append({"file": _rel(path, root), "status": STATUS_UNKNOWN,
                            "reason_code": "not_an_object",
                            "detail": f"JSON 顶层是 {type(doc).__name__}，不是对象；无法判断闭合",
                            "declared_episodes": None, "actual": None})
            continue
        verdict = inspect_document(doc, require_trace=require_trace)
        verdict["file"] = _rel(path, root)
        records.append(verdict)
    return records


# --------------------------------------------------------------------------- #
# 偏序比较：绝不输出总分
# --------------------------------------------------------------------------- #
def _arm_seed(path: Path, doc: Dict[str, Any]) -> Tuple[str, Optional[int]]:
    """臂名 + 种子。种子优先取 ``config.seed``，否则从文件名剥。"""
    match = _SEED_RE.match(path.stem)
    arm = match.group("arm") if match else path.stem
    seed: Optional[int] = None
    cfg = doc.get("config")
    if isinstance(cfg, dict) and isinstance(cfg.get("seed"), int):
        seed = int(cfg["seed"])
    elif match:
        seed = int(match.group("seed"))
    return arm, seed


def _get_metric(doc: Dict[str, Any], dotted: str) -> Optional[float]:
    node: Any = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def build_partial_order(paths: Iterable[Path], metric: str) -> Dict[str, Any]:
    """按 (arm, seed) 汇总，输出逐种子配对的偏序结果。

    **不产生任何总分 / 排名**：``total_score`` 恒 None，``ranking_emitted`` 恒 False。
    """
    by_arm: Dict[str, Dict[int, float]] = defaultdict(dict)
    # 被丢掉的样本必须留下计数：旧实现四处 ``continue`` 静默丢文件，glob 命中
    # 10 个而实际只比了 2 个，输出里看不出来（"没有一条比较"也能 exit 0）。
    skipped = {"unreadable": 0, "not_object": 0, "no_seed": 0, "no_metric": 0}
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            skipped["unreadable"] += 1
            continue
        if not isinstance(doc, dict):
            skipped["not_object"] += 1
            continue
        arm, seed = _arm_seed(path, doc)
        if seed is None:
            skipped["no_seed"] += 1
            continue
        value = _get_metric(doc, metric)
        if value is None:
            skipped["no_metric"] += 1
            continue
        by_arm[arm][seed] = value

    arms = sorted(by_arm)
    pairs: List[Dict[str, Any]] = []
    for i, left in enumerate(arms):
        for right in arms[i + 1:]:
            common = sorted(set(by_arm[left]) & set(by_arm[right]))
            only_left = sorted(set(by_arm[left]) - set(by_arm[right]))
            only_right = sorted(set(by_arm[right]) - set(by_arm[left]))
            wins = sum(1 for s in common if by_arm[left][s] > by_arm[right][s])
            losses = sum(1 for s in common if by_arm[left][s] < by_arm[right][s])
            ties = len(common) - wins - losses
            if len(common) < 2:
                relation = "incomparable"
            elif wins and not losses:
                relation = f"{left} dominates on shared seeds"
            elif losses and not wins:
                relation = f"{right} dominates on shared seeds"
            elif wins and losses:
                relation = "mixed (no order)"
            else:
                relation = "tie"
            pairs.append({
                "left": left, "right": right, "relation": relation,
                "shared_seeds": len(common),
                "left_wins": wins, "right_wins": losses, "ties": ties,
                "seeds_only_left": only_left[:12], "seeds_only_right": only_right[:12],
                "comparable": len(common) >= 2,
            })

    return {
        "metric": metric,
        "arms": {arm: {"seeds": len(seeds), "seed_list": sorted(seeds)[:12]}
                 for arm, seeds in sorted(by_arm.items())},
        "pairs": pairs,
        "skipped": skipped,
        "total_score": None,
        "ranking_emitted": False,
        "note": "偏序口径：仅共有种子配对计数；不产生总分与排名，样本量不齐即报 incomparable。",
    }


# --------------------------------------------------------------------------- #
# 自证：故意造坏夹具，缺一个没抓到就算门禁失效
# --------------------------------------------------------------------------- #
SELF_TEST_CASES: Tuple[Tuple[str, Any, str], ...] = (
    ("clean", {
        "config": {"n_episodes": 500, "seed": 1},
        "summary": {"total_episodes": 500, "avg_reward": -40.0,
                    "avg_env_reward": -45.0, "avg_cooperation_rate": 0.5},
        "episode_rewards": [float(i % 7) - 40 for i in range(500)],
        "env_rewards": [float(i % 5) - 45 for i in range(500)],
        "cooperation_rates": [0.4 + 0.001 * (i % 9) for i in range(500)],
    }, STATUS_PASS),
    ("truncated", {
        "config": {"n_episodes": 500},
        "summary": {"total_episodes": 500},
        "episode_rewards": [-40.0] * 100,
    }, STATUS_TRUNCATED),
    ("zero_filled", {
        "config": {"n_episodes": 800},
        "summary": {"total_episodes": 800, "avg_cooperation_rate": 0.0},
        "episode_rewards": [float(i) for i in range(800)],
    }, STATUS_FAIL),
    ("degenerate", {
        "config": {"n_episodes": 8000},
        "summary": {"total_episodes": 8000, "avg_cooperation_rate": 0.0},
        "episode_rewards": [float(i % 11) for i in range(8000)],
        "cooperation_rates": [0.0] * 8000,
    }, STATUS_UNKNOWN),
    ("no_evidence", {
        "config": {"n_episodes": 500},
        "summary": {"total_episodes": 500, "avg_env_reward": -30.0},
    }, STATUS_UNKNOWN),
    # 汇总报告：不该被算成"没跑完"
    ("report_only", {
        "server_up": True,
        "tabs": {"0_总览": {"charts": 3}},
    }, STATUS_NA),
    # 结构性零值：selfish_ratio=0 时 betrayal 恒 0 属定义使然，必须放过
    ("structural_zero", {
        "config": {"n_episodes": 500, "selfish_ratio": 0.0},
        "summary": {"total_episodes": 500, "avg_betrayal_rate": 0.0},
        "episode_rewards": [float(i % 9) - 30 for i in range(500)],
        "betrayal_rates": [0.0] * 500,
    }, STATUS_PASS),
    # 声明写成 500.0（numpy 除法的产物）：当成"没声明"就等于把截断放行
    ("float_declared_truncated", {
        "config": {"n_episodes": 500.0},
        "summary": {"total_episodes": 500.0},
        "episode_rewards": [-40.0] * 100,
    }, STATUS_TRUNCATED),
    # 列在、但读不成数值数组：有东西却读不懂，不许聚合成 pass
    ("malformed_column", {
        "config": {"n_episodes": 500},
        "episode_rewards": [float(i) for i in range(500)],
        "cooperation_rates": ["0.5"] * 500,
    }, STATUS_UNKNOWN),
    # 顶层是数组：读得懂，但不是本门禁能判的形态；必须留记录而非静默跳过
    ("list_root", [{"episode": i, "reward": 1.0} for i in range(3)], STATUS_UNKNOWN),
)


def run_self_test(verbose: bool = True) -> int:
    """在临时目录造夹具，断言每一类坏样本都被抓住。"""
    failures: List[str] = []
    with tempfile.TemporaryDirectory(prefix="closure_selftest_") as tmp:
        root = Path(tmp)
        for name, doc, _expected in SELF_TEST_CASES:
            (root / f"{name}.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        records = {rec["file"]: rec for rec in scan_root(root)}
        for name, _doc, expected in SELF_TEST_CASES:
            got = records.get(f"{name}.json", {})
            status = got.get("status")
            if status != expected:
                failures.append(
                    f"{name}: 期望 {expected}，实得 {status}（{got.get('reason_code')}）")
            elif verbose:
                logger.info("[自证] %-12s → %-9s %s", name, status, got.get("reason_code"))

    # 聚合规则自证：有 unknown 就不得 complete
    ledger = summarize([r for r in records.values() if r["status"] != STATUS_PASS])
    if ledger["complete"]:
        failures.append("聚合规则失效：存在非 pass 记录却判 complete=True")

    if failures:
        for item in failures:
            logger.error("[自证失败] %s", item)
        return ac.EXIT_FAIL
    logger.info("[自证] %d/%d 夹具命中，聚合规则 fail-closed 成立",
                len(SELF_TEST_CASES), len(SELF_TEST_CASES))
    return ac.EXIT_OK


# --------------------------------------------------------------------------- #
# 汇总 / 输出
# --------------------------------------------------------------------------- #
def summarize(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_TRUNCATED: 0,
              STATUS_UNKNOWN: 0, STATUS_NA: 0}
    reasons: Dict[str, int] = defaultdict(int)
    for rec in records:
        status = rec.get("status", STATUS_UNKNOWN)
        counts[status] = counts.get(status, 0) + 1
        reasons[f"{status}:{rec.get('reason_code', '')}"] += 1
    applicable = len(records) - counts[STATUS_NA]
    complete = (applicable > 0
                and counts[STATUS_FAIL] == 0
                and counts[STATUS_TRUNCATED] == 0
                and counts[STATUS_UNKNOWN] == 0)
    return {
        "complete": complete,
        "applicable": applicable,
        "summary": counts,
        "by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "rule": "fail/truncated/unknown 永不聚合成 pass；not_applicable 不计入分母",
    }


def _print_report(ledger: Dict[str, Any], records: Sequence[Dict[str, Any]],
                  limit: int = 12) -> None:
    agg = ledger["aggregation"]
    counts = agg["summary"]
    print(f"\n扫描 {len(records)} 个 JSON | 有效样本 {agg['applicable']} | "
          f"complete={agg['complete']}")
    print(f"  pass={counts[STATUS_PASS]}  fail={counts[STATUS_FAIL]}  "
          f"truncated={counts[STATUS_TRUNCATED]}  unknown={counts[STATUS_UNKNOWN]}  "
          f"不适用={counts[STATUS_NA]}")
    if agg["by_reason"]:
        print("  原因分布:")
        for reason, count in list(agg["by_reason"].items())[:10]:
            print(f"    {reason}: {count}")
    bad = [r for r in records if r["status"] != STATUS_PASS]
    if bad:
        print(f"\n前 {min(limit, len(bad))} 条非 pass：")
        for rec in bad[:limit]:
            print(f"  [{rec['status']:9}] {rec['file']}  {rec['reason_code']}  {rec['detail'][:90]}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="实验证据闭合门禁：截断/零填充/退化/无证据，一律不许算通过")
    parser.add_argument("--root", default=None, help="扫描根（默认 ac.RESULTS_DIR）")
    parser.add_argument("--compare", default=None, help="偏序比较的 glob（相对 repo 根）")
    parser.add_argument("--metric", default=ac.PRIMARY_FIELD,
                        help=f"偏序比较口径（默认 {ac.PRIMARY_FIELD}）")
    parser.add_argument("--strict", action="store_true", help="unknown 也判失败（退出码 4）")
    parser.add_argument("--require-trace", action="store_true",
                        help="审计口径：只有汇总没有逐回合数组的文件记 unknown（默认记为不适用）")
    parser.add_argument("--json-out", default=None, help="ledger 输出路径（默认不覆盖）")
    parser.add_argument("--limit", type=int, default=12, help="终端最多列几条非 pass")
    parser.add_argument("--self-test", action="store_true", help="跑内置坏夹具自证门禁非空洞")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    root = Path(args.root) if args.root else ac.RESULTS_DIR
    if not root.is_dir():
        logger.error("根目录不可读：%s", root)
        return ac.EXIT_DATA_MISSING

    records = scan_root(root, require_trace=args.require_trace)
    if not records:
        logger.error("根目录下没有可分析的 JSON：%s", root)
        return ac.EXIT_DATA_MISSING

    ledger: Dict[str, Any] = {
        "schema_version": "1",
        "generated_at": ac.now_iso(),
        "root": str(root),
        "aggregation": summarize(records),
        "records": records,
    }

    compare_broken: Optional[str] = None
    if args.compare:
        paths = sorted(ac.REPO_ROOT.glob(args.compare))
        if not paths:
            compare_broken = (f"--compare 的 glob 一个文件都没匹配到：{args.compare}"
                              f"（相对仓库根 {ac.REPO_ROOT}）")
        else:
            po = build_partial_order(paths, args.metric)
            ledger["partial_order"] = po
            if not po["arms"]:
                compare_broken = (f"--compare 匹配到 {len(paths)} 个文件，但没有一个同时具备"
                                  f"种子与口径 {args.metric}；实际比对 0 条，不计为成功"
                                  f"（丢弃统计 {po['skipped']}）")

    _print_report(ledger, records, args.limit)

    if "partial_order" in ledger:
        po = ledger["partial_order"]
        print(f"\n偏序（{po['metric']}，不输出总分）：")
        for arm, info in po["arms"].items():
            print(f"  {arm}: {info['seeds']} 个种子")
        for pair in po["pairs"]:
            print(f"  {pair['left']} vs {pair['right']}: {pair['relation']} "
                  f"(win {pair['left_wins']} / lose {pair['right_wins']} / tie {pair['ties']})")
        if any(po["skipped"].values()):
            print(f"  丢弃（未参与配对）：{po['skipped']}")

    if args.json_out:
        target = Path(args.json_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        written = ac.safe_write_json(ledger, target, overwrite=False)
        print(f"\nledger 已写入：{written}")

    if compare_broken:
        # 只比到 0 条却 exit 0，等于把"什么都没比"报成"比较完成"。
        logger.error("%s", compare_broken)
        return ac.EXIT_DATA_MISSING

    agg = ledger["aggregation"]
    if agg["summary"][STATUS_FAIL] or agg["summary"][STATUS_TRUNCATED]:
        return ac.EXIT_FAIL
    if agg["summary"][STATUS_UNKNOWN]:
        return ac.EXIT_STRICT_PENDING if args.strict else ac.EXIT_OK
    return ac.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
