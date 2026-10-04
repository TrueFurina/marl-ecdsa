#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""secrets_scan.py 的变异验证（不纳入 pytest 收集，手动跑）。

原理：把 40 位 base64（AWS Secret）模式的负向前瞻删掉，制造一个"退化版"，
断言该退化版会把绝对路径 / 40 位纯 hex 误报（exit 1）——从而证明当前正则里的
负向前瞻不是摆设，删掉它门禁的"豁免半边"就会失效。

用法：
    python tests/_mutate_secrets_scan.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = REPO_ROOT / "scripts" / "pre-commit" / "secrets_scan.py"
PY = sys.executable

# 原正则（含负向前瞻排除路径/纯 hex）
ORIGINAL = re.compile(
    r'(?<![:\w/+])(?!([0-9a-f]{40})(?![0-9a-zA-Z/+]))[0-9a-zA-Z/+]{40}(?![0-9a-zA-Z/+])'
)
# 退化版：删掉负向前瞻（退化成裸 [0-9a-zA-Z/+]{40}，历史版本就是这样）
MUTATED = re.compile(r'[0-9a-zA-Z/+]{40}')

# 三个"应豁免"的非密钥样本
EXEMPT_SAMPLES = {
    "绝对路径": "PY = 'C:/Users/Lenovo/AppData/Local/Programs/Python/python.exe'",
    "纯40hex": "seed = '36727819239baabaf4634d93f1e98668de254a20'",
}


def main() -> int:
    ok = True
    # 1) 原正则：三者都不命中
    for name, line in EXEMPT_SAMPLES.items():
        if ORIGINAL.search(line):
            print(f"[FAIL] 原正则误报「{name}」——豁免失效")
            ok = False
    # 2) 退化正则：路径 / 纯 hex 至少一项会命中（证明负向前瞻有真实作用）
    mutated_hits = [n for n, line in EXEMPT_SAMPLES.items() if MUTATED.search(line)]
    if not mutated_hits:
        print("[FAIL] 退化正则也全不命中——负向前瞻纯属摆设，变异无区分度")
        ok = False
    else:
        print(f"[OK] 退化正则命中 {mutated_hits}（证明负向前瞻有真实豁免作用）")

    # 3) 端到端：把 SCAN 源码里的负向前瞻摘除后，跑一个含路径的文件应 exit 1
    src = SCAN.read_text(encoding="utf-8")
    mutated_src = src.replace(
        r"(?<![:\w/+])(?!([0-9a-f]{40})(?![0-9a-zA-Z/+]))[0-9a-zA-Z/+]{40}(?![0-9a-zA-Z/+])",
        "[0-9a-zA-Z/+]{40}",
    )
    if mutated_src == src:
        print("[FAIL] 未能在 SCAN 源码中找到待变异正则，检查模式是否已变")
        return 1
    with tempfile.TemporaryDirectory() as td:
        mut_path = Path(td) / "secrets_scan_mutated.py"
        sample = Path(td) / "sample.py"
        mut_path.write_text(mutated_src, encoding="utf-8")
        sample.write_text("PY = 'C:/Users/Lenovo/AppData/Local/Programs/Python/python.exe'\n",
                          encoding="utf-8")
        proc = subprocess.run([PY, str(mut_path), str(sample)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 1:
            print("[OK] 端到端变异：退化版把路径误报为密钥（exit 1）——当前正则的豁免是必要的")
        else:
            print(f"[FAIL] 端到端变异：退化版未误报（exit {proc.returncode}），豁免可能本就不必要")
            ok = False

    print("变异验证", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
