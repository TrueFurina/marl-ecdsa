"""守卫：禁止装饰器形式的**无条件** skip（永久放弃覆盖）。

病灶来源（2026-11-04 实测）：
  `d9e701c8`「sync 源码对齐 V29 新基线（口径 n=101）」改了根副本
  `analyze_all_experiments.py` 的 `_REGISTRY_FALLBACK`（n=71 → n=101），漏了
  `scripts/legacy/analysis/` 下那份。两份副本语义漂移 ⇒
  `test_live_copy_is_semantically_identical_to_its_legacy_sibling` 变红。
  处置方式不是修数据，而是把**同一个 reason 字符串**贴到 6 条用例上一起 skip——
  其中 5 条与漂移毫无关系（README 存在性、同名 basename 冻结清单、门禁自扫），
  纯属连带误伤，且因为是无条件 skip，它们再也不会自己活过来。

本守卫的判据（刻意收窄，避免误伤）：
  1. 只拦**装饰器形式**：`@pytest.mark.skip(...)` —— 这是"永久放弃"的形态。
  2. 不拦 `skipif` / `importorskip`：条件满足时会自己恢复执行，是正当用法。
  3. 不拦函数体内的 `pytest.skip(...)`：通常前面有 `if <条件>:` 判定
     （如缺 dilithium 后端、缺证据 JSON、非 Windows），这类不是放弃覆盖，
     而是"本环境不适用"。若要连这类也收紧，应另加一条按"函数体首条语句
     是否受 if 保护"判定的守卫，不在本条范围内。
  4. 万一确有永久放弃的必要：登记进 `ALLOWED` 并写明**为什么不能写成 skipif**。
     登记要求本身就是一次自省——多数情况下写到这里就会发现理由不成立。
"""
import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

#: 形如 {"tests/xxx.py::test_yyy": "为什么无法写成 skipif"}；当前为空。
#: 想往这里加条目之前，先回答：这里的"条件"到底是什么？能否写成表达式？
ALLOWED = {}


def _scan(root: Path):
    """返回 [(相对路径, 行号, 节点名, 装饰器源码)]。"""
    hits = []
    for f in sorted(root.rglob("test_*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for dec in getattr(node, "decorator_list", []):
                src = ast.unparse(dec)
                if not src.startswith("pytest.mark.skip("):
                    continue
                name = getattr(node, "name", "<module>")
                rel = f.relative_to(root).as_posix()
                hits.append((rel, dec.lineno, name, src))
    return hits


def test_no_unconditional_skip_decorator():
    hits = _scan(TESTS_ROOT)
    bad = [h for h in hits if "%s::%s" % (h[0], h[2]) not in ALLOWED]
    if bad:
        lines = ["%s:%d  %s  →  %s" % (rel, ln, name, src[:96])
                 for rel, ln, name, src in bad]
        raise AssertionError(
            "存在装饰器形式的无条件 skip（永久放弃覆盖）：\n  "
            + "\n  ".join(lines)
            + "\n\n处置方式（按优先级）：\n"
              "  1. 去掉 skip，让它真的跑 —— 先实测它到底过不过，别假设。\n"
              "  2. 若依赖确实缺失，改用 `@pytest.mark.skipif(<具体条件>, reason=...)`，\n"
              "     条件满足时它会自己恢复执行。\n"
              "  3. 确需永久放弃，登记进本文件 ALLOWED 并写明为什么不能写成 skipif。\n"
              "禁止的做法：把同一个 reason 字符串贴到多条不相干用例上，从而"
              "「让 CI 变绿」——那 6 条覆盖就是这么丢的。"
        )


def test_scanner_actually_detects_a_planted_skip(tmp_path):
    """自检：守卫必须真能命中样例，否则匹配写错就退化成"永远通过"的空转。"""
    p = tmp_path / "test_planted.py"
    p.write_text(
        "import pytest\n\n"
        "@pytest.mark.skip(reason='planted')\n"
        "def test_planted():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    hits = _scan(tmp_path)
    assert len(hits) == 1, "扫描器没命中植入样例，守卫已失效：%r" % (hits,)
    assert hits[0][2] == "test_planted"


def test_scanner_ignores_skipif_and_importorskip(tmp_path):
    """自检边界：skipif / importorskip 不得被误报，否则会逼人绕过守卫。"""
    p = tmp_path / "test_cond.py"
    p.write_text(
        "import pytest\n\n"
        "@pytest.mark.skipif(1 > 2, reason='条件永不成立')\n"
        "def test_cond():\n"
        "    pytest.importorskip('definitely_not_a_real_module_xyz')\n",
        encoding="utf-8",
    )
    assert _scan(tmp_path) == [], "skipif/importorskip 被误判为无条件 skip"
