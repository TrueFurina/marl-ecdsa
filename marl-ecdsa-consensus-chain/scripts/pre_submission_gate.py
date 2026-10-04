#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提交前口径终检（P0-7）：一条命令跑完「仓库内 + 工作区材料」的口径检查。

## 存在理由（架构审查 D1）

口径门禁原本只有两种跑法：

* pre-commit ``--cached`` → 只看**暂存区**（＝仓库内文件）
* CI ``--root $PWD``      → 只看**检出目录**（＝仓库）

而真正的提交材料 ``competition_submission/``、``MARL-ECDSA_共识链_提交包/``、
``competition-materials/`` 都在**工作区、不在仓库内** ⇒ **它们从未被任何门禁扫过**。
本脚本补的正是这一段：以**工作区根**为范围跑全量扫描，把材料层纳入检查。

## 为什么刻意不进 pre-commit

编辑中途的瞬态（例如改 HTML 时短暂写回旧数字）会让门禁拦死提交，
反而把开发者逼向 ``--no-verify`` —— 那才是真正的失守。故本脚本定位为
**提交前手动/流水线终检**，不属于提交钩子。

## 用法

    python -X utf8 scripts/pre_submission_gate.py               # 口径六项（含 D4 code_check）
    python -X utf8 scripts/pre_submission_gate.py --with-tests  # 追加全量测试（junit 判定）

退出码：``0`` 全部通过；``1`` 有未通过项；``2`` 用法错误。

## 六项检查

1. 口径扫描·工作区全量（含 ``competition_submission/`` 等材料层）
2. 引用域·合成文献扫描
3. 登记表镜像一致性
4. public/private 配置一致性
5. 结构守卫（全仓）
6. 口径 vs 代码一致性（``code_check`` 类条目，架构审查 D4）

第 6 项把 ``verify_numbers.py --code-check-only`` 接入终检：任何会话改
``cw_pbft.py`` 等源码打破权重/可用性口径（如新增 ``MAX_WEIGHT``），终检会**直接
变红报警**，不再像此前那样静默漂移（该工具原本不在 CI/门禁链上）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402

REPORTS = ac.REPORTS_DIR
VOID_REPORT = REPORTS / "pre_submit_void_tokens.json"
CIT_REPORT = REPORTS / "pre_submit_citation.json"
CLAIM_REPORT = REPORTS / "claim_code_check.json"


def run(cmd: list[str]) -> tuple[int, str]:
    """在仓库根跑一条命令，返回 ``(rc, 输出尾部)``。"""
    r = subprocess.run(cmd, cwd=str(ac.REPO_ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode, out[-600:]


def blocking_of(report: Path) -> int | None:
    """读扫描报告的 blocking 数；报告缺失返回 None。"""
    if not report.exists():
        return None
    doc = json.loads(report.read_text(encoding="utf-8"))
    return int(doc.get("summary", {}).get("blocking", -1))


def check_void(tokenless: bool = False) -> tuple[bool, str]:
    if tokenless:
        return True, "跳过（--skip-void）"
    rc, out = run([sys.executable, "-X", "utf8", "scripts/scan_void_tokens.py",
                   "--report", str(VOID_REPORT), "--overwrite"])
    n = blocking_of(VOID_REPORT)
    hits = ""
    if VOID_REPORT.exists():
        s = json.loads(VOID_REPORT.read_text(encoding="utf-8"))["summary"]
        hits = (f"files={s.get('files_scanned')} hits={s.get('hits')} "
                f"block={s.get('blocking')} warn={s.get('warn')} info={s.get('info')}")
    return (n == 0), f"{hits}  rc={rc}"


def check_citation() -> tuple[bool, str]:
    rc, out = run([sys.executable, "-X", "utf8", "scripts/scan_citation_blacklist.py",
                   "--report", str(CIT_REPORT), "--overwrite"])
    n = blocking_of(CIT_REPORT)
    return (n == 0), f"blocking={n}  rc={rc}"


def check_mirror() -> tuple[bool, str]:
    rc, out = run([sys.executable, "-X", "utf8", "scripts/check_registry_mirror.py"])
    return (rc == 0), (out.splitlines()[-1] if out else "")


def check_config() -> tuple[bool, str]:
    rc, out = run([sys.executable, "-X", "utf8", "scripts/gen_assurance_config.py", "--check"])
    return (rc == 0), (out.splitlines()[-1] if out else "")


def check_structure() -> tuple[bool, str]:
    rc, out = run([sys.executable, "-X", "utf8", "scripts/pre-commit/structure_guard.py", "--all"])
    return (rc == 0), (out.splitlines()[-1] if out else "")


def check_tests() -> tuple[bool, str]:
    junit = REPORTS / "pre_submit_junit.xml"
    rc, out = run([sys.executable, "-X", "utf8", "-m", "pytest", "-q",
                   f"--junitxml={junit}", "-p", "no:cacheprovider"])
    if not junit.exists():
        return False, f"无 junit 产出，rc={rc}"
    ts = ET.parse(junit).getroot()
    ts = ts if ts.tag == "testsuite" else ts.find("testsuite")
    a = ts.attrib
    tot, fail, err, sk = (int(a.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
    # 判定以 junit 为准：环境的 safe-delete 钩子会污染 pytest 的 shell 退出码
    return (fail == 0 and err == 0), f"tests={tot} failures={fail} errors={err} skipped={sk}"


def check_claim_code_consistency() -> tuple[bool, str]:
    """架构审查 D4：把 code_check 类「口径 vs 代码」条目接入终检。

    原本 ``verify_numbers.py --run-tests`` 报告 NR-15 FAIL，但该工具**不在 CI、
    也不在门禁链上** ⇒ 任何会话改 ``cw_pbft.py`` 打破权重口径（如新增
    ``MAX_WEIGHT``）都是**静默漂移**。这里把它做成终检原子：

    * 用 ``--code-check-only`` 只跑 code_check 条目（快、与数值漂移解耦）；
    * 判据以报告 JSON 为准（与 junit 同理，不依赖 shell 退出码）；
    * 任一 code_check 条目 FAIL → 门禁变红报警（fail-closed）。

    注意：本步**不进 pre-commit**（D1 已说明原因），仅出现在提交前终检，
    因此不会拦死并发会话的日常提交，只会在提交前逼出口径冲突。
    """
    # 本函数可被单独调用（终检第 6 步 / 测试直调），此处确保报告目录存在，
    # 否则在干净 checkout 上 verify_numbers 无法落盘报告 → 门禁误判为无报告。
    CLAIM_REPORT.parent.mkdir(parents=True, exist_ok=True)
    rc, out = run([sys.executable, "-X", "utf8", "scripts/verify_numbers.py",
                   "--code-check-only", "--report", str(CLAIM_REPORT), "--overwrite"])
    if not CLAIM_REPORT.exists():
        # 工具缺失/报错 → fail-closed，绝不放行
        return False, f"无报告产出（工具可能报错），rc={rc} :: {out[-300:]}"
    doc = json.loads(CLAIM_REPORT.read_text(encoding="utf-8"))
    entries = doc.get("entries", [])
    broken = [e["id"] for e in entries if e.get("status") == "FAIL"]
    s = doc.get("summary", {})
    detail = (f"code_check: total={s.get('total')} PASS={s.get('pass')} "
              f"FAIL={s.get('fail')}  broken={broken or '-'}")
    return (not broken), detail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="提交前口径终检")
    ap.add_argument("--with-tests", action="store_true", help="追加全量 pytest（junit 判定）")
    ap.add_argument("--skip-void", action="store_true", help="跳过工作区口径扫描（不推荐）")
    args = ap.parse_args(argv)

    REPORTS.mkdir(parents=True, exist_ok=True)
    checks: list[tuple[str, tuple[bool, str]]] = []

    print("=== 提交前口径终检 ===")
    print(f"扫描范围：工作区根 {ac.WORKSPACE_ROOT}")
    print()

    for name, fn in [
        ("口径扫描·工作区全量（含 competition_submission/）", lambda: check_void(args.skip_void)),
        ("引用域·合成文献扫描", check_citation),
        ("登记表镜像一致性", check_mirror),
        ("public/private 配置一致性", check_config),
        ("结构守卫（全仓）", check_structure),
        ("口径 vs 代码一致性（code_check，D4）", check_claim_code_consistency),
    ]:
        ok, detail = fn()
        checks.append((name, (ok, detail)))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")

    if args.with_tests:
        ok, detail = check_tests()
        checks.append(("全量测试（junit XML 判定）", (ok, detail)))
        print(f"  [{'PASS' if ok else 'FAIL'}] 全量测试（junit XML 判定）")
        print(f"         {detail}")

    bad = [n for n, (ok, _) in checks if not ok]
    print()
    if bad:
        print(f"❌ 未通过 {len(bad)} 项：")
        for n in bad:
            print(f"   - {n}")
        print("\n提示：blocking>0 的命中明细见 deliverables/assurance/reports/*.json")
        return 1
    print(f"✅ 全部通过（{len(checks)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
