#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""幂等安装 pre-commit 门禁 hook。

.git/hooks/pre-commit 不受 git 跟踪，克隆/新环境后不会自动存在。本脚本把
scripts/pre-commit/pre-commit（唯一真源模板）安装到 .git/hooks/pre-commit，
并保证可执行位。重复运行幂等（内容以模板为准，覆盖旧版）。

用法（在仓库根执行）：
    python scripts/pre-commit/install_hooks.py
"""
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "scripts" / "pre-commit" / "pre-commit"
HOOK = REPO_ROOT / ".git" / "hooks" / "pre-commit"


def main() -> int:
    if not (REPO_ROOT / ".git").exists():
        print(f"[FAIL] 未找到 .git，请在仓库根执行：{REPO_ROOT}")
        return 1
    if not TEMPLATE.exists():
        print(f"[FAIL] 模板不存在：{TEMPLATE}")
        return 1

    template_text = TEMPLATE.read_text(encoding="utf-8")
    current = HOOK.read_text(encoding="utf-8") if HOOK.exists() else ""
    if current == template_text:
        print(f"[OK] hook 已是最新，无需变更：{HOOK}")
    else:
        HOOK.write_text(template_text, encoding="utf-8")
        print(f"[OK] 已安装/更新 hook：{HOOK}")

    # 保证可执行位（Windows 上 os.chmod 的 x 位意义有限，但 Linux/mac 需要）
    try:
        os.chmod(HOOK, 0o755)
    except OSError:
        pass
    print("[OK] pre-commit 门禁安装完成（6 步 fail-closed）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
