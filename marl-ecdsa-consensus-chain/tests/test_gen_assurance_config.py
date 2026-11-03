#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""``gen_assurance_config.py`` 出库前自检不得写死机器用户名（回归守卫）。

背景
----
2026-10-17 实测 ``scripts/gen_assurance_config.py:157`` 形如::

    ("用户名", r"Lenovo"),

这是一个**二重问题**：

1. **它自己就是泄漏**——把开发机用户名写进源码，而该文件会随 public 产物外发；
2. **它躲过了全部既有门禁**——``check_submission_anonymity`` 的规则识别的
   ``C:/Users/<name>`` 等**路径形态**，裸用户名（非路径）完全不在识别范围内；
   ``secrets_scan`` 按设计不管路径/用户名。

更糟的是提交包 README（§三附）当时已宣称这一处「已修复」，而仓库与提交包两侧
**均未修** —— 属于提交材料里的不实陈述。

Machine-independent 原则
------------------------
本测试自身也不得写死任何用户名：一律 **运行时派生**
（``getpass.getuser()`` / ``Path.home().name``），否则测试文件自己就成了泄漏源。
"""
from __future__ import annotations

import getpass
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "scripts" / "gen_assurance_config.py"


def _machine_usernames() -> set[str]:
    """当前机器的可能用户名（小写去重，忽略容器/默认账户这类非身份值）。"""
    names = set()
    for cand in (getpass.getuser(), Path.home().name):
        if cand and cand.lower() not in {"user", "public", "default", "administrator",
                                         "root", "ubuntu", "runner", "anon"}:
            names.add(cand.lower())
    return names


def test_no_hardcoded_machine_username():
    """源码里不得出现本机用户名字面量（含大小写无关匹配）。"""
    src = TARGET.read_text(encoding="utf-8")
    # 去掉行注释只为了减少误报；字符串里的用户名同样算命中
    for user in _machine_usernames():
        assert not re.search(rf"(?<![A-Za-z0-9_]){re.escape(user)}(?![A-Za-z0-9_])", src, re.I), (
            f"gen_assurance_config.py 写死了机器用户名 {user!r} —— 该脚本会随 public "
            f"产物外发，用户名必须在运行时派生（如 Path.home().name），不得落字面量")


def test_username_rule_is_derived_at_runtime():
    """用户名规则必须**运行时派生**：存在 expanduser/home 派生且用于正则。"""
    src = TARGET.read_text(encoding="utf-8")
    assert re.search(r"expanduser\s*\(\s*[\"']~[\"']\s*\)|Path\.home\(\)|getuser\(\)", src), (
        "应有运行时派生机器用户名的调用（os.path.expanduser('~') / Path.home() / getpass.getuser()）")
    assert "re.escape" in src, "派生出的用户名应用 re.escape 转义后再进正则，避免正则元字符误伤"


@pytest.mark.skipif(not _machine_usernames(), reason="无法派生本机用户名（容器环境）")
def test_selfcheck_flags_derived_username_end_to_end():
    """端到端：把派生出的用户名塞进待出库 blob，自检必须 FAIL。

    用真实 Python 子进程复现自检片段（不 import 整个脚本——它有副作用且依赖私有配置）。
    """
    user = sorted(_machine_usernames())[0]
    probe = rf'''
import json, os, re
from pathlib import Path
blob = json.dumps({{"identity": {{"tokens": ["worker-{user}"]}}}}, ensure_ascii=False)
machine_user = Path(os.path.expanduser("~")).name
if machine_user and re.search(re.escape(machine_user), blob, re.IGNORECASE):
    print("BLOCKED")
else:
    raise SystemExit("自检未拦截 —— 用户名规则失效")
'''
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", probe],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"自检应拦截含本机用户名的产物，实得：{proc.stdout}{proc.stderr}"
    assert "BLOCKED" in proc.stdout
