# -*- coding: utf-8 -*-
"""变异目标登记表的静态守卫（不跑变异，只查登记本身）。

为什么需要这一层：`scripts/mutation_probe.py` 是**手动**调查工具（刻意不进
ci.yml 必需链），所以登记表漂移只会安静地烂在仓库里——locator 指向的行被
改掉之后，探针直到下次有人手动跑才会喊。本文件把"探针拒跑的条件"提前成
CI 里的一条红/绿：

* 必填字段齐全、id 唯一；
* locator 在目标文件里**恰好**命中 1 次（0 次 = 漂移，多次 = 歧义）；
* locator 与 mutation 不同（相同则注入后文本无变化，是空变异）；
* pytest 类目标的关联测试文件真实存在；
* 审计简报里那批安全/正确性修复仍在登记表里（防止静默删目标）。

校验规则与探针共用 `scripts.mutation_probe.validate_targets()`——只有一套
真值，不会出现"探针说不行、测试说没事"。
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts.mutation_probe import (  # noqa: E402
    TARGETS_FILE,
    load_targets,
    read_source,
    validate_targets,
    write_source,
)

# 审计简报 §1/§2/§3/§4/§5/§6/§7/§8/§9 与 2026-11-04 flush_pending 缺陷、
# 2026-11-05 匿名门禁两处 fail-open、2026-11-05 BC→MARL 反馈层（λ 调度 +
# 奖励塑形）七处非有限值/口径缺陷、2026-11-05 κ 三元组"假单一真源"对应的目标 id。
# 删掉一个就等于放弃一处承重证据，必须显式改这个集合并在评审里说明。
AUDIT_INVARIANT_IDS = {
    "security-guard-r-type-normalization",
    "security-guard-timestamp-normalization",
    "security-guard-nonce-normalization",
    "ecdsa-payload-field-binding",
    "mappo-critic-target-shape",
    "qmix-state-index-hash-seed",
    "nash-mixed-p-me-formula",
    "pbft-self-reported-weight",
    "failover-unknown-heartbeat",
    "incentive-nan-clamp",
    "world-state-nonfinite-reject",
    "action-recorder-flush-clear",
    "anon-placeholder-per-match",
    "anon-self-exempt-name-only",
    "adaptive-lambda-nan-metric-guard",
    "adaptive-lambda-rate-domain-clamp",
    "rl-lambda-consensus-key-contract",
    "rl-lambda-nan-reward-guard",
    "shaper-weight-finite-guard",
    "shaper-stats-eta-accounting",
    "shaper-outlet-finite-guard",
    "kappa-scoring-ignores-config",
    "kappa-normalization-check",
    "kappa-unit-interval-guard",
    "kappa-invalid-value-partial-adoption",
    "kappa-stats-read-same-cache",
    # 2026-11-06：数字门禁的「零断言 PASS」——空 declared 曾被 compare() 判通过，
    # 4 条 ML 指标条目在无任何数据时也 PASS；连同嵌套取数与迁移幂等一并承重。
    "verify-empty-declared-failopen",
    "verify-unverified-status-blocks",
    "verify-path-unknown-aggregation",
    "verify-path-min-max-aggregation",
    "wire-notes-append-idempotent",
    # 2026-11-06：探针自身的判定口径（假红事故）——变异侧不再认「rc=1 但零失败」，
    # 缺失汇总行不再被当成证据。
    "probe-mutated-requires-failure-evidence",
    "probe-truncated-output-not-evidence",
    # 2026-11-06：口径门禁的「零真值通过」——登记簿缺失/损坏/真值残缺时
    # --strict 仍判 ✅；以及宣称覆盖 .docx/.pptx 却按 UTF-8 读二进制。
    "caliber-strict-requires-truth",
    "caliber-office-text-extracted",
    "caliber-unparsed-format-fail-closed",
    # 2026-11-06：证据闭合门禁的「读不懂 = 没有」——声明写成 500.0/"500" 被当
    # 没声明、非数值列与空数组被静默丢出可核对集合、顶层非对象的 JSON 不进分母、
    # --compare 零样本仍 exit 0。
    "closure-float-declared-count",
    "closure-empty-array-is-truncation",
    "closure-malformed-column-blocks",
    "closure-non-object-json-recorded",
    "closure-compare-requires-samples",
    # 2026-11-06：数字复算器的「失败不可隔离 / 误诊 / 双源校验从未跑通」——
    # 一条坏数据让整份报告消失、登记缺陷被报成数据缺失、--check-mirror 第一条
    # 就 KeyError 且零比较判「一致」。
    "verify-crash-isolation",
    "verify-sources-present-globs",
    "verify-mirror-zero-not-consistent",
    "verify-mirror-all-patterns",
    "verify-crashed-entry-is-fail",
    "honesty-z-split",
    "honesty-utf16-bom",
    "honesty-unreadable-blocks",
    "honesty-strict-zero-scan",
    "honesty-substring-skip",
    "honesty-git-error-not-pass",
}


def _target(file_path, locator, mutation="MUTATED", kind="pytest", args=("tests/test_nash_verifier_canonical.py", "-q")):
    """构造一条最小合法目标（字段名与登记表一致）。"""
    return {
        "id": "synthetic",
        "file": str(file_path),
        "locator": locator,
        "mutation": mutation,
        "check": {"kind": kind, "args": list(args), "expect": "all_red"},
        "why": "synthetic target for validator self-check",
    }


def test_registry_file_exists_and_parses():
    assert TARGETS_FILE.exists(), f"登记表缺失：{TARGETS_FILE}"
    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    assert isinstance(data.get("targets"), list) and data["targets"]


def test_registry_passes_static_validation():
    """真登记表必须零问题——这是探针能否开跑的前提。"""
    problems = validate_targets(load_targets())
    assert problems == [], "登记表校验未通过：\n  - " + "\n  - ".join(problems)


def test_registry_ids_are_unique():
    ids = [t["id"] for t in load_targets()]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    assert duplicated == [], f"目标 id 重复：{duplicated}"


def test_audit_invariants_stay_registered():
    """各批修复（审计简报 / flush_pending / 匿名门禁）的承重证据不得被静默删除。

    不写死数量：数量每次加目标都会变，写死只会留下一句迟早过期的自述。
    """
    registered = {t["id"] for t in load_targets()}
    missing = sorted(AUDIT_INVARIANT_IDS - registered)
    assert missing == [], (
        "以下审计不变量目标从登记表里消失（等于放弃承重证据）："
        f"{missing}；确需移除请同步修改 AUDIT_INVARIANT_IDS 并在评审说明理由")


def test_validator_flags_missing_target_file(tmp_path):
    """自检：目标文件不存在必须被判红（防校验器退化成空转）。"""
    problems = validate_targets([_target(tmp_path / "not_here.py", "x = 1")])
    assert any("目标文件不存在" in p for p in problems), problems


def test_validator_flags_ambiguous_locator(tmp_path):
    """自检：locator 命中 2 次必须判红（歧义比漂移更危险，会改错位置）。"""
    f = tmp_path / "dup.py"
    f.write_text("x = 1\nx = 1\n", encoding="utf-8")
    problems = validate_targets([_target(f, "x = 1")])
    assert any("匹配 2 次" in p for p in problems), problems


def test_validator_flags_drifted_locator(tmp_path):
    """自检：locator 命中 0 次（目标行被改掉）必须判红。"""
    f = tmp_path / "one.py"
    f.write_text("x = 2\n", encoding="utf-8")
    problems = validate_targets([_target(f, "x = 1")])
    assert any("匹配 0 次" in p for p in problems), problems


def test_validator_flags_noop_mutation(tmp_path):
    """自检：locator 与 mutation 相同 = 空变异，必须判红。"""
    f = tmp_path / "one.py"
    f.write_text("x = 1\n", encoding="utf-8")
    problems = validate_targets([_target(f, "x = 1", mutation="x = 1")])
    assert any("locator 与 mutation 相同" in p for p in problems), problems


def test_validator_flags_missing_related_test(tmp_path):
    """自检：pytest 类目标的关联测试不存在必须判红（否则变异无从判定）。"""
    f = tmp_path / "one.py"
    f.write_text("x = 1\n", encoding="utf-8")
    problems = validate_targets([_target(f, "x = 1", args=["tests/test_not_exist_xyz.py", "-q"])])
    assert any("关联测试不存在" in p for p in problems), problems


def test_validator_flags_unknown_check_kind(tmp_path):
    f = tmp_path / "one.py"
    f.write_text("x = 1\n", encoding="utf-8")
    problems = validate_targets([_target(f, "x = 1", kind="shell")])
    assert any("check.kind" in p for p in problems), problems


def test_validator_rejects_empty_registry():
    assert validate_targets([]) == ["目标登记为空——空清单不放过（REA #154）"]


def test_read_write_source_roundtrip_preserves_bytes(tmp_path):
    """自检：行尾必须逐字节往返（Windows 上 write_text 会把 LF 整份翻成 CRLF）。"""
    for name, raw in (("lf.py", b"a = 1\nb = 2\n"), ("crlf.py", b"a = 1\r\nb = 2\r\n")):
        p = tmp_path / name
        p.write_bytes(raw)
        text, crlf = read_source(p)
        assert text == "a = 1\nb = 2\n", f"{name}: 行尾未归一到 \\n"
        assert crlf is (name == "crlf.py"), f"{name}: CRLF 判定错误"
        write_source(p, text, crlf)
        assert p.read_bytes() == raw, f"{name}: 往返后字节发生变化"


def test_write_source_with_mutation_is_reversible(tmp_path):
    """自检：注入 + 还原的完整往返也不得改变字节。"""
    p = tmp_path / "lf.py"
    original = b"lock = True\n"
    p.write_bytes(original)
    text, crlf = read_source(p)
    write_source(p, text.replace("lock = True", "lock = False"), crlf)
    assert p.read_bytes() == b"lock = False\n"
    write_source(p, text, crlf)
    assert p.read_bytes() == original


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
