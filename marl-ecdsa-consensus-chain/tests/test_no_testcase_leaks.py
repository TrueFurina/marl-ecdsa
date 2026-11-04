"""守卫：测试模块之间不得「传染」TestCase 类，否则同一条用例会被收集多次。

## 为什么需要这条守卫（2026-11-04 实测事故）

`tests/test_v12_consensus_invariants.py` 原先写的是：

```python
from tests.test_v11_epoch_view import ConsensusV11
class ConsensusV12(ConsensusV11):
```

pytest 收集规则里，`python_classes` 的 `Test*` 前缀过滤**只作用于普通类**；
`unittest.TestCase` 子类**无条件收集**。于是同一个模块里：

* 命名空间中的 `ConsensusV11` → 收集 4 条
* 继承它的 `ConsensusV12` → 再收集同样的 4 条
* `test_v11_epoch_view.py` 自身 → 又 4 条

同一条用例跑 3 遍。实测最慢的 `test_epoch_reconfiguration_old_certificate`
27.47s / 27.36s / 27.29s，四条合计重复约 **120s，占整套 21.6%**，而
`visualization.distributed_consensus` 是无状态模块、`setUp` 每次新建临时
目录 —— 重复执行**零新增覆盖**。

## 规则

* **夹具可以共享**：把 `setUp/tearDown/start/...` 放进**不继承 TestCase**
  的普通类（如 `test_v11_epoch_view._ConsensusHarness`），子类各自补用例。
* **TestCase 不能跨模块复用**：既不得 `from tests.test_x import TestCase子类`，
  也不得 `class Y(隔壁的TestCase子类)`。

本守卫用 AST 静态判定，不 import 被测模块（避免副作用与顺序依赖）。
"""
import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

#: 形如 ``test_xxx`` 的模块名（可带 ``tests.`` 前缀）
_TEST_MODULE = re.compile(r"^(?:.*\.)?(test_[A-Za-z0-9_]+)$")


def _dotted(node) -> str:
    """把基类表达式还原成点号串：``TestCase`` / ``unittest.TestCase``。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else node.attr
    return ""


def _is_testcase_base(dotted: str) -> bool:
    return dotted == "TestCase" or dotted.endswith(".TestCase")


def _classes(path: Path):
    """{类名: [基类点号串, ...]}（只看模块顶层）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.name: [_dotted(b) for b in n.bases]
        for n in tree.body
        if isinstance(n, ast.ClassDef)
    }


def _testcase_closure(bases_map: dict) -> set:
    """在一个模块内求「继承链能追到 unittest.TestCase」的类名集合。"""
    tc = set()
    changed = True
    while changed:
        changed = False
        for name, bases in bases_map.items():
            if name in tc:
                continue
            if any(_is_testcase_base(b) or b in tc for b in bases):
                tc.add(name)
                changed = True
    return tc


def _module_defs() -> dict:
    """{模块名: TestCase 子类名集合}，覆盖 ``tests/`` 下全部 ``test_*.py``。"""
    out = {}
    for p in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            out[p.stem] = _testcase_closure(_classes(p))
        except SyntaxError:
            continue
    return out


def _violations(path: Path, tc_defs: dict) -> list:
    """返回该模块的违规描述（import 别处的 TestCase / 继承别处的 TestCase）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = []

    # 1) from tests.test_x import 某个 TestCase 子类
    imported_tc = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        m = _TEST_MODULE.match(node.module)
        if not m:
            continue
        src = m.group(1)
        if src not in tc_defs or src == path.stem:
            continue
        for alias in node.names:
            if alias.name in tc_defs[src]:
                imported_tc[alias.asname or alias.name] = src
                problems.append(
                    f"{path.name}: 从 {src} import 了 TestCase 子类 {alias.name!r}"
                    f" —— pytest 会把它在本模块再收集一遍（同一用例多跑一次）"
                )

    # 2) class Y(别处 import 的 TestCase 子类)
    local_bases = _classes(path)
    for cls, bases in local_bases.items():
        for b in bases:
            root = b.split(".")[-1]
            if root in imported_tc:
                problems.append(
                    f"{path.name}: class {cls} 继承了 {imported_tc[root]}.{root}"
                    f" —— 继承来的用例会在本模块再跑一遍"
                )
    return problems


def test_no_testcase_leaks_between_test_modules():
    """测试模块之间不得互相 import / 继承 TestCase 子类。"""
    tc_defs = _module_defs()
    assert tc_defs, "没有扫到任何 TestCase 定义，守卫失效（检查 glob 与解析）"

    problems = []
    for p in sorted(TESTS_DIR.glob("test_*.py")):
        problems.extend(_violations(p, tc_defs))

    assert not problems, (
        "检测到 TestCase 跨模块传染（会导致同一用例被重复收集、整套变慢）：\n  "
        + "\n  ".join(problems)
        + "\n\n修法：把夹具抽到不继承 TestCase 的普通类里共享（参考 "
          "tests/test_v11_epoch_view.py 的 _ConsensusHarness），"
          "用例本身只在定义它的模块里跑一次。"
    )


def test_guard_catches_known_pattern():
    """自检：守卫确实能识别「import + 继承」这种写法（防止守卫本身退化成空转）。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "test_base.py").write_text(
            "import unittest\n"
            "class Base(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        assert True\n",
            encoding="utf-8",
        )
        (tmp / "test_child.py").write_text(
            "import unittest\n"
            "from tests.test_base import Base\n"
            "class Child(Base):\n"
            "    def test_b(self):\n"
            "        assert True\n",
            encoding="utf-8",
        )
        # 在临时目录上重算定义表，不能污染真实 tests/
        defs = {
            p.stem: _testcase_closure(_classes(p))
            for p in tmp.glob("test_*.py")
        }
        assert "Base" in defs["test_base"], "自检前提失效：Base 未被判定为 TestCase"
        problems = _violations(tmp / "test_child.py", defs)
        assert any("import 了 TestCase 子类" in x for x in problems), problems
        assert any("继承了" in x for x in problems), problems
