#!/usr/bin/env python
# -*- coding: utf-8 -*-
# anon-gate-exemption: rule-definition —— 本文件承载规则负向夹具，属于豁免准入内容
"""``check_submission_anonymity.py`` 门禁契约测试（fail-closed 不被误修击穿）。

背景
----
2026-10-17 实测：提交包 ``source_code/`` 中仍有 9 处开发机用户名路径
（``start_dashboard.bat`` + 4 个 ``run_*.sh``，硬编码 ``C:/Users/<用户名>/...``），
而仓库侧既有门禁全部漏判——

* ``secrets_scan`` 按设计**明确豁免绝对路径**（``test_exempts_absolute_path``）；
* ``scan_identity`` 的 ``include_ext`` 只覆盖 ``.md/.txt/.html/.htm/.pdf/.pptx``，
  **.sh/.bat 根本不在扫描范围**。

即 README §六「不含开发机用户名或绝对路径」的声明长期没有任何自动化兜底。
本门禁（从提交包侧移植入仓）补的正是这个缺口，本测试钉死其契约：

1. **真泄漏必检出**：Windows/Unix 用户目录、绝对工程路径、UNC、手机号；
2. **通用占位必豁免**：``/home/user``、``/Users/runner``、``SomeUser``、
   ``example.com``——否则 Docker 夹具与文档样例会造成误报洪水；
3. **规则/夹具自豁免**：门禁自身与负向夹具文件里的路径串不算泄漏；
4. **机器无关**：门禁源码自身不得写死任何用户名（用门禁自己的规则扫自己）；
5. **退出码语义**：0 干净 / 1 命中（禁止上传）/ 2 用法错误。

注意：测试文件内的"真泄漏"字样一律**运行时拼接**——若写字面量，本门禁
（``--tracked`` 模式）扫到本文件就会把自己拦下（门禁自锁，无法提交）。
"""
from __future__ import annotations


import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "check_submission_anonymity.py"
PY = sys.executable

# 运行时拼接的"真泄漏"向量（绝不在本文件留字面量）
# ⚠️ 假用户名必须避开门禁占位豁免表（someuser/runner/user/...），
#    否则测的是豁免而不是检出（2026-10-17 首轮测试即踩此坑）。
WIN_USER = "C:" + "/Users/" + "devuser01" + "/AppData/x.py"
WIN_USER_BS = "C:" + "\\Users\\" + "devuser01" + "\\x.py"
UNIX_HOME = "/home/" + "devuser01" + "/work/x.py"
UNIX_USERS = "/Users/" + "devuser01" + "/x.py"
APPDATA = "D:" + "\\AppData\\Local\\x.py"
UNC = "\\\\fileserver" + "\\share\\x.py"
PHONE = "138" + "0013" + "8000"


def _run_gate(*args: str, cwd: Path = REPO_ROOT) -> tuple[int, str]:
    proc = subprocess.run(
        [PY, str(GATE), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _write_tmp(content: str, suffix: str = ".py") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="anonscan_")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def _scan_tmp(content: str, suffix: str = ".py") -> tuple[int, str]:
    """把内容写进临时目录，以该目录为 root 跑门禁，返回 (exit, out)。"""
    with tempfile.TemporaryDirectory(prefix="anonscan_root_") as td:
        target = Path(td) / ("leak" + suffix)
        target.write_text(content, encoding="utf-8")
        return _run_gate("--root", td)


# ── 1. 真泄漏必检出 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("vector,label", [
    (WIN_USER, "Windows 用户目录（正斜杠）"),
    (WIN_USER_BS, "Windows 用户目录（反斜杠）"),
    (UNIX_HOME, "Linux home 目录"),
    (UNIX_USERS, "macOS Users 目录"),
    (APPDATA, "绝对工程路径 AppData"),
    (UNC, "UNC 共享路径"),
    (PHONE, "中国大陆手机号"),
])
def test_detects_real_leaks(vector: str, label: str):
    code, out = _scan_tmp(f"PATH = '{vector}'\n")
    assert code == 1, f"{label} 必检出（exit 1），实得 {code}\n{out}"


def test_detects_leak_in_shell_script():
    """.sh 是 2026-10-17 事故的载体（仓库门禁 include_ext 不含 .sh）。"""
    code, out = _scan_tmp(
        '#!/usr/bin/env bash\nexport PY="%s"\n' % WIN_USER, suffix=".sh")
    assert code == 1, f".sh 内用户目录必检出，实得 {code}\n{out}"
    assert "用户目录" in out


def test_detects_leak_in_batch_file():
    code, out = _scan_tmp("set PY=%s\n" % WIN_USER_BS, suffix=".bat")
    assert code == 1, f".bat 内用户目录必检出，实得 {code}\n{out}"


# ── 2. 通用占位必豁免（防误报洪水）─────────────────────────────────────────


@pytest.mark.parametrize("vector", [
    "/home/user/x.py",          # Docker 默认工作路径
    "/home/ubuntu/x.py",
    "/Users/runner/x.py",       # CI runner
    "/Users/Default/x.py",
    "C:/Users/SomeUser/x.py",   # 文档样例占位
    "https://example.com/a",    # 文档联系邮箱/链接
    "foo@example.com",
])
def test_exempts_generic_placeholders(vector: str):
    code, out = _scan_tmp(f"REF = '{vector}'\n")
    assert code == 0, f"通用占位不得判泄漏：{vector}\n{out}"


@pytest.mark.parametrize("vector", [
    "/home/" + "user2" + "/x.py",     # 占位前缀 + 数字后缀 = 真泄漏
    "/Users/" + "runnerx" + "/x.py",  # 占位前缀 + 字母后缀 = 真泄漏
    "C:/Users/" + "someuser2" + "/x.py",
])
def test_placeholder_prefix_is_not_a_free_pass(vector: str):
    """占位豁免不得靠前缀子串匹配放跑真泄漏（边界回归，2026-10-17）。

    原版占位正则无边界：``/home/user`` 会误豁免 ``/home/user2``——
    门禁看着通过、真泄漏大摇大摆进包。本测试钉死边界行为。
    """
    code, out = _scan_tmp(f"PATH = '{vector}'\n")
    assert code == 1, f"占位前缀变体必检出：{vector}\n{out}"


def test_placeholder_before_real_leak_still_flagged():
    """占位豁免必须**逐处**生效，不得整行短路（2026-11-05 修）。

    旧实现每行每类只取 ``re.search`` 的**首处**匹配，首处是占位就 ``continue``
    掉整行 —— ``占位 ... 真泄漏`` 同处一行时真泄漏一路放行（实测 exit 0）。
    这在文档里极常见：「把 C:/Users/SomeUser/... 改成 C:/Users/<真名>/...」。
    """
    real = "C:" + "/Users/" + "devuser01" + "/y"
    code, out = _scan_tmp(
        "把 C:/Users/SomeUser/x 换成 %s\n" % real, suffix=".md")
    assert code == 1, f"占位之后的真泄漏必须检出，实得 {code}\n{out}"


def test_two_leaks_on_one_line_both_reported():
    """同一行两处真泄漏都要报（旧实现只报首处，少报数量）。"""
    mod = _load_gate_module()
    compiled = [(c, re.compile(r)) for c, r in mod.RULES]
    a = "C:" + "/Users/" + "alice01"
    b = "C:" + "/Users/" + "bob02"
    with tempfile.TemporaryDirectory(prefix="anonscan_two_") as td:
        p = Path(td) / "d.md"
        p.write_text("%s/x %s/y\n" % (a, b), encoding="utf-8")
        hits = mod.scan_file(p, compiled)
    snippets = [h[2] for h in hits]
    assert len(snippets) == 2, f"同一行两处泄漏都该报，实得 {snippets}"
    assert any("alice01" in s for s in snippets) and any("bob02" in s for s in snippets), snippets


def test_files_mode_scans_only_named_files():
    """``<file>...`` 显式模式：pre-commit 靠它把范围收敛到本批次暂存文件。

    契约：显式模式不得顺带把同目录干净文件（``sibling_clean.md``）算进去——
    否则 pre-commit 会为历史文件的既有泄漏阻塞无关提交。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_files_") as td:
        dirty = Path(td) / "dirty.py"
        clean = Path(td) / "sibling_clean.md"
        dirty.write_text('PY = "%s"\n' % WIN_USER, encoding="utf-8")
        clean.write_text("clean\n", encoding="utf-8")

        code, out = _run_gate("--root", td, "--files", "sibling_clean.md")
        assert code == 0, f"只给干净文件应退出 0，实得 {code}\n{out}"
        assert "已扫描文件: 1" in out, f"应只扫 1 个文件\n{out}"

        code, out = _run_gate("--root", td, "--files", "dirty.py")
        assert code == 1, f"给脏文件应退出 1，实得 {code}\n{out}"


def test_files_mode_ignores_out_of_scope_extension():
    """不在扩展名白名单里的文件即使显式传参也不扫（与 walk/tracked 同口径）。"""
    with tempfile.TemporaryDirectory(prefix="anonscan_ext_") as td:
        img = Path(td) / "leak.png"
        img.write_bytes(b"\x89PNG\r\n" + WIN_USER.encode("utf-8"))
        code, out = _run_gate("--root", td, "--files", "leak.png")
        assert code == 0, f".png 不在白名单应跳过，实得 {code}\n{out}"
        assert "已扫描文件: 0" in out, f"应扫 0 个文件\n{out}"


def test_staged_mode_flags_only_staged_file():
    """``--staged`` 只看暂存区：pre-commit 的主用法。

    用真实 git 索引验证（而非 mock），因为这条路的价值就在于依赖 git 状态。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_staged_") as td:
        root = Path(td)
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"],
                       cwd=str(root), check=True)
        subprocess.run(["git", "config", "user.name", "tester"],
                       cwd=str(root), check=True)

        untracked = root / "untracked_leak.py"
        untracked.write_text('PY = "%s"\n' % WIN_USER, encoding="utf-8")

        code, out = _run_gate("--staged", "--root", td)
        assert code == 0, f"未入索引的文件不应被拦截，实得 {code}\n{out}"

        subprocess.run(["git", "add", "untracked_leak.py"], cwd=str(root), check=True)
        code, out = _run_gate("--staged", "--root", td)
        assert code == 1, f"暂存后应拦截，实得 {code}\n{out}"
        assert "用户目录" in out


def test_files_mode_takes_priority_over_staged():
    """``--staged`` 与显式文件同时给出时，显式文件优先（files 模式）。

    契约意义：脏文件若**尚未**入索引，``--staged`` 会漏；显式传参必须能补齐，
    且模式串应显示 ``files`` 而非 ``staged``——否则排查时会读错实际覆盖范围。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_prio_") as td:
        root = Path(td)
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
        clean = root / "clean.md"
        clean.write_text("ok\n", encoding="utf-8")
        subprocess.run(["git", "add", "clean.md"], cwd=str(root), check=True)

        dirty = root / "dirty.py"
        dirty.write_text('PY = "%s"\n' % WIN_USER, encoding="utf-8")

        code, out = _run_gate("--staged", "--root", td, "--files", "dirty.py")
        assert code == 1, f"显式文件应覆盖 --staged，实得 {code}\n{out}"
        assert "files 模式" in out, f"应走 files 模式\n{out}"


def test_files_mode_with_empty_list_does_not_fall_back_to_walk():
    """``--files`` 无参数 → files 模式扫 0 个文件，**不得**静默回落到全仓 walk。

    这条是 pre-commit 场景的硬约束：``$()`` 空展开后 ``--files`` 就是无参，
    若回落到 walk，一次提交会挂 8 分钟扫全仓。

    判据刻意用**含 1 个干净文件的临时根目录**而非真实仓库根：walk 模式会扫到
    那 1 个文件（计数 1），files 模式必须计数 0——既能区分模式，又不必跑全仓 8 分钟。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_empty_") as td:
        (Path(td) / "clean.md").write_text("ok\n", encoding="utf-8")
        code, out = _run_gate("--root", td, "--files")
        assert code == 0, f"空 --files 应通过，实得 {code}\n{out}"
        assert "已扫描文件: 0" in out, f"空清单必须扫 0 个文件（未回落 walk）\n{out}"
        assert "files 模式" in out, f"应停留在 files 模式\n{out}"
        assert "本次未做实际检查" in out, f"空清单应显式告警，而非静默通过\n{out}"


def test_fixture_files_carry_no_machine_identity():
    """secrets_scan 的负向夹具不得写死**本机**路径（2026-10-18 实测仍含真实用户名）。

    为什么这条必须存在
    ------------------
    ``test_exempts_absolute_path`` 验证「绝对路径不被判为密钥」，它是 secrets_scan
    的正确行为。**但夹具完全可以用占位用户名**（``SomeUser``）来构造绝对路径，
    断言语义不变；写死本机名纯属多余，且会把真名随提交包外发。

    更糟的是 ``check_submission_anonymity`` 的 ``SELF_EXEMPT_FILES`` 把这两个夹具
    与真正的规则定义文件一起豁免了 —— 连座豁免让它们在门禁眼里永远隐身。
    """
    import getpass
    from pathlib import Path as _P

    users = {u.lower() for u in (getpass.getuser(), _P.home().name)}
    fixtures = ["tests/test_secrets_scan.py", "tests/_mutate_secrets_scan.py"]
    for rel in fixtures:
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        for user in users:
            # ⚠️ 必须 re.I：源码里的用户名可能是首字母大写，而派生值通常小写。
            #    2026-10-18 首版漏了这个 flag —— 红灯用例自己假绿，等于没有测试。
            assert not re.search(
                rf"[Uu]sers[\\/]+{re.escape(user)}(?![\w.-])", src, re.I), (
                f"{rel} 写死了本机用户名路径（{user}）——改用通用占位 SomeUser，"
                f"断言「绝对路径豁免」的语义完全不受影响")


def test_self_exempt_covers_only_rule_definitions():
    """SELF_EXEMPT 只允许容纳**规则定义/夹具自证**文件，不得豁免普通测试夹具。

    2026-10-18 修正：``test_secrets_scan.py`` / ``_mutate_secrets_scan.py``
    被豁免后，其内的真实机器路径在提交包里一路无人拦截。
    """
    exempt = _load_self_exempt()
    forbidden = {"test_secrets_scan.py", "_mutate_secrets_scan.py"}
    leaked = exempt & forbidden
    assert not leaked, (
        "以下文件不应享受自豁免（它们是普通测试夹具，里面的绝对路径用占位用户名"
        f"构造即可达到同样的断言效果）：{sorted(leaked)}")


def _load_self_exempt() -> set[str]:
    """从门禁源码里读出 SELF_EXEMPT_FILES（避免 import 该模块的副作用）。"""
    src = GATE.read_text(encoding="utf-8")
    m = re.search(r"SELF_EXEMPT_FILES\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "门禁应定义 SELF_EXEMPT_FILES"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# ── 3. 规则/夹具自豁免 ─────────────────────────────────────────────────────


def test_self_exempt_files_not_flagged():
    """门禁自身文件名 **且** 文件头带豁免标记：路径串是规则定义，不算泄漏。"""
    with tempfile.TemporaryDirectory(prefix="anonscan_self_") as td:
        target = Path(td) / "check_submission_anonymity.py"
        target.write_text(
            "# anon-gate-exemption: rule-definition\nRULE = \"%s\"\n" % WIN_USER,
            encoding="utf-8")
        code, out = _run_gate("--root", td)
        assert code == 0, f"门禁自身文件名应自豁免，实得 {code}\n{out}"


def test_self_exempt_name_without_marker_is_scanned():
    """同名文件**不等于**规则定义：缺豁免标记就按普通文件扫（2026-11-05 修）。

    旧实现只比文件名，于是把一份自己写的 ``secrets_scan.py`` 打进提交包，
    里面写死 ``C:/Users/<真名>/...`` 也永远隐身 —— 与「只有内容才是规则定义
    才可豁免」的准入判据直接矛盾。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_impostor_") as td:
        target = Path(td) / "secrets_scan.py"
        target.write_text("TEMPLATE = \"%s\"\n" % WIN_USER, encoding="utf-8")
        code, out = _run_gate("--root", td)
        assert code == 1, f"同名但无标记的文件必须被扫出，实得 {code}\n{out}"
        assert "缺豁免标记" in out, f"应显式提示缺标记，便于定位：\n{out}"


def test_repo_exempt_files_carry_marker_in_head():
    """仓库里真正享受豁免的 3 个文件必须自带标记（否则 CI 会扫出规则定义字样）。"""
    mod = _load_gate_module()
    for name in sorted(mod.SELF_EXEMPT_FILES):
        hits = [p for p in REPO_ROOT.rglob(name) if p.is_file()]
        assert hits, f"豁免表里的 {name} 在仓库中不存在——豁免表已过期"
        for p in hits:
            head = p.read_bytes()[:mod.EXEMPT_MARKER_WINDOW]
            assert mod.EXEMPT_MARKER.encode("utf-8") in head, (
                f"{p.relative_to(REPO_ROOT)} 缺豁免标记（首 {mod.EXEMPT_MARKER_WINDOW} 字节内）")



# ── 4. 机器无关：门禁源码自身零泄漏 ────────────────────────────────────────


# 2026-11-04 移除无条件 skip：实测可通过。原 skip 系 d9e701c8
# 为掩盖 legacy 副本口径漂移所加，随漂移一并修复后恢复执行。
def test_gate_source_is_machine_independent():
    """用门禁自己的规则扫门禁自己（ tracked 模式）——源码不得写死用户名。"""
    code, out = _run_gate("--tracked")
    assert code == 0, f"门禁 tracked 模式应零命中，实得 {code}\n{out}"


# ── 5. 退出码语义 ──────────────────────────────────────────────────────────


def test_exit_zero_on_clean_root():
    with tempfile.TemporaryDirectory(prefix="anonscan_clean_") as td:
        (Path(td) / "ok.py").write_text("x = 1\n", encoding="utf-8")
        code, out = _run_gate("--root", td)
    assert code == 0, f"干净目录应 exit 0，实得 {code}\n{out}"


def test_usage_error_on_missing_root():
    code, out = _run_gate("--root", "Z:\\__definitely_missing_dir__")
    assert code == 2, f"不存在的 root 应 exit 2，实得 {code}\n{out}"


# ── 6. 覆盖缺口回归（2026-10-18）─────────────────────────────────────────────
# 背景：门禁此前三点「看着通过、实际没检查」——
#   a) 默认 root 在仓库内跑 → 扫未提交产物 + 历史审计报告 → 18min 且必假阳性；
#      在提交包 source_code/scripts 里跑 → 只扫 source_code/，漏 other/ documents/
#   b) MAX_BYTES=4MB 让 12.3MB 的交付 exe **从未被扫过**
#   c) docx/pdf 是压缩容器，逐行 decode 得到乱码，等于没扫
# 下面每条都用「注入-检出」验证，而不是断言常量存在。


def _load_gate_module():
    """按路径加载门禁模块（只读常量与纯函数，无 CLI 副作用）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _make_package(base: Path, name: str) -> Path:
    """造一个最小提交包结构：source_code/ + other/。"""
    pkg = base / name
    (pkg / "source_code").mkdir(parents=True)
    (pkg / "other").mkdir(parents=True)
    return pkg


def test_binary_channel_detects_utf16_path():
    """exe 里的路径多为 UTF-16LE ——PyInstaller 的典型形态，按行 decode 抓不到。"""
    with tempfile.TemporaryDirectory(prefix="anonscan_bin_") as td:
        exe = Path(td) / "app.exe"
        exe.write_bytes(b"MZ\x90\x00" + b"\x00" * 64
                        + WIN_USER_BS.encode("utf-16-le") + b"\x00" * 16)
        code, out = _run_gate("--root", td)
        assert code == 1, f"exe 内 UTF-16 路径必检出，实得 {code}\n{out}"
        assert "binary=1" in out, f"应走 binary 通道\n{out}"


def test_exe_not_skipped_by_text_size_limit():
    """12.3MB 的交付 exe 曾因 MAX_BYTES=4MB 被整文件跳过。

    这里用 5MB（> 文本阈值 4MB、< 二进制阈值）的 exe 钉死：必须扫到文件尾部。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_bigexe_") as td:
        exe = Path(td) / "big.exe"
        filler = b"\x00" * (5 * 1024 * 1024)
        exe.write_bytes(filler + WIN_USER_BS.encode("utf-16-le"))
        assert exe.stat().st_size > 4 * 1024 * 1024, "夹具必须大于文本阈值"
        code, out = _run_gate("--root", td)
        assert code == 1, f"超过文本阈值但属二进制上限内的 exe 必须被扫，实得 {code}\n{out}"
        assert "体积超限跳过" not in out, f"exe 不应计入跳过项\n{out}"


def test_docx_joins_text_split_across_runs():
    """Word 会把一句话拆成多个 run：``C:/Users/`` + ``devuser01``。

    只看单个 <w:t> 会漏判，必须按文本节点拼接后判定。
    """
    import zipfile

    with tempfile.TemporaryDirectory(prefix="anonscan_docx_") as td:
        docx = Path(td) / "leak.docx"
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr(
                "word/document.xml",
                "<w:document><w:body><w:p>"
                "<w:r><w:t>C:/Users/</w:t></w:r>"
                "<w:r><w:t>" + "devuser01" + "/thesis.docx</w:t></w:r>"
                "</w:p></w:body></w:document>")
        code, out = _run_gate("--root", td)
        assert code == 1, f"跨 run 拼接后必检出，实得 {code}\n{out}"
        assert "container=1" in out, f"应走 container 通道\n{out}"


def test_pdf_flate_stream_detected():
    """PDF 正文在 FlateDecode 流里：不解压就完全看不到文本。"""
    import zlib

    with tempfile.TemporaryDirectory(prefix="anonscan_pdf_") as td:
        pdf = Path(td) / "leak.pdf"
        payload = ("BT /F1 12 Tf (" + WIN_USER + ") Tj ET").encode("utf-8")
        comp = zlib.compress(payload)
        pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Length " + str(len(comp)).encode()
                        + b" /Filter /FlateDecode >>\nstream\n" + comp
                        + b"\nendstream\nendobj\ntrailer\n%%EOF\n")
        code, out = _run_gate("--root", td)
        assert code == 1, f"PDF 压缩流内路径必检出，实得 {code}\n{out}"


def test_container_falls_back_to_strings_when_not_a_real_zip():
    """扩展名是 .docx 但内容不是 zip（改名的文本等）：退回二进制串通道，不得静默放过。"""
    with tempfile.TemporaryDirectory(prefix="anonscan_fake_docx_") as td:
        fake = Path(td) / "fake.docx"
        fake.write_bytes(WIN_USER.encode("utf-8"))
        code, out = _run_gate("--root", td)
        assert code == 1, f"伪容器必须回退到串提取，实得 {code}\n{out}"


def test_detect_package_root_from_repo_sibling():
    """默认 root 应自动落到**同级**的提交包（仓库根与提交包是兄弟目录的常见布局）。"""
    mod = _load_gate_module()
    with tempfile.TemporaryDirectory(prefix="anonscan_pkg_") as td:
        base = Path(td)
        repo = base / "repo"
        (repo / "scripts").mkdir(parents=True)
        pkg = _make_package(base, "MySubmission")
        assert mod.detect_package_root(repo) == pkg


def test_detect_package_root_prefers_primary_over_backup():
    """同级存在 ``_提交包清理备份_20261016`` 这类目录时，不得选中备份。"""
    mod = _load_gate_module()
    with tempfile.TemporaryDirectory(prefix="anonscan_pkg2_") as td:
        base = Path(td)
        repo = base / "repo"
        (repo / "scripts").mkdir(parents=True)
        real = _make_package(base, "Submission")
        _make_package(base, "_提交包清理备份_20261016")
        assert mod.detect_package_root(repo) == real


def test_detect_package_root_refuses_ambiguity():
    """两个同等候选时**不猜**，返回 None 并记录候选（宁可让用户显式 --root）。"""
    mod = _load_gate_module()
    with tempfile.TemporaryDirectory(prefix="anonscan_pkg3_") as td:
        base = Path(td)
        repo = base / "repo"
        (repo / "scripts").mkdir(parents=True)
        _make_package(base, "SubA")
        _make_package(base, "SubB")
        assert mod.detect_package_root(repo) is None
        assert len(mod.LAST_DETECT_AMBIGUOUS) == 2


def test_scan_output_states_root_source_and_coverage():
    """范围必须自证：输出要写清 root 来源、顶层子目录、通道分布。

    没有这三行，"通过"与"没检查"在输出上无法区分——本次三个缺陷都源于此。
    """
    with tempfile.TemporaryDirectory(prefix="anonscan_cov_") as td:
        (Path(td) / "ok.py").write_text("x = 1\n", encoding="utf-8")
        code, out = _run_gate("--root", td)
    assert code == 0
    assert "来源：显式 --root" in out, out
    assert "通道分布" in out, out
    assert "text=1" in out, out
