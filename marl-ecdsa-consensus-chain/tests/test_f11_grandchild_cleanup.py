"""F11：supervisor 孙进程跟踪（Windows Job Object）的负测。

病灶：supervisor 只直接持有 Web/节点的 Popen，训练进程是 Web 的孙进程；
只 terminate 直接子进程不会回收它们。修复：Windows 下建 Job Object
（KILL_ON_JOB_CLOSE）并把每个子进程 Assign 进去，句柄关闭时 OS 连带杀掉全部后代。

本测用真实进程验证：父(=子进程) → 孙进程，关闭 Job 后两者都必须死亡。
环境不支持 Job/Assign（如嵌套 Job 受限）时 skip，不误报失败。
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "launcher_supervisor", _ROOT / "launcher" / "supervisor.py")
sup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sup)


def _alive(pid):
    """只读探测，绝不向目标进程发信号。"""
    if not (isinstance(pid, int) and pid > 0):
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_job_kills_grandchild():
    job = sup._make_job()
    if not job:
        pytest.skip("CreateJobObject/SetInformation 不可用（环境限制）")
    tmp = Path(tempfile.mkdtemp(prefix="f11_gc_"))
    pidfile = tmp / "grandchild.pid"
    child_code = (
        "import subprocess,sys,time,pathlib;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"pathlib.Path(r'{pidfile}').write_text(str(p.pid));"
        "time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code])
    gpid = None
    try:
        if not sup._assign_job(job, child.pid):
            pytest.skip("AssignProcessToJobObject 不可用（环境限制）")
        for _ in range(60):
            if pidfile.exists():
                break
            time.sleep(0.1)
        assert pidfile.exists(), "孙进程未启动"
        gpid = int(pidfile.read_text().strip())
        assert _alive(child.pid), "子进程应存活"
        assert _alive(gpid), "孙进程应存活"
        sup._close_job(job)
        time.sleep(0.8)
        assert not _alive(child.pid), "直接子进程未被 Job 回收"
        assert not _alive(gpid), "孙进程未被 Job 回收"
    finally:
        try:
            if child.poll() is None:
                child.kill()
        except Exception:
            pass
        if gpid:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(gpid)],
                               capture_output=True, timeout=5)
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
