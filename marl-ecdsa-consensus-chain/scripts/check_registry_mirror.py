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

1. **权威源缺失**（CI / 全新克隆的常态）→ 打印 ``SKIP`` 并**只做镜像自身的结构校验**，
   退出码 0。**不静默通过**：SKIP 的原因必须出现在输出里。
2. **权威源存在**：
   a. 断言镜像里记录的 ``_mirror_sha256`` == 权威文件当前 sha256 —— 抓"权威改了、镜像没同步"；
   b. 断言镜像的实体内容（排除 ``_mirror*`` 元数据键）== 权威内容 —— 抓"镜像被手改"。
   任一不成立 → 打印差异条目 id 与两侧哈希 → 退出码 1。

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
import sys
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402

MIRROR_KEYS = ("_mirror_of", "_mirror_note", "_mirror_sha256", "_mirror_generated_by")


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


def structural_check(doc, label):
    """镜像自身的结构校验（CI 里权威缺失时唯一可做的检查）。"""
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
        print(f"[FAIL] {label} 结构校验未通过（{len(problems)} 项）:")
        for p in problems[:20]:
            print(f"        - {p}")
    else:
        print(f"[ok ] {label} 结构校验通过（{len(ents)} 条目，id 无重复，declared/analysis/sources 齐备）")
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
    nl = data.index(b"\n")                      # 第一个换行 = 顶层 "{" 行之后
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=None, help="权威源路径（默认 assurance_common.REGISTRY_PATH）")
    ap.add_argument("--mirror", default=None, help="镜像路径（默认 <仓库根>/number_registry.json）")
    ap.add_argument("--sync", action="store_true", help="把权威源写入镜像（含 _mirror* 元数据）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

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
        return 1

    mir_doc = json.loads(mir_path.read_text(encoding="utf-8"))
    say(f"镜像哈希: {sha256_file(mir_path)[:16]}…")

    # --- 权威缺失：CI / 全新克隆的常态 ---
    if not auth_path.exists():
        say("")
        say("[SKIP] 权威源不存在（CI / 全新克隆属正常情形）——跳过一致性比对。")
        say("       注意：这**不代表**镜像已与权威对齐；本地开发机请务必跑一次本脚本。")
        say("       同时，镜像中登记的数字在 CI 里**无法复算**（results/ 数据 3.2 GB 不入库）。")
        say("")
        problems = structural_check(mir_doc, "镜像")
        return 1 if problems else 0

    auth_doc = json.loads(auth_path.read_text(encoding="utf-8"))
    auth_sha = sha256_file(auth_path)          # 文件字节哈希（仅作诊断输出）
    auth_eid = entity_fingerprint(auth_doc)    # 内容指纹（记录 / 比对用，跨平台稳定）
    say(f"权威字节哈希 {auth_sha[:16]}…  内容指纹 {auth_eid}")

    # --- 同步模式 ---
    if args.sync:
        n = sync_mirror(mir_path, auth_path, auth_eid)
        say(f"[sync] 已写入镜像（插入 {n} 行元数据；实体逐字节同权威），"
            f"内容指纹 = {auth_eid}")
        return 0

    # --- 一致性比对 ---
    recorded = mir_doc.get("_mirror_sha256")
    ok = True

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
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
