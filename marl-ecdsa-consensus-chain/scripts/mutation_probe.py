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
  5. 前后对照对 pytest 类同样成立（2026-11-05 加）：基线（未注入）必须
     **绿**，注入后必须**红且退出码恰为 1**。理由有二——
     · 红基线下的"变异后仍红"不证明任何承重，此前 pytest 类没有基线检查，
       一个本来就红的文件可以让任何变异体都"通过"；
     · rc=2/3/4/5（中断 / 内部错误 / 用法错 / 一条没收集）都不是"有用例
       失败"，却是非零——此前一律被当成承重，属于把门禁噪音读成通过了。
     command 类仍是「基线匹配 expect_pattern、注入后不匹配」（#157）；
  6. 行尾必须逐字节往返（2026-11-05 加）：`read_text/write_text` 默认做
     universal newline 转换，在 Windows 上把 LF 文件整份改写成 CRLF——
     注入虽被"恢复"，工作树却留下一份整文件行尾翻转的假改动；
  7. 报告落 reports/mutation/（gitignored），含"未覆盖守卫类别"声明
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

# 已知未覆盖的守卫类别（诚实声明盲区，REA #168）。
# 2026-11-05 起，审计简报 §1/§2/§3/§4/§5/§6/§7/§8/§9 的九处修复与 11-04 的
# flush_pending 缺陷已全部登记为目标（见 tests/mutation_targets.json），
# 因此原先列在这里的「marl/ 共识层守卫」一条已划掉（已覆盖的部分不再自称盲区）。
# 同日划掉「匿名门禁逐模式承重」：占位逐处判定与自豁免标记已各有一条目标。
#
# ⚠️ 2026-11-05 自我推翻一条**过期情报**：旧注释里写的
#   「scripts/pack_submission_zips.py 打包链路」在本仓库**不存在**
#   （`git ls-files | grep -i pack` 只有 scripts/pack_slim_testdata.py，
#    全仓 grep "pack_submission" 只命中本文件的注释自己）。
#   一条不存在的文件不能算盲区 —— 那是把"没查过"写成"查过但没测"。
# 同日第二批划掉「marl/integration 的自适应 λ 与结算系数」：λ 调度（adaptive /
# rl 两支）与奖励塑形的非有限值处置、统计口径已各登记为目标（共 7 条）。
# 注意「结算系数」严格说仍未全覆盖 —— 已覆盖的是 shap 侧的权重系数与
# settlement_coordinator 的 bc_reward 钳位，激励合约本身的 κ 三元组仍无变异目标。
UNCOVERED_NOTE = (
    "未覆盖守卫类别：visualization/ 与 static/ 前端路由；train.py 等训练脚本；"
    "incentive_contract 的 κ 三元组权重推导（只覆盖了 settlement 侧的 bc_reward 钳位）；"
    "匿名门禁的容器/二进制通道只靠 pytest 家族兜底，未逐规则登记变异目标。"
    "（原列的 pack_submission_zips 打包链路由实为不存在的文件，2026-11-05 删除。）"
    "新增目标请带 why + 审计日期。"
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


REQUIRED_FIELDS = ("id", "file", "locator", "mutation", "check", "why")


def load_targets() -> list[dict]:
    """读登记表并做静态校验；不合格即 SystemExit（fail-closed，不静默跳过）。"""
    if not TARGETS_FILE.exists():
        raise SystemExit(f"FAIL: 目标登记文件不存在: {TARGETS_FILE}")
    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    problems = validate_targets(data.get("targets"))
    if problems:
        raise SystemExit(
            "FAIL: 变异目标登记不合格（探针拒跑）：\n  - " + "\n  - ".join(problems))
    return data["targets"]


def read_source(path: Path) -> tuple[str, bool]:
    """返回 (以 ``\\n`` 归一的行文本, 原文是否 CRLF)。

    行尾必须自己管：``Path.read_text()`` / ``write_text()`` 默认做 universal
    newline 转换，Windows 上会把 LF 文件**整份**写成 CRLF——注入虽被恢复，
    恢复的是文本而不是字节，工作树留下整文件行尾翻转的假改动。
    """
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def write_source(path: Path, text: str, crlf: bool) -> None:
    """按原文行尾写回，保证字节级往返。"""
    out = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(out.encode("utf-8"))


def locate(path: Path, locator: str) -> tuple[str, int]:
    """返回 (行尾归一后的原文, locator 匹配次数)。"""
    text, _ = read_source(path)
    return text, text.count(locator)


def validate_targets(targets) -> list[str]:
    """登记表静态校验，返回问题清单（空 = 合格）。

    与 ``load_targets()`` 共用同一套规则：探针拒跑的登记，测试也必须判红，
    否则会出现"探针说不行、测试说没事"的两套真值。

    校验项：必填字段 / id 唯一 / check.kind 与关联测试存在 / locator 与
    mutation 不得相同 / locator 必须**恰好**命中 1 次（0 次 = 漂移，多次 =
    歧义，两种都必须 fail-closed，REA #154）。
    """
    problems: list[str] = []
    if not isinstance(targets, list) or not targets:
        return ["目标登记为空——空清单不放过（REA #154）"]

    seen: set[str] = set()
    for i, t in enumerate(targets):
        if not isinstance(t, dict):
            problems.append(f"#{i}: 目标不是对象")
            continue
        tid = t.get("id") or f"#{i}"
        for field in REQUIRED_FIELDS:
            if field not in t:
                problems.append(f"{tid}: 缺少必填字段 {field}")
        if tid in seen:
            problems.append(f"{tid}: id 重复")
        seen.add(tid)

        check = t.get("check") or {}
        kind = check.get("kind")
        if kind not in ("pytest", "command"):
            problems.append(f"{tid}: check.kind 仅支持 pytest/command（实为 {kind!r}）")
        elif kind == "pytest":
            files = [a for a in (check.get("args") or []) if str(a).endswith(".py")]
            if not files:
                problems.append(f"{tid}: pytest 类未给出测试文件路径")
            for f in files:
                if not (REPO / f).exists():
                    problems.append(f"{tid}: 关联测试不存在 {f}")
        else:
            if not check.get("cmd") or not check.get("expect_pattern"):
                problems.append(f"{tid}: command 类缺 cmd / expect_pattern")

        target_file = t.get("file")
        if target_file is not None:
            f = REPO / str(target_file)
            if not f.exists():
                problems.append(f"{tid}: 目标文件不存在 {target_file}")
            elif "locator" in t:
                text, _ = read_source(f)
                n = text.count(t["locator"])
                if n != 1:
                    problems.append(f"{tid}: locator 匹配 {n} 次（必须恰好 1 次，REA #154）")
            if "locator" in t and "mutation" in t and t["locator"] == t["mutation"]:
                problems.append(f"{tid}: locator 与 mutation 相同（注入后文本无变化）")
    return problems


def check_pytest(args: list[str]) -> tuple[int, str]:
    """跑关联测试，返回 (退出码, 末行摘要)。

    退出码语义必须区分：0=全绿、1=有用例失败、2=被中断、3=内部错误、
    4=用法错、5=一条都没收集。只有 1 才算"变异被抓到"。
    """
    r = run([sys.executable, "-m", "pytest", *args])
    tail = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
    return r.returncode, (tail[-1][-160:] if tail else "(无输出)")


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

    raw_before = path.read_bytes()
    original, crlf = read_source(path)
    count = original.count(target["locator"])
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
    result["original_sha256"] = hashlib.sha256(raw_before).hexdigest()
    result["original_text_sha256"] = sha256_text(original)
    result["line_ending"] = "CRLF" if crlf else "LF"

    if dry_run:
        result["ok"] = True
        result["steps"].append("dry-run：仅定位，未注入")
        return result

    check = target["check"]
    try:
        # ── 基线对照（未注入）：两类都必须先证明"改动前本来是对的" ──
        if check["kind"] == "command":
            ok, detail = check_command(check["cmd"], check["expect_pattern"], injected=False)
            if not ok:
                result["steps"].append(f"FAIL: 基线对照未过——{detail}（模式或命令有误，先修登记再探）")
                return result
            result["steps"].append(f"基线对照 ✓（{detail}）")
        else:
            rc, detail = check_pytest(check.get("args", []))
            result["baseline_rc"] = rc
            if rc != 0:
                result["steps"].append(
                    f"FAIL: 基线（未注入）退出码 {rc}——{detail}；"
                    "红基线下的『变异后仍红』不证明任何承重（先修关联测试再探）")
                return result
            result["steps"].append(f"基线（未注入）绿 ✓（{detail}）")

        mutated = original.replace(target["locator"], target["mutation"], 1)
        if mutated == original:
            result["steps"].append("FAIL: 注入后文本无变化（locator 与 mutation 相同？）")
            return result
        write_source(path, mutated, crlf)

        if check["kind"] == "pytest":
            rc, detail = check_pytest(check.get("args", []))
            result["mutated_rc"] = rc
            if rc == 1:
                ok = True
                verdict = f"变异后 {detail} ✓（守卫承重）"
            elif rc == 0:
                ok = False
                verdict = f"变异后仍绿 ✗（守卫不承重）— {detail}"
            else:
                ok = False
                verdict = (
                    f"变异后退出码 {rc}（不是『有用例失败』）✗ — {detail}；"
                    "按 fail-closed 记 FAIL（2=中断 / 3=内部错误 / 4=用法错 / 5=一条没收集）")
        else:
            ok, detail = check_command(check["cmd"], check["expect_pattern"], injected=True)
            verdict = f"变异后断言失效 ✓（守卫承重）— {detail}" if ok else f"变异后断言仍成立 ✗ — {detail}"
        result["steps"].append(verdict)
        result["ok"] = ok
    finally:
        write_source(path, original, crlf)
        restored, rcount = locate(path, target["locator"])
        if path.read_bytes() == raw_before and rcount == 1:
            result["steps"].append("原文恢复 ✓（逐字节一致，含行尾）")
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
