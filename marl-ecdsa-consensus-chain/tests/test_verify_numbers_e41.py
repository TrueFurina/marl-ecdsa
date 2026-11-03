"""
verify_numbers 的 e41_longrun 分支测试（2026-10-16）
====================================================
E41（端到端长跑一致性）的结果结构与既有 analysis 类型都不同，故在
verify_numbers.py 新增 `e41_longrun` 分支。本文件守护该分支的契约：

  1) 正常报告 ⇒ computed 产出约定的 8 个标量键
  2) 报告缺失 ⇒ 报错且 computed 为空（fail-closed）
  3) sources 缺 file/glob ⇒ 报错
  4) declared 与 computed 一致 ⇒ compare 通过；篡改任一值 ⇒ 失败
  5) 🔴 **declared 禁放 list**（如 divergences）：verify 的 _compare_value 对
     「declared 是 list 而 computed 无对应 key」直接判 False ⇒ 会静默 FAIL。
     一致性结论必须用 `n_divergence_checks == 0` 这个标量表达。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import verify_numbers as vn  # noqa: E402  (conftest 已注入 scripts/**)


def _make_report(tmp_path: Path, summary: dict) -> Path:
    rel = Path("e41_ledger_consistency/e41_ledger_consistency.json")
    fp = tmp_path / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps({"meta": {}, "summary": summary},
                             ensure_ascii=False), encoding="utf-8")
    return rel


def _summary(**over):
    base = {
        "success_count": 1000, "n_rounds": 1000, "success_rate": 1.0,
        "n_checks": 10, "n_divergence_checks": 0,
        "divergences": [],
        "latency_ms": {"mean": 123.4, "max": 456.7, "min": 12.3},
        "total_msg_sent": 99999,
    }
    base.update(over)
    return base


def _entry(rel: Path) -> dict:
    return {
        "id": "NR-TEST",
        "analysis": "e41_longrun",
        "sources": [{"file": str(rel)}],
        "statistic": ["success_count", "success_rate", "n_divergence_checks"],
        "declared": {},
        "tolerance": {"abs": 0.001, "p_abs": 0.001},
    }


class TestRecomputeE41:
    def test_normal_report_produces_scalar_keys(self, tmp_path):
        rel = _make_report(tmp_path, _summary())
        errs: list = []
        computed, files = vn._recompute_e41_longrun(_entry(rel), tmp_path, errs)
        assert errs == []
        assert files == 1
        assert computed["success_count"] == 1000
        assert computed["success_rate"] == 1.0
        assert computed["n_divergence_checks"] == 0
        assert computed["latency_ms_mean"] == 123.4
        assert computed["latency_ms_max"] == 456.7
        assert computed["total_msg_sent"] == 99999
        # 全部为标量（禁 list/dict 泄漏进 computed）
        assert all(isinstance(v, (int, float)) for v in computed.values())

    def test_missing_report_is_fail_closed(self, tmp_path):
        entry = _entry(Path("e41_ledger_consistency/nope.json"))
        errs: list = []
        computed, files = vn._recompute_e41_longrun(entry, tmp_path, errs)
        assert computed == {}
        assert files == 0
        assert errs and "缺失" in errs[0]

    def test_missing_source_field_is_fail_closed(self, tmp_path):
        entry = {"id": "NR-TEST", "analysis": "e41_longrun", "sources": [{}]}
        errs: list = []
        computed, _ = vn._recompute_e41_longrun(entry, tmp_path, errs)
        assert computed == {}
        assert errs and "file/glob" in errs[0]

    def test_compare_passes_when_declared_matches(self, tmp_path):
        rel = _make_report(tmp_path, _summary())
        entry = _entry(rel)
        entry["declared"] = {
            "success_count": 1000, "n_rounds": 1000, "success_rate": 1.0,
            "n_checks": 10, "n_divergence_checks": 0,
            "latency_ms_mean": 123.4, "latency_ms_max": 456.7,
            "total_msg_sent": 99999,
        }
        errs: list = []
        computed, _ = vn._recompute_e41_longrun(entry, tmp_path, errs)
        ok, _deltas = vn.compare(entry, computed)
        assert ok and not errs

    def test_compare_fails_when_declared_tampered(self, tmp_path):
        rel = _make_report(tmp_path, _summary())
        entry = _entry(rel)
        entry["declared"] = {
            "success_count": 1000, "n_rounds": 1000, "success_rate": 1.0,
            "n_checks": 10, "n_divergence_checks": 0,
            "latency_ms_mean": 123.4, "latency_ms_max": 456.7,
            "total_msg_sent": 99999,
        }
        computed, _ = vn._recompute_e41_longrun(entry, tmp_path, [])
        entry["declared"]["n_divergence_checks"] = 3      # 把 0 篡改成 3
        ok, deltas = vn.compare(entry, computed)
        assert ok is False
        assert deltas["n_divergence_checks"] == 3

    def test_divergences_list_in_declared_is_rejected(self, tmp_path):
        """🔴 回归防护：divergences 是 list，放进 declared 会静默 FAIL。"""
        rel = _make_report(tmp_path, _summary())
        entry = _entry(rel)
        entry["declared"] = {
            "success_count": 1000, "n_rounds": 1000, "success_rate": 1.0,
            "n_checks": 10, "n_divergence_checks": 0,
            "latency_ms_mean": 123.4, "latency_ms_max": 456.7,
            "total_msg_sent": 99999,
            "divergences": ["某条不一致"],        # 违反契约
        }
        computed, _ = vn._recompute_e41_longrun(entry, tmp_path, [])
        ok, deltas = vn.compare(entry, computed)
        assert ok is False, "declared 含 list 字段必须被判失败（computed 无对应键）"
        assert deltas["divergences"] == "MISSING"

    def test_zero_divergence_expresses_consistency(self, tmp_path):
        """一致性结论由标量 n_divergence_checks == 0 表达（不是 list 长度）。"""
        rel = _make_report(tmp_path, _summary(n_divergence_checks=0,
                                              divergences=[]))
        computed, _ = vn._recompute_e41_longrun(_entry(rel), tmp_path, [])
        assert computed["n_divergence_checks"] == 0
        # 非零时必须能区分
        rel2 = _make_report(tmp_path, _summary(n_divergence_checks=2,
                                               divergences=["a", "b"]))
        computed2, _ = vn._recompute_e41_longrun(_entry(rel2), tmp_path, [])
        assert computed2["n_divergence_checks"] == 2
