#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密钥/凭据扫描器 — pre-commit 门禁
用法：python scripts/pre-commit/secrets_scan.py [文件列表...]
退出码：0=通过，1=命中密钥（fail-closed）
"""
import re
import sys
from pathlib import Path

# 常见密钥模式（覆盖主流云厂商/数据库/消息队列）
SECRET_PATTERNS = [
    # AWS
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key ID'),
    # 40 位 base64（AWS Secret Access Key）。极宽的模式会误伤三类非密钥：
    #  ① 绝对路径（/Users/...、C:/Users/...）——紧邻 "/" 或 ":/" 盘符；
    #  ② 40 位裸 hex（区块哈希/种子/校验和）——纯 [0-9a-f]，AWS key 必含非 hex 的 base64 字符；
    #  ③ 字段名上下文（hash=/sha256= 等）——由 HASH_FIELD_RE 在 scan_file 层豁免。
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


def compile_patterns():
    secret_res = [(re.compile(p, re.IGNORECASE), desc) for p, desc in SECRET_PATTERNS]
    allow_res = [re.compile(p, re.IGNORECASE) for p in ALLOWLIST_PATTERNS]
    return secret_res, allow_res


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


def scan_file(filepath: Path) -> list:
    """扫描单文件，返回命中列表 [(行号, 类型, 匹配内容)]"""
    hits = []
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return hits

    secret_res, allow_res = compile_patterns()

    # tests/ 下的私钥块是单元测试固定向量（ECDSA 签名/验签必需），非真实凭据
    in_tests = 'tests' in filepath.parts

    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        # 跳过空行、注释
        if not stripped or stripped.startswith('#'):
            continue

        # 哈希/摘要字段豁免：这类值是公开摘要，不是密钥
        if HASH_FIELD_RE.search(line):
            continue

        for pattern, desc in secret_res:
            matches = pattern.finditer(line)
            for m in matches:
                matched = m.group(0)
                if is_allowed(matched, allow_res):
                    continue
                # tests/ 下的私钥块 = 单元测试固定向量，不算泄漏
                if in_tests and desc == 'Private Key':
                    continue
                snippet = f'{matched[:50]}...' if len(matched) > 50 else matched
                hits.append((i, desc, snippet))
    return hits


def gitignored_set(root='.') -> set:
    """返回被 .gitignore 覆盖的文件集合（这些文件不入库、不交付，无需扫描）。

    典型例子：``keys/``（运行时生成的真实私钥）、``training_results*.json``。
    它们留在工作区是正常的，但既不会进 git 也不会进交付包。
    """
    try:
        import subprocess
        out = subprocess.check_output(
            ['git', 'ls-files', '--others', '--ignored', '--exclude-standard'],
            cwd=root, stderr=subprocess.DEVNULL,
        ).decode('utf-8', 'ignore')
        return set(out.splitlines())
    except Exception:
        return set()


def main():
    import sys
    # 空参数 = 无暂存文件（pre-commit 第 1 步 `$(git diff --cached --name-only)` 在空暂存时
    # 展开为空）。此时**必须直接通过**，而不是退化成全仓 rglob 扫描——否则会扫到未跟踪的
    # 历史脚本/运行产物，产生误报（如 Windows 绝对路径被误判为密钥）且拖慢提交。
    if len(sys.argv) <= 1:
        print('✅ 密钥扫描通过（无暂存文件）')
        return 0
    files = sys.argv[1:]

    # 被 .gitignore 覆盖的文件不入库也不交付，扫描它们只会产生噪音
    ignored = gitignored_set()

    all_hits = []
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        # 跳过二进制/大文件
        if p.stat().st_size > 1_000_000:
            continue
        # 跳过已知忽略
        if any(ign in str(p) for ign in ['.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build',
                                        'backup', 'archive', '_scratch']):
            continue
        # 跳过被 .gitignore 覆盖的运行产物
        if p.as_posix() in ignored:
            continue

        hits = scan_file(p)
        if hits:
            for line_num, desc, match in hits:
                print(f'❌ {p}:{line_num}: 疑似密钥[{desc}] - {match}')
            return 1

    print('✅ 密钥扫描通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())