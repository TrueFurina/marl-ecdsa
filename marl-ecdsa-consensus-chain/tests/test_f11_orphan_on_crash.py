"""F11：Web 崩溃后训练孙进程/子进程不再成为孤儿的持久回归测试。

验证 business_service._win_job_kill_on_close 的 Job Object（KILL_ON_JOB_CLOSE）：
内层脚本模拟 Web（起训练→os._exit 硬崩），外层断言训练进程被内核自动终止。
对照组（无修复）已在 2026-11-02 实测复现孤儿存活（A/B 实验记录于
项目深度梳理_20261101/_f11_a_result.json 与 _f11_b_result.json）。"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CRASH_SCRIPT = Path(__file__).resolve().parents[3] / "项目深度梳理_20261101" / "_f11_crash_web.py"


def test_train_killed_when_web_crashes():
    if not CRASH_SCRIPT.exists():  # 提交包外脚本缺失时跳过（冻结件不含诊断目录）
        import pytest
        pytest.skip("crash 模拟脚本不在（仅完整工作区可跑）")
    out = Path(tempfile.mkdtemp(prefix="f11_test_")) / "crash.json"
    subprocess.run([sys.executable, str(CRASH_SCRIPT), str(out)],
                   cwd=str(ROOT), timeout=60, capture_output=True)
    d = json.loads(out.read_text(encoding="utf-8"))
    pid = d["pid"]
    # Web 已 os._exit；给内核一点时间执行 Job 终止
    for _ in range(20):
        try:
            import psutil
            psutil.Process(pid)
            time.sleep(0.5)
        except Exception:
            break
    else:
        import psutil
        p = psutil.Process(pid)  # 仍存活则清理并失败
        p.kill(); p.wait(timeout=5)
        raise AssertionError(f"Web 崩溃后训练孤儿 pid={pid} 仍在运行（Job Object 未生效）")
