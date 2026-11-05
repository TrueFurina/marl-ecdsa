#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``secrets_scan.py`` 的「扫了等于没扫」回归测试（2026-11-06）。

背景
----
这道门禁是 pre-commit 第 1 步、也是 CI 的 `Pre-commit gates — repo-wide` 第一步。
它此前有五类情况会把「含真密钥的文件」判成 ✅ 通过，全部在 2026-11-06 实测复现：

1. **哈希字段整行豁免**：``if HASH_FIELD_RE.search(line): continue`` —— 同一行里
   只要出现 ``merkle_root`` / ``block_id`` / ``tx_id`` 任一字段名，该行的真 token
   一并跳过。单行 JSON 与前端配置行因此完全失明。
2. **UTF-16 读出空白**：``read_text(errors="ignore")`` 把 UTF-16 文档整段丢弃
   （Windows 记事本「Unicode」另存即此编码）。
3. **路径子串跳过**：``'.git' in '.github/workflows/ci.yml'`` 成立 ⇒ 运行本门禁
   的那个 CI 文件、``.gitignore``、``scripts/build_*.py``、``static/v9-distributed.*``
   等 8 个已跟踪文件从未被扫过。
4. **静默跳过**：路径不存在 / 是目录 / 超过 1 MB —— 三者都 ``continue``，一个字不打印。
5. **零文件通过**：CI 里 ``$(git ls-files)`` 若因 cwd 跑偏而为空，打印「无暂存文件」通过。

合成密钥一律**运行时拼接**：本文件也在扫描范围内，字面量会自锁（门禁拦自己）。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = REPO_ROOT / "scripts" / "pre-commit" / "secrets_scan.py"
PY = sys.executable

sys.path.insert(0, str(REPO_ROOT / "scripts" / "pre-commit"))
import secrets_scan as ss  # noqa: E402


def _gh_token() -> str:
    return "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "ABCDEFGHIJKL"


def _run(*files: str) -> tuple[int, str]:
    proc = subprocess.run([PY, str(SCAN), *files], cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace") + \
          (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out


def _tmp_file(tmp_path: Path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ── 1. 哈希字段豁免只能豁免「自己那个值」 ────────────────────────────────

def test_hash_field_on_same_line_does_not_shield_token(tmp_path):
    """单行 JSON：``merkle_root`` 在前、真 token 在后 —— 旧版整行豁免，判通过。"""
    line = '{"merkle_root": "aa11", "deploy_token": "%s"}\n' % _gh_token()
    code, out = _run(_tmp_file(tmp_path, "one_line.json", line.encode("utf-8")))
    assert code == 1, f"同一行含哈希字段不得豁免真密钥，实得 {code}\n{out}"
    assert "GitHub Token" in out, out


def test_hash_field_in_js_line_does_not_shield_token(tmp_path):
    line = 'const cfg = {block_hash: "aa", apiKey: "%s"};\n' % _gh_token()
    code, out = _run(_tmp_file(tmp_path, "cfg.js", line.encode("utf-8")))
    assert code == 1, f"前端配置行同样不得整行豁免，实得 {code}\n{out}"


def test_hash_value_itself_still_exempt(tmp_path):
    """豁免的本意仍然有效：哈希值就是紧跟在 hash 字段后的那个串。"""
    line = "block_hash = 'd7042aeb6929f6694bc89b1c35d9456ef5417f79'\n"
    code, out = _run(_tmp_file(tmp_path, "h.py", line.encode("utf-8")))
    assert code == 0, f"纯 hex 哈希值不应误报，实得 {code}\n{out}"


def test_json_hash_value_exempt():
    line = '{"prev_block_hash": "d7042aeb6929f6694bc89b1c35d9456ef5417f79"}'
    assert ss.scan_text(line) == [], line


# ── 2. 编码：UTF-16 / UTF-8 BOM / GBK ───────────────────────────────────

@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "gbk"])
def test_encoded_documents_are_scanned(tmp_path, encoding):
    line = "TOKEN = '%s'\n" % _gh_token()
    name = {"utf-16": "u16.txt", "utf-8-sig": "bom.txt", "gbk": "gbk.txt"}[encoding]
    code, out = _run(_tmp_file(tmp_path, name, line.encode(encoding)))
    assert code == 1, f"{encoding} 文档里的密钥必须检出，实得 {code}\n{out}"


def test_decode_bytes_reports_binary_without_bom():
    text, status, reason = ss.decode_bytes(b"\x00\x01\x02binary")
    assert status == ss.STATUS_BINARY, (text, status, reason)


# ── 3. 跳过规则只看路径段 ────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    ".github/workflows/ci.yml",
    ".gitignore",
    "scripts/build_dashboard_data.py",
    "static/v9-distributed.js",
    "visualization/distributed_consensus.py",
])
def test_dot_git_prefix_does_not_skip(path):
    assert not ss.is_skipped_path(Path(path)), f"{path} 曾被 '.git'/'build'/'dist' 子串跳过"


@pytest.mark.parametrize("path", ["build/out.py", "dist/app.js", ".git/hooks/pre-commit"])
def test_real_build_dirs_still_skipped(path):
    assert ss.is_skipped_path(Path(path))


def test_main_has_no_second_substring_filter():
    """回归锁：`main()` 里不得再出现 `any(ign in str(p) for ign in [...])` 这种第二套规则。"""
    src = (REPO_ROOT / "scripts" / "pre-commit" / "secrets_scan.py").read_text(encoding="utf-8")
    body = src.split("def main(", 1)[1]
    assert "ign in str" not in body, "子串过滤回潮：跳过规则必须只有 is_skipped_path 一处"


def test_source_does_not_use_errors_ignore():
    """回归锁：读文件不得再传 ``errors=`` ——「读不懂就当没有」正是本次要堵的失明。

    用 AST 而不是字符串搜索：文档字符串里**提到**旧写法是正常的，要拦的是代码里**用**它。
    """
    import ast

    src = (REPO_ROOT / "scripts" / "pre-commit" / "secrets_scan.py").read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in {"read_text", "open", "read_bytes"}:
            if any(kw.arg == "errors" for kw in node.keywords):
                offenders.append((name, node.lineno))
    assert not offenders, f"读文件不得传 errors=：{offenders}"


# ── 4. 静默跳过：不存在 / 目录 / 超大 ────────────────────────────────────

def test_missing_path_is_reported_not_ignored():
    code, out = _run("no_such_file_xyz.py")
    assert code == 1, f"路径不存在必须报「没被检查」，实得 {code}\n{out}"
    assert "没被检查" in out, out


def test_directory_argument_is_reported(tmp_path):
    code, out = _run(str(tmp_path))
    assert code == 1, f"目录当参数必须报错，实得 {code}\n{out}"
    assert "是目录不是文件" in out, out


def test_oversize_file_is_scanned(tmp_path):
    """1.1 MB 的文件此前被静默 `continue`；现在必须扫到里面的密钥。"""
    body = ("#" + "x" * 1_100_000 + "\nTOKEN = '%s'\n" % _gh_token()).encode("utf-8")
    code, out = _run(_tmp_file(tmp_path, "big.py", body))
    assert code == 1, f"超过 1 MB 的文件此前被静默跳过，实得 {code}\n{out}"


def test_truncation_is_a_reported_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "MAX_SCAN_BYTES", 64)
    p = tmp_path / "huge.md"
    p.write_bytes(b"#" * 256 + b"\n")
    doc = ss.scan_document(p)
    assert doc["status"] == ss.STATUS_TRUNCATED, doc["status"]
    assert "只扫了前" in str(doc["reason"]), doc["reason"]


# ── 5. 文件名/零文件：--stdin0 与 --strict ──────────────────────────────

def test_stdin0_keeps_spaces_in_name(tmp_path):
    line = "TOKEN = '%s'\n" % _gh_token()
    target = tmp_path / "报告 记录.md"
    target.write_bytes(line.encode("utf-8"))
    proc = subprocess.run([PY, str(SCAN), "--stdin0"], cwd=REPO_ROOT,
                          capture_output=True, input=(str(target) + "\0").encode("utf-8"))
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 1, f"带空格的文件名必须被扫到，实得 {proc.returncode}\n{out}"


def test_split_z_keeps_newline_in_name():
    raw = "a\nb.md\0c.md\0".encode("utf-8")
    assert ss.split_z(raw) == ["a\nb.md", "c.md"]


def test_strict_fails_on_zero_files():
    proc = subprocess.run([PY, str(SCAN), "--stdin0", "--strict"], cwd=REPO_ROOT,
                          capture_output=True, input=b"")
    assert proc.returncode == 1, proc.stdout
    assert "零个文件" in (proc.stdout or b"").decode("utf-8", "replace")


def test_git_error_is_not_an_empty_file_list(tmp_path):
    """git 不可用时必须判环境错误（2），不能退化成「0 个文件 ⇒ 通过」。"""
    proc = subprocess.run([PY, str(SCAN), "--staged"], cwd=str(tmp_path), capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 2, f"非仓库目录下 --staged 必须报环境错误，实得 {proc.returncode}\n{out}"
    assert "环境错误" in out, out


def test_non_strict_zero_files_passes():
    proc = subprocess.run([PY, str(SCAN), "--stdin0"], cwd=REPO_ROOT,
                          capture_output=True, input=b"")
    assert proc.returncode == 0
    assert "无暂存文件" in (proc.stdout or b"").decode("utf-8", "replace")


# ── 6. 判定入口与自证 ────────────────────────────────────────────────────

def test_decide_exit_unreadable_blocks():
    assert ss.decide_exit([], [{"path": "x"}], 1, False)[0] == 1


def test_decide_exit_clean_passes():
    assert ss.decide_exit([], [], 3, True)[0] == 0


def test_self_test_passes():
    proc = subprocess.run([PY, str(SCAN), "--self-test"], cwd=REPO_ROOT, capture_output=True)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert "自证通过" in out, out
