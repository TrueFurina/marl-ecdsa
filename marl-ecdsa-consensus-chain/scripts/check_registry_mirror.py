#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""number_registry 镜像一致性守门器（F2 修复件）。

## 背景

数字口径的"唯一权威源"在真实仓库里存在 **三处互相矛盾的地址声明**：

  - 代码实际读的那份：``assurance_common.REGISTRY_PATH``
    = ``<工作区>/deliverables/number_registry.json``（工作区根，**不进版本库**）
  - 仓库内已入库的同名副本：``<仓库根>/number_registry.json``（**只读镜像**）
  - 文档里的引用：上面两者都出现过，都自称"唯一权威源"

两份内容今天字节相同纯属**人工同步**的结果，没有任何机制阻止漂移。
而"改了不生效"是历史上真实发生过的事故形态（改登记表却没改代码读的那份）。

## 本脚本的判定

1. **权威源缺失**（CI / 全新克隆的常态）→ 打印 ``SKIP``，并做**镜像自身完整性校验**：
   结构（键齐 / id 唯一 / entries 非空）+ ``_mirror_sha256`` 与镜像实体内容指纹自洽。
   退出码 0。**不静默通过**：SKIP 的原因必须出现在输出里。
2. **权威源存在**：
   a. 断言镜像里记录的 ``_mirror_sha256`` == 权威文件当前内容指纹 —— 抓"权威改了、镜像没同步"；
   b. 断言镜像的实体内容（排除 ``_mirror*`` 元数据键）== 权威内容 —— 抓"镜像被手改"。
   任一不成立 → 打印差异条目 id 与两侧哈希 → 退出码 1。

2026-11-08 修的假绿（实测复现，见 CHANGELOG）：CI 里权威源必然缺失，于是
``structural_check()`` 是**唯一生效的检查**，而它只查「有没有这些键」。实测把镜像
换成 ``{"entries": []}``、3 条假条目、把真实镜像改一个数字、删掉一条、删掉
``_mirror_sha256`` —— 五种都打印「[ok] 结构校验通过」并 ``exit 0``。
现在补上**不需要权威源就能算**的自洽校验：
``entity_fingerprint(strip_mirror(镜像)) == 镜像._mirror_sha256``。

退出码：0 通过；1 不一致 / 结构不合格；2 数据读不出（JSON 损坏 / 顶层非对象）。

## 用法

    python -X utf8 scripts/check_registry_mirror.py              # 检查，不一致则 exit 1
    python -X utf8 scripts/check_registry_mirror.py --quiet      # 只在失败时输出
    python -X utf8 scripts/check_registry_mirror.py --sync       # 权威 → 镜像（幂等，含元数据）
    python -X utf8 scripts/check_registry_mirror.py --registry <path>   # 覆盖权威源路径
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402

MIRROR_KEYS = ("_mirror_of", "_mirror_note", "_mirror_sha256", "_mirror_generated_by")
EXIT_OK, EXIT_FAIL, EXIT_DATA_ERROR = 0, 1, 2
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{16}$")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def strip_mirror(obj):
    """去掉镜像元数据键，得到可与权威逐键比较的实体。"""
    return {k: v for k, v in obj.items() if k not in MIRROR_KEYS}


#: 指纹长度（十六进制字符数）。**不要加长到 40 及以上**：pre-commit 的
#: ``scripts/pre-commit/secrets_scan.py`` 有一条 ``[0-9a-zA-Z/+]{40}``（AWS Secret Key）
#: 规则，任何 ≥40 位的连续十六进制串都会被判为「疑似密钥」而拦死提交
#: （实测：首版用完整 64 位 sha256 即被 [1/4] 密钥扫描拦下）。
#: 16 hex = 64 bit，对「检测内容是否改动」已足够（碰撞概率可忽略）。
FINGERPRINT_LEN = 16


def entity_fingerprint(doc) -> str:
    """权威**内容**的规范化指纹（排序键 / 紧凑分隔 / 不含 ``_mirror*``）。

    刻意不用文件字节哈希：字节会随行尾（LF↔CRLF）与缩进变化而变化，
    而 ``core.autocrlf`` 在不同机器上取值不同 → 字节哈希会让 ``--check``
    在换机后误报「权威改了」。用规范化 JSON 实体则跨平台稳定，
    且仍然精确反映**内容**是否改动。

    返回 ``sha256:<16hex>``；长度上限受 ``FINGERPRINT_LEN`` 约束（原因见该常量）。
    """
    canon = json.dumps(strip_mirror(doc), sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]
    return f"sha256:{h}"


def entity_diff_ids(a_doc, b_doc):
    """返回 (仅存在于 a 的 id, 仅存在于 b 的 id, 两侧 declared 不同的 id)。"""
    a = {e.get("id"): e for e in a_doc.get("entries", [])}
    b = {e.get("id"): e for e in b_doc.get("entries", [])}
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = []
    for i in sorted(set(a) & set(b)):
        if json.dumps(a[i], sort_keys=True, ensure_ascii=False) != \
           json.dumps(b[i], sort_keys=True, ensure_ascii=False):
            changed.append(i)
    return only_a, only_b, changed


def structural_check(doc, label, quiet=False):
    """镜像自身的结构校验（CI 里权威缺失时可做的检查之一）。

    ``quiet=True`` 只收集问题不打印，供 ``integrity_check()`` 汇总后统一输出。
    """
    problems = []
    if not isinstance(doc, dict):
        problems.append("顶层不是对象")
        return problems
    ents = doc.get("entries")
    if not isinstance(ents, list):
        problems.append("缺少 entries 数组")
        return problems
    ids = []
    for i, e in enumerate(ents):
        if not isinstance(e, dict):
            problems.append(f"entries[{i}] 不是对象")
            continue
        nid = e.get("id")
        if not nid:
            problems.append(f"entries[{i}] 缺 id")
        else:
            ids.append(nid)
        if "declared" not in e:
            problems.append(f"{nid or i} 缺 declared")
        if "analysis" not in e:
            problems.append(f"{nid or i} 缺 analysis")
        if e.get("analysis") not in (None, "pytest") and "sources" not in e and "source" not in e \
                and not (e.get("analysis") in ("consensus_row", "consensus_rows") and "consensus_file" in e):
            problems.append(f"{nid or i} 缺 sources（analysis={e.get('analysis')}）")
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        problems.append(f"重复 id: {dupes}")
    if problems:
        if not quiet:
            print(f"[FAIL] {label} 结构校验未通过（{len(problems)} 项）:")
            for p in problems[:20]:
                print(f"        - {p}")
    elif not quiet:
        print(f"[ok ] {label} 结构校验通过（{len(ents)} 条目，id 无重复，declared/analysis/sources 齐备）")
    return problems


def load_json_document(path: Path):
    """读一份 JSON 文档，返回 ``(doc, error)``；读不懂/不是对象都是**错误**而非空表。

    旧实现直接 ``json.loads(path.read_text(encoding='utf-8'))``：损坏 JSON 与
    UTF-16 文档都会抛 traceback（无诊断），顶层非对象还会让后面 ``.get()`` 再炸一次。
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"读不出（{exc.__class__.__name__}: {exc}）"
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", "replace")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", "replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                return None, "utf-8 与 gbk 均解不开"
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return None, f"JSON 解析失败：{exc}"
    if not isinstance(doc, dict):
        return None, f"顶层不是对象（{type(doc).__name__}）"
    return doc, ""


def self_consistent_problems(doc):
    """不需要权威源在场就能判的镜像自洽性（条目数 + 元数据 + 实体指纹）。"""
    problems = []
    ents = doc.get("entries") if isinstance(doc.get("entries"), list) else []
    if not ents:
        problems.append("entries 为空 —— 空表不等于结构合格")
    recorded = doc.get("_mirror_sha256") if isinstance(doc, dict) else None
    if recorded is None:
        problems.append("缺少 _mirror_sha256 —— 无法证明镜像实体未被手改")
    elif not isinstance(recorded, str) or not _FINGERPRINT_RE.fullmatch(recorded):
        problems.append(f"_mirror_sha256 格式非法：{recorded!r}")
    else:
        actual = entity_fingerprint(doc)
        if recorded != actual:
            problems.append(f"镜像实体指纹与 _mirror_sha256 不符（记录 {recorded} / 实算 {actual}）"
                            " —— 镜像内容被手改或已过期")
    return problems


def integrity_check(doc, label):
    """权威源缺失时也要能做的完整性校验：结构 + 自洽。

    关键：``_mirror_sha256`` 是 ``--sync`` 时按**权威实体内容**算出来的，而镜像实体
    又是权威的字节级副本，所以 ``entity_fingerprint(strip_mirror(mir))`` 必须等于它。
    这个判据不需要权威源在场，却能抓住任何对镜像实体的手改（改数字 / 删条目 / 清空）。
    """
    problems = list(structural_check(doc, label, quiet=True))
    problems.extend(self_consistent_problems(doc))
    if problems:
        print(f"[FAIL] {label} 完整性校验未通过（{len(problems)} 项）:")
        for p in problems[:20]:
            print(f"        - {p}")
    else:
        n = len(doc.get("entries", []))
        print(f"[ok ] {label} 完整性校验通过（{n} 条目，指纹自洽 {doc.get('_mirror_sha256')}）")
    return problems


def sync_mirror(mir_path: Path, auth_path: Path, auth_entity_sha: str) -> int:
    """把权威源写为镜像：**直接复制权威字节，再插入 4 行元数据**。

    记录的是**内容**规范化哈希（``entity_sha256``）而非文件字节哈希，理由见该函数。

    为什么不用 ``json.dump`` 重序列化：那会因为 ``indent`` / 行尾差异产生数千行
    噪声 diff（实测 3943+/3939-），既无法人工审查，也把真正的改动淹没掉。
    这里改为字节级复制 + 定点插入，镜像的**实体与权威逐字节相同**，
    diff 恒为 4 行，且缩进/行尾自动继承权威文件。

    返回插入的元数据行数。
    """
    meta = [
        ("_mirror_of", "deliverables/number_registry.json"),
        ("_mirror_note",
         "只读镜像，供版本库内离线查阅与文档引用。**唯一权威源在工作区 deliverables/"
         "number_registry.json**（代码经 assurance_common.REGISTRY_PATH 读取该份）。"
         "由 scripts/check_registry_mirror.py --sync 生成，勿手改。"),
        ("_mirror_sha256", auth_entity_sha),
        ("_mirror_generated_by", "scripts/check_registry_mirror.py --sync"),
    ]
    data = auth_path.read_bytes()
    try:
        nl = data.index(b"\n")                  # 第一个换行 = 顶层 "{" 行之后
    except ValueError as exc:
        raise ValueError("权威源是单行 JSON，无法定点插入元数据；请先格式化为多行") from exc
    head, rest = data[:nl + 1], data[nl + 1:]
    stripped = rest.lstrip(b" \t")
    indent = rest[:len(rest) - len(stripped)]   # 继承权威文件的缩进
    eol = b"\n"
    block = b"".join(
        indent + json.dumps(k, ensure_ascii=False).encode("utf-8") + b": "
        + json.dumps(v, ensure_ascii=False).encode("utf-8") + b"," + eol
        for k, v in meta
    )
    mir_path.write_bytes(head + block + rest)
    return len(meta)


def run_self_test(verbose: bool = True) -> int:
    """临时目录现造镜像样本，证明「只查键」的旧校验确实被补上了。"""
    import copy
    import subprocess
    import tempfile

    failures = []
    passed = 0

    def ck(name, ok, detail=""):
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<32} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<32} → FAIL {detail}")

    def legal_doc():
        d = {"entries": [{"id": f"NR-{i}", "declared": {"value": i},
                          "analysis": "pytest", "sources": []} for i in range(3)]}
        d["_mirror_sha256"] = entity_fingerprint(d)
        return d

    with tempfile.TemporaryDirectory(prefix="mirror_selftest_") as td:
        root = Path(td)
        legal = legal_doc()
        ck("legal_mirror_clean",
           structural_check(legal, "夹具", quiet=True) == [] and not self_consistent_problems(legal))

        empty = {"entries": []}
        empty["_mirror_sha256"] = entity_fingerprint(empty)
        ck("empty_entries_blocked",
           any("entries 为空" in p for p in self_consistent_problems(empty)))

        tampered = copy.deepcopy(legal)
        tampered["entries"][0]["declared"] = {"value": 999999}
        ck("tampered_value_blocked",
           any("指纹与 _mirror_sha256 不符" in p for p in self_consistent_problems(tampered)))

        removed = copy.deepcopy(legal)
        removed["entries"].pop(0)
        ck("removed_entry_blocked",
           any("指纹与 _mirror_sha256 不符" in p for p in self_consistent_problems(removed)))

        nometa = copy.deepcopy(legal)
        nometa.pop("_mirror_sha256")
        ck("missing_meta_blocked",
           any("缺少 _mirror_sha256" in p for p in self_consistent_problems(nometa)))

        badfmt = copy.deepcopy(legal)
        badfmt["_mirror_sha256"] = "not-a-fingerprint"
        ck("bad_meta_format_blocked",
           any("格式非法" in p for p in self_consistent_problems(badfmt)))

        fake = {"entries": [{"id": "NR-X", "declared": {}, "analysis": "pytest", "sources": []}]}
        ck("fake_entries_pass_structure",
           structural_check(fake, "夹具", quiet=True) == [])
        ck("fake_entries_fail_integrity",
           bool(integrity_check(fake, "夹具")))

        broken = root / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        _, e1 = load_json_document(broken)
        ck("broken_json_has_error", bool(e1), e1 or "")

        listed = root / "list.json"
        listed.write_text("[1, 2]", encoding="utf-8")
        _, e2 = load_json_document(listed)
        ck("non_object_has_error", bool(e2), e2 or "")

        u16 = root / "u16.json"
        u16.write_bytes(json.dumps(legal, ensure_ascii=False).encode("utf-16"))
        d16, e3 = load_json_document(u16)
        ck("utf16_bom_decoded", not e3 and isinstance(d16, dict), e3 or "ok")

        # 端到端：CI 常态（权威缺失）下，篡改镜像必须 rc=1，合法镜像 rc=0
        def cli(mir: Path) -> int:
            r = subprocess.run(
                [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                 "--registry", str(root / "NO_SUCH_AUTHORITY.json"),
                 "--mirror", str(mir)], capture_output=True)
            return r.returncode

        good_p = root / "good_mirror.json"
        good_p.write_text(json.dumps(legal, ensure_ascii=False, indent=1), encoding="utf-8")
        ck("cli_legal_passes", cli(good_p) == EXIT_OK)
        bad_p = root / "bad_mirror.json"
        bad_p.write_text(json.dumps(tampered, ensure_ascii=False, indent=1), encoding="utf-8")
        ck("cli_tampered_fails", cli(bad_p) == EXIT_FAIL)

    total = passed + len(failures)
    if failures:
        for item in failures:
            print(f"❌ [自证失败] {item}")
        print(f"❌ 自证失败 {len(failures)}/{total} 项")
        return 1
    print(f"✅ 自证通过 {passed}/{total}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=None, help="权威源路径（默认 assurance_common.REGISTRY_PATH）")
    ap.add_argument("--mirror", default=None, help="镜像路径（默认 <仓库根>/number_registry.json）")
    ap.add_argument("--sync", action="store_true", help="把权威源写入镜像（含 _mirror* 元数据）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--self-test", action="store_true", help="内置夹具自证")
    args = ap.parse_args()

    if args.self_test:
        return run_self_test()

    auth_path = Path(args.registry) if args.registry else ac.REGISTRY_PATH
    mir_path = Path(args.mirror) if args.mirror else (ac.REPO_ROOT / "number_registry.json")

    def say(*a):
        if not args.quiet:
            print(*a)

    say(f"权威源 : {ac.rel_to_workspace(auth_path)}")
    say(f"镜像   : {ac.rel_to_workspace(mir_path)}")

    # --- 镜像必须存在（它是入库产物）---
    if not mir_path.exists():
        print("[FAIL] 仓库内镜像不存在——文档引用它，但它不在版本库里。")
        return EXIT_FAIL

    mir_doc, mir_err = load_json_document(mir_path)
    if mir_err:
        print(f"[FAIL] 镜像读不出：{mir_err}")
        return EXIT_DATA_ERROR
    say(f"镜像哈希: {sha256_file(mir_path)[:16]}…")

    # --- 权威缺失：CI / 全新克隆的常态 ---
    if not auth_path.exists():
        say("")
        say("[SKIP] 权威源不存在（CI / 全新克隆属正常情形）——跳过一致性比对。")
        say("       注意：这**不代表**镜像已与权威对齐；本地开发机请务必跑一次本脚本。")
        say("       同时，镜像中登记的数字在 CI 里**无法复算**（results/ 数据 3.2 GB 不入库）。")
        say("       但镜像实体指纹与 _mirror_sha256 的自洽性**可以**核对，下面照做。")
        say("")
        problems = integrity_check(mir_doc, "镜像")
        return EXIT_FAIL if problems else EXIT_OK

    auth_doc, auth_err = load_json_document(auth_path)
    if auth_err:
        print(f"[FAIL] 权威源读不出：{auth_err}")
        return EXIT_DATA_ERROR
    auth_sha = sha256_file(auth_path)          # 文件字节哈希（仅作诊断输出）
    auth_eid = entity_fingerprint(auth_doc)    # 内容指纹（记录 / 比对用，跨平台稳定）
    say(f"权威字节哈希 {auth_sha[:16]}…  内容指纹 {auth_eid}")

    # --- 同步模式 ---
    if args.sync:
        aproblems = structural_check(auth_doc, "权威源")
        if aproblems:
            print("[FAIL] 权威源结构不合格，拒绝同步（避免把坏数据写进版本库）。")
            return EXIT_FAIL
        try:
            n = sync_mirror(mir_path, auth_path, auth_eid)
        except ValueError as exc:
            print(f"[FAIL] 同步失败：{exc}")
            return EXIT_DATA_ERROR
        say(f"[sync] 已写入镜像（插入 {n} 行元数据；实体逐字节同权威），"
            f"内容指纹 = {auth_eid}")
        return EXIT_OK

    # --- 一致性比对 ---
    recorded = mir_doc.get("_mirror_sha256")
    ok = True

    # 自洽性不依赖权威源，任何情况下都先核一遍
    extra = self_consistent_problems(mir_doc)
    if extra:
        print("[FAIL] 镜像自身完整性未通过：")
        for p in extra:
            print(f"        - {p}")
        ok = False

    if recorded is None:
        print("[FAIL] 镜像缺少 _mirror_sha256 记录 —— 无法证明它与权威源同源。")
        print("       修法：python -X utf8 scripts/check_registry_mirror.py --sync")
        ok = False
    elif recorded != auth_eid:
        print("[FAIL] 镜像记录的 _mirror_sha256 与权威源当前内容指纹不符 —— 权威改了、镜像未同步。")
        print(f"       记录值 {recorded}  实际值 {auth_eid}")
        print("       修法：python -X utf8 scripts/check_registry_mirror.py --sync")
        ok = False

    only_a, only_b, changed = entity_diff_ids(auth_doc, strip_mirror(mir_doc))
    if only_a or only_b or changed:
        print("[FAIL] 镜像实体内容与权威源不一致：")
        if only_a:
            print(f"       权威有、镜像无: {only_a}")
        if only_b:
            print(f"       镜像有、权威无: {only_b}")
        if changed:
            print(f"       同 id 但内容不同: {changed}")
        ok = False

    if ok:
        n = len(auth_doc.get("entries", []))
        print(f"[ok ] 镜像与权威源一致（{n} 条目，内容指纹 {auth_eid}）")
        return EXIT_OK
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
