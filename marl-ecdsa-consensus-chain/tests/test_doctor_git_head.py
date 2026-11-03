"""
doctor._git_head 执行基线契约测试（2026-10-20）

契约焦点：_git_head 只接受「40 位 SHA」，git 失败（rc!=0）、输出异常
（截断/多行/空）一律显式 "unknown"——绝不返回空串或垃圾文本。
意义（#134）：执行基线 pin 的价值就在于「失败显式化」；静默放行
空 head 会让 CI 归因链断掉而无人知晓。

本文件是变异探针目标 doctor-git-head-format 的关联测试：变异
（去掉 40 位校验兜底）必须使 G6/G7 变红——变异必须产生可观测
差异（REA #157），故测试覆盖 git 失败路径而非仅正常路径。
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCTOR = REPO / "scripts" / "doctor.py"


def _load_doctor():
    spec = importlib.util.spec_from_file_location("doctor_under_test", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_g6_git_failure_returns_unknown(monkeypatch):
    """git rev-parse 失败（rc!=0）→ unknown，不是空串。"""
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "run",
                        lambda *a, **k: (128, "fatal: not a git repository\n", 0.0))
    assert doctor._git_head(REPO) == "unknown"


def test_g7_garbage_output_returns_unknown(monkeypatch):
    """git 输出非 40 位（截断/短哈希）→ unknown。"""
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "run", lambda *a, **k: (0, "deadbeef\n", 0.0))
    assert doctor._git_head(REPO) == "unknown"


def test_g8_valid_sha_passthrough(monkeypatch):
    """40 位 SHA 原样返回（正常路径不误报）。"""
    doctor = _load_doctor()
    sha = "a" * 40
    monkeypatch.setattr(doctor, "run", lambda *a, **k: (0, sha + "\n", 0.0))
    assert doctor._git_head(REPO) == sha
