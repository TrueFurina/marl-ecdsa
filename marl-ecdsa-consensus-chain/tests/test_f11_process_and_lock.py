"""F11：安全存活探测 + 跨进程文件锁的回归/负测。"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from blockchain.crypto.key_manager import KeyManager, _file_lock
from visualization.business_service import _pid_alive


def test_pid_alive_self_and_dead():
    assert _pid_alive(os.getpid()) is True          # 当前进程必存活
    assert _pid_alive(999_999) is False             # 不可能存在的 pid（<pid_max 上界内一般不存在）
    for bad in (None, 0, -1, "x", 3.5):
        assert _pid_alive(bad) is False             # 非法输入安全返回 False，绝不发信号


def test_file_lock_acquire_release_ok():
    """锁文件被建出、可重复获取释放、两次都真的走完上下文管理器

    原来只有两个 with 没有断言：即使 `_file_lock` 退化成空上下文管理器
    （yield 前直接 return），这条也会绿。
    """
    d = tempfile.mkdtemp(prefix='f11_lock_')
    lock_path = __import__('pathlib').Path(d) / '.t.lock'
    entered = []
    try:
        with _file_lock(lock_path):
            entered.append(1)
            assert lock_path.exists()      # O_CREAT：锁文件真的被建出来
        with _file_lock(lock_path):        # 可重复获取释放不死锁
            entered.append(2)
            assert lock_path.exists()
        # 两次都完整进入并退出（不是被异常吞掉提前跳过循环体）
        assert entered == [1, 2]
        # 实现只 close fd、不删锁文件；下次仍复用同一个 inode
        assert lock_path.exists()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_keymanager_shared_dir_same_key_across_instances():
    d = tempfile.mkdtemp(prefix='f11_km_')
    try:
        km1 = KeyManager(key_dir=d)
        k1, _ = km1.generate_or_load('agent_0')
        km2 = KeyManager(key_dir=d)                # 另一实例（模拟另一进程读同一目录）
        k2, _ = km2.generate_or_load('agent_0')
        assert k1.private_numbers().private_value == k2.private_numbers().private_value
        assert os.path.exists(os.path.join(d, '.agent_0.lock'))  # 跨进程锁文件已建
    finally:
        shutil.rmtree(d, ignore_errors=True)
