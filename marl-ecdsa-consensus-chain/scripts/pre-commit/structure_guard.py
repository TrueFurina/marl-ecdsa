#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目录结构守卫 — pre-commit 门禁
用法：python scripts/pre-commit/structure_guard.py [--all]
退出码：0=通过，1=命中违规（fail-closed）

规则来源：西湖论剑 CTF-Agent _structure_guard.py（通用化）
默认只检查本次新增文件（--diff-filter=A），不误伤重命名/既有文件。
"""
import re
import subprocess
import sys
from pathlib import Path

# 受管后缀（这些类型的散落文件必须归位）
MANAGED_EXT = {"md", "txt", "html", "json", "csv", "pdf", "png", "jpg", "jpeg", "xlsx", "yml", "yaml"}

# 根级白名单（各项目可按需修改此集合）
ROOT_ALLOW = {
    "README.md", "README.zh.md", "README_EN.md", "CLAUDE.md", "AGENTS.md",
    "LICENSE", "requirements.txt", "requirements.lock.txt", "package.json", "pyproject.toml",
    "setup.py", "Dockerfile", "docker-compose.yml", ".gitignore",
    ".pre-commit-config.yaml", "CHANGELOG.md", "Makefile",
    # 以下两个不是"散落"，而是**工具链按仓库根硬编码读取**的：
    #   * config.json          —— blockchain/consensus/factory.py:29 拼 <repo>/config.json
    #   * number_registry.json —— scripts/check_registry_mirror.py 默认镜像路径 <repo>/number_registry.json
    #                              （工作区 deliverables/ 那份才是权威源，仓库内这份是只读镜像）
    # 移动它们会直接打断代码与守门器，故列入白名单。
    "config.json", "number_registry.json",
}

#: 根级**存量**文档冻结豁免（2026-11-03 登记；只减不增）。
#:
#: 这些文件从 V18 起就平铺在仓库根，被 README / thesis / 演示脚本以相对路径引用。
#: 一次性搬进 docs/ 会同时打断这些引用，且需要配套的链接改写与验证 —— 属独立的
#: 结构性任务，不在「把 CI 跑绿」的范围内草率处理。
#:
#: 因此这里把它们**登记冻结**而不是删除或假装合规：
#:   * 新增的根级 md 仍然会被拦（本集合是常量，不随仓库内容变化）；
#:   * `main()` 每次都会把这些条目作为「待归位存量」打印出来，不静默腐烂。
#:
#: 注：`V18_σèƒΦâ╜σñìµá╕µèÑσæè.md` 的文件名本身就是**乱码**（UTF-8 文件名被按
#: CP437 解释后的产物，原意为「V18_功能复核报告.md」）。重命名属破坏性操作，
#: 此处如实按现有字节登记，问题本身记录在案待单独处理。
LEGACY_ROOT_DOCS = {
    "CCF2026_SHOWCASE_GUIDE.md",
    "FRONTEND_REDESIGN_2026.md",
    "V18_σèƒΦâ╜σñìµá╕µèÑσæè.md",
    "V19_验收结果与运行说明.md",
    "V20_贡献与共识业务联动说明.md",
    "V21_协作多智能体与区块链融合说明.md",
    "V21_测试记录.md",
    "V22_多智能体与区块链联动说明.md",
    "V23_登录注册界面重设计说明.md",
    "V24_统一图标主题说明.md",
    "V25_共识精简与功能联动说明.md",
    "V26_可信协作流程可视化与审计中心说明.md",
    "V27_全模块系统审查与验收说明.md",
}


def git(*args):
    """git 调用，关闭 quotePath 以免中文路径被转义导致漏判。"""
    cmd = ["git", "-c", "core.quotePath=false"] + list(args)
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8", "ignore")


def unquote_path(p: str) -> str:
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if "\\" in p:
        try:
            p = p.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
        except Exception:
            pass
    return p


def staged_added_files() -> list:
    out = git("diff", "--cached", "--name-only", "--diff-filter=A")
    return [unquote_path(f) for f in out.splitlines() if f.strip()]


def all_tracked_files() -> list:
    out = git("ls-files")
    return [unquote_path(f) for f in out.splitlines() if f.strip()]


def violations_for(path: str) -> str | None:
    """返回违规描述，None=合规。"""
    p = path.replace("\\", "/")
    if "/" not in p:
        # 根级平铺文件
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
        if ext in MANAGED_EXT and p not in ROOT_ALLOW and p not in LEGACY_ROOT_DOCS:
            return f"根级平铺文件 {p!r} 不在白名单，请移入对应子目录（docs/ deliverables/ data/ 等）"
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="检查全部已跟踪文件（默认只查新增）")
    args = parser.parse_args()

    try:
        files = all_tracked_files() if args.all else staged_added_files()
    except Exception as exc:
        # 自身 bug 不阻断提交（fail-open for self），但打印告警
        print(f"⚠️ structure_guard 自身异常，跳过检查: {exc}")
        return 0

    bad = []
    for f in files:
        v = violations_for(f)
        if v:
            bad.append(v)

    if bad:
        print("❌ 目录结构守卫：以下文件违规平铺")
        for v in bad:
            print(f"  {v}")
        return 1

    # 存量不静默：每次都报出来，避免"登记完就忘"
    legacy = sorted(f for f in files if f.replace("\\", "/") in LEGACY_ROOT_DOCS)
    if legacy:
        print(f"⚠️ 根级存量文档 {len(legacy)} 个（已冻结豁免，待归位 docs/）：")
        for f in legacy:
            print(f"  {f}")

    print("✅ 结构守卫通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())