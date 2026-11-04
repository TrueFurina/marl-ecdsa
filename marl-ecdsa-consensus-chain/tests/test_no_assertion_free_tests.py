"""守卫：禁止「零断言用例」—— 名义覆盖，实际不校验任何东西。

## 病灶来源（2026-11-04 实测）

全仓扫出 16 条 `test_*` 函数体内**没有任何断言**。它们永远 PASS，
即使被测行为完全错了也不会红。其中两条各自掩盖了一个真实问题：

1. `test_flush_pending_stub_mode`（tests/test_action_recorder.py）
   docstring 写「stub 模式下仅清空缓冲」，实现却把 `clear()` 嵌在
   `if bc_node is not None` 之内 —— stub 模式 flush 是**空操作**，
   缓冲随回合数单调增长（实测 20 回合 ×100 步累积 2000 条从不释放）。
   注释精确描述了这个缺陷，但没有断言，谁也不会注意到。调用方
   `Bridge.on_episode_end()` 只能自己补一句 `_pending_actions.clear()`
   兜底 —— 那正是缺陷留下的痕迹。

2. `test_corrupted_priv_key_regenerates`（tests/test_key_manager.py）
   docstring 写「新实例应能检测损坏并重新生成」，实际**既没调用被测
   方法也没有断言**，只留了准备代码。实测真实行为是抛 `ValueError`
   （fail-closed，这是对的：静默换钥会让已上链的公钥与历史签名全部
   失配）。写错的是 docstring 和用例名，不是实现。

## 判据（刻意收窄，避免误伤）

一条用例只要含有下列任一形态即视为「有断言」，不追究断言强弱：

* `assert` 语句
* `raise`（测试函数里 raise 就是失败信号）
* 调用名以 `assert` 开头（unittest 的 `self.assertEqual` 等）
* `pytest.raises` / `fail` / `warns` / `approx` / `deprecated_call`

**不拦弱断言**（例如对 `len()` 恒真的 `assert x >= 0`）。那是另一个族，
需要按表达式推断恒真性，误报率高，不在本条范围内。

## 例外

`ALLOWED` 逐条登记并写明理由 —— 当前只有 import 契约一条。
写 `assert True` / `is not None` 去"满足"守卫，是把空转伪装成断言，
比不加更糟：它会让这条守卫失去意义。
"""
import ast
import textwrap
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

#: 形如 {"test_xxx.py::test_yyy": "为什么这条确实不需要断言"}
#: 键的路径相对 tests/ 目录（与本文件其它守卫一致）
ALLOWED = {
    "test_deps_scripts.py::test_deps_importable":
        "契约本身就是「import 不抛 ImportError」。没有可加的真断言："
        "写 assert True 或 is not None 只是把空转伪装成断言；"
        "而有意义的断言（如模块属性）会与 requirements 脱钩，"
        "换依赖版本就误报。保留为显式例外，比加假断言诚实。",
}

_ASSERT_CALLS = {"raises", "fail", "warns", "approx", "deprecated_call"}


def _has_assertion(fn) -> bool:
    """函数体内是否存在任一断言形态。"""
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assert, ast.Raise)):
            return True
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None) or ""
            if name.startswith("assert") or name in _ASSERT_CALLS:
                return True
    return False


def _scan(root: Path):
    """返回 (越界用例列表, 用例总数)。

    列表元素为 ``(相对路径, 行号, 用例名)``；同时返回总数，供分母自检——
    只返回违规而不管扫了多少，判据一旦写错就会退化成"永远通过"的空转。
    """
    hits = []
    total = 0
    for f in sorted(root.rglob("test_*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = f.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            total += 1
            if not _has_assertion(node):
                hits.append((rel, node.lineno, node.name))
    return hits, total


def test_every_test_function_contains_an_assertion():
    hits, total = _scan(TESTS_ROOT)
    bad = [h for h in hits if "%s::%s" % (h[0], h[2]) not in ALLOWED]

    if bad:
        lines = ["%s:%d  %s" % (rel, ln, name) for rel, ln, name in bad]
        raise AssertionError(
            "以下用例体内**没有任何断言**，永远 PASS（名义覆盖）：\n  "
            + "\n  ".join(lines)
            + "\n\n处置方式（按优先级）：\n"
              "  1. 补上**可失败**的断言 —— 先问「这个行为错了长什么样」，\n"
              "     再写出能把它区分出来的那一句。状态不变就比长度/集合，\n"
              "     返回就比具体值，不要写 `>= 0` 这种对 len() 恒真的条件。\n"
              "  2. 若断言加不上，说明这条用例本来就不该存在，删掉比留着强。\n"
              "  3. 确属「不抛异常即契约」（如 import 检查），登记进 ALLOWED\n"
              "     并写明为什么加不了真断言。\n"
              "禁止的做法：写 `assert True` / `assert x is not None` 糊过去 ——"
              "那只是把空转伪装成断言。"
        )

    # 双向对账：ALLOWED 里的每条都必须仍是一条真实存在的「无断言用例」。
    # 否则条目过期后（用例补了断言 / 改名 / 删除）会静默放过同名的新空用例——
    # 那正好是登记表失效却看不出来的形态。
    registered = {"%s::%s" % (rel, name) for rel, _ln, name in hits}
    stale = sorted(set(ALLOWED) - registered)
    assert not stale, (
        "ALLOWED 中存在过期条目（当前已不是「无断言用例」）：\n  "
        + "\n  ".join(stale)
        + "\n\n可能是那条用例已补上断言，或已被改名/删除。请删掉对应条目；"
          "留着它会让将来同名的空用例被静默放过。"
    )

    # 分母自检：扫不到足够多的用例，说明 rglob 或判据已经退化。
    # 当前约 2200 条；阈值取 2000 留 9% 余量，大量删测试时应当主动复核。
    assert total >= 2000, (
        "只扫到 %d 条 test_* 用例，远少于预期（≈2200）：扫描根或判据已失效，"
        "此守卫正在空转而不是在保护。" % total)


def test_scanner_detects_a_planted_assertion_free_test(tmp_path):
    """自检：植入一条只有赋值、没有断言的用例，必须被命中。"""
    p = tmp_path / "test_planted.py"
    p.write_text(
        "def test_nothing():\n"
        "    x = 1 + 1\n",
        encoding="utf-8",
    )
    hits, total = _scan(tmp_path)
    assert total == 1
    assert len(hits) == 1, "扫描器没命中植入样例，守卫已失效：%r" % (hits,)
    assert hits[0][2] == "test_nothing"


def test_scanner_accepts_the_common_assertion_forms(tmp_path):
    """自检边界：6 种合法断言形态都不得误报，否则会逼人绕过守卫。"""
    p = tmp_path / "test_forms.py"
    p.write_text(textwrap.dedent("""
        import pytest


        def test_builtin_assert():
            assert 1 == 1


        def test_unittest_style():
            class _T:
                def assertEqual(self, a, b):
                    pass
            _T().assertEqual(1, 1)


        def test_pytest_raises():
            with pytest.raises(ValueError):
                int("x")


        def test_pytest_fail():
            pytest.fail("planted")


        def test_bare_raise():
            raise AssertionError("planted")


        def test_pytest_warns():
            with pytest.warns(UserWarning):
                import warnings
                warnings.warn("x")
    """), encoding="utf-8")
    hits, total = _scan(tmp_path)
    assert total == 6
    assert hits == [], "合法的断言形态被误报：%r" % (hits,)


def test_scanner_covers_async_tests(tmp_path):
    """自检：async 用例同样要纳入判定，别让协程用例成为盲区。"""
    p = tmp_path / "test_async.py"
    p.write_text(
        "async def test_async_empty():\n"
        "    pass\n",
        encoding="utf-8",
    )
    hits, total = _scan(tmp_path)
    assert total == 1
    assert len(hits) == 1, "async 用例未被纳入扫描：%r" % (hits,)
