"""
config_loader（惩罚阈值单一真值源）测试
=====================================
2026-10-16 新增：覆盖率报告显示 blockchain/config_loader.py 仅 77%，
且**整个模块此前零测试覆盖**——它是 2026-10-01 工程整改（消除三处重复定义）
的产物，"单一真值源"本身没有守护，属于工程缺口。

覆盖点：
  - config.json 缺失 ⇒ 回退默认阈值（fail-safe）
  - config.json 损坏 ⇒ 回退默认阈值 + 记 warning
  - 简化格式 ``blockchain.penalty_thresholds``
  - 旧分级格式 ``blockchain.penalty_levels`` 的兼容转换与嵌套默认
  - 简化格式优先于旧格式
  - 返回**副本**而非共享常量（防调用方原地改坏）
  - caller_logger 日志归因
"""
import json
import logging

import pytest

from blockchain import config_loader
from blockchain.config_loader import (
    DEFAULT_PENALTY_THRESHOLDS,
    load_penalty_thresholds,
)


def _write_cfg(tmp_path, payload):
    """把 payload 写到临时 config.json 并让模块指向它。"""
    fp = tmp_path / "config.json"
    fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return fp


class TestDefaultsFallback:
    def test_missing_config_falls_back_to_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "nope.json")
        assert load_penalty_thresholds() == DEFAULT_PENALTY_THRESHOLDS

    def test_corrupted_json_falls_back_and_warns(self, tmp_path, monkeypatch, caplog):
        fp = tmp_path / "config.json"
        fp.write_text("{ this is not valid json", encoding="utf-8")
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        with caplog.at_level(logging.WARNING):
            thresholds = load_penalty_thresholds()
        assert thresholds == DEFAULT_PENALTY_THRESHOLDS
        assert any("加载 config.json 失败" in r.message for r in caplog.records)

    def test_returns_copy_not_shared_constant(self, tmp_path, monkeypatch):
        """docstring 承诺：返回副本，调用方改返回值不得污染模块常量。"""
        monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "nope.json")
        got = load_penalty_thresholds()
        got["ban"] = 99999
        assert DEFAULT_PENALTY_THRESHOLDS["ban"] == 50


class TestSimplifiedFormat:
    def test_penalty_thresholds_read(self, tmp_path, monkeypatch):
        fp = _write_cfg(tmp_path, {"blockchain": {
            "penalty_thresholds": {"warning": 3, "demotion": 7, "ban": 11}}})
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        assert load_penalty_thresholds() == {"warning": 3, "demotion": 7, "ban": 11}

    def test_simplified_takes_precedence_over_legacy(self, tmp_path, monkeypatch):
        """两种格式同时存在时，简化格式优先（避免歧义）。"""
        fp = _write_cfg(tmp_path, {"blockchain": {
            "penalty_thresholds": {"warning": 1, "demotion": 2, "ban": 3},
            "penalty_levels": {"warning": {"threshold": 100}}}})
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        assert load_penalty_thresholds() == {"warning": 1, "demotion": 2, "ban": 3}

    def test_no_blockchain_section_uses_defaults(self, tmp_path, monkeypatch):
        fp = _write_cfg(tmp_path, {"other": {"x": 1}})
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        assert load_penalty_thresholds() == DEFAULT_PENALTY_THRESHOLDS


class TestLegacyLevelsFormat:
    def test_legacy_levels_converted(self, tmp_path, monkeypatch):
        """旧分级格式 ⇒ 简化三键（demoted/banned 键名映射到 demotion/ban）。"""
        fp = _write_cfg(tmp_path, {"blockchain": {"penalty_levels": {
            "warning": {"threshold": 5},
            "demoted": {"threshold": 15},
            "banned": {"threshold": 25}}}})
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        assert load_penalty_thresholds() == {"warning": 5, "demotion": 15, "ban": 25}

    def test_legacy_levels_missing_keys_use_defaults(self, tmp_path, monkeypatch):
        """旧格式缺键 ⇒ 逐键回退默认值（不能整份丢弃）。"""
        fp = _write_cfg(tmp_path, {"blockchain": {"penalty_levels": {
            "warning": {"threshold": 4}}}})
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        assert load_penalty_thresholds() == {
            "warning": 4,
            "demotion": DEFAULT_PENALTY_THRESHOLDS["demotion"],
            "ban": DEFAULT_PENALTY_THRESHOLDS["ban"],
        }


class TestLoggerAttribution:
    def test_caller_logger_used_on_failure(self, tmp_path, monkeypatch, caplog):
        """caller_logger 应承接 warning，保留原模块的日志归因标签。"""
        fp = tmp_path / "config.json"
        fp.write_text("broken", encoding="utf-8")
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        caller = logging.getLogger("test.caller.penalty_contract")
        with caplog.at_level(logging.WARNING):
            thresholds = load_penalty_thresholds(caller_logger=caller)
        assert thresholds == DEFAULT_PENALTY_THRESHOLDS
        assert any(r.name == "test.caller.penalty_contract" for r in caplog.records)

    def test_default_logger_used_without_caller(self, tmp_path, monkeypatch, caplog):
        fp = tmp_path / "config.json"
        fp.write_text("broken", encoding="utf-8")
        monkeypatch.setattr(config_loader, "CONFIG_PATH", fp)
        with caplog.at_level(logging.WARNING):
            load_penalty_thresholds()
        assert any(r.name == config_loader.logger.name for r in caplog.records)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
