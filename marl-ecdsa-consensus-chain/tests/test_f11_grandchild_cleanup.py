"""F11：supervisor 孙进程跟踪（Windows Job Object）的负测。

病灶：supervisor 只直接持有 Web/节点的 Popen，训练进程是 Web 的孙进程；
只 terminate 直接子进程不会回收它们。修复：Windows 下建 Job Object
（KILL_ON_JOB_CLOSE）并把每个子进程 Assign 进去，句柄关闭时 OS 连带杀掉全部后代。

本测用真实进程验证：父(=子进程) → 孙进程，关闭 Job 后两者都必须死亡。
环境不支持 Job/Assign（如嵌套 Job 受限）时 skip，不误报失败。

2026-11-04 重接线（原测在跑一个**不存在的实现**）：
  本文件原先 `exec_module` 一个本仓库没有的 `launcher/supervisor.py`
  （那边才叫 `_make_job/_assign_job/_close_job`）。模块级加载失败 ⇒ 收集期错误
  ⇒ 整份套件中断（CI 实测 Interrupted: 1 error during collection），
  随后降级为整模块 skip —— 于是这条用例实际覆盖为**零**，而且它是无条件 skip，
  永远不会自己活过来。
  而真实实现自 2026-11-02 起就在 `visualization/business_service._win_job_kill_on_close`，
  由 `business_service.py:248` 对每个训练子进程调用。现在直接打真实实现：
  测的终于是活代码，而不是一份缺席实现的影子。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from visualization import business_service as bs  # noqa: E402


def _close_job(job):
    """模拟「持句柄的 Web 进程退出」：关闭 Job 句柄，KILL_ON_JOB_CLOSE 随之触发。

    这是**测试侧**工具，不是生产接口：生产代码刻意不提供「关 Job」的入口，
    它把句柄挂在 `_JOB_HANDLES` 上一直持有到本进程退出——正因如此，Web 崩溃
    （os._exit / 被杀）时内核才会连带杀掉训练子进程。本测手动关句柄，
    就是为了构造「持句柄的进程退出」这一触发条件。

    64 位下必须显式设 argtypes，否则句柄按 c_int 截断（business_service 自己踩过这个坑）。
    """
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.restype = wintypes.BOOL
    bs._JOB_HANDLES.discard(job)   # 别让本进程退出时再去关一个已失效的句柄
    return k32.CloseHandle(job)


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
        # 真实实现一步完成 CreateJobObject + SetInformation(KILL_ON_JOB_CLOSE) + Assign；
        # 任一步失败返回 None（best-effort 语义，不抛异常）。
        job = bs._win_job_kill_on_close(child)
        if not job:
            pytest.skip("CreateJobObject/SetInformation/Assign 不可用（环境限制，如嵌套 Job 受限）")
        for _ in range(60):
            if pidfile.exists():
                break
            time.sleep(0.1)
        assert pidfile.exists(), "孙进程未启动"
        gpid = int(pidfile.read_text().strip())
        assert _alive(child.pid), "子进程应存活"
        assert _alive(gpid), "孙进程应存活"
        _close_job(job)
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
