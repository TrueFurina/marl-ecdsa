#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutation_probe.py — MARL-ECDSA 守卫承重变异探针（调查工具，非 CI 门禁）

纪律来源：REA stryker 配置 + scripts/lib/reverse-tools-mutation-targets.mjs
（2026-10-20 映射，续篇九 #153/#154/#155/#157）：

  1. 变异目标显式登记于 tests/mutation_targets.json，不随机全变异（#153）；
  2. 每个目标的 locator 必须唯一定位——0 个或多个匹配都判 FAIL，
     绝不静默跳过（#154 fail-closed 变异目标层）；
  3. 变异后关联检查必须"承重"：pytest 家族全红 / 命令断言由成立变不成立。
     "变异后仍绿" = 该守卫不承重 = 探针 FAIL（#138 的可复跑制度化）；
  4. 只读保证：开跑前**目标文件本身**必须干净（git status 对该文件无输出，
     否则拒跑——防止把别人的未提交改动卷进变异/恢复）；仓库整体脏改动
     不拒跑，但快照进报告备查；每目标记录原内容 SHA256；finally 恢复并
     逐字节校验；中断不残留变异体；
  5. command 类目标做前后对照：基线（未注入）必须匹配 expect_pattern，
     注入后必须不匹配——防止模式写错导致误判承重（#157 的语义：目标
     定位与断言都必须真实）；
  6. 报告落 reports/mutation/（gitignored），含"未覆盖守卫类别"声明
     （#168：知道自己没测什么）。

用法：
    python -X utf8 scripts/mutation_probe.py            # 全目标
    python -X utf8 scripts/mutation_probe.py --id X     # 单目标
    python -X utf8 scripts/mutation_probe.py --dry-run  # 只验证定位，不注入

定位：调查工具。不设分数门槛（#155），可手动/定时跑；**不进 ci.yml
必需链**——避免为绿而动门禁。退出码 0 = 全部目标探测且承重。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS_FILE = REPO / "tests" / "mutation_targets.json"
REPORT_DIR = REPO / "reports" / "mutation"

# 已知未覆盖的守卫类别（诚实声明盲区，REA #168）：
#   - marl/ 共识层（非 integration 签名层）的守卫；
#   - scripts/pack_submission_zips.py 打包链路（未登记 pytest 家族）；
#   - check_submission_anonymity.py 的逐模式承重（只测过整链）；
#   - 训练/评估脚本（train.py 等，非交付面）。
UNCOVERED_NOTE = (
    "未覆盖守卫类别：marl/ 共识层守卫；pack_submission_zips 打包链路；"
    "匿名门禁逐模式承重；train.py 等训练脚本。新增目标请带 why + 审计日期。"
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def git_file_clean(rel: str) -> tuple[bool, str]:
    """目标文件自身的 git 状态：干净才允许注入（安全范围=操作范围）。
    - 未跟踪（??）→ 拒跑：无 HEAD 版本可作恢复基准；
    - 仅行尾（CRLF/LF）差异 → 视为干净：core.autocrlf 环境的状态噪音
      （实测：diff 空但 status 报 M，实质差异为零）。"""
    r = run(["git", "status", "--porcelain", "--", rel])
    out = r.stdout.strip()
    if not out:
        return True, ""
    if out.startswith("??"):
        return False, out
    d = run(["git", "diff", "--ignore-cr-at-eol", "--quiet", "--", rel])
    if d.returncode == 0:
        return True, "(仅行尾差异，视为干净)"
    return False, out


def git_dirty_snapshot(limit: int = 2000) -> str:
    r = run(["git", "status", "--porcelain"])
    return (r.stdout or "")[:limit]


def load_targets() -> list[dict]:
    if not TARGETS_FILE.exists():
        raise SystemExit(f"FAIL: 目标登记文件不存在: {TARGETS_FILE}")
    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    targets = data.get("targets")
    if not isinstance(targets, list) or len(targets) == 0:
        raise SystemExit("FAIL: 变异目标登记为空——空清单不放过（REA #154）")
    for t in targets:
        for field in ("id", "file", "locator", "mutation", "check", "why"):
            if field not in t:
                raise SystemExit(f"FAIL: 目标缺少必填字段 {field}: {t.get('id', '?')}")
        if t["check"].get("kind") not in ("pytest", "command"):
            raise SystemExit(f"FAIL: 目标 {t['id']} 的 check.kind 仅支持 pytest/command")
    return targets


def locate(path: Path, locator: str) -> tuple[str, int]:
    """返回 (原文, locator 匹配次数)。"""
    text = path.read_text(encoding="utf-8")
    return text, text.count(locator)


def check_pytest(args: list[str]) -> tuple[bool, str]:
    r = run([sys.executable, "-m", "pytest", *args])
    return r.returncode != 0, f"rc={r.returncode}"


def check_command(cmd: list[str], pattern: str, injected: bool) -> tuple[bool, str]:
    """前后对照：未注入时必须匹配 pattern，注入后必须不匹配（承重）。"""
    if cmd[0].endswith(".py"):  # Windows 无 .py 直执行关联，防御性前缀解释器
        full = [sys.executable, *cmd]
    elif cmd[0] == "python":
        full = [sys.executable, *cmd[1:]]
    else:
        full = list(cmd)
    r = run(full)
    matched = re.search(pattern, r.stdout or "") is not None
    if not injected:
        return matched, f"baseline matched={matched}"
    # 注入后：匹配消失 = 守卫承重
    return (not matched), f"mutated matched={matched}（应 False）"


def probe(target: dict, dry_run: bool) -> dict:
    tid = target["id"]
    path = REPO / target["file"]
    result: dict = {"id": tid, "file": target["file"], "ok": False, "steps": []}

    if not path.exists():
        result["steps"].append(f"FAIL: 文件不存在 {target['file']}")
        return result

    original, count = locate(path, target["locator"])
    if count != 1:
        result["steps"].append(
            f"FAIL: locator 匹配 {count} 次（必须恰好 1 次）——"
            "目标漂移或歧义，fail-closed 不跳过（REA #154）")
        return result
    result["steps"].append("定位唯一 ✓")

    file_clean, dirty = git_file_clean(target["file"])
    if not file_clean:
        result["steps"].append(
            f"FAIL: 目标文件自身有未提交改动，拒跑（先提交该文件）：\n    {dirty.strip()}")
        return result
    result["steps"].append("目标文件 git 干净 ✓")
    result["original_sha256"] = sha256_text(original)

    if dry_run:
        result["ok"] = True
        result["steps"].append("dry-run：仅定位，未注入")
        return result

    check = target["check"]
    try:
        # command 类先做基线对照（未注入必须匹配）
        if check["kind"] == "command":
            ok, detail = check_command(check["cmd"], check["expect_pattern"], injected=False)
            if not ok:
                result["steps"].append(f"FAIL: 基线对照未过——{detail}（模式或命令有误，先修登记再探）")
                return result
            result["steps"].append(f"基线对照 ✓（{detail}）")

        mutated = original.replace(target["locator"], target["mutation"], 1)
        if mutated == original:
            result["steps"].append("FAIL: 注入后文本无变化（locator 与 mutation 相同？）")
            return result
        path.write_text(mutated, encoding="utf-8")

        if check["kind"] == "pytest":
            ok, detail = check_pytest(check.get("args", []))
            verdict = "变异后测试全红 ✓（守卫承重）" if ok else "变异后测试仍绿 ✗（守卫不承重）"
        else:
            ok, detail = check_command(check["cmd"], check["expect_pattern"], injected=True)
            verdict = f"变异后断言失效 ✓（守卫承重）— {detail}" if ok else f"变异后断言仍成立 ✗ — {detail}"
        result["steps"].append(verdict)
        result["ok"] = ok
    finally:
        path.write_text(original, encoding="utf-8")
        restored, rcount = locate(path, target["locator"])
        if rcount == 1 and sha256_text(restored) == result["original_sha256"]:
            result["steps"].append("原文恢复 ✓（SHA256 逐字节一致）")
        else:
            result["steps"].append("FAIL: 原文恢复异常——立即 git checkout 该文件并排查！")
            result["ok"] = False
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="MARL-ECDSA 守卫承重变异探针（调查工具）")
    ap.add_argument("--id", help="只跑指定目标 id")
    ap.add_argument("--dry-run", action="store_true", help="只验证定位，不注入")
    args = ap.parse_args()

    clean = True  # 目标文件级干净在各 probe() 内逐项校验；此处保留仓库脏快照备查
    _ = clean

    targets = load_targets()
    if args.id:
        targets = [t for t in targets if t["id"] == args.id]
        if not targets:
            print(f"FAIL: 未找到目标 id={args.id}")
            return 1

    print("=" * 72)
    print("  MARL-ECDSA · 守卫承重变异探针" + ("（dry-run）" if args.dry_run else ""))
    print(f"  登记目标 {len(targets)} 个 | {UNCOVERED_NOTE}")
    print("=" * 72)

    results = []
    for t in targets:
        print(f"\n▶ {t['id']}  ({t['file']})")
        print(f"  理由: {t['why']}")
        r = probe(t, args.dry_run)
        for s in r["steps"]:
            print(f"  {'✅' if '✓' in s else '❌'} {s}")
        results.append(r)

    passed = sum(1 for r in results if r["ok"])
    print("\n" + "-" * 72)
    print(f"  汇总: {passed}/{len(results)} 目标探测且承重")

    if not args.dry_run:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report = {
            "tool": "mutation_probe",
            "repo": str(REPO),
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": args.dry_run,
            "dirty_snapshot": git_dirty_snapshot(),
            "results": results,
            "summary": {"total": len(results), "passed": passed},
            "uncovered_note": UNCOVERED_NOTE,
        }
        out = REPORT_DIR / f"probe-{stamp}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告: {out.relative_to(REPO)}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
