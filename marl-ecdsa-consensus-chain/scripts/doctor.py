#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""doctor.py — marl-ecdsa-consensus-chain 一键健康自检（只读聚合，不新增门禁语义）

用法::

    python -X utf8 scripts/doctor.py            # 快速档（秒级）：环境 + git 卫生 + 登记簿新鲜度
    python -X utf8 scripts/doctor.py --full     # 追加全量门禁（verify_numbers ~4min + 匿名全包 + 终检）
    python -X utf8 scripts/doctor.py --json     # 机器可读（供 agent 读取）
    python -X utf8 scripts/doctor.py --strict   # WARN/unknown 也判失败
    python -X utf8 scripts/doctor.py --ci       # CI 模式：跳过仓库外工作区资产（registry/提交包/报告/git）

设计纪律（REA 最佳实践映射 2026-10-19，见 E:\\Program\\REA最佳实践映射-多智能体主线-2026-10-19.md）::

    1. 只读：不写、不改、不删任何文件；调用既有门禁，不复制其逻辑；
    2. 证据分级：每条结果带 observed（直接测得）/ derived（由观测推导）/ unknown（未能确认），
       unknown 显式输出，不静默省略（"没报出来" != "没有问题"）；
    3. 全量门禁耗时（verify_numbers 约 4 分钟、匿名全包约 2-5 分钟）不放快速档，
       快速档改读「最近一次全量报告的新鲜度」，full 档才真跑；
    4. 退出码：0 = 全部通过；1 = 存在 FAIL（--strict 下 WARN/unknown 也计失败）。

与 AGENTS.md 的关系：本脚本不替代 AGENTS.md 任何纪律（NR 取号、registry 备份、多会话铁律），
只在并发改仓场景下提供 10 秒级态势自检。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]          # marl-ecdsa-consensus-chain/
WS = REPO.parent                                     # CCF 竞赛外层工作区
PKG = WS / "MARL-ECDSA_共识链_提交包"                # 提交包（终检/匿名门禁目标）
REGISTRY = WS / "deliverables" / "number_registry.json"
REPORTS = WS / "deliverables" / "assurance" / "reports"

RESULTS: list[dict] = []


def record(name: str, ok, level: str = "observed", detail: str = "") -> None:
    RESULTS.append({
        "name": name,
        "ok": "PASS" if ok is True else "FAIL" if ok is False else "WARN",
        "level": level,
        "detail": detail,
    })


def run(cmd: list[str], cwd: Path, timeout: int | None = None):
    """落盘式执行：完整捕获 stdout/stderr 与 RC，绝不用管道掩盖失败。"""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {timeout}s", time.time() - t0
    except FileNotFoundError as e:
        return None, f"FileNotFoundError: {e}", time.time() - t0


def _git_head(repo: Path) -> str:
    """执行基线：pin 仓库 HEAD，供 CI 归因与历史对比（REA #134）。失败不炸，记 unknown。"""
    rc, out, _ = run(["git", "rev-parse", "HEAD"], repo, timeout=10)
    head = out.strip().splitlines()[0].strip() if rc == 0 and out.strip() else ""
    return head if len(head) == 40 else "unknown"


# ---------------------------------------------------------------- 快速档
def check_python() -> None:
    v = sys.version.split()[0]
    ok = sys.version_info >= (3, 10)
    record(f"Python {v}（>=3.10）", ok, "observed",
           "" if ok else "版本过低，脚本可能无法运行")


def check_git(ci: bool = False) -> None:
    if ci:
        record("Git 分支/工作区（CI 跳过）", None, "unknown",
               "CI checkout 为 detached HEAD 且无工作区语义——本地跑 doctor 时该项生效")
        return
    rc, out, _ = run(["git", "branch", "--show-current"], REPO)
    branch = out.strip()
    if rc != 0 or not branch:
        record("Git 分支", False, "observed", "detached 或非 git 仓库（多会话改仓时先确认 HEAD 归属）")
    else:
        record(f"Git 分支 = {branch}", True, "observed")
    rc, out, _ = run(["git", "status", "--porcelain"], REPO)
    lines = [l for l in out.splitlines() if l.strip()]
    untracked = sum(1 for l in lines if l.startswith("??"))
    record(f"工作区 {len(lines) - untracked} 改 / {untracked} 未跟踪", True, "observed",
           "动 registry 前先备份并 ls 确认；登记编号用 scripts/next_nr.py 原子取号（AGENTS.md 铁律）" if lines else "")


def check_registry(ci: bool = False) -> None:
    if ci and not REGISTRY.is_file():
        record("number_registry.json（CI 跳过）", None, "unknown",
               "registry 在仓库外工作区（deliverables/），CI clone 不含——本地/上传前跑时该项生效")
        return
    if not REGISTRY.is_file():
        record("number_registry.json 存在", False, "observed", f"未找到: {REGISTRY}")
        return
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        record("number_registry.json 可解析", False, "observed", str(e))
        return
    entries = data.get("entries", data if isinstance(data, list) else [])
    ids = [e.get("id", "") for e in entries if isinstance(e, dict)]
    max_nr = 0
    for i in ids:
        m = re.match(r"NR-(\d+)", str(i))
        if m:
            max_nr = max(max_nr, int(m.group(1)))
    record(f"登记簿条目 {len(ids)} 条（最大编号 NR-{max_nr}）", len(ids) > 0, "observed",
           "登记进度以实际最大编号为准，勿凭记忆（AGENTS.md 铁律 5）")


def check_report_freshness(ci: bool = False) -> None:
    if ci and not REPORTS.is_dir():
        record("verify_numbers 报告新鲜度（CI 跳过）", None, "unknown",
               "报告目录在仓库外工作区，CI clone 不含——CI 的对应保障是 ci.yml 的 Caliber gate 步骤")
        return
    if not REPORTS.is_dir():
        record("最近全量门禁报告", False, "unknown", f"目录不存在: {REPORTS}")
        return
    reports = sorted(REPORTS.glob("number_verification_report_*.json"))
    if not reports:
        record("最近全量门禁报告", False, "unknown", "未找到 number_verification_report_*.json")
        return
    latest = reports[-1]
    age_h = (time.time() - latest.stat().st_mtime) / 3600
    try:
        rep = json.loads(latest.read_text(encoding="utf-8"))
        summary = rep.get("summary", rep)
        bits = {k: summary[k] for k in ("total", "PASS", "FAIL", "PENDING", "INVALID") if k in summary}
        detail = f"{latest.name}（{age_h:.1f}h 前）汇总={bits}"
    except Exception as e:  # noqa: BLE001
        detail = f"{latest.name}（{age_h:.1f} 前，解析失败: {e}）"
    ok = age_h <= 24 * 7
    record("verify_numbers 报告新鲜度", ok, "derived",
           detail + ("" if ok else " —— 超过 7 天，上传/答辩前请 --full 复跑"))


def check_scripts(ci: bool = False) -> None:
    need = ["verify_numbers.py", "check_submission_anonymity.py", "final_check.py",
            "next_nr.py", "pre_submission_gate.py", "check_evidence_closure.py"]
    missing = [s for s in need if not (REPO / "scripts" / s).is_file()]
    record(f"关键门禁脚本 {len(need) - len(missing)}/{len(need)} 在位", not missing, "observed",
           f"缺失: {missing}" if missing else "")
    if not PKG.is_dir():
        if ci:
            record("提交包目录（CI 跳过）", None, "unknown",
                   "提交包在仓库外工作区，CI clone 不含——上传前夜本地跑 doctor 时该项生效")
        else:
            record("提交包目录存在", False, "unknown", f"未找到: {PKG}（--full 的匿名/终检将跳过）")


# ---------------------------------------------------------------- full 档
def full_verify_numbers() -> None:
    cmd = [sys.executable, "-X", "utf8", "scripts/verify_numbers.py",
           "--registry", str(REGISTRY), "--data-root", "results"]
    rc, out, dt = run(cmd, REPO, timeout=900)
    m = re.search(r"汇总：total=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+PENDING=(\d+)\s+INVALID=(\d+)", out)
    detail = (f"{dt:.0f}s；{m.group(0).replace('汇总：', '')}" if m else f"RC={rc}，未解析到汇总行（详见原始输出）")
    record("verify_numbers（登记簿数字复算）", rc == 0, "observed", detail)


def full_anonymity() -> None:
    if not PKG.is_dir():
        record("匿名门禁（提交包全扫）", None, "unknown", "提交包目录不存在，跳过")
        return
    rc, out, dt = run([sys.executable, "-X", "utf8", "scripts/check_submission_anonymity.py",
                       "--root", str(PKG)], REPO, timeout=900)
    files = re.search(r"已扫描文件:\s*(\d+)", out)
    hit = "匿名合规门禁通过" in out
    record("匿名门禁（提交包全扫）", rc == 0 and hit, "observed",
           f"{dt:.0f}s；扫描 {files.group(1) if files else '?'} 文件；{'通过' if hit else '未确认通过（见原始输出）'}")


def full_final_check() -> None:
    rc, out, dt = run([sys.executable, "-X", "utf8", "scripts/final_check.py", "--quick"],
                      REPO, timeout=900)
    passed = re.search(r"(\d+) 通过 / (\d+) 未通过", out)
    record("提交包终检 final_check --quick", rc == 0, "observed",
           f"{dt:.0f}s；{passed.group(0) if passed else f'RC={rc}'}")


def full_evidence_closure() -> None:
    rc, out, dt = run([sys.executable, "-X", "utf8", "scripts/check_evidence_closure.py"],
                      REPO, timeout=600)
    record("证据闭合 check_evidence_closure", rc == 0, "observed", f"{dt:.0f}s；RC={rc}")


# ---------------------------------------------------------------- 输出
def emit(json_mode: bool, strict: bool, full: bool, ci: bool) -> int:
    fails = sum(1 for r in RESULTS if r["ok"] == "FAIL")
    warns = sum(1 for r in RESULTS if r["ok"] == "WARN")
    failed = fails + (warns if strict else 0)
    if json_mode:
        # strict_fail = 当前严格度下的有效失败数（--strict 时 WARN/unknown 计入）。
        # 单独给出：机器消费方不能只靠退出码反推「失败来自 FAIL 还是 strict 升级」。
        # head/ran_at = 执行基线 pin，供 CI 归因与历史对比（REA #134）。
        print(json.dumps({"tool": "doctor", "repo": str(REPO), "full": full, "strict": strict,
                          "ci": ci, "head": _git_head(REPO),
                          "ran_at": datetime.now(timezone.utc).isoformat(),
                          "results": RESULTS,
                          "summary": {"pass": len(RESULTS) - fails - warns, "fail": fails,
                                      "warn": warns, "strict_fail": failed}},
                         ensure_ascii=False, indent=2))
    else:
        mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}
        width = max(len(r["name"]) for r in RESULTS) + 2
        print("=" * 78)
        print("  MARL-ECDSA 共识链 · 健康自检（doctor）"
              + (" · --full" if full else " · 快速档") + (" · --ci" if ci else ""))
        print(f"  基线 HEAD: {_git_head(REPO)}  运行时刻: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 78)
        for r in RESULTS:
            print(f"  {mark[r['ok']]} {r['name']:<{width}} [{r['level']}]" + (f" — {r['detail']}" if r["detail"] else ""))
        print("-" * 78)
        print(f"  汇总: {len(RESULTS) - fails - warns} 通过 / {fails} 失败 / {warns} 警告"
              + ("（--strict：WARN 计失败）" if strict else ""))
        if failed:
            print("  退出码 1：存在未通过项，详见上表（原始输出已在本进程内完整捕获）")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="MARL-ECDSA 一键健康自检（只读聚合）")
    ap.add_argument("--full", action="store_true", help="追加全量门禁（分钟级）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--strict", action="store_true", help="WARN/unknown 也判失败")
    ap.add_argument("--ci", action="store_true",
                    help="CI 模式：跳过依赖仓库外工作区的检查（registry/提交包/报告/git），"
                         "仓库外资产以 unknown 显式登记，不静默省略、不误判失败")
    args = ap.parse_args()

    check_python()
    check_git(ci=args.ci)
    check_registry(ci=args.ci)
    check_report_freshness(ci=args.ci)
    check_scripts(ci=args.ci)
    if args.full:
        full_verify_numbers()
        full_anonymity()
        full_final_check()
        full_evidence_closure()
    return emit(args.json, args.strict, args.full, args.ci)


if __name__ == "__main__":
    sys.exit(main())
