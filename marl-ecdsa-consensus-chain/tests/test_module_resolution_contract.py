#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""同名模块解析契约（F13 守卫）：把「靠没有同名冲突的运气」变成「可判定的断言」。

背景
----
仓库里有 100+ 处手工 ``sys.path.insert/append``，某个名字能否被正确解析**取决于插入
顺序**。架构审查 F13 记录的风险是"靠无同名冲突的运气"。2026-09-23 实测把运气量化了：
284 个项目 ``.py`` 中**只有 5 个 basename 存在冲突**，其中只有 1 个被测试真正消费：

============================  ==================================================  ==============
basename                      两处路径                                            消费者
============================  ==================================================  ==============
analyze_all_experiments.py    ``./analyze_all_experiments.py``                    ✅ 1 个测试（裸 import）
                              ``scripts/legacy/analysis/analyze_all_experiments.py``  ✅ 1 个流水线（显式注入）
analyze_deep_tests.py         ``./analyze_deep_tests.py``                         ⬜ 无（孤儿）
                              ``scripts/legacy/analysis/analyze_deep_tests.py``
deep_test_driver.py           ``scripts/legacy/analysis/deep_test_driver.py``      ⬜ 无（孤儿）
                              ``scripts/legacy/experiments/deep_test_driver.py``
deep_test_orchestrator.py     ``scripts/legacy/analysis/…``                        ⬜ 无（孤儿）
                              ``scripts/legacy/experiments/…``
run_all.py                    ``scripts/ablation/run_all.py``                      ⚠️ 2 个测试（**均显式注入**）
                              ``scripts/benchmark/run_all.py``
============================  ==================================================  ==============

危险不在"当前解析错了"，而在**解析变了没人知道**：

* ``tests/test_analyze_all_experiments.py`` **不做任何路径注入**，完全依赖
  ``pyproject.toml`` 的 ``pythonpath = ["."]`` → 拿到仓库根那一份；另一份在
  ``scripts/legacy/analysis/``。两份只是**同逻辑的两个文件**，谁被解析到取决环境配置。
  一旦有人在其中一份里改逻辑（另一份不变），"测试通过"就不再等于"交付行为正确"。
* ``run_all`` 的两份是**有意不同**的两个脚本（消融 vs 基准），只能靠显式注入区分；
  若哪天仓库根出现 ``run_all.py``，裸 ``import run_all`` 会**静默**拿到错误的那个。

本测试**只做断言、不重构、不删文件**（拆模块/合并副本会破坏既有实验的精确复现，
且团队硬规则禁止删除）。它把四件事钉死：

1. 同名 basename 清单**冻结** —— 新增冲突必须显式更新本文件（而非静默发生）；
2. **有测试消费者的那一对副本必须语义等价**（剥掉 legacy 样板头后逐行相同）；
3. 两个消费者解析到**同一份**（测试靠 ``pythonpath=["."]``；流水线显式注入仓库根）；
4. ``run_all`` 从仓库根**不可解析**，且两个测试各自显式注入自己的目录。

另有一条"防止死灰复燃"的断言：3 对孤儿副本**至今无人引用**，若将来被接线，
它们之间已知的漂移必须先被处理 —— 届时本测试会 FAIL 提醒。

变异验证：把 ``scripts/legacy/analysis/analyze_all_experiments.py`` 的任意一行逻辑
改动（或把 ``run_all`` 两处显式注入删掉），对应断言必须 FAIL。
"""
from __future__ import annotations


import os
import re
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.9 兼容回退
from importlib.machinery import PathFinder
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# 冻结清单（改动必须是有意的：更新本文件 + commit message 说明原因）
# --------------------------------------------------------------------------

# basename -> 仓库内相对路径（排序后）
FROZEN_DUPLICATES = {
    "analyze_all_experiments.py": [
        "analyze_all_experiments.py",
        "scripts/legacy/analysis/analyze_all_experiments.py",
    ],
    "analyze_deep_tests.py": [
        "analyze_deep_tests.py",
        "scripts/legacy/analysis/analyze_deep_tests.py",
    ],
    "deep_test_driver.py": [
        "scripts/legacy/analysis/deep_test_driver.py",
        "scripts/legacy/experiments/deep_test_driver.py",
    ],
    "deep_test_orchestrator.py": [
        "scripts/legacy/analysis/deep_test_orchestrator.py",
        "scripts/legacy/experiments/deep_test_orchestrator.py",
    ],
    "run_all.py": [
        "scripts/ablation/run_all.py",
        "scripts/benchmark/run_all.py",
    ],
}

# 被 tests/ 裸 import 或显式 import 的同名模块 -> 引用它的测试文件
FROZEN_TEST_IMPORTERS = {
    "analyze_all_experiments": ["tests/test_analyze_all_experiments.py"],
    "run_all": [
        "tests/test_benchmark_main_args.py",
        "tests/test_benchmark_run_all.py",
    ],
}

# --------------------------------------------------------------------------
# 处置登记表（T7）：每个同名 basename 必须显式声明「为什么不构成缺陷」
# --------------------------------------------------------------------------
#
# FROZEN_DUPLICATES 只记录「哪些名字撞了」。撞了之后**怎么处置**此前只存在于
# 讨论与 commit message 里 —— 5 对里只有 analyze_all_experiments 那一对被 T2
# 真正校验等价，其余 4 对为何不需要校验，没有任何机器可读的记录。后果是：下一对
# 副本出现时，最省力的过测方式是往 FROZEN_DUPLICATES 里加一行了事，而"这一对
# 要不要等价"这个判断被静默跳过。
#
# 本表把该判断落成代码，kind 只有三种，每种都有既有断言背书：
#
#   equivalent     两份必须语义等价（T2 按本表参数化逐条校验，不是靠这行字）
#   explicit_path  两份**有意不同**，每个消费者都必须显式注入自己的目录（T4）
#   orphan_unused  两份无任何消费者，歧义面为零，且 T5 保证它保持无引用
#
# 交叉校验（T7）：orphan_unused 不得有消费者；explicit_path 必须有消费者；
# equivalent 必须与 SEMANTIC_EQUIVALENT_PAIR 一一对应。三张表不得互相矛盾。

DUPLICATE_DISPOSITION = {
    "analyze_all_experiments.py": {
        "kind": "equivalent",
        "reason": (
            "tests/test_analyze_all_experiments.py 裸 import 它，落到哪份由 "
            "pythonpath 决定；两份已同步为逐字节相同（25183 bytes），"
            "T2 持续校验，任何单侧修改都会 FAIL。"
        ),
    },
    "analyze_deep_tests.py": {
        "kind": "orphan_unused",
        "reason": (
            "两份逐字节相同（12277 bytes），且仓库内无任何入口 import；"
            "无消费者即无解析歧义面。T5 断言其保持无人引用。"
        ),
    },
    "deep_test_driver.py": {
        "kind": "orphan_unused",
        "reason": (
            "两份 128 vs 119 行，BASE（结果目录）一处对一处错；但 "
            "results/scalability_test 等目标目录两处都不存在 ⇒ 从未在本仓库"
            "运行过。无消费者，漂移不构成当前缺陷；T5 禁止其被接线。"
        ),
    },
    "deep_test_orchestrator.py": {
        "kind": "orphan_unused",
        "reason": (
            "两份 126 vs 118 行，PYTHON 解释器路径一处对一处错；与 driver 同属"
            "未运行过的遗留编排脚本。无消费者，T5 禁止其被接线。"
        ),
    },
    "run_all.py": {
        "kind": "explicit_path",
        "reason": (
            "两份是**有意不同**的脚本（ablation 263 行 / benchmark 359 行），"
            "不可能等价；两个测试各自在 import 前显式注入 scripts/benchmark，"
            "且仓库根不存在 run_all.py —— 均由 T4 断言。"
        ),
    },
}

_DISPOSITION_KINDS = {"equivalent", "explicit_path", "orphan_unused"}

# T2 的参数来源：凡声明 equivalent 的 basename 都必须真的被逐行校验
_EQUIVALENT_BASENAMES = sorted(
    b for b, d in DUPLICATE_DISPOSITION.items() if d["kind"] == "equivalent")

# 有测试消费者的那对副本：必须语义等价（另一份是 legacy 兼容副本）
SEMANTIC_EQUIVALENT_PAIR = {
    "name": "analyze_all_experiments",
    "root_copy": "analyze_all_experiments.py",
    "legacy_copy": "scripts/legacy/analysis/analyze_all_experiments.py",
}

# 仍在消费 analyze_all_experiments 的流水线（必须以"注入仓库根"的方式解析）
PIPELINE_CONSUMER = "scripts/legacy/experiments/run_experiment_pipeline.py"

# 3 对"孤儿"副本的 basename：允许出现的引用面只有它们自身
ORPHAN_BASENAMES = [
    "analyze_deep_tests",
    "deep_test_driver",
    "deep_test_orchestrator",
]
ORPHAN_OWN_FILES = {
    "analyze_deep_tests.py",
    "scripts/legacy/analysis/analyze_deep_tests.py",
    "scripts/legacy/analysis/deep_test_driver.py",
    "scripts/legacy/experiments/deep_test_driver.py",
    "scripts/legacy/analysis/deep_test_orchestrator.py",
    "scripts/legacy/experiments/deep_test_orchestrator.py",
}

_SCAN_EXT = (".py", ".sh", ".bat", ".yml", ".yaml", ".cfg", ".toml", ".ini")
_SKIP_DIRS = {
    ".git", ".venv", "backup", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "deliverables",
}

# legacy 移动兼容样板头（唯一被允许的副本差异）
_BOOTSTRAP_RE = re.compile(
    r"^# ===== 自动注入: 仓库根路径 \(legacy 移动兼容\) =====\n"
    r"(?:.*\n)*?"
    r"^# ===== 自动注入结束 =====\n",
    re.MULTILINE,
)

_SYS_PATH_INJECT_START_RE = re.compile(r"sys\.path\.(?:insert|append)\s*\(")


def _iter_sys_path_injects(text: str):
    """提取每个 ``sys.path.insert/append(...)`` 调用的**路径参数**原文。

    不能用 ``\\((.+?)\\)`` 这种非贪婪正则：真实写法里路径参数常含嵌套括号
    （``str(Path(__file__).resolve().parent / 'scripts' / 'benchmark')``），
    非贪婪会在第一个 ``)`` 处截断。这里改为平衡括号扫描（并跳过字符串字面量
    内的括号与逗号）。
    """
    out = []
    for m in _SYS_PATH_INJECT_START_RE.finditer(text):
        i = m.end()
        depth, j, quote = 1, i, None
        while j < len(text) and depth:
            ch = text[j]
            if quote:
                if ch == quote and text[j - 1] != "\\":
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner = text[i:j]

        parts, cur, depth, quote = [], [], 0, None
        for ch in inner:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0 and not quote:
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        parts.append("".join(cur))
        if len(parts) >= 2:
            out.append(parts[-1].strip())
    return out


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _iter_repo_files(exts=_SCAN_EXT):
    """遍历仓库内文本文件（排除 .venv/backup/deliverables 等），返回相对 POSIX 路径。"""
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        rel_parts = path.relative_to(REPO_ROOT).parts
        if any(p in _SKIP_DIRS or p.startswith("_backup") for p in rel_parts):
            continue
        yield path.relative_to(REPO_ROOT).as_posix(), path


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _normalized_semantic_text(rel: str) -> str:
    """剥掉 legacy 样板头 + 统一换行 + 丢弃纯空行（保留注释与缩进）。"""
    txt = _read(rel).replace("\r\n", "\n").replace("\r", "\n")
    txt = _BOOTSTRAP_RE.sub("", txt)
    return "\n".join(ln.rstrip() for ln in txt.split("\n") if ln.strip())


def _duplicate_basenames() -> dict[str, list[str]]:
    by_base: dict[str, list[str]] = {}
    for rel, path in _iter_repo_files((".py",)):
        by_base.setdefault(path.name, []).append(rel)
    return {k: sorted(v) for k, v in by_base.items()
            if len(v) > 1 and k != "__init__.py"}


def _resolve_from(path_dirs: list[str], name: str):
    """在给定 sys.path 目录列表下解析顶层模块 -> 相对路径 或 None。"""
    spec = PathFinder.find_spec(name, path_dirs)
    if spec is None or not spec.origin:
        return None
    origin = Path(spec.origin).resolve()
    try:
        return origin.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return origin.as_posix()


def _configured_pythonpath() -> list[str]:
    """读取 pyproject.toml 的 [tool.pytest.ini_options].pythonpath。"""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    opts = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    return list(opts.get("pythonpath", []))


# --------------------------------------------------------------------------
# T1 冻结同名清单
# --------------------------------------------------------------------------

# 2026-11-04 移除无条件 skip：实测可通过。原 skip 系 d9e701c8
# 为掩盖 legacy 副本口径漂移所加，随漂移一并修复后恢复执行。
def test_duplicate_module_basenames_are_frozen():
    """同名 basename 清单冻结：新增/消失都必须显式改本文件。"""
    actual = _duplicate_basenames()
    expected = {k: sorted(v) for k, v in FROZEN_DUPLICATES.items()}

    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    moved = {k: (expected[k], actual[k]) for k in set(actual) & set(expected)
             if actual[k] != expected[k]}

    msg_lines = []
    if added:
        msg_lines.append("新增同名 basename（会引入解析歧义）：")
        for k in added:
            msg_lines.append("  %s -> %s" % (k, actual[k]))
    if removed:
        msg_lines.append("清单中的 basename 已不存在（需同步清理本文件）：%s" % removed)
    if moved:
        msg_lines.append("路径集合变化：")
        for k, (e, a) in sorted(moved.items()):
            msg_lines.append("  %s\n      期望 %s\n      实际 %s" % (k, e, a))
    if msg_lines:
        msg_lines.append(
            "\n处置方式：确认无歧义后，更新本文件的 FROZEN_DUPLICATES 并在 commit "
            "message 中说明原因；不要为了过测试而扩大白名单。")
        pytest.fail("\n".join(msg_lines))


# --------------------------------------------------------------------------
# T2 有测试消费者的副本必须语义等价
# --------------------------------------------------------------------------

# 2026-11-04 移除无条件 skip：实测可通过。原 skip 系 d9e701c8
# 为掩盖 legacy 副本口径漂移所加，随漂移一并修复后恢复执行。
@pytest.mark.parametrize("basename", _EQUIVALENT_BASENAMES)
def test_live_copy_is_semantically_identical_to_its_legacy_sibling(basename):
    """声明为 equivalent 的每一对副本，除 legacy 样板头外必须逐行相同。

    这是本守卫的核心：该名字被测试**裸 import**，解析到哪一份由环境决定；
    只要两份内容等价，解析顺序就无关紧要。反之，任何单侧修改都会让
    "测试通过" 与 "交付行为" 脱钩 —— 那正是 F13 要防的滚雪球。

    参数来自 ``DUPLICATE_DISPOSITION`` 而非硬编码唯一一对：将来任何新增的
    ``equivalent`` 声明都会自动进入本用例，不会出现"登记了但没人校验"。
    """
    copies = FROZEN_DUPLICATES[basename]
    assert len(copies) >= 2, "%s 在 FROZEN_DUPLICATES 里不足两份" % basename

    pivot_rel = SEMANTIC_EQUIVALENT_PAIR["root_copy"]
    assert pivot_rel in copies, (
        "%s 的基准副本 %s 不在 FROZEN_DUPLICATES 登记路径 %s 里"
        % (basename, pivot_rel, copies))
    pivot_txt = _normalized_semantic_text(pivot_rel)

    drifted = {}
    for rel in copies:
        if rel == pivot_rel:
            continue
        txt = _normalized_semantic_text(rel)
        if txt != pivot_txt:
            drifted[rel] = txt

    if drifted:
        import difflib
        rel, txt = sorted(drifted.items())[0]
        diff = list(difflib.unified_diff(
            pivot_txt.split("\n"), txt.split("\n"),
            pivot_rel, rel, lineterm="", n=2))
        pytest.fail(
            "%s 的两份活副本已发生语义漂移（除 legacy 样板头外不允许有任何差异）：\n"
            % basename
            + "\n".join("  " + l for l in diff[:60])
            + "\n\n处置方式：两份必须同步修改（或把 legacy 那份改成薄转发）。"
              "禁止只改其中一份，然后依赖「测试全绿」。"
        )


# --------------------------------------------------------------------------
# T3 两个消费者必须解析到同一份
# --------------------------------------------------------------------------

# 2026-11-04 移除无条件 skip：实测可通过。原 skip 系 d9e701c8
# 为掩盖 legacy 副本口径漂移所加，随漂移一并修复后恢复执行。
def test_both_consumers_of_analyze_all_experiments_resolve_to_root_copy():
    """测试（裸 import）与流水线（显式注入）必须解析到**同一个文件**。"""
    name = SEMANTIC_EQUIVALENT_PAIR["name"]
    expected = SEMANTIC_EQUIVALENT_PAIR["root_copy"]

    # (a) pytest 口径：pythonpath 里的目录
    pytest_dirs = [str((REPO_ROOT / p).resolve()) for p in _configured_pythonpath()]
    assert pytest_dirs, ("pyproject.toml 缺少 [tool.pytest.ini_options].pythonpath；"
                         "tests/test_analyze_all_experiments.py 的裸 import 将无解析依据")
    resolved_pytest = _resolve_from(pytest_dirs, name)
    assert resolved_pytest == expected, (
        "pytest 口径下 %s 解析到 %s，期望 %s —— 说明 pythonpath 被改动，"
        "测试可能正在跑另一份副本" % (name, resolved_pytest, expected))

    # (b) 流水线口径：显式把仓库根插到 sys.path 首位
    pipeline_txt = _read(PIPELINE_CONSUMER)
    injected = _iter_sys_path_injects(pipeline_txt)
    assert injected, "%s 已不再注入 sys.path，却仍 import %s" % (PIPELINE_CONSUMER, name)
    resolved_pipeline = _resolve_from([str(REPO_ROOT)], name)
    assert resolved_pipeline == expected, (
        "流水线把仓库根插入 sys.path 后，%s 解析到 %s，期望 %s"
        % (name, resolved_pipeline, expected))


def test_no_test_imports_an_ambiguous_module_without_being_registered():
    """任何新增的「测试 import 同名模块」都必须登记在 FROZEN_TEST_IMPORTERS。"""
    found: dict[str, set[str]] = {}
    for rel, _path in _iter_repo_files((".py",)):
        if not rel.startswith("tests/"):
            continue
        txt = _read(rel)
        for base in FROZEN_DUPLICATES:
            mod = base[:-3]
            if re.search(r"^\s*(?:from\s+%s\s+import|import\s+%s\b)"
                         % (re.escape(mod), re.escape(mod)), txt, re.MULTILINE):
                found.setdefault(mod, set()).add(rel)

    actual = {k: sorted(v) for k, v in found.items()}
    expected = {k: sorted(v) for k, v in FROZEN_TEST_IMPORTERS.items()}
    assert actual == expected, (
        "测试里对「同名模块」的 import 面发生变化（这是解析歧义的高危入口）：\n"
        "  实际 %s\n  期望 %s\n"
        "处置：确认新测试是否显式注入了目标目录；把结果登记到 FROZEN_TEST_IMPORTERS。"
        % (actual, expected))


# --------------------------------------------------------------------------
# T4 run_all 必须靠显式注入，不允许"从仓库根就能 import 到"
# --------------------------------------------------------------------------

def test_run_all_is_unresolvable_from_repo_root():
    """仓库根不得存在 ``run_all.py``；否则裸 import 会静默拿到错误的那一份。"""
    resolved = _resolve_from([str(REPO_ROOT)], "run_all")
    assert resolved is None, (
        "仓库根已能解析到 run_all -> %s；两个 run_all 变体（ablation / benchmark）"
        "本应只能靠显式注入区分，裸 import 现在会静默命中错误实现" % resolved)
    assert not (REPO_ROOT / "run_all.py").exists()


@pytest.mark.parametrize("test_file, expected_dir_token", [
    ("tests/test_benchmark_run_all.py", "benchmark"),
    ("tests/test_benchmark_main_args.py", "benchmark"),
])
def test_run_all_consumers_inject_their_own_directory(test_file, expected_dir_token):
    """两个 run_all 测试必须各自显式注入 ``scripts/benchmark``，且注入语句在 import 之前。"""
    txt = _read(test_file)
    m = re.search(r"^\s*import\s+run_all\b", txt, re.MULTILINE)
    assert m, "%s 不再 import run_all" % test_file

    injects = _iter_sys_path_injects(txt[:m.start()])
    assert injects, (
        "%s 在 import run_all 之前没有任何 sys.path 注入 —— 解析退化为"
        "「看运气」，请恢复显式注入" % test_file)
    assert any(expected_dir_token in a for a in injects), (
        "%s 的 sys.path 注入未指向 %s 目录：%s"
        % (test_file, expected_dir_token, injects))


# --------------------------------------------------------------------------
# T5 孤儿副本仍然无人引用（若被接线，须先处理其已知漂移）
# --------------------------------------------------------------------------

def test_orphan_duplicate_scripts_are_still_unreferenced():
    """3 对孤儿副本若被任何入口引用，必须先解决其已知漂移。"""
    offenders: dict[str, list[str]] = {}
    for base in ORPHAN_BASENAMES:
        pat = re.compile(r"\b" + re.escape(base) + r"\b")
        refs = []
        for rel, _path in _iter_repo_files():
            if rel in ORPHAN_OWN_FILES or rel == "tests/test_module_resolution_contract.py":
                continue
            if pat.search(_read(rel)):
                refs.append(rel)
        if refs:
            offenders[base] = sorted(refs)

    assert not offenders, (
        "以下孤儿副本被新接线了 —— 它们之间已知存在漂移（BASE/RESULTS 目录、"
        "PYTHON 解释器、种子收集范围），接线前必须先把两份统一：\n%s"
        % "\n".join("  %s -> %s" % (k, v) for k, v in offenders.items()))


# --------------------------------------------------------------------------
# T6 扁平命名空间：不得遮蔽标准库 / 已声明依赖
# --------------------------------------------------------------------------
#
# ``tests/conftest.py`` 为了「单文件跑 == 全量跑」，把**仓库根**与
# ``scripts/**`` 下所有含 ``.py`` 的目录插到 ``sys.path[0]``。代价是**扁平命名
# 空间**：这些目录里一旦出现 ``json.py`` / ``queue.py``，就会静默遮蔽标准库；
# 出现 ``numpy.py`` 就会遮蔽真实依赖 —— 报错点会离真正原因很远。
#
# 2026-09-23 实测：与 ``sys.stdlib_module_names``、与 ``requirements.txt`` 声明的
# 顶层名**均无交集**。也就是说现在的正确**靠的是运气**。下面两条断言把运气固定下来。

# requirements.txt + pyproject.toml 声明的依赖 → 其顶层 import 名
_DECLARED_TOP_LEVEL = {
    "cryptography": "cryptography",
    "torch": "torch",
    "numpy": "numpy",
    "scipy": "scipy",
    "scikit-learn": "sklearn",
    "pyyaml": "yaml",
    "matplotlib": "matplotlib",
    "flask": "flask",
    "tqdm": "tqdm",
}


def _flat_namespace_roots():
    """conftest 实际会注入的根：仓库根 + ``scripts/**`` 下所有含 .py 的目录。"""
    roots = [REPO_ROOT]
    scripts = REPO_ROOT / "scripts"
    if scripts.is_dir():
        for cur, subdirs, files in os.walk(scripts):
            subdirs[:] = [d for d in subdirs if d != "__pycache__"]
            if any(f.endswith(".py") for f in files):
                roots.append(Path(cur))
    return sorted(set(roots))


def _flat_namespace_modules():
    """这些根下**能被顶层 import 到的名字**（保守超集：取并集）。"""
    names: dict[str, set] = {}
    for root in _flat_namespace_roots():
        for p in sorted(root.glob("*.py")):
            names.setdefault(p.stem, set()).add(
                p.relative_to(REPO_ROOT).as_posix())
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith(".") \
                    and d.name != "__pycache__" and (d / "__init__.py").exists():
                names.setdefault(d.name, set()).add(
                    d.relative_to(REPO_ROOT).as_posix())
    return names


def test_no_project_module_shadows_stdlib():
    """被注入 ``sys.path`` 的目录里，不得出现与标准库同名的模块。"""
    # sys.stdlib_module_names 在 Python 3.10+ 才提供；3.9 回退到 builtin 集合
    _stdlib_names = getattr(sys, "stdlib_module_names", ())
    stdlib = {n.lower() for n in _stdlib_names} | {n.lower() for n in sys.builtin_module_names}
    clash = {n: sorted(v) for n, v in _flat_namespace_modules().items()
             if n.lower() in stdlib and not n.startswith("__")}
    assert not clash, (
        "以下项目模块会**遮蔽标准库**（因为 conftest 把它们所在目录插到了 sys.path 首位）：\n%s\n"
        "处置：重命名该文件/目录（例如加前缀），不要依赖 import 顺序。"
        % "\n".join("  %s -> %s" % (k, v) for k, v in sorted(clash.items())))


def test_no_project_module_shadows_declared_dependency():
    """被注入 ``sys.path`` 的目录里，不得出现与已声明依赖同名的模块。"""
    declared = set(_DECLARED_TOP_LEVEL.values())
    clash = {n: sorted(v) for n, v in _flat_namespace_modules().items()
             if n.lower() in declared}
    assert not clash, (
        "以下项目模块会**遮蔽 requirements 里声明的依赖**：\n%s\n"
        "处置：重命名该文件/目录。"
        % "\n".join("  %s -> %s" % (k, v) for k, v in sorted(clash.items())))


# --------------------------------------------------------------------------
# T7 处置登记表必须覆盖全部同名副本，且与消费者表/等价表/孤儿表互不矛盾
# --------------------------------------------------------------------------

def test_every_duplicate_basename_declares_a_consistent_disposition():
    """每对同名副本「为什么不构成缺陷」必须显式登记，且四张表互相自洽。

    T1 只保证撞名清单冻结；T2 只校验被声明为 equivalent 的那一对；T4/T5 各自
    只管一类消费者。**此前没有任何一条断言要求"每一对副本都被归过类"** ——
    于是新增一对副本时，只要把 T1 的白名单同步一下就能全绿，处置判断本身可以
    完全不做。本用例补上这个缺口，并钉住几种会互相矛盾、却都能单独过测的登记。
    """
    declared = DUPLICATE_DISPOSITION
    problems = []

    # (a) 覆盖：与 FROZEN_DUPLICATES 双向对账（新增一对副本不能只加白名单）
    missing = sorted(set(FROZEN_DUPLICATES) - set(declared))
    extra = sorted(set(declared) - set(FROZEN_DUPLICATES))
    if missing:
        problems.append("以下同名副本未登记处置方式（可选 %s）：%s"
                        % ("/".join(sorted(_DISPOSITION_KINDS)), missing))
    if extra:
        problems.append("处置表登记了 FROZEN_DUPLICATES 里不存在的名字：%s" % extra)

    # (b) 每条登记本身合法：kind 在集合内，reason 必须是真实依据而非占位符
    for base in sorted(declared):
        entry = declared[base]
        kind = entry.get("kind")
        if kind not in _DISPOSITION_KINDS:
            problems.append("%s 的 kind=%r 不在允许集合 %s 内"
                            % (base, kind, sorted(_DISPOSITION_KINDS)))
        if len(str(entry.get("reason", "")).strip()) < 20:
            problems.append("%s 的 reason 过短（需写明实测依据，不接受占位符）" % base)

    # (c) 与消费者表交叉校验：kind 蕴含"有无消费者"，两者必须一致
    consumer_modules = set(FROZEN_TEST_IMPORTERS)
    for base in sorted(declared):
        kind = declared[base].get("kind")
        mod = base[:-3] if base.endswith(".py") else base
        has_consumer = mod in consumer_modules
        if kind == "orphan_unused" and has_consumer:
            problems.append(
                "%s 声明为 orphan_unused，却被 %s import —— 无消费者正是它免于"
                "等价校验的唯一理由" % (base, FROZEN_TEST_IMPORTERS[mod]))
        elif kind in ("equivalent", "explicit_path") and not has_consumer:
            problems.append(
                "%s 声明为 %s，但 FROZEN_TEST_IMPORTERS 里没有消费者；"
                "无消费者的副本应归为 orphan_unused" % (base, kind))

    # (d) equivalent 与 SEMANTIC_EQUIVALENT_PAIR 必须一一对应
    #     （T3 只读后者；多余的 equivalent 会被静默跳过）
    eq_bases = sorted(b for b, d in declared.items() if d.get("kind") == "equivalent")
    pair_name = SEMANTIC_EQUIVALENT_PAIR.get("name")
    if eq_bases and pair_name is None:
        problems.append("有 equivalent 登记但 SEMANTIC_EQUIVALENT_PAIR 缺失")
    elif eq_bases and [pair_name + ".py"] != eq_bases:
        problems.append(
            "equivalent 登记集合 %s 与 SEMANTIC_EQUIVALENT_PAIR[name]=%r 不一致"
            % (eq_bases, pair_name))

    # (e) orphan_unused 必须与 T5 实际扫描的清单一致
    #     否则"声明为孤儿"只是个标签：没人会断言它保持无人引用
    orphan_bases = sorted(b[:-3] for b, d in declared.items()
                          if d.get("kind") == "orphan_unused")
    if orphan_bases != sorted(ORPHAN_BASENAMES):
        problems.append(
            "orphan_unused 登记 %s 与 T5 的 ORPHAN_BASENAMES %s 不一致；"
            "未进入后者的副本不会被断言「保持无人引用」"
            % (orphan_bases, sorted(ORPHAN_BASENAMES)))

    # (f) 防退化自检：T2 的参数表变空等于等价校验整体消失
    if not _EQUIVALENT_BASENAMES:
        problems.append(
            "T2 的参数表 _EQUIVALENT_BASENAMES 为空 —— 等价校验已被整体跳过，"
            "本文件的核心断言静默失效")

    assert not problems, (
        "同名副本的处置登记不自洽：\n"
        + "\n".join("  - " + p for p in problems)
        + "\n\n处置方式：为每对副本在 DUPLICATE_DISPOSITION 里选一种 kind 并写明"
          "实测依据；若 kind 与消费者现状矛盾，先确认是哪一边过时，不要改断言迁就。"
    )
