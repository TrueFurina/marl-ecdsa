"""提交包一键终验（final_check）—— 固化 2026-10-18 手工终检流程

用法:
    python scripts/final_check.py            # 全部检查
    python scripts/final_check.py --quick    # 跳过 SHA 抽验（快）

检查项（全部来自当日踩坑，勿删）:
  C1  documents/ 七份 docx 存在且可解析
  C2  问答库 docx 关键字（前沿对照节/题数/口径引用）
  C3  other/测试数据 目录齐备性（E35~E40 必须在）
  C4  测试数据总体积 ≤ 1G（官方 other.zip 限制）
  C5  SHA256SUMS 存在且抽验 3 条
  C6  verify 口径引用一致性：最新 verify 报告 vs 问答库节头数字
  C7  遗留结构提醒（06_ 等分栏目录、旧 PDF）
  C8  实验证据闭合（other/测试数据：截断/零填充/退化/无证据不算通过）
退出码：有任何 ❌ 即 1（fail-closed）。--strict-closure 把 unknown 也升级为 ❌。
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parents[2]          # 项目根
PKG = WS / "MARL-ECDSA_共识链_提交包"
FAILS = []
WARNS = []


def check(name, ok, detail=""):
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def warn(name, detail=""):
    print(f"  ⚠️ {name}" + (f" — {detail}" if detail else ""))
    WARNS.append(name)


def docx_text(p):
    z = zipfile.ZipFile(p)
    return re.sub(r"<[^>]+>", "", z.read("word/document.xml").decode("utf-8", "replace"))


def main():
    quick = "--quick" in sys.argv
    print("=" * 78)
    print("  提交包一键终验（final_check）")
    print("=" * 78)

    # C1 documents/ docx
    print("\n[C1] documents/ docx 清单")
    docs = sorted(glob.glob(str(PKG / "documents" / "*.docx")))
    check("docx 数量 ≥ 7", len(docs) >= 7, f"实际 {len(docs)}")
    for p in docs:
        try:
            docx_text(p)
        except Exception as e:
            check(f"  解析 {os.path.basename(p)[:16]}", False, str(e)[:60])

    # C2 问答库关键字
    print("\n[C2] 问答库关键字")
    qa = PKG / "documents" / "答辩问答库+MARL-ECDSA共识链——面向协作多智能体的可信共识与激励机制.docx"
    if qa.exists():
        t = docx_text(qa)
        for kw in ["Q57-Q61", "Q61: DART、TNSE 2026", "前沿对照类"]:
            check(f"  含「{kw[:24]}」", kw in t)
    else:
        check("问答库 docx 存在", False)

    # C3/C4 测试数据
    print("\n[C3] other/测试数据 目录齐备性")
    td = PKG / "other" / "测试数据"
    need = ["e35_lambda_sensitivity", "e36_lambda_3000ep", "e37_lambda_fine",
            "e38_lambda_extend", "e40_adaptive_lambda", "e31_main_n101",
            "e18_scale_w5x5", "e20_qmix_w5x5", "consensus_comparison"]
    for d in need:
        p = td / d
        n = len(glob.glob(str(p / "*.json"))) if p.is_dir() else 0
        check(f"  {d} ≥ 1 json", n > 0, f"{n}")

    print("\n[C4] 测试数据体积")
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(td) for f in fs) if td.is_dir() else 0
    check("体积 ≤ 1G", total < 1024 ** 3, f"{total / 1024 / 1024:.1f} MB")

    # C5 SHA
    print("\n[C5] SHA256SUMS")
    sha_p = PKG / "source_code" / "SHA256SUMS.txt"
    if not sha_p.exists():
        check("SHA256SUMS 存在", False)
    else:
        lines = [l for l in sha_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        check("条数 ≥ 400", len(lines) >= 400, f"{len(lines)}")
        if not quick:
            ok_cnt = 0
            for line in lines[:3]:
                h, f = line.split("  ", 1)
                fp = sha_p.parent / f
                ok = fp.exists() and hashlib.sha256(fp.read_bytes()).hexdigest() == h
                ok_cnt += ok
            check("抽验 3 条", ok_cnt == 3)
        else:
            warn("SHA 抽验已跳过（--quick）")

    # C6 verify 口径引用一致性
    print("\n[C6] verify 口径引用一致性")
    reports = sorted(glob.glob(str(WS / "deliverables" / "assurance" / "reports" /
                                 "number_verification_report_*.md")))
    latest = None
    for r in reversed(reports):
        m = re.search(r"total=(\d+) PASS=(\d+) FAIL=(\d+)", Path(r).read_text(encoding="utf-8"))
        if m:
            latest = (int(m.group(1)), int(m.group(2)), int(m.group(3)), r)
            break
    if latest is None:
        warn("未找到 verify 报告（跳过口径比对）")
    else:
        tot, pas, fail, rpath = latest
        print(f"  最新 verify: total={tot} PASS={pas} FAIL={fail}（{Path(rpath).name[-24:]}）")
        if fail != 0:
            check("verify FAIL=0", False, f"FAIL={fail}")
        if qa.exists():
            t = docx_text(qa)
            m = re.search(r"total=(\d+) / PASS=(\d+)", t)
            if m:
                cited = (int(m.group(1)), int(m.group(2)))
                check("问答库节头口径与最新 verify 一致",
                      cited == (tot, pas), f"docx 引用 {cited} vs 最新 ({tot},{pas})")
            else:
                warn("问答库节头无 verify 口径引用")
        stale = []
        for p in docs:
            if "答辩问答库" in p:
                continue
            t = docx_text(p)
            if re.search(r"total=\d+ / PASS=\d+", t):
                stale.append(os.path.basename(p)[:14])
        if stale:
            warn(f"其他 docx 也含 verify 口径引用（检查是否过时）: {stale}")

    # C7 遗留结构
    print("\n[C7] 遗留结构提醒")
    for d in sorted(glob.glob(str(PKG / "0[0-9]_*"))):
        warn(f"分栏目录残留（09-30 已定案 documents.zip 唯一方案）: {os.path.basename(d)}")
    for p in glob.glob(str(PKG / "**" / "*.pdf"), recursive=True):
        warn(f"PDF 残留（PDF 已弃用，待拍板清理）: {os.path.relpath(p, PKG)}")

    # C8 实验证据闭合（2026-10-18 新增）
    # 动因：verify_numbers 只管"声明值算得对不对"，不管"没跑完的算不算通过"。
    # 评审拿到的 other/测试数据 里若有"声明 3000 回合但无逐回合记录"的文件，
    # 任何一次复核都会问同一个问题，而仓库原先没有任何自动化答案。
    print("\n[C8] 实验证据闭合（other/测试数据）")
    gate = Path(__file__).resolve().parents[1] / "scripts" / "check_evidence_closure.py"
    strict_closure = "--strict-closure" in sys.argv
    if not gate.exists():
        check("闭合门禁脚本存在", False, str(gate))
    elif not td.is_dir():
        warn("测试数据目录缺失，跳过闭合检查")
    else:
        ledger_path = Path(tempfile.mkdtemp(prefix="closure_")) / "ledger.json"
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(gate), "--root", str(td),
             "--limit", "0", "--json-out", str(ledger_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=900,
        )
        if not ledger_path.exists():
            check("闭合门禁产出 ledger", False, (proc.stderr or proc.stdout or "")[-200:])
        else:
            agg = json.loads(ledger_path.read_text(encoding="utf-8"))["aggregation"]
            stats = agg["summary"]
            check("无截断（truncated=0）", stats["truncated"] == 0, str(stats["truncated"]))
            check("无零填充（fail=0）", stats["fail"] == 0, str(stats["fail"]))
            if stats["unknown"]:
                if strict_closure:
                    check("无不可核对项（unknown=0）", False, str(stats["unknown"]))
                else:
                    warn(f"不可核对项 unknown={stats['unknown']}"
                         f"（加 --strict-closure 可升级为失败）")
            print(f"     适用样本 {agg['applicable']} / 不适用 {stats['not_applicable']}")

    # 汇总
    print("\n" + "=" * 78)
    print(f"  结论: {'✅ 全部通过' if not FAILS else '❌ ' + str(len(FAILS)) + ' 项失败'}"
          f" | 警告 {len(WARNS)} 项")
    print("=" * 78)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
