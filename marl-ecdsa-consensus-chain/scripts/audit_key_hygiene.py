#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
私钥卫生审计 · 全检 #4 配套
=============================================================================
为什么需要它：2026-09-28 全检发现，"私钥已加密存储"这句日志缺乏可核验依据 ——
实测仓库 keys/ 下 20 个私钥中 **15 个是明文 PEM**，另 5 个虽为加密 PEM，却是
用随源码公开的 ``DEFAULT_KEY_PASSPHRASE`` 加密的（本脚本实测可原样解开），
即**加密形态存在但保密性为零**。当时没有任何一处能回答"到底有几个明文私钥"。

本脚本把这件事变成**可复验、可进门禁**的事实：逐个私钥文件判定其真实保护等级，
并给出用词建议（防止材料里再次出现"私钥均已加密存储"这类无法举证的表述）。

判定等级
-----------------------------------------------------------------------------
``PLAINTEXT``        明文 PEM —— 零保护，任何人可读即用
``DEFAULT_PASSPHRASE``  加密形态，但用公开默认口令加密 —— **等于明文**（本脚本已能解开）
``PROTECTED``        加密形态，且默认口令**解不开**（口令来自环境变量或外部密钥）
``UNREADABLE``       既非明文、默认口令也解不开，且当前环境问题导致无法归类

用法
-----------------------------------------------------------------------------
    python -X utf8 scripts/audit_key_hygiene.py                 # 审计 ./keys
    python -X utf8 scripts/audit_key_hygiene.py --key-dir scripts/keys
    python -X utf8 scripts/audit_key_hygiene.py --migrate       # 顺带把明文迁移为加密 PEM
    python -X utf8 scripts/audit_key_hygiene.py --allow-plaintext  # 审计但退出码恒 0

退出码
-----------------------------------------------------------------------------
    0  无 ``PLAINTEXT`` / ``DEFAULT_PASSPHRASE`` 条目（或被 --allow-plaintext 放行）
    1  存在上述条目（默认 fail-closed，可直接挂进 CI / 终检）
    2  用法错误（如 --key-dir 不存在）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.crypto.ecdsa_utils import (  # noqa: E402
    DEFAULT_KEY_PASSPHRASE,
    ECDSAUtils,
)

ENCRYPTED_MARK = b"ENCRYPTED PRIVATE KEY"

LEVEL_ORDER = ["PLAINTEXT", "DEFAULT_PASSPHRASE", "UNREADABLE", "PROTECTED"]

SUGGESTION = {
    "PLAINTEXT":
        "零保护。材料里不得出现「私钥均已加密存储」；"
        "若要保留「加密存储」表述，必须同时限定「口令由环境变量提供，且不随源码分发」。",
    "DEFAULT_PASSPHRASE":
        "形态加密但口令随源码公开 → 保密性为零。材料口径同 PLAINTEXT 处理。",
    "UNREADABLE":
        "无法用默认口令解开，也无法在本环境归类：先确认口令来源再下结论。",
    "PROTECTED":
        "默认口令解不开，具备实际保护效果 —— 这是唯一支持「私钥已加密存储」表述的情形。",
}


def classify(pem: bytes) -> str:
    """判定单个私钥 PEM 的真实保护等级。"""
    if ENCRYPTED_MARK not in pem:
        # 可能是明文私钥（EC/PKCS8/RSA）或 TLS 私钥
        return "PLAINTEXT"
    try:
        ECDSAUtils.private_key_from_bytes(pem, DEFAULT_KEY_PASSPHRASE)
        # 默认口令能解开 → 保护等级等价于明文
        return "DEFAULT_PASSPHRASE"
    except Exception:
        # 解不开：可能是环境变量口令加密的正品
        return "PROTECTED"


def is_private(path: Path) -> bool:
    name = path.name
    return ("private" in name) or ("tls_key" in name)


def main() -> int:
    ap = argparse.ArgumentParser(description="私钥卫生审计（全检 #4）")
    ap.add_argument("--key-dir", default="./keys",
                    help="待审计目录（默认 ./keys）")
    ap.add_argument("--migrate", action="store_true",
                    help="把 PLAINTEXT 私钥就地迁移为加密 PEM（幂等；用当前口令）")
    ap.add_argument("--allow-plaintext", action="store_true",
                    help="仅报告，不因发现明文/默认口令而改变退出码")
    ap.add_argument("--quiet", action="store_true", help="只打印汇总行")
    args = ap.parse_args()

    key_dir = Path(args.key_dir)
    if not key_dir.is_absolute():
        key_dir = ROOT / key_dir
    if not key_dir.exists():
        print(f"[FAIL] 目录不存在: {key_dir}")
        return 2

    files = sorted(p for p in key_dir.rglob("*.pem") if is_private(p))
    if not files:
        print(f"[ok ] {key_dir} 下没有私钥 PEM 文件")
        return 0

    rows = []
    migrated = 0
    for f in files:
        try:
            pem = f.read_bytes()
        except OSError as e:
            rows.append((f, "UNREADABLE", f"读取失败: {e}"))
            continue

        level = classify(pem)
        note = ""
        if level == "PLAINTEXT" and args.migrate:
            try:
                priv = ECDSAUtils.private_key_from_bytes(pem, None)
                from blockchain.crypto.ecdsa_utils import resolve_key_passphrase
                pw = resolve_key_passphrase()
                f.write_bytes(ECDSAUtils.private_key_to_bytes(priv, pw))
                try:
                    os.chmod(str(f), 0o600)
                except (OSError, AttributeError):
                    pass
                level = classify(f.read_bytes())
                migrated += 1
                note = "已迁移"
            except Exception as e:
                note = f"迁移失败: {type(e).__name__}: {e}"

        try:
            mode = oct(os.stat(f).st_mode & 0o777)
        except OSError:
            mode = "?"
        rows.append((f, level, (f"{note} " if note else "") + f"perm={mode}"))

    counts = {lv: 0 for lv in LEVEL_ORDER}
    for _, level, _ in rows:
        counts[level] += 1

    if not args.quiet:
        print(f"\n私钥卫生审计 · 目录 {key_dir}")
        print("-" * 78)
        for path, level, note in rows:
            print(f"  [{level:<20}] {path.relative_to(ROOT)}  {note}")
        print("-" * 78)

    total = len(rows)
    bad = counts["PLAINTEXT"] + counts["DEFAULT_PASSPHRASE"]
    print(
        f"合计 {total} 个私钥: "
        f"明文 {counts['PLAINTEXT']} / 默认口令(等价明文) {counts['DEFAULT_PASSPHRASE']} / "
        f"受保护 {counts['PROTECTED']} / 无法归类 {counts['UNREADABLE']}"
        + (f"  （本次迁移 {migrated} 个）" if migrated else "")
    )

    if counts["PLAINTEXT"] or counts["DEFAULT_PASSPHRASE"]:
        print("\n⚠️ 材料用词建议（禁止无依据地宣称「私钥均已加密存储」）：")
        for lv in ("PLAINTEXT", "DEFAULT_PASSPHRASE"):
            if counts[lv]:
                print(f"  - 有 {counts[lv]} 个 {lv}: {SUGGESTION[lv]}")
    else:
        print("\n✅ 全部私钥均由非公开口令保护，可支撑「私钥已加密存储」表述。")

    if bad and not args.allow_plaintext:
        print(f"\n[FAIL] 存在 {bad} 个不具保密性的私钥（改普查或加 --allow-plaintext）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
