#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诚实口径扫描器 — pre-commit 门禁

用法::

    python scripts/pre-commit/honesty_scan.py [--cached] [--strict] [--self-test] [文件...]

退出码::

    0  通过：确实扫过文本内容，且零命中
    1  命中假水位短语/正则；或有文件**读不出/解不开**（读不懂 ≠ 没有）；
       --strict 下零个文件被扫描
    2  用法或环境错误（--cached 但 git 不可用 / 不在仓库里）

规则来源：西湖论剑 CTF-Agent 诚实口径扫描器
核心原则：平台 accepted=0 时，任何"解出数递增/真实解出 flag/自主X/X"均为假水位

2026-11-06 修复的四种「扫了等于没扫」：

1. **文件名含空格 → 文件被切碎**：``--cached`` 用 ``split()`` 切 ``git diff`` 输出，
   ``我的 报告.md`` 变成 ``我的`` 与 ``报告.md`` 两个不存在的路径，读失败又被
   ``except Exception: return []`` 吞掉 → 含假水位的文档判「✅ 通过」。改用 ``-z``。
2. **编码不对 → 短语永远不可能命中**：``read_text(errors="ignore")`` 读 UTF-16/GBK
   文档时把中文整段丢掉，剩下的 ASCII 里没有假水位短语 → 「通过」。改为多编码探测。
3. **子串过滤把真文件排除在外**：主循环另叠一层 ``"dist" in path`` 判断，于是
   ``.github/workflows/ci.yml``（含 ``.git``）、``scripts/build_*.py``、
   ``static/v9-distributed.*`` 等 8 个文件从未被扫过 —— **包括运行本门禁的 CI 文件本身**。
   改为单一跳过规则（路径段精确匹配）。
4. **读不出与没违规不可分、零扫描也打 ✅**：目录/权限/悬空链接、以及「一个文件都没扫到」
   都曾打印「✅ 诚实口径扫描通过」。现在给出扫描计数，并让读不出在默认模式下即失败。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# 命中即报错的短语（历史违规样本）
FORBIDDEN_PHRASES = (
    "冲第一", "真实水位 89%", "真实水位 92%", "真实水位 100%",
    "自主 7/7", "将功补过", "解出数提升",
    "5→13", "13→15", "15→16", "16→26",
    "解出数 16", "解出数 26",
)

# 命中即报错的正则
FORBIDDEN_PATTERNS = (
    re.compile(r"解出数\s*\d+\s*→\s*\d+"),
    re.compile(r"\+\d+\s*真实解出"),
    re.compile(r"真实解出[^。\n]*flag"),
)

# 引号包裹的内容是「提及」非「使用」，剥离后再匹配
_QUOTE_RE = re.compile("「[^」]*」|『[^』]*』|\"[^\"]*\"|'[^']*'")

# 排除目录（**路径段精确匹配**，不是子串）
_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", "dist", "build"}
_SKIP_PREFIX = ("_archive", "race_attachments", "work_web", "platform_downloads")

#: 依次尝试的文本编码。顺序不是随意的：UTF-8 严格优先（错判成本最低），
#: GBK 殿后（它对任意字节都能解出**某些东西**，所以必须最后试、且要过可读性闸门）。
TEXT_ENCODINGS: Tuple[str, ...] = ("utf-8", "utf-8-sig", "gbk")

#: 除 \t\r\n 外的控制字符占比上限。GBK/UTF-16 能「成功」解出二进制垃圾，
#: 这个闸门负责把那种「解出来了但明显不是文本」挡回去。
CONTROL_RATIO_MAX = 0.02

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")

STATUS_TEXT = "text"
STATUS_EMPTY = "empty"
STATUS_BINARY = "binary"
STATUS_UNREADABLE = "unreadable"
STATUS_DECODE_FAILED = "decode_failed"

#: 这两种状态表示「读不懂」，与「读懂了、没命中」必须分开。
PROBLEM_STATUSES = (STATUS_UNREADABLE, STATUS_DECODE_FAILED)


def is_skipped(path: Path) -> bool:
    """是否整份忽略。只认**路径段**，不做子串匹配。

    子串匹配的历史教训：``".git" in ".github/workflows/ci.yml"`` 为真，于是 CI 配置
    本身从未被这道门禁读过；同理 ``"build"`` 会把 ``scripts/build_dashboard_data.py``、
    ``"dist"`` 会把 ``static/v9-distributed.js`` 一并吞掉（本仓 8 个文件）。
    """
    parts = set(path.parts)
    if parts & _SKIP_DIRS:
        return True
    for part in path.parts:
        if part.startswith(_SKIP_PREFIX):
            return True
    return False


def scan_text(text: str, path: str = "") -> List[str]:
    hits = []
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = _QUOTE_RE.sub("", line)
        for phrase in FORBIDDEN_PHRASES:
            if phrase in stripped:
                hits.append(f"{path}:{idx}: 假水位短语 {phrase!r}")
        for pat in FORBIDDEN_PATTERNS:
            if pat.search(stripped):
                hits.append(f"{path}:{idx}: 假水位正则 {pat.pattern!r}")
    return hits


def _readable(text: str) -> bool:
    if not text:
        return False
    bad = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\r\n")
    return bad / len(text) <= CONTROL_RATIO_MAX


def classify_bytes(raw: bytes) -> Tuple[str, str, str]:
    """把原始字节判成 (文本, 状态, 说明)。

    「解不开」必须是一个**状态**而不是空字符串：空字符串会让调用方以为
    「读到了内容但没有命中」，也就是把「读不懂」折叠成「没有」。
    """
    if not raw:
        return "", STATUS_EMPTY, "空文件"
    if raw.startswith(_UTF16_BOMS):
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            return "", STATUS_DECODE_FAILED, f"UTF-16 BOM 但解码失败：{exc}"
        if not _readable(text):
            return "", STATUS_BINARY, "UTF-16 解码后控制字符占比过高"
        return text, STATUS_TEXT, "utf-16"
    if b"\x00" in raw:
        # 无 BOM 的 UTF-16 与二进制（PNG/PDF/PE）在字节层无法安全区分。
        # 按二进制显式跳过并计数，绝不假装「扫过且干净」。
        return "", STATUS_BINARY, "含 NUL 且无 UTF-16 BOM"
    attempted = []
    for enc in TEXT_ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError as exc:
            attempted.append(f"{enc}@{exc.start}")
            continue
        if not _readable(text):
            return "", STATUS_BINARY, f"按 {enc} 解码后控制字符占比过高"
        return text, STATUS_TEXT, enc
    return "", STATUS_DECODE_FAILED, "非 UTF-8/GBK 文本（" + "，".join(attempted) + "）"


def read_document(path: Path) -> Tuple[str, str, str]:
    """读一个文件，返回 (文本, 状态, 说明)。绝不把异常折叠成「没有命中」。"""
    try:
        if path.is_dir():
            return "", STATUS_UNREADABLE, "是目录不是文件"
        raw = path.read_bytes()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        return "", STATUS_UNREADABLE, f"{exc.__class__.__name__}: {detail}"
    return classify_bytes(raw)


def scan_document(path: Path) -> Dict[str, object]:
    text, status, reason = read_document(path)
    hits = scan_text(text, str(path)) if status == STATUS_TEXT else []
    return {"path": str(path), "status": status, "reason": reason, "hits": hits}


def scan_file(filepath: Path) -> List[str]:
    """兼容旧调用：只返回命中列表（读不出时返回空，需详细状态请用 scan_document）。"""
    if is_skipped(filepath):
        return []
    return list(scan_document(filepath)["hits"])  # type: ignore[arg-type]


def split_z(raw: bytes) -> List[str]:
    """解析 ``git ... -z`` 的 NUL 分隔输出。

    文件名可以含空格、制表符甚至换行；``str.split()`` 会把它们切成不存在的路径，
    随后「读失败 → 无命中 → 通过」。这里只按 ``\\0`` 切。
    """
    text = raw.decode("utf-8", "surrogateescape")
    return [item for item in text.split("\0") if item]


def get_staged_files(cwd: Optional[Path] = None) -> Tuple[List[Path], str]:
    """返回 (暂存文件列表, 错误说明)。git 不可用时错误说明非空 —— 调用方必须失败。"""
    cmd = ["git", "-c", "core.quotePath=false", "diff", "--cached",
           "--name-only", "-z", "--diff-filter=ACM"]
    try:
        proc = subprocess.run(cmd, capture_output=True, cwd=str(cwd) if cwd else None)
    except OSError as exc:
        return [], f"无法执行 git：{exc}"
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.decode("utf-8", "replace").splitlines()
                 if ln.strip()]
        # git 的用法提示会刷几十行，真正的原因在 "fatal:"/"error:" 那行；
        # 只取最后一行会把「not a git repository」淹没在 usage 里。
        detail = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))),
                      lines[0] if lines else "无错误输出")
        return [], f"git 退出码 {proc.returncode}：{detail}"
    return [Path(item) for item in split_z(proc.stdout)], ""


def collect_default_files() -> List[Path]:
    return [p for p in sorted(Path(".").rglob("*")) if p.is_file()]


def decide_exit(hits: Sequence[str], problems: Sequence[Dict[str, object]],
                scanned: int, strict: bool) -> Tuple[int, str]:
    """唯一的判定入口。抽成纯函数，便于自证与变异测试。"""
    if hits:
        return 1, f"命中 {len(hits)} 处假水位"
    if problems:
        return 1, f"{len(problems)} 个文件读不出/解不开 —— 读不懂不等于没有假水位"
    if scanned == 0:
        if strict:
            return 1, "零个文件被扫描 —— 什么都没扫不等于通过（--strict）"
        return 0, "零个文件被扫描（未启用 --strict，不判失败）"
    return 0, ""


# --------------------------------------------------------------------------- #
# 自证：用临时目录现造样本，证明四类失明都被堵上
# --------------------------------------------------------------------------- #
_FIXTURE_PHRASE = "本轮解出数 5→13 个"


def run_self_test(verbose: bool = True) -> int:
    failures: List[str] = []
    passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<22} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<22} → FAIL {detail}")

    def scan_hits(text: str) -> List[str]:
        return scan_text(text, "<fixture>")

    check("phrase_hits", bool(scan_hits(_FIXTURE_PHRASE)))
    check("quoted_mention", not scan_hits("他提到「解出数 5→13」这个词"))

    with tempfile.TemporaryDirectory(prefix="honesty_selftest_") as tmp:
        root = Path(tmp)

        spaced = root / "报告 记录.md"
        spaced.write_bytes((_FIXTURE_PHRASE + "\n").encode("utf-8"))
        names = split_z((str(spaced) + "\0" + str(root / "b.md") + "\0").encode("utf-8"))
        check("z_split_keeps_space", len(names) == 2 and names[0].endswith("报告 记录.md"),
              f"{names}")
        doc = scan_document(spaced)
        check("spaced_name_scanned", doc["status"] == STATUS_TEXT and bool(doc["hits"]),
              f"{doc['status']}")

        u16 = root / "u16.md"
        u16.write_bytes(_FIXTURE_PHRASE.encode("utf-16"))  # Windows 记事本「Unicode」
        d16 = scan_document(u16)
        check("utf16_bom_decoded", d16["status"] == STATUS_TEXT and bool(d16["hits"]),
              f"{d16['status']}")

        gbk = root / "gbk.md"
        gbk.write_bytes(_FIXTURE_PHRASE.encode("gbk"))
        dgbk = scan_document(gbk)
        check("gbk_decoded", dgbk["status"] == STATUS_TEXT and bool(dgbk["hits"]),
              f"{dgbk['status']}")

        png = root / "fig.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 16)
        dpng = scan_document(png)
        check("binary_skipped", dpng["status"] == STATUS_BINARY,
              f"{dpng['status']} {dpng['reason']}")

        ddir = scan_document(root)
        check("dir_unreadable", ddir["status"] == STATUS_UNREADABLE, f"{ddir['status']}")

        missing = scan_document(root / "not_there.md")
        check("missing_unreadable", missing["status"] == STATUS_UNREADABLE,
              f"{missing['status']}")

    check("github_not_skipped", not is_skipped(Path(".github/workflows/ci.yml")))
    check("build_dir_skipped", is_skipped(Path("build/out.py")))
    check("dist_file_not_skipped", not is_skipped(Path("static/v9-distributed.js")))

    check("strict_zero_fails", decide_exit([], [], 0, True)[0] == 1)
    check("zero_nonstrict_passes", decide_exit([], [], 0, False)[0] == 0)
    check("unreadable_blocks", decide_exit([], [{"path": "x"}], 1, False)[0] == 1)
    check("scanned_clean_passes", decide_exit([], [], 3, True)[0] == 0)

    total = passed + len(failures)
    if failures:
        for item in failures:
            print(f"❌ [自证失败] {item}")
        print(f"❌ 自证失败 {len(failures)}/{total} 项")
        return 1
    print(f"✅ 自证通过 {passed}/{total}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="诚实口径扫描器（假水位短语/正则）")
    parser.add_argument("--cached", action="store_true", help="扫描暂存区文件")
    parser.add_argument("--strict", action="store_true",
                        help="零个文件被扫描时判失败（默认只告警）")
    parser.add_argument("--self-test", action="store_true", help="内置夹具自证")
    parser.add_argument("files", nargs="*", help="指定文件列表")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    error = ""
    if args.cached:
        files, error = get_staged_files()
    elif args.files:
        files = [Path(f) for f in args.files]
    else:
        files = collect_default_files()

    if error:
        # 拿不到文件列表 ≠ 没有违规。旧实现这里返回 []，于是「✅ 通过」。
        print(f"❌ 无法取得待扫文件列表（{error}）—— 未扫描不等于通过")
        return 2

    hits: List[str] = []
    problems: List[Dict[str, object]] = []
    scanned = binary = ignored = 0

    for item in files:
        path = Path(item)
        if is_skipped(path):
            ignored += 1
            continue
        doc = scan_document(path)
        status = doc["status"]
        if status == STATUS_BINARY:
            binary += 1
            continue
        if status == STATUS_EMPTY:
            continue
        if status in PROBLEM_STATUSES:
            problems.append(doc)
            continue
        scanned += 1
        hits.extend(doc["hits"])  # type: ignore[arg-type]

    for hit in hits:
        print(f"❌ {hit}")
    for doc in problems:
        print(f"❌ {doc['path']}: 读不出（{doc['reason']}）—— 读不懂不等于没有假水位")

    code, why = decide_exit(hits, problems, scanned, args.strict)
    stats = f"扫过 {scanned} 个文本文件，跳过 {binary} 个二进制、{ignored} 个忽略路径"
    if code == 0:
        if scanned == 0:
            print(f"⚠️ 诚实口径扫描：零个文件被扫描（{stats}）—— 未启用 --strict，不判失败")
        else:
            print(f"✅ 诚实口径扫描通过（{stats}）")
    else:
        print(f"❌ {why}（{stats}）")
    return code


if __name__ == '__main__':
    sys.exit(main())
