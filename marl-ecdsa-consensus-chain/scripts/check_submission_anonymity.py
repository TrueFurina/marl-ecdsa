#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_submission_anonymity.py —— 身份/机器路径合规门禁（一票否决）
=================================================================

为什么要有这个脚本（仓库侧根因）
--------------------------------
README §六 声明提交包「不含团队成员姓名、学校、指导教师、个人邮箱/手机、
私钥证书、**开发机用户名或绝对路径**」。但 2026-10-17 之前，这条声明
**长期没有任何自动化门禁兜底**：

* ``secrets_scan`` 只管密钥，且按其设计**绝对路径是被明确豁免的**
  （见 ``tests/test_secrets_scan.py::test_exempts_absolute_path``）；
* ``scan_identity`` 的 ``include_ext`` 只覆盖
  ``.md/.txt/.html/.htm/.pdf/.pptx``——**.sh/.bat 根本不在扫描范围**。

2026-10-17 实测在提交包 ``source_code/`` 中仍有 9 处
``C:/Users/<用户名>/...``（``start_dashboard.bat`` + 4 个 ``run_*.sh``），
即该声明被击穿。本脚本补的就是这个缺口，与 secrets_scan 互补、互不替代：

    secrets_scan      → 密钥/凭据（绝对路径豁免）
    check_anonymity   → 身份/机器路径（正是 secrets_scan 豁免掉的那部分）

用法
----
    python scripts/check_submission_anonymity.py                 # 自动定位提交包根；找不到则扫仓库根
    python scripts/check_submission_anonymity.py --tracked       # 只扫 git 跟踪文件（CI 快路）
    python scripts/check_submission_anonymity.py --staged        # 只扫暂存区文件（pre-commit 快路）
    python scripts/check_submission_anonymity.py --files <file>...  # 显式指定文件（优先级最高）
    python scripts/check_submission_anonymity.py --root <路径>    # 指定根（如提交包目录）
    python scripts/check_submission_anonymity.py --strict         # 告警也判失败

三条扫描通道（2026-10-18 补后两者，此前它们的"通过"只是没被检查）
------------------------------------------------------------------
    text       直接 decode：源码 / 脚本 / JSON / 文档
    binary     ASCII + UTF-16LE 串提取：exe / dll（PyInstaller 路径多为 UTF-16）
    container  docx/xlsx/pptx 解 zip 取文本节点（跨 run 拼接）；pdf 解 FlateDecode 流

三者职责分工（pre-commit / CI / 打包前三段防线）：

    --staged   pre-commit：只对本批次入索引的文件负责，泄漏即拦截
    --tracked  CI：全量跟踪文件复扫，兜底历史泄漏（不受分批绕过影响）
    默认/--root 打包后：对提交包成品目录做最后一英里复核

退出码
------
    0  无命中（允许提交/上传）
    1  有命中（禁止）
    2  用法/配置错误
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# ── 检测规则：(类别, 正则) ────────────────────────────────────────────────
# 设计原则：机器无关。绝不在本文件里写死某一台机器的用户名，
# 否则规则本身就成为泄漏源（这正是原 gen_assurance_config.py 的问题）。
RULES: list[tuple[str, str]] = [
    # Windows 用户目录：C:/Users/<name>/ 或 C:\Users\<name>\
    ("用户目录(Win)", r"[A-Za-z]:[\\/]+[Uu]sers[\\/]+[A-Za-z0-9._-]+"),
    # macOS / Linux 用户目录：/Users/<name>/ 或 /home/<name>/
    # 前置排除冒号：否则 C:/Users/<name> 会被 Win 规则与 Unix 规则各报一次（实测重复计数）
    ("用户目录(Unix)", r"(?<![\w:])(?:/Users/|/home/)[A-Za-z0-9._-]+"),
    # 开发者/评审可见的绝对工程路径（不含用户目录形态的兜底）
    ("绝对路径(Win)", r"[A-Za-z]:[\\/]+(?:Program\s+Files|AppData|Workspace|Projects|Dev)[\\/]"),
    # UNC 共享路径：\\server\share[\...]
    # 收紧两点（2026-10-18 实测 exe 字符串）：
    #   1) 分隔符只认反斜杠 —— 原 `[\\/]` 让二进制里的 "\\u6/4" 这类转义片段误命中
    #   2) 排除 u6/u4 这种 Unicode 转义残片形态（后随反斜杠）
    ("UNC", r"\\\\(?!(?i:u[0-9a-f]{1,3}\\))[A-Za-z0-9_.-]{2,}(?:\\[A-Za-z0-9_.$-]+)+"),
    # 邮箱
    ("邮箱", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # 中国大陆手机号
    # 前后均排除数字**和小数点**：否则实验数据里的浮点尾数
    # （如 15753.17172498096）会被误判 —— 这类误伤必须靠边界排除，不能靠放宽规则。
    # 边界须排除字母：否则 64 位十六进制哈希里恰好出现的 11 位数字会被误判
    # （实测：current_block_hash "f1d1…f14379350934a91c…"）。真实手机号前后不会紧邻字母。
    ("手机号", r"(?<![0-9A-Za-z.])1[3-9]\d{9}(?![0-9A-Za-z])"),
]

# 仅告警（不判失败）：出现在规则定义/测试用例里属正常，人工复核即可
WARN_ONLY_CATEGORIES = {"邮箱"}  # 文档里可能有官方联系邮箱，允许人工确认

# 通用占位 / 容器默认路径：不构成机器身份，必须豁免，否则会像浮点尾数一样淹没真信号。
# （实测来源：other/测试数据 里大量 "/home/user"，是 Docker 内的默认工作路径）
# ⚠️ 每个占位后必须跟 (?![\w.-]) 边界：否则 "/home/user" 会误豁免 "/home/user2"、
#    "/Users/runnerx" 这类真泄漏（前缀子串匹配，2026-10-17 测试揪出并修复）。
GENERIC_PLACEHOLDER = re.compile(
    r"(?i)"
    r"(?:[\\/]Users[\\/](?:Shared|Public|Default|runner|administrator|someuser))(?![\w.-])"
    r"|(?:[\\/]home[\\/](?:user|ubuntu|anon|runner|root|default))(?![\w.-])"
    r"|SomeUser(?![\w])|EXAMPLE(?![\w])|example\.com(?![\w.-])"
    r"|foo@bar(?![\w])|placeholder(?![\w])|<[A-Za-z_-]+>"
)

# ── 扫描范围 ──────────────────────────────────────────────────────────────
# 覆盖脚本类文件：.bat/.sh/.ps1/.cmd 是历史上被漏掉的（secrets_scan 只看代码）
INCLUDE_EXT = {
    ".py", ".bat", ".cmd", ".sh", ".ps1", ".bash", ".zsh",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".js", ".ts", ".vue", ".jsx", ".tsx",
    ".c", ".h", ".cpp", ".java", ".go", ".rs", ".sol",
}
# 二进制：按可打印串提取（ASCII + UTF-16LE）后判，不逐行 decode
BINARY_EXT = {".exe", ".dll", ".so", ".dylib", ".pyd", ".node"}
# 压缩容器：逐行 decode 只会得到乱码，必须解压后抽文本再判
CONTAINER_EXT = {".docx", ".xlsx", ".pptx", ".pdf"}
INCLUDE_EXT |= BINARY_EXT | CONTAINER_EXT
EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "dist", "build",
    ".rea-probe",
}
# 本脚本自身与既有豁免样例：规则/负向夹具里的路径串不算泄漏
# ⚠️ 连座豁免的危害（2026-10-18 实测）：原先把 test_secrets_scan.py /
#    _mutate_secrets_scan.py 也豁免了，而它们只是**普通夹具** —— 里面写死着
#    真实机器路径 C:/Users/<真用户名>/...，在门禁眼里却永远隐身，一路随提交包外发。
#    夹具完全可以用 SomeUser 之类的占位构造绝对路径，断言语义不变。
#   → 准入判据：只有当文件里出现的东西是**规则定义本身**（如 secrets_scan 的豁免注释、
#     本脚本的正则常量）才可豁免；测试数据一律不得豁免。由
#     tests/test_check_submission_anonymity.py::test_self_exempt_covers_only_rule_definitions 钉死。
SELF_EXEMPT_FILES = {
    "check_submission_anonymity.py",
    "test_check_submission_anonymity.py",
    "secrets_scan.py",
}
# ⚠️ 体积上限必须按类型分级（2026-10-18 修）：
#    原先单一 MAX_BYTES=4MB 让交付的 12.3MB exe **从未被扫过一次** ——
#    也就是说它是「因为没被检查所以通过」。PyInstaller 打包的 exe 恰恰最容易
#    带出构建机的 C:/Users/<name>/... ，是最高风险文件。
MAX_TEXT_BYTES = 4 * 1024 * 1024        # 文本：4MB 足够，再大多为数据噪声
MAX_BINARY_BYTES = 128 * 1024 * 1024    # 二进制：按串提取扫，128MB 兜底
MAX_CONTAINER_BYTES = 64 * 1024 * 1024  # 压缩容器：解压后抽文本
# 兼容旧名（外部脚本/文档可能引用）
MAX_BYTES = MAX_TEXT_BYTES


def _limit_for(suffix: str) -> int:
    if suffix in CONTAINER_EXT:
        return MAX_CONTAINER_BYTES
    if suffix in BINARY_EXT:
        return MAX_BINARY_BYTES
    return MAX_TEXT_BYTES


def _within_limit(p: Path) -> bool:
    try:
        return p.stat().st_size <= _limit_for(p.suffix.lower())
    except OSError:
        return False


def iter_files(root: Path, skipped: list | None = None):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() not in INCLUDE_EXT:
                continue
            if not _within_limit(p):
                # 跳过必须可见：否则「通过」和「没检查」在输出上无法区分（本脚本踩过）
                if skipped is not None:
                    try:
                        skipped.append((p, p.stat().st_size))
                    except OSError:
                        skipped.append((p, -1))
                continue
            yield p


def iter_tracked(root: Path):
    """只扫 git 跟踪文件 —— CI/pre-commit 快路（仓库含约 7400 个未跟踪实验产物，
    walk 模式实测 8 分钟以上，无法进 CI；跟踪文件仅约 500 个，秒级）。"""
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if proc.returncode != 0:
        print(f"[fail] git ls-files 失败（root={root}）：{proc.stderr.strip()}",
              file=sys.stderr)
        sys.exit(2)
    for rel in proc.stdout.splitlines():
        if not rel.strip():
            continue
        yield from _filter_paths([root / rel], root)


def iter_staged(root: Path):
    """只扫暂存区（git diff --cached）文件 —— pre-commit 快路。

    比 --tracked 更准：pre-commit 只应对本批次进入索引的文件负责，
    不该为历史文件的既有泄漏阻塞新提交（历史泄漏由 CI 的 --tracked 兜底）。
    """
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", "diff", "--cached",
         "--name-only", "--diff-filter=ACM"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if proc.returncode != 0:
        print(f"[fail] git diff --cached 失败（root={root}）：{proc.stderr.strip()}",
              file=sys.stderr)
        sys.exit(2)
    yield from _filter_paths((root / rel for rel in proc.stdout.splitlines()), root)


def iter_explicit(names, root: Path):
    """扫显式给出的文件路径 —— pre-commit 与一次性定向排查。"""
    yield from _filter_paths(_resolve_each(names, root), root)


def _resolve_each(names, root: Path):
    for raw in names:
        raw = raw.strip()
        if not raw:
            continue
        p = Path(raw)
        yield p if p.is_absolute() else (root / p)


def _filter_paths(paths, root: Path):
    """统一过滤：扩展名白名单 + 体积上限 + 存在性。"""
    for p in paths:
        if not p.is_file():
            continue
        if p.suffix.lower() not in INCLUDE_EXT:
            continue
        if not _within_limit(p):
            continue
        yield p


# ── 文本抽取：三条通道 ────────────────────────────────────────────────────
# text      → 直接 decode
# binary    → 抽可打印串（ASCII + UTF-16LE），PyInstaller exe 的路径多为 UTF-16
# container → docx/xlsx/pptx 解 zip 取 XML 文本；pdf 解 FlateDecode 流取字符串
_PRINTABLE_ASCII = re.compile(rb"[\x20-\x7e]{5,}")
_PRINTABLE_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){5,}")
_XML_TEXT = re.compile(r"<(?:\w+:)?t(?:\s[^>]*)?>(.*?)</(?:\w+:)?t>", re.S)
_XML_TAG = re.compile(r"<[^>]+>")


def _strings_from_binary(raw: bytes) -> list[str]:
    """从二进制里抽可打印串。同一条串可能两种编码都存在，去重后返回。"""
    out: list[str] = []
    out.extend(s.decode("ascii", "ignore") for s in _PRINTABLE_ASCII.findall(raw))
    out.extend(s.decode("utf-16-le", "ignore") for s in _PRINTABLE_UTF16.findall(raw))
    return out


def _text_from_ooxml(path: Path) -> list[str]:
    """docx/xlsx/pptx 本质是 zip：取 <w:t>/<a:t>/<t> 文本节点拼接。"""
    import zipfile
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                low = name.lower()
                if not low.endswith((".xml", ".rels")):
                    continue
                if not (low.startswith("word/") or low.startswith("xl/")
                        or low.startswith("ppt/") or low.endswith(".rels")):
                    continue
                try:
                    xml = zf.read(name).decode("utf-8", "replace")
                except (OSError, RuntimeError):
                    continue
                # 先按文本节点拼接（Word 会把一句话拆成多个 run），再退化为整体去标签
                parts = _XML_TEXT.findall(xml)
                if parts:
                    chunks.append("".join(parts))
                chunks.append(_XML_TAG.sub(" ", xml))
    except (zipfile.BadZipFile, OSError):
        return []
    return chunks


def _text_from_pdf(path: Path) -> list[str]:
    """不依赖第三方库：解 FlateDecode 流，抽 Tj/TJ 的 (…) 与 <…> 字面量。"""
    import zlib
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    chunks: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        body = m.group(1)
        try:
            data = zlib.decompress(body)
        except zlib.error:
            data = body
        # 圆括号字符串（注意转义）与十六进制字符串
        for lit in re.finditer(rb"\((?:\\.|[^\\()])*\)", data):
            s = lit.group(0)[1:-1]
            s = re.sub(rb"\\(.)", rb"\1", s)
            chunks.append(s.decode("utf-8", "ignore"))
        for lit in re.finditer(rb"<([0-9A-Fa-f\s]{8,})>", data):
            hexs = re.sub(rb"\s", b"", lit.group(1))
            if len(hexs) % 4 == 0:
                try:
                    chunks.append(bytes.fromhex(hexs.decode()).decode("utf-16-be", "ignore"))
                except ValueError:
                    pass
    return chunks


def extract_units(path: Path) -> tuple[list[str], str]:
    """返回 (待扫文本单元, 通道名)。每个单元视作一行，便于定位。"""
    suffix = path.suffix.lower()
    try:
        raw = path.read_bytes()
    except OSError:
        return [], "unreadable"
    if suffix in BINARY_EXT:
        return _strings_from_binary(raw), "binary"
    if suffix in CONTAINER_EXT:
        units = _text_from_pdf(path) if suffix == ".pdf" else _text_from_ooxml(path)
        # 兜底：容器可能不是有效 zip/pdf（改名的文本等），再按二进制串试一次
        if not units:
            units = _strings_from_binary(raw)
            if units:
                return units, "container→binary"
        return units, "container"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text.splitlines(), "text"


def scan_file(path: Path, compiled, stats=None) -> list[tuple[str, int, str, str]]:
    units, channel = extract_units(path)
    if stats is not None:
        stats[channel] = stats.get(channel, 0) + 1
    hits = []
    for lineno, line in enumerate(units, 1):
        if not line:
            continue
        for category, rx in compiled:
            m = re.search(rx, line)
            if m:
                snippet = m.group(0)
                # 过滤通用占位：负向夹具样例 / 容器默认路径等（不构成机器身份）
                if GENERIC_PLACEHOLDER.search(snippet):
                    continue
                hits.append((category, lineno, snippet, line.strip()[:160]))
    return hits


# ── 扫描根解析（2026-10-18 修：默认根两边都不对） ──────────────────────────
# 旧行为 `root = Path(__file__).parent.parent`：
#   * 在仓库内跑 → 扫到 results/ 数千个未跟踪 JSON + 历史审计报告 → 18min 且必假阳性
#   * 在提交包 source_code/scripts 里跑 → 只扫 source_code/，**漏 other/ documents/**
# 现改为：显式 --root > 提交包自动探测 > 脚本上级（并显式提示范围，不静默）。
PACKAGE_MARKERS = ("source_code", "other", "documents")

#: 同级存在多个候选提交包时的歧义记录（交由 main 显式提示，绝不擅自挑一个）
LAST_DETECT_AMBIGUOUS: list[Path] = []


def _is_package_root(p: Path) -> bool:
    try:
        if not p.is_dir():
            return False
        names = {c.name for c in p.iterdir() if c.is_dir()}
    except OSError:
        return False
    return "source_code" in names and bool({"other", "documents"} & names)


_BACKUP_NAME = re.compile(r"(?i)备份|backup|bak\b|副本|copy|old\b|tmp|临时")


def _looks_like_backup(p: Path) -> bool:
    """目录名带备份/临时语义 → 不是当前提交包（实测存在 ``_提交包清理备份_20261016``）。"""
    return bool(_BACKUP_NAME.search(p.name)) or p.name.startswith("_")


def detect_package_root(start: Path) -> Path | None:
    """寻找提交包根：先向上两层，再看**一层**同级目录。

    判据是结构性的 ``source_code/`` + （``other/`` 或 ``documents/``），不依赖目录名，
    因此中英文命名的提交包都能命中。

    同级只看 ``start.parent`` 这一层：扩大到祖父级会把无关目录（例如临时目录下的
    其他工程/夹具）也算成候选，导致真实场景恒被判歧义（2026-10-18 测试实测）。

    歧义处理：同级命中多个时，先排除备份/临时目录；若仍不唯一，**不猜**，
    返回 None 并由 main 打印候选清单。
    """
    for cand in (start, start.parent):
        if _is_package_root(cand):
            return cand
    # 仓库根与提交包常常是兄弟目录：只在「唯一命中」时才采用
    LAST_DETECT_AMBIGUOUS.clear()
    hits: list[Path] = []
    try:
        parent = start.parent
        children = [c for c in parent.iterdir() if c.is_dir() and not c.name.startswith(".")]
    except OSError:
        children = []
    for c in children:
        if c == start or c in hits:
            continue
        if _is_package_root(c):
            hits.append(c)
    primary = [h for h in hits if not _looks_like_backup(h)]
    if len(primary) == 1:
        return primary[0]
    LAST_DETECT_AMBIGUOUS.extend(primary if len(primary) > 1 else hits)
    return None


def _git_toplevel(start: Path) -> Path | None:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          cwd=str(start), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return Path(out) if out else None


def resolve_root(explicit: str | None, prefer_git: bool) -> tuple[Path, str]:
    if explicit:
        return Path(explicit).resolve(), "显式 --root"
    here = Path(__file__).resolve().parent
    base = here.parent if here.name == "scripts" else here
    if prefer_git:
        top = _git_toplevel(base)
        return (top, "git 仓库根") if top else (base, "脚本上级（未找到 git 根）")
    pkg = detect_package_root(base)
    if pkg is not None:
        return pkg, "自动探测：提交包根"
    return base, "脚本上级（未探测到提交包结构）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="扫描根路径，默认本文件所在仓库/包的根")
    ap.add_argument("--tracked", action="store_true",
                    help="只扫 git 跟踪文件（CI/pre-commit 快路，跳过未跟踪实验产物）")
    ap.add_argument("--strict", action="store_true", help="告警项也判失败")
    ap.add_argument("--staged", action="store_true",
                    help="只扫暂存区文件（pre-commit 快路）")
    # ⚠️ 必须是 **选项** 而非位置参数：argparse 对 nargs="*" 的位置参数在缺失时
    #    也返回 []，无法区分「没传」和「传了空列表」——pre-commit 里
    #    $() 空展开后就会静默回落到全仓 walk（实测 8 分钟，且覆盖范围与意图不符）。
    ap.add_argument("--files", nargs="*", default=None,
                    help="显式指定待扫文件（优先级最高；pre-commit 传暂存区文件）")
    args = ap.parse_args()

    prefer_git = bool(args.tracked or args.staged)
    root, root_reason = resolve_root(args.root, prefer_git)
    if not root.exists():
        print(f"[fail] 扫描根不存在：{root}", file=sys.stderr)
        return 2

    compiled = [(cat, re.compile(rx)) for cat, rx in RULES]

    failures: list[tuple[Path, str, int, str, str]] = []
    warnings: list[tuple[Path, str, int, str, str]] = []
    skipped: list[tuple[Path, int]] = []
    channels: dict[str, int] = {}
    scanned = 0

    if args.files is not None:
        source, mode = iter_explicit(args.files, root), "files"
    elif args.staged:
        source, mode = iter_staged(root), "staged"
    elif args.tracked:
        source, mode = iter_tracked(root), "tracked"
    else:
        source, mode = iter_files(root, skipped), "walk"
    for p in source:
        if p.name in SELF_EXEMPT_FILES:
            continue
        scanned += 1
        for category, lineno, snippet, line in scan_file(p, compiled, channels):
            rec = (p, category, lineno, snippet, line)
            if category in WARN_ONLY_CATEGORIES:
                warnings.append(rec)
            else:
                failures.append(rec)

    print(f"[scan] 根目录: {root}（{mode} 模式；来源：{root_reason}）")
    try:
        tops = sorted(d.name for d in root.iterdir()
                      if d.is_dir() and d.name not in EXCLUDE_DIRS and not d.name.startswith("."))
        print(f"[scan] 顶层子目录: {', '.join(tops) if tops else '（无）'}")
    except OSError:
        pass
    print(f"[scan] 已扫描文件: {scanned}")
    if channels:
        detail = "  ".join(f"{k}={v}" for k, v in sorted(channels.items()))
        print(f"[scan] 通道分布: {detail}" + ("（binary=exe/dll 串提取；container=docx/xlsx/pptx/pdf）"
                                             if ("binary" in channels or "container" in channels) else ""))
    if skipped:
        print(f"[warn] 因体积超限跳过 {len(skipped)} 个文件（按类型分级阈值：文本 "
              f"{MAX_TEXT_BYTES // 1024 // 1024}MB / 容器 {MAX_CONTAINER_BYTES // 1024 // 1024}MB / "
              f"二进制 {MAX_BINARY_BYTES // 1024 // 1024}MB）：")
        for p, size in skipped[:10]:
            print(f"  - {p}（{size / 1024 / 1024:.1f}MB）")
    if mode == "walk" and root_reason.startswith("脚本上级"):
        print("[hint] 未探测到唯一的提交包结构（source_code/ + other|documents/），本次扫的是源码仓库根。\n"
              "       评审视角请显式指定：--root <提交包目录>；否则会连带扫描未提交的实验产物与历史审计报告。")
        if LAST_DETECT_AMBIGUOUS:
            print("       检测到多个候选提交包，未擅自选择：")
            for cand in LAST_DETECT_AMBIGUOUS:
                print(f"         - {cand}")
    if args.files is not None and not args.files:
        # 空清单必须显式可见：否则 pre-commit 里 $() 空展开会表现为「门禁啥也没干就过了」，
        # 与「门禁真的扫过且干净」在输出上难以区分。
        print("[warn] --files 未收到任何待扫文件，本次未做实际检查")

    if warnings:
        print(f"\n[WARN] 需人工复核 {len(warnings)} 处：")
        for p, cat, lineno, snippet, line in warnings[:30]:
            print(f"  {p}:{lineno}  [{cat}]  {snippet}")
            print(f"      └─ {line}")

    if failures:
        print(f"\n[FAIL] 命中 {len(failures)} 处 —— 禁止提交/上传：")
        for p, cat, lineno, snippet, line in failures[:60]:
            print(f"  {p}:{lineno}  [{cat}]  {snippet}")
            print(f"      └─ {line}")
        if len(failures) > 60:
            print(f"  … 另有 {len(failures) - 60} 处")
        print("\n修法：")
        print("  1) .bat  → 用 %LOCALAPPDATA%\\... 或 where python 回退，勿写死用户名")
        print("  2) .sh   → 用 export PY=\"${PY:-$(command -v python3 || command -v python)}\"")
        print("  3) 夹具  → 路径样例改用 C:/Users/SomeUser/... 之类的通用占位")
        return 1

    if args.strict and warnings:
        print("\n[FAIL] --strict 模式下告警项也判失败")
        return 1

    print("\n[ok ] 匿名合规门禁通过：无开发机用户名 / 绝对路径 / 邮箱 / 手机号 / UNC 命中")
    print("      （注：本门禁只覆盖身份与机器路径；密钥另由 secrets_scan.py 负责）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
