#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径数字对齐检查器 —— 以登记簿为真值源的**口径漂移体检**

用法：
    python scripts/pre-commit/caliber_check.py [--cached] [--strict] [文件列表...]
退出码：
    0 = 无「未豁免漂移」且（不加 --strict 时）真值缺失仅告警
    1 = ``--strict`` 下存在未豁免漂移，**或**无可用真值源，**或**有文件读不出文字

--------------------------------------------------------------------------------
历史与定位（2026-09-28 重写，勿删这段说明）
--------------------------------------------------------------------------------
本脚本原名「口径数字对齐检查器 — pre-commit 门禁」，但复查发现它三重失效：

1. **死门禁**：``.git/hooks/pre-commit`` 的 5 步（密钥/诚实口径/作废令牌/结构守卫/
   测试文件禁改）与 ``.github/workflows/ci.yml`` **都没有调用它** —— 它从未真正跑过。
2. **正则瞎**：旧式样 ``n\\s*=\\s*(\\d+)\\s*(?:seeds|samples|runs|episodes)``
   **匹配不到** ``n=22/组``、``n=22 种子`` 这类中文写法，而这正是本项目作废口径的
   实际书写形式。
3. **无真值源**：旧实现只是把每处像指标的数字打印一遍（连 ``(\\d+(\\.\\d+)?)\\s*%``
   这种泛匹配都在内），一旦改为 fail-closed 会把**每一次提交**全拦死 ——
   所以它当年只能 ``return 0  # 警告而非拦截``。这不是懒，是结构上无法收紧。

现在改为**高精度、可机验、真值驱动**的体检，只查两类能对上权威真值的口径族：

* **样本量族** ``n=NN 种子 / seeds / 组 / group`` → 必须等于登记簿的 n；
* **测试数族** ``NN passed`` → 必须等于登记簿 NR-19 的下限式表述。

百分比族**不在此处**查：它已由 ``scripts/scan_void_tokens.py`` 的作废令牌
（``29.2`` / ``0.126`` 等，含 ``needs_review`` 降级机制）覆盖，重复实现只会
制造两套口径。真值一律从**权威登记簿**读，不手抄、不落第二份。

--------------------------------------------------------------------------------
无真值 ≠ 无漂移（2026-11-06 修复，勿删）
--------------------------------------------------------------------------------
此前 ``--strict`` 只在「扫到了漂移」时才 exit 1，于是**读不到真值的时候一律判通过**。
四条实测路径全部 rc=0 且末行写着「✅ 口径体检通过（无未豁免漂移）」：

1. 登记簿被删/改名 —— 两个候选都不存在；
2. 登记簿 JSON 坏了（合并冲突、半截写入）—— ``load_registry`` 里 ``except: continue``
   静默跳过，最终退化成「未找到」；
3. 登记簿在，但抽不出任何样本量真值（``n_expected`` / ``declared.n*`` 全缺）——
   ``if not uni: continue`` 让样本量族**整族跳过**；
4. NR-19 缺失或没有可解析的下限 —— ``tests_floor is None`` 让测试数族整族跳过。

前两条是"门禁根本没法判定"，后两条是"只判定了一半"。四种情形输出里都有一行
``⚠️``，但**末行仍是 ✅、退出码仍是 0** —— 这正是本仓库反复清理的那类
「零断言通过」：告警不是阻断，读者只看末行与退出码。

现在把真值可用性做成**显式状态**：``truth_blockers()`` 返回阻塞项，``--strict``
下有阻塞项直接 exit 1，并明确写出「无真值 ≠ 无漂移」。不加 ``--strict``
（pre-commit 交互场景）仍只告警，避免把每次提交都拦死。

**格式覆盖也要是真的**：``DOC_EXT`` 一直声称支持 ``.docx / .pdf / .pptx``，但读取
走的是 ``read_text(encoding="utf-8", errors="ignore")`` —— 这三种是二进制容器，
读出来是压缩流的乱码，一个数字也匹配不到。即"宣称覆盖 6 类格式，其中 3 类
永远读不出字"。现在 ``.docx`` / ``.pptx`` 用标准库 ``zipfile`` 抽 ``word/document.xml``
与 ``ppt/slides/*.xml`` 的正文；``.pdf`` 依赖 ``pypdf``（缺失即判"未解析"）；
任何**读不出文字**的文件都进 ``unparsed``，``--strict`` 下一律 fail-closed——
没读过的文件不得计入"已通过"。

严重度：命中行若含「作废 / 历史快照 / 预警 / 旧口径 / 已被取代 …」等**口径豁免
标记**（与 ``scan_void_tokens`` 的 ``context_markers.mention`` 同源），
判为 ``[豁免]``，不计入 ``--strict`` 的失败。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from pathlib import Path

# --------------------------------------------------------------------------- #
# 真值源：权威登记簿（仓库外 deliverables/ 优先，仓库内镜像兜底）
# --------------------------------------------------------------------------- #
_REPO = Path(__file__).resolve().parents[2]
_WORKSPACE = _REPO.parent
REGISTRY_CANDIDATES = [
    _WORKSPACE / "deliverables" / "number_registry.json",   # 权威
    _REPO / "number_registry.json",                          # 入库镜像
]

#: 纯文本类：直接按 UTF-8 读。
TEXT_EXT = {".md", ".txt", ".html", ".htm"}
#: 容器类：正文在 zip 里的 XML，必须抽出来才可能有字（见 read_doc_text）。
OFFICE_EXT = {".docx", ".pptx"}
#: 检查的扩展名全集。代码里的数字是真值源，不检。
DOC_EXT = TEXT_EXT | OFFICE_EXT | {".pdf"}

#: 解码失败判据：替换符占比超过千分之一才判「读不出字」。
#: 实测依据（2026-11-06，仓库 41 篇文档）：替换符计数全为 0，故本判据不会误伤；
#: 取"占比"而非"出现即判"，是为了不因单个坏字节把整份文档判成未解析。
DECODE_BAD_RATIO = 0.001

#: 真值可用性的显式状态码（与 tests/test_caliber_check_truth_source.py 对齐）。
TRUTH_NO_REGISTRY = "no_registry"
TRUTH_REGISTRY_UNREADABLE = "registry_unreadable"
TRUTH_NO_SAMPLE = "no_sample_truth"
TRUTH_NO_TESTS = "no_tests_truth"

#: 样本量族：``n=71`` / ``n=22 种子`` / ``n=22/组`` / ``n=22 seeds/group``
_RE_SAMPLE = re.compile(
    r"n\s*=\s*(\d+)\s*(?:个)?\s*(?:种子|seeds?|组|groups?|samples?|runs?|episodes?|/"
    r"(?:组|group))", re.I)
#: 测试数族：``1624 passed`` / ``2,183 passed`` / ``1624 个测试通过``
#:
#: 2026-11-03 修复：原式是 `(\d{3,5})`，遇到**带千分位**的写法会从逗号后开始匹配 ——
#: `2,183 passed` 被读成 **183**，于是 README 那条明明等于下限的表述被判成「低于下限
#: 2183」的漂移（假红）。现同时接受 `1,234` 与 `1234` 两种写法，取值时去逗号。
_RE_TESTS = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d{3,5})\s*(?:passed|个测试通过|个测试用例全部通过|tests passed)",
    re.I)

#: 口径豁免标记（与 scan_void_tokens 的 mention 同源；此处内联一份常量，
#: 避免本体检脚本依赖 scanning 运行时，缺失配置时仍可独立工作）
EXEMPT_MARKERS = (
    "作废", "历史快照", "预警", "旧口径", "口径混用", "口径错误", "已被取代", "取代",
    "勘误", "已修正", "曾写作", "原写作", "早期", "当时口径", "小样本估计", "无出处",
    "不得声称", "不得宣称", "不得表述为", "不可表述为", "排除", "未使用", "禁用",
    "禁止", "应改为", "所谓", "待核", "待补", "溯源档", "作废值", "非全量", "推算",
)


def load_registry() -> tuple[dict, dict]:
    """读取登记簿，返回 ``(登记内容, 来源信息)``。

    来源信息 ``{"source": 命中路径或 None, "error": 解析错误或 ""}`` 必须带出去：
    此前"文件不存在"与"JSON 解析失败"都退化成空 dict，调用方无从区分
    「没有真值源」与「真值源坏了」，只能一律按"没找到，跳过判定"处理 ——
    而"跳过判定"在 ``--strict`` 下等价于通过。
    """
    info = {"source": None, "error": ""}
    for p in REGISTRY_CANDIDATES:
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # 损坏必须显式记账，不能 continue 掉了事
            info["error"] = f"{p.name}: {type(exc).__name__}: {exc}"
            continue
        info["source"] = str(p)
        return doc if isinstance(doc, dict) else {}, info
    return {}, info


def _entry(reg: dict, nid: str):
    ents = reg.get("entries", reg) if isinstance(reg, dict) else reg
    if isinstance(ents, dict):
        return ents.get(nid)
    for e in ents or []:
        if isinstance(e, dict) and e.get("id") == nid:
            return e
    return None


def _dig(obj, *keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def authoritative_facts(reg: dict) -> dict:
    """从登记簿抽出可机验真值。

    * ``n_universe``：**全部**条目的样本量取值集合 —— 本项目并行存在多种合法样本量
      （NR-1 收敛=71 / E1·E3=30 / 消融=10 / NR-29=60 …），所以"样本量"的合法判据
      **不是「等于 71」**，而是**「落在登记簿出现过的取值集合内」**：落在集合外即
      无出处口径（已作废的 n=22 正属此列）。
    * ``tests_floor``：NR-19 下限式表述的阈值（``claim`` 里的 ``1600+``）；低于它即漂移。
    """
    ents = reg.get("entries", reg) if isinstance(reg, dict) else reg
    if isinstance(ents, dict):
        ents = list(ents.values())
    ents = [e for e in (ents or []) if isinstance(e, dict)]

    ns: set = set()
    for e in ents:
        v = e.get("n_expected")
        if isinstance(v, int):
            ns.add(v)
        dec = e.get("declared")
        if isinstance(dec, dict):
            for k in ("n", "n_a", "n_b", "n_seeds", "seeds"):
                if isinstance(dec.get(k), int):
                    ns.add(dec[k])

    floor = None
    for e in ents:
        if e.get("id") == "NR-19":
            m = re.search(r"(\d{3,5})\s*\+", str(e.get("claim", "")))
            floor = int(m.group(1)) if m else _dig(e, "declared", "passed")
            break
    return {"n_universe": ns, "tests_floor": floor, "registry_found": bool(ents)}


def truth_blockers(facts: dict, info: dict | None = None) -> list:
    """真值可用性 → 阻塞项清单 ``[(状态码, 说明)]``。空清单 = 两族都判得了。

    "读到空"与"读到 0"必须分开（同 2026-11-06 ``verify_numbers.compare()`` 的修法）：
    真值侧读不到，就是**判不了**，不是**没问题**。
    """
    info = info or {}
    out: list = []
    if not facts.get("registry_found"):
        err = (info.get("error") or "").strip()
        if err:
            out.append((TRUTH_REGISTRY_UNREADABLE,
                        f"登记簿存在但无法解析（{err}）——真值源坏了不等于没有漂移"))
        else:
            tried = "、".join(str(p) for p in REGISTRY_CANDIDATES)
            out.append((TRUTH_NO_REGISTRY,
                        f"登记簿缺失（已找过：{tried}）——无真值可对，不得判通过"))
        return out
    if not facts.get("n_universe"):
        out.append((TRUTH_NO_SAMPLE,
                    "登记簿里抽不出任何样本量真值（n_expected / declared.n* 全缺）"
                    "——样本量族整族无法判定"))
    if facts.get("tests_floor") is None:
        out.append((TRUTH_NO_TESTS,
                    "登记簿 NR-19 缺失或没有可解析的测试数下限"
                    "——测试数族整族无法判定"))
    return out


def is_exempt(line: str) -> bool:
    return any(mk in line for mk in EXEMPT_MARKERS)


def scan_text(text: str) -> list:
    """返回 ``[(行号, 口径族, 值, 是否豁免, 原行)]``。"""
    out = []
    for idx, line in enumerate(text.splitlines(), start=1):
        for m in _RE_SAMPLE.finditer(line):
            out.append((idx, "sample_size", int(m.group(1)), is_exempt(line), line.strip()))
        for m in _RE_TESTS.finditer(line):
            out.append((idx, "tests", int(m.group(1).replace(",", "")), is_exempt(line), line.strip()))
    return out


def gather_files(args) -> list:
    if args.cached:
        import subprocess
        try:
            raw = subprocess.check_output(
                ["git", "diff", "--cached", "-z", "--name-only", "--diff-filter=ACM"],
                stderr=subprocess.DEVNULL)
            names = [f for f in raw.decode("utf-8", "replace").split("\x00") if f]
        except Exception:
            names = []
        files = [Path(x) for x in names]
    elif args.files:
        files = [Path(x) for x in args.files]
    else:
        files = [p for p in Path(".").rglob("*") if p.is_file()]
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
            ".mpl_cache", ".pytest_cache", "backup"}
    return [f for f in files
            if f.suffix.lower() in DOC_EXT and not (skip & set(f.parts))]


# --------------------------------------------------------------------------- #
# 取文：不同格式拿字的方式不同；拿不到字就必须明说
# --------------------------------------------------------------------------- #
#: XML 段落边界 → 换行（先于去标签执行，避免把两段焊成一行）
_XML_BLOCK_END = re.compile(r"</w:p>|</a:p>|<w:br\s*/>|<w:cr\s*/>|<a:br\s*/>", re.I)
_XML_TAG = re.compile(r"<[^>]+>")


def _xml_to_text(raw: bytes) -> str:
    """去标签取正文。段尾转换行；标签之间不插分隔符（被拆成多个 run 的数字要能接回）。"""
    text = raw.decode("utf-8", "replace")
    text = _XML_BLOCK_END.sub("\n", text)
    text = _XML_TAG.sub("", text)
    return html.unescape(text)


def _docx_text(path: Path) -> str:
    """``.docx`` 正文在 ``word/document.xml``（页眉/脚注不取，已知边界）。"""
    with zipfile.ZipFile(path) as zf:
        return _xml_to_text(zf.read("word/document.xml"))


def _pptx_text(path: Path) -> str:
    """``.pptx`` 逐页取 ``ppt/slides/slideN.xml``，按页号排序。"""
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist()
                 if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        names.sort(key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n".join(_xml_to_text(zf.read(n)) for n in names)


def _pdf_text(path: Path) -> str:
    """``.pdf`` 需要真正的解析器；装了 pypdf 才读得动。"""
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # noqa: BLE001 —— 缺依赖也是"读不出"
        raise RuntimeError(f"pdf_no_parser（pip install pypdf 后可读）：{exc}") from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def read_doc_text(path: Path) -> tuple[str | None, str]:
    """返回 ``(正文, 读不出的原因)``；读得出时原因为空串。

    **读不出 ≠ 没有数字**：调用方必须把 ``None`` 计入「未解析」并 fail-closed，
    否则格式覆盖就只是扩展名列表上的一句空话。
    """
    suffix = path.suffix.lower()
    if suffix in OFFICE_EXT:
        reader = _docx_text if suffix == ".docx" else _pptx_text
        try:
            return reader(path), ""
        except Exception as exc:  # noqa: BLE001
            return None, f"{suffix[1:]}_unreadable: {type(exc).__name__}: {exc}"
    if suffix == ".pdf":
        try:
            return _pdf_text(path), ""
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)[:160]
    try:
        text = path.read_bytes().decode("utf-8", "replace")
    except OSError as exc:
        return None, f"unreadable: {exc}"
    bad = text.count("\ufffd")
    if bad and bad >= DECODE_BAD_RATIO * max(len(text), 1):
        return None, (f"decode_failed: {bad}/{len(text)} 个替换符"
                      "（文件不是 UTF-8？转码后重跑）")
    return text, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="口径漂移体检（登记簿驱动）")
    ap.add_argument("--cached", action="store_true", help="只检查 git 暂存区文件")
    ap.add_argument("--strict", action="store_true",
                    help="存在未豁免漂移 / 无可用真值源 / 有文件读不出文字时 exit 1"
                         "（默认仅警示，不阻断）")
    ap.add_argument("files", nargs="*", help="指定文件列表")
    args = ap.parse_args(argv)

    reg, info = load_registry()
    facts = authoritative_facts(reg)
    blockers = truth_blockers(facts, info)

    if blockers:
        for code, detail in blockers:
            print(f"⚠️ [无真值 {code}] {detail}")
        if args.strict:
            print("❌ --strict：门禁没有可用的真值源，拒绝判通过"
                  "（无真值 ≠ 无漂移；修好登记簿或去掉 --strict 再看告警）")
            return 1
        print("   （未加 --strict：本次仅告警，不阻断）")
    else:
        print(f"真值源：登记簿（合法样本量集合={sorted(facts['n_universe'])}，"
              f"测试数下限={facts['tests_floor']}）")

    drift, exempt, unparsed = [], [], []
    scanned = 0
    for f in gather_files(args):
        text, reason = read_doc_text(f)
        if text is None:
            unparsed.append((f, reason))
            continue
        scanned += 1
        for lineno, family, value, ex, line in scan_text(text):
            if family == "sample_size":
                uni = facts["n_universe"]
                if not uni or value in uni:
                    continue
                shown = f"不在登记簿合法集合 {sorted(uni)} 内"
            else:
                floor = facts["tests_floor"]
                if floor is None or value >= floor:
                    continue
                shown = f"低于下限 {floor}"
            (exempt if ex else drift).append((f, lineno, family, value, shown, line[:120]))

    for f, lineno, family, value, auth, line in exempt:
        print(f"[豁免] {f}:{lineno}: {family}={value}（真值 {auth}） — {line}")
    for f, lineno, family, value, auth, line in drift:
        print(f"[漂移] {f}:{lineno}: {family}={value} ≠ 真值 {auth} — {line}")
    for f, reason in unparsed:
        print(f"[未解析] {f} — {reason}")

    print(f"\n合计：扫描 {scanned} 篇文档，未豁免漂移 {len(drift)} 条，"
          f"已豁免 {len(exempt)} 条，未解析 {len(unparsed)} 篇")

    if unparsed and args.strict:
        print(f"❌ --strict：{len(unparsed)} 篇文档读不出文字，其数字一个都没被检查——"
              "没读过的文件不得计入『已通过』")
        return 1
    if drift and args.strict:
        print("❌ --strict：存在未豁免口径漂移")
        return 1
    if scanned == 0 and args.strict:
        # 全仓模式下一篇都没扫到 = 选择器/扩展名坏了，不是"没问题"
        print("❌ --strict：一篇文档都没扫到（扩展名选择器可能已失效）——"
              "空扫描不得判通过")
        return 1
    if drift:
        print("⚠️ 存在未豁免口径漂移（默认不阻断；如需阻断请加 --strict，"
              "或为该行补口径豁免标记）")
    elif unparsed:
        print("⚠️ 有文档读不出文字（默认不阻断；--strict 下会阻断）")
    else:
        print("✅ 口径体检通过（无未豁免漂移）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
