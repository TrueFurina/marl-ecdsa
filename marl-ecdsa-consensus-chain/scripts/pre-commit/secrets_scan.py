#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# anon-gate-exemption: rule-definition —— 本文件的豁免注释/正则是规则定义本体
"""密钥/凭据扫描器 — pre-commit 门禁

用法::

    python scripts/pre-commit/secrets_scan.py --staged          # pre-commit 第 1 步
    python scripts/pre-commit/secrets_scan.py --tracked --strict # CI 全量复扫
    python scripts/pre-commit/secrets_scan.py [--stdin0] [文件...]
    python scripts/pre-commit/secrets_scan.py --self-test

退出码：0=通过，1=命中密钥或读不出文件（读不懂 ≠ 没有密钥），2=环境/用法错误
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# 常见密钥模式（覆盖主流云厂商/数据库/消息队列）
SECRET_PATTERNS = [
    # AWS
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key ID'),
    # 40 位 base64（AWS Secret Access Key）。极宽的模式会误伤三类非密钥：
    #  ① 绝对路径（/Users/...、C:/Users/...）——紧邻 "/" 或 ":/" 盘符；
    #  ② 40 位裸 hex（区块哈希/种子/校验和）——纯 [0-9a-f]，AWS key 必含非 hex 的 base64 字符；
    #  ③ 字段名上下文（hash=/sha256= 等）——由 HASH_FIELD_RE 在 scan 层豁免。
    # 真实 AWS key 不以 "/" 开头、不含纯 hex、不紧贴路径分隔符，故不受影响。
    (r'(?<![:\w/+])(?!([0-9a-f]{40})(?![0-9a-zA-Z/+]))[0-9a-zA-Z/+]{40}(?![0-9a-zA-Z/+])', 'AWS Secret Access Key (base64)'),
    # GitHub
    (r'gh[pousr]_[A-Za-z0-9_]{36,}', 'GitHub Token'),
    # Generic API Key
    (r'(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)[\s:=]+[\'"]?([a-zA-Z0-9_\-]{20,})', 'Generic API Key'),
    # 数据库连接串
    (r'(?i)(postgres|mysql|redis|mongodb)://[^\s]+:\S+@[^\s/]+', 'Database Connection String'),
    # JWT
    (r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', 'JWT Token'),
    # Private Key
    (r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----', 'Private Key'),
    # Slack
    (r'xox[baprs]-[A-Za-z0-9-]{10,}', 'Slack Token'),
    # Generic
    (r'(?i)(secret|password|token)[\s:=]+[\'"]?([a-zA-Z0-9_\-]{20,})', 'Potential Secret'),
]

# 允许列表（测试/示例/占位符）
ALLOWLIST_PATTERNS = [
    r'your[_-]?api[_-]?key',
    r'your[_-]?secret',
    r'example[_-]?key',
    r'test[_-]?key',
    r'dummy[_-]?secret',
    r'placeholder',
    r'xxxxxxxx',
    r'your[_-]?password',
]


# 哈希/摘要类字段（区块哈希、指纹、校验和、交易/区块 ID 等）
# ——是公开摘要而非密钥，豁免扫描。
# 背景：区块哈希为 64 位 hex，会被 `[0-9a-zA-Z/+]{40}`（AWS Secret 模式）误报为密钥。
HASH_FIELD_RE = re.compile(
    r'(?i)["\']?\w*(hash|digest|sha\d*|fingerprint|checksum|merkle|tx_id|block_id)\w*["\']?\s*[:=]'
)

#: 字段名与值之间允许出现的字符（含 JSON 的 `": "`、Python 的 `= '`、YAML 的 `: `）。
_FIELD_LEAD_RE = re.compile(r'[\s:=]*["\']?$')

#: 明确不是文本的扩展名：按二进制计数，不假装扫过。
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip", ".gz",
    ".tar", ".7z", ".rar", ".woff", ".woff2", ".ttf", ".eot", ".so", ".dll", ".exe",
    ".pyc", ".pkl", ".npy", ".npz", ".mp4", ".mp3", ".wav", ".xlsx", ".db", ".sqlite",
}

#: 单文件扫描上限（字节）。超过则只扫前 N 字节并**记入汇总**，不再静默跳过。
#: 本仓最大的已跟踪文件约 0.5 MB，留 16 倍余量。
MAX_SCAN_BYTES = 8_000_000

STATUS_TEXT = "text"
STATUS_BINARY = "binary"
STATUS_UNREADABLE = "unreadable"
STATUS_IGNORED = "ignored"
STATUS_TRUNCATED = "truncated"

#: 路径**段**级跳过（唯一规则）。此前用子串匹配，`".git" in ".github/..."` 成立 ⇒
#: 运行本门禁的 `.github/workflows/ci.yml`、`.gitignore`、`scripts/build_*.py`、
#: `static/v9-distributed.*` 等 8 个已跟踪文件**从未被扫过**（2026-11-06 实测）。
SKIP_DIR_NAMES = {
    "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    "backup", "archive", "_scratch", ".pytest_cache", ".mypy_cache",
}

#: 这些顶层目录/Git 元数据目录按段跳过（`.git` 只跳目录本身，不影响 `.gitignore`）。
SKIP_EXACT = {".git"}


def compile_patterns():
    secret_res = [(re.compile(p, re.IGNORECASE), desc) for p, desc in SECRET_PATTERNS]
    allow_res = [re.compile(p, re.IGNORECASE) for p in ALLOWLIST_PATTERNS]
    return secret_res, allow_res


def is_skipped_path(path) -> bool:
    """按路径**段**判断是否跳过（唯一规则，不再有第二套子串过滤）。"""
    p = Path(path)
    if p.name in SKIP_EXACT or any(part in SKIP_EXACT for part in p.parts[:-1]):
        return True
    return any(part in SKIP_DIR_NAMES for part in p.parts)


def is_allowed(text: str, allow_res) -> bool:
    """占位符豁免：仅当「整个 token 就是占位符」时才豁免。

    此前用 ``r.search(text)``（子串匹配），会误伤真实密钥——例如 AWS 文档示例密钥
    ``wJalrXUtnFEMI/K7MDENG/bPxRfiCY`` + ``EXAMPLEKEY``（40 位 base64）因结尾含
    ``EXAMPLEKEY`` 被 ``example[_-]?key`` 误豁免（真实密钥漏检，门禁 fail-open）。
    改为 ``fullmatch``：只豁免 token 整体等于占位符（去掉首尾空白/引号）的情形，
    任何「包含占位符子串的真实密钥」都不再豁免。
    """
    token = text.strip().strip("'\"")
    return any(r.fullmatch(token) for r in allow_res)


def hash_field_exempts(line: str, start: int) -> bool:
    """判断 ``line[start:]`` 处命中的 token 是否**真的**是哈希字段的值。

    旧实现是 ``if HASH_FIELD_RE.search(line): continue`` —— **整行**豁免。
    于是同一行里只要出现任意 hash 字段名（``merkle_root`` / ``block_id`` /
    ``tx_id`` …），该行里的真密钥就一并被跳过：

        {"merkle_root": "aa11", "deploy_token": "ghp_..."}   → 旧版 ✅ 通过

    新实现要求「字段名 + 分隔符 + 可选引号」**紧邻**该 token，中间不得夹别的
    键值对。哈希值是公开摘要，密钥不是——两者的区别就在这个邻接关系上。
    """
    for m in HASH_FIELD_RE.finditer(line):
        if m.end() > start:
            continue
        if _FIELD_LEAD_RE.fullmatch(line[m.end():start]):
            return True
    return False


def decode_bytes(raw: bytes) -> Tuple[str, str, str]:
    """把原始字节解成文本，返回 ``(text, status, reason)``。

    旧实现 ``read_text(encoding='utf-8', errors='ignore')``：UTF-16（Windows
    记事本「Unicode」另存）整段被丢弃，中文与密钥一起消失，门禁报 ✅。
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", "replace"), STATUS_TEXT, ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace"), STATUS_TEXT, ""
    if b"\x00" in raw[:4096]:
        return "", STATUS_BINARY, "含 NUL 且无 BOM（按二进制跳过）"
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc), STATUS_TEXT, ""
        except UnicodeDecodeError:
            continue
    return "", STATUS_BINARY, "utf-8 与 gbk 均解不开（按二进制跳过）"


def scan_text(text: str, in_tests: bool = False) -> List[Tuple[int, str, str]]:
    """扫描一段文本，返回 ``[(行号, 类型, 摘要)]``。纯函数，便于自证/变异。"""
    secret_res, allow_res = compile_patterns()
    hits: List[Tuple[int, str, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # 跳过空行、注释
        if not stripped or stripped.startswith('#'):
            continue
        for pattern, desc in secret_res:
            for m in pattern.finditer(line):
                matched = m.group(0)
                if is_allowed(matched, allow_res):
                    continue
                # 哈希字段豁免：只豁免「这个 token 就是该字段的值」，不是整行
                if hash_field_exempts(line, m.start()):
                    continue
                # tests/ 下的私钥块 = 单元测试固定向量，不算泄漏
                if in_tests and desc == 'Private Key':
                    continue
                snippet = f'{matched[:50]}...' if len(matched) > 50 else matched
                hits.append((i, desc, snippet))
    return hits


def scan_document(filepath, ignored: Optional[set] = None) -> Dict[str, object]:
    """扫描单个文件，返回状态字典：``status`` 是**事实**，不是空列表。

    ``unreadable`` / ``truncated`` 都是可报告的缺口：前者意味着「这次提交里
    有个路径没被检查」，后者意味着「只检查了前 8 MB」。两者都不再折叠成
    「没有命中 ⇒ 通过」。
    """
    p = Path(filepath)
    out: Dict[str, object] = {
        "path": str(filepath), "status": STATUS_UNREADABLE,
        "reason": "", "hits": [], "bytes": 0,
    }
    if ignored and p.as_posix() in ignored:
        out["status"] = STATUS_IGNORED
        out["reason"] = "被 .gitignore 覆盖（不入库、不交付）"
        return out
    if is_skipped_path(p):
        out["status"] = STATUS_IGNORED
        out["reason"] = "路径段命中跳过规则"
        return out
    if p.is_dir():
        out["status"] = STATUS_UNREADABLE
        out["reason"] = "是目录不是文件（传参错误）"
        return out
    if not p.exists():
        out["status"] = STATUS_UNREADABLE
        out["reason"] = "路径不存在（文件名可能在 shell 展开时被空格切开）"
        return out
    if p.suffix.lower() in BINARY_EXT:
        out["status"] = STATUS_BINARY
        out["reason"] = f"扩展名 {p.suffix.lower()} 属二进制"
        return out
    try:
        raw = p.read_bytes()
    except OSError as exc:
        out["status"] = STATUS_UNREADABLE
        out["reason"] = f"读不出（{exc.__class__.__name__}: {exc}）"
        return out

    out["bytes"] = len(raw)
    truncated = len(raw) > MAX_SCAN_BYTES
    if truncated:
        raw = raw[:MAX_SCAN_BYTES]
    text, status, reason = decode_bytes(raw)
    if status != STATUS_TEXT:
        out["status"] = status
        out["reason"] = reason
        return out

    in_tests = "tests" in p.parts
    hits = scan_text(text, in_tests=in_tests)
    out["hits"] = hits
    out["status"] = STATUS_TRUNCATED if truncated else STATUS_TEXT
    if truncated:
        out["reason"] = f"超过 {MAX_SCAN_BYTES} 字节，只扫了前 {MAX_SCAN_BYTES} 字节"
    return out


def scan_file(filepath) -> List[Tuple[int, str, str]]:
    """兼容旧调用：只返回命中列表（读不出为空，需状态请用 ``scan_document``）。"""
    return list(scan_document(filepath)["hits"])  # type: ignore[arg-type]


def split_z(raw: bytes) -> List[str]:
    """解析 ``git ... -z`` 的 NUL 分隔输出。文件名可含空格/制表符/换行。"""
    text = raw.decode("utf-8", "surrogateescape")
    return [item for item in text.split("\0") if item]


def git_files(args: List[str], cwd: Optional[str] = None) -> Tuple[List[str], str]:
    """跑 git 并返回 ``(路径列表, 错误说明)``。错误说明非空 ⇒ 调用方必须判失败。

    pre-commit / CI 此前用 ``secrets_scan.py $(git … --name-only)`` 传参：shell 会按
    空格切词，``报告 记录.md`` 变成两个不存在的路径，两个都被静默跳过 —— 含真密钥
    的文件因此「检查过了」。改由本脚本自己调 git（``-z``），路径不经过 shell。
    """
    cmd = ["git", "-c", "core.quotePath=false"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, cwd=cwd)
    except OSError as exc:
        return [], f"无法执行 git：{exc}"
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.decode("utf-8", "replace").splitlines()
                 if ln.strip()]
        detail = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))),
                      lines[0] if lines else "无错误输出")
        return [], f"git 退出码 {proc.returncode}：{detail}"
    return split_z(proc.stdout), ""


def staged_files(cwd: Optional[str] = None) -> Tuple[List[str], str]:
    """本次暂存的新增/复制/修改文件（相对仓库根）。"""
    return git_files(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACM"], cwd=cwd)


def tracked_files(cwd: Optional[str] = None) -> Tuple[List[str], str]:
    return git_files(["ls-files", "-z"], cwd=cwd)


def gitignored_set(root='.') -> set:
    """返回被 .gitignore 覆盖的文件集合（这些文件不入库、不交付，无需扫描）。

    典型例子：``keys/``（运行时生成的真实私钥）、``training_results*.json``。
    它们留在工作区是正常的，但既不会进 git 也不会进交付包。
    """
    try:
        import subprocess
        out = subprocess.check_output(
            ['git', '-c', 'core.quotePath=false', 'ls-files', '--others', '--ignored',
             '--exclude-standard', '-z'],
            cwd=root, stderr=subprocess.DEVNULL,
        )
        return set(split_z(out))
    except Exception:
        return set()


def decide_exit(hits: Sequence, problems: Sequence, scanned: int,
                strict: bool) -> Tuple[int, str]:
    """唯一的判定入口（纯函数，便于自证与变异测试）。"""
    if hits:
        return 1, f"命中 {len(hits)} 处疑似密钥"
    if problems:
        return 1, (f"{len(problems)} 个文件没被检查（读不出 / 是目录 / 不存在）"
                   " —— 没检查不等于没有密钥")
    if scanned == 0:
        if strict:
            return 1, "零个文件被扫描 —— 什么都没扫不等于干净（--strict）"
        return 0, "零个文件被扫描（未启用 --strict，不判失败）"
    return 0, ""


def print_summary(counts: Dict[str, int]) -> None:
    print(f"扫描 {counts['scanned']} 个文件：文本 {counts[STATUS_TEXT]} / "
          f"二进制 {counts[STATUS_BINARY]} / 截断 {counts[STATUS_TRUNCATED]} / "
          f"读不出 {counts[STATUS_UNREADABLE]} / 按规则忽略 {counts[STATUS_IGNORED]}")


# --------------------------------------------------------------------------- #
# 自证：用临时目录现造样本，证明五类失明都被堵上
# --------------------------------------------------------------------------- #
def run_self_test(verbose: bool = True) -> int:
    import tempfile

    failures: List[str] = []
    passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<26} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<26} → FAIL {detail}")

    # 合成密钥一律运行时拼接：本文件也会被自己扫描，字面量会自锁。
    gh = "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJKL"
    aws = "AKIA" + "IOSFODNN7" + "EXAMPLE"

    def hits_of(text: str) -> List[Tuple[int, str, str]]:
        return scan_text(text)

    # ① 真密钥必检出
    check("github_token_detected", bool(hits_of(f"TOKEN = '{gh}'")))
    check("aws_key_detected", bool(hits_of(f"ID = '{aws}'")))

    # ② 哈希字段豁免必须**只豁免自己那个值**
    check("hash_value_exempt", not hits_of("block_hash = 'd7042aeb6929f6694bc89b1c35d9456ef5417f79'"))
    check("json_hash_value_exempt",
          not hits_of('{"prev_block_hash": "d7042aeb6929f6694bc89b1c35d9456ef5417f79"}'))
    same_line = '{"merkle_root": "aa11", "deploy_token": "%s"}' % gh
    check("hash_field_does_not_shield_line", bool(hits_of(same_line)), same_line[:40])
    js_line = 'const cfg = {block_hash: "aa", apiKey: "%s"};' % gh
    check("js_same_line_detected", bool(hits_of(js_line)), js_line[:40])

    # ③ 编码：UTF-16 / GBK 都要能读出中文与密钥
    gh_line = f"TOKEN = '{gh}'\n"
    for enc, name in (("utf-16", "utf16_bom"), ("utf-8", "utf8"), ("gbk", "gbk")):
        raw = gh_line.encode(enc)
        text, status, _ = decode_bytes(raw)
        check(f"{name}_decoded", status == STATUS_TEXT and bool(scan_text(text)), status)

    with tempfile.TemporaryDirectory(prefix="secscan_selftest_") as tmp:
        root = Path(tmp)

        spaced = root / "报告 记录.md"
        spaced.write_bytes(gh_line.encode("utf-8"))
        names = split_z((str(spaced) + "\0" + str(root / "b.md") + "\0").encode("utf-8"))
        check("z_split_keeps_space",
              len(names) == 2 and names[0].endswith("报告 记录.md"), str(names))
        doc = scan_document(spaced)
        check("spaced_name_scanned",
              doc["status"] == STATUS_TEXT and bool(doc["hits"]), str(doc["status"]))

        u16 = root / "u16.txt"
        u16.write_bytes(gh_line.encode("utf-16"))
        check("utf16_file_hits", bool(scan_document(u16)["hits"]))

        try:
            newline_name = root / "a\nb.md"
            newline_name.write_bytes(gh_line.encode("utf-8"))
            got = split_z((str(newline_name) + "\0").encode("utf-8"))
            check("z_split_keeps_newline",
                  len(got) == 1 and got[0] == str(newline_name), str(got))
        except OSError:
            check("z_split_keeps_newline", True, "本平台不允许换行文件名，跳过")

        png = root / "fig.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        check("binary_counted", scan_document(png)["status"] == STATUS_BINARY)

        check("dir_is_unreadable", scan_document(root)["status"] == STATUS_UNREADABLE)
        check("missing_is_unreadable",
              scan_document(root / "not_there.md")["status"] == STATUS_UNREADABLE)

        big = root / "big.md"
        big.write_bytes(b"#" + b"x" * (MAX_SCAN_BYTES + 16) + b"\n" + gh_line.encode())
        big_doc = scan_document(big)
        check("oversize_counted", big_doc["status"] == STATUS_TRUNCATED, str(big_doc["status"]))

    # ④ 跳过规则只看路径段
    check("github_not_skipped", not is_skipped_path(Path(".github/workflows/ci.yml")))
    check("gitignore_not_skipped", not is_skipped_path(Path(".gitignore")))
    check("build_script_not_skipped",
          not is_skipped_path(Path("scripts/build_dashboard_data.py")))
    check("distributed_not_skipped", not is_skipped_path(Path("static/v9-distributed.js")))
    check("build_dir_skipped", is_skipped_path(Path("build/out.py")))
    check("git_dir_skipped", is_skipped_path(Path(".git/hooks/pre-commit")))

    # ④b git 清单：带空格的文件名必须原样到达（-z），git 失败必须报错
    with tempfile.TemporaryDirectory(prefix="secscan_git_") as tmp:
        root = Path(tmp)
        ok_env = True
        for c in (["git", "init", "-q"], ["git", "config", "user.email", "selftest@example.invalid"],
                  ["git", "config", "user.name", "selftest"]):
            if subprocess.run(c, cwd=str(root), capture_output=True).returncode != 0:
                ok_env = False
                break
        if ok_env:
            (root / "报告 记录.md").write_bytes(gh_line.encode("utf-8"))
            subprocess.run(["git", "add", "-A"], cwd=str(root), capture_output=True)
            got, err = staged_files(cwd=str(root))
            check("staged_sees_spaced_name",
                  not err and got == ["报告 记录.md"], f"{got} {err}")
        else:
            check("staged_sees_spaced_name", True, "本机缺 git，跳过")

        # 非仓库目录：git 必须报错，而不是返回空清单让上层判「没有密钥」
        with tempfile.TemporaryDirectory(prefix="secscan_nogit_") as nogit:
            _, err2 = staged_files(cwd=nogit)
            check("git_error_reported", bool(err2), (err2 or "无错误")[:40])

    # ⑤ 判定入口
    check("hit_blocks", decide_exit([(1, "x", "y")], [], 1, False)[0] == 1)
    check("unreadable_blocks", decide_exit([], [{"path": "x"}], 1, False)[0] == 1)
    check("strict_zero_fails", decide_exit([], [], 0, True)[0] == 1)
    check("zero_nonstrict_passes", decide_exit([], [], 0, False)[0] == 0)
    check("clean_passes", decide_exit([], [], 3, True)[0] == 0)

    total = passed + len(failures)
    if failures:
        for item in failures:
            print(f"❌ [自证失败] {item}")
        print(f"❌ 自证失败 {len(failures)}/{total} 项")
        return 1
    print(f"✅ 自证通过 {passed}/{total}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="密钥/凭据扫描器（fail-closed）")
    parser.add_argument("--staged", action="store_true",
                        help="扫描暂存区变更文件（pre-commit 快路；内部调 git -z，路径不过 shell）")
    parser.add_argument("--tracked", action="store_true",
                        help="扫描全部已跟踪文件（CI 全量复扫）")
    parser.add_argument("--stdin0", action="store_true",
                        help="从 stdin 读取 NUL 分隔的文件名（配合 git ... -z）")
    parser.add_argument("--strict", action="store_true",
                        help="零个文件被扫描时判失败（默认只告警）")
    parser.add_argument("--self-test", action="store_true", help="内置夹具自证")
    parser.add_argument("files", nargs="*", help="指定文件列表")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    files: List[str] = list(args.files)
    error = ""
    if args.staged:
        got, error = staged_files()
        files.extend(got)
    elif args.tracked:
        got, error = tracked_files()
        files.extend(got)
    if args.stdin0:
        files.extend(split_z(sys.stdin.buffer.read()))
    if error:
        # 读不到文件清单 ≠ 没有密钥。退出码 2（环境/用法错误）与 1（命中）区分开。
        print(f"❌ 密钥扫描：环境错误：{error} —— 一个文件都没检查，不等于没有密钥")
        return 2

    if not files:
        # 本地空暂存区是正常状态（pre-commit 第一步在无暂存时展开为空），
        # 但 CI 里「一个文件都没有」意味着命令没拿到输入 —— 正是 --strict 的用途。
        code, msg = decide_exit([], [], 0, args.strict)
        if code:
            print(f"❌ {msg}")
            return code
        print('✅ 密钥扫描通过（无暂存文件）')
        return 0

    ignored = gitignored_set()
    counts = {STATUS_TEXT: 0, STATUS_BINARY: 0, STATUS_UNREADABLE: 0,
              STATUS_IGNORED: 0, STATUS_TRUNCATED: 0, "scanned": 0}
    all_hits = []
    problems: List[Dict[str, object]] = []
    seen = set()

    for f in files:
        key = Path(f).as_posix()
        if key in seen:
            continue
        seen.add(key)
        doc = scan_document(f, ignored=ignored)
        status = str(doc["status"])
        counts[status] = counts.get(status, 0) + 1
        if status in (STATUS_BINARY, STATUS_IGNORED):
            continue
        counts["scanned"] += 1
        if status == STATUS_UNREADABLE:
            problems.append({"path": f, "reason": doc["reason"]})
            print(f"⚠️ {f}: 没被检查 —— {doc['reason']}")
            continue
        if status == STATUS_TRUNCATED:
            print(f"⚠️ {f}: {doc['reason']}")
        for line_num, desc, match in doc["hits"]:  # type: ignore[union-attr]
            all_hits.append((f, line_num, desc, match))
            print(f'❌ {f}:{line_num}: 疑似密钥[{desc}] - {match}')

    code, msg = decide_exit(all_hits, problems, counts["scanned"], args.strict)
    print_summary(counts)
    if code:
        # 命中细节上面已经逐条打印过；这里只补一句判定理由
        print(f"❌ {msg}")
        return code
    print('✅ 密钥扫描通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
