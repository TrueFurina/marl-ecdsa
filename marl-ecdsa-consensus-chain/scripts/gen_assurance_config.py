#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径门禁配置的「公开 / 私有」分层生成器（F7 修复件）。

## 为什么需要分层

外置配置原先整份放在工作区 ``deliverables/assurance/config/``（**不进 git**），
原因是这两份文件里混着**机器本地与其身份信息**：

  - ``assurance_blacklist.json`` 的 ``identity.tokens``：明文真名 / QQ 号 / 邮箱后缀
  - ``scan_targets.json`` 的 ``thesis_inbox_dir``：本机绝对路径

但同一文件里**其余部分全是纯口径规则**（作废令牌清单、语义规则、上下文标记、扫描范围），
不含任何身份信息，本来就是可以公开的。

后果：CI 里读不到配置 → ``load_*`` 抛 ``OSError`` → 门禁 **exit 2**
→ **口径门禁在 CI 里根本无法运行**（F1 / F7）。

## 分层方案（零重叠 —— 每一条规则只有一个真源）

  - **public**（入库）``scripts/assurance_config/*.public.json``
    ``void_tokens`` / ``semantic_rules`` / ``citation_*`` / ``context_markers``
    + 扫描范围（``exclude_dirs`` / ``exclude_globs`` / ``include_ext`` / 各类 markers）
  - **private**（仓库外，保持原样）``deliverables/assurance/config/*.json``
    只被真正需要的 ``identity`` 与 ``thesis_inbox_dir`` 继续生效

叠加顺序：**public 为基线，private 覆盖**。
→ 开发机行为与分层前**完全一致**；CI 里 private 缺失，public 兜底，门禁照跑。

## 用法

    python -X utf8 scripts/gen_assurance_config.py            # 生成/刷新 public 配置
    python -X utf8 scripts/gen_assurance_config.py --check     # 只校验两者是否一致（不一致 exit 1）
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
import assurance_common as ac  # noqa: E402

PUBLIC_DIR = ac.REPO_ROOT / "scripts" / "assurance_config"
RULES_PUBLIC = PUBLIC_DIR / "assurance_rules.public.json"
TARGETS_PUBLIC = PUBLIC_DIR / "scan_targets.public.json"

# 可公开的规则键（其余键视为机器/身份本地项，不出库）
RULES_PUBLIC_KEYS = ["void_tokens", "semantic_rules", "citation_blacklist",
                     "citation_markers", "context_markers"]
TARGETS_PUBLIC_KEYS = [
    "scan_roots", "include_ext", "exclude_dirs", "exclude_globs",
    # F14：源码注释层的语义扫描范围 + 其独立严重度
    "semantic_scan_ext", "semantic_scan_ext_severity",
    "identity_self_exclude", "thesis_drafts_dir", "held_drafts_dir",
    "snapshot_dir_markers", "snapshot_name_markers",
    "meta_name_markers", "external_material_markers",
]
# 明确**不进**公开库的键（留作审计/守门器交叉验证）
RULES_PRIVATE_ONLY = ["identity"]
TARGETS_PRIVATE_ONLY = ["thesis_inbox_dir"]

PUBLIC_NOTE = (
    "本文件由 scripts/gen_assurance_config.py 从工作区私有配置派生，**入库、供 CI 使用**；"
    "请勿手改，改私有配置后跑 `python -X utf8 scripts/gen_assurance_config.py` 刷新。"
    "身份串（真名/QQ/邮箱）与机器本地路径不在本文件，仅在仓库外私有配置中。"
)


def _read_private(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _build_public(priv, keys, private_only, note_extra=""):
    pub = {
        "schema_version": (priv or {}).get("schema_version", "1.0"),
        "note": PUBLIC_NOTE + note_extra,
        "_generated_from": None,   # 由调用方填入相对路径
        "_public_keys": list(keys),
        "_private_only_keys": list(private_only),
    }
    for k in keys:
        if priv is not None and k in priv:
            pub[k] = priv[k]
    return pub


def expected():
    """返回 (rules_doc, targets_doc, 各自派生来源描述)。"""
    priv_rules = _read_private(ac.BLACKLIST_PATH)
    priv_targets = _read_private(ac.SCAN_TARGETS_PATH)

    r = _build_public(priv_rules, RULES_PUBLIC_KEYS, RULES_PRIVATE_ONLY,
                      note_extra=" 内含作废令牌清单与语义规则，是口径门禁的规则真源。")
    r["_generated_from"] = ac.rel_to_workspace(ac.BLACKLIST_PATH)

    t = _build_public(priv_targets, TARGETS_PUBLIC_KEYS, TARGETS_PRIVATE_ONLY,
                      note_extra=" 内含扫描范围与严重度判定标记。")
    t["_generated_from"] = ac.rel_to_workspace(ac.SCAN_TARGETS_PATH)
    return r, t


def dump(p: Path, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写盘；不一致则 exit 1")
    args = ap.parse_args(argv)

    priv_ok = ac.BLACKLIST_PATH.exists() and ac.SCAN_TARGETS_PATH.exists()
    exp_r, exp_t = expected()

    if not priv_ok:
        print("[SKIP] 私有配置不存在（CI / 全新克隆属正常情形）——无法派生，跳过。")
        print("       注意：CI 使用的是已入库的 public 配置，门禁仍可运行。")
        for p in (RULES_PUBLIC, TARGETS_PUBLIC):
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                print(f"       [ok ] {ac.rel_to_workspace(p)} 存在（{len(d)} 个顶层键）")
            else:
                print(f"       [FAIL] {ac.rel_to_workspace(p)} 缺失 —— CI 将无法运行门禁。")
                return 1
        return 0

    if args.check:
        bad = []
        for path, exp in ((RULES_PUBLIC, exp_r), (TARGETS_PUBLIC, exp_t)):
            if not path.exists():
                bad.append(f"{ac.rel_to_workspace(path)} 不存在")
                continue
            got = json.loads(path.read_text(encoding="utf-8"))
            if got != exp:
                keys = sorted(set(got) | set(exp))
                diff = [k for k in keys if got.get(k) != exp.get(k)]
                bad.append(f"{ac.rel_to_workspace(path)} 与私有配置不一致，差异键: {diff}")
        if bad:
            print("[FAIL] public 配置已过期：")
            for b in bad:
                print(f"       - {b}")
            print("       修法：python -X utf8 scripts/gen_assurance_config.py")
            return 1
        print(f"[ok ] public 配置与私有配置一致（{ac.rel_to_workspace(RULES_PUBLIC)}、"
              f"{ac.rel_to_workspace(TARGETS_PUBLIC)}）")
        return 0

    # 出库前自检：public 产物不得含身份串 / 机器路径（fail-closed，先验后写）
    import re
    blob = json.dumps(exp_r, ensure_ascii=False) + json.dumps(exp_t, ensure_ascii=False)
    leaks = [name for name, pat in (
        ("绝对路径", r"[A-Za-z]:[\\/]"),
        ("用户名", r"Lenovo"),
        ("邮箱", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        ("UNC", r"\\\\[A-Za-z0-9_-]{1,15}(?=\\\\)"),
    ) if re.search(pat, blob)]
    if leaks:
        print(f"[FAIL] public 产物含敏感串 {leaks} —— 拒绝写盘（派生逻辑需先修正）。")
        return 1
    print("[ok ] 出库前自检：public 产物无绝对路径 / 用户名 / 邮箱 / UNC")

    dump(RULES_PUBLIC, exp_r)
    dump(TARGETS_PUBLIC, exp_t)
    print(f"[gen] {ac.rel_to_workspace(RULES_PUBLIC)}")
    print(f"      void_tokens={len(exp_r.get('void_tokens', []))} "
          f"semantic_rules={len(exp_r.get('semantic_rules', []))} "
          f"mention={len(exp_r.get('context_markers', {}).get('mention', []))}")
    print(f"[gen] {ac.rel_to_workspace(TARGETS_PUBLIC)}")
    print(f"      exclude_dirs={len(exp_t.get('exclude_dirs', []))} "
          f"exclude_globs={len(exp_t.get('exclude_globs', []))}")
    print("      私有键（未出库）:", RULES_PRIVATE_ONLY + TARGETS_PRIVATE_ONLY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
