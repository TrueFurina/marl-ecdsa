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

def test_live_copy_is_semantically_identical_to_its_legacy_sibling():
    """``analyze_all_experiments`` 两份副本除样板头外必须逐行相同。

    这是本守卫的核心：该名字被测试**裸 import**，解析到哪一份由环境决定；
    只要两份内容等价，解析顺序就无关紧要。反之，任何单侧修改都会让
    "测试通过" 与 "交付行为" 脱钩 —— 那正是 F13 要防的滚雪球。
    """
    root_txt = _normalized_semantic_text(SEMANTIC_EQUIVALENT_PAIR["root_copy"])
    legacy_txt = _normalized_semantic_text(SEMANTIC_EQUIVALENT_PAIR["legacy_copy"])

    if root_txt != legacy_txt:
        import difflib
        diff = list(difflib.unified_diff(
            root_txt.split("\n"), legacy_txt.split("\n"),
            SEMANTIC_EQUIVALENT_PAIR["root_copy"],
            SEMANTIC_EQUIVALENT_PAIR["legacy_copy"],
            lineterm="", n=2))
        pytest.fail(
            "两份活副本已发生语义漂移（除 legacy 样板头外不允许有任何差异）：\n"
            + "\n".join("  " + l for l in diff[:60])
            + "\n\n处置方式：两份必须同步修改（或把 legacy 那份改成薄转发）。"
              "禁止只改其中一份，然后依赖「测试全绿」。"
        )


# --------------------------------------------------------------------------
# T3 两个消费者必须解析到同一份
# --------------------------------------------------------------------------

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
