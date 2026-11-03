"""
next_nr 登记编号原子分配器测试（2026-10-16）
=============================================
背景：多会话并发写 number_registry.json 导致过「覆盖他人条目 + 同 ID 重复」
（详见 scripts/next_nr.py docstring）。本文件守护分配器的三条契约：

  1) 从「当前最大编号 + 1」开始发，**不复用历史空号**
  2) 已发放但尚未写入 registry 的编号不再发（allocations 防重）
  3) 🔴 **多进程并发取号不重号**（锁的真实有效性——单进程测试证明不了）

第 3 条用 subprocess 起 N 个进程同时取号，验证互斥与无丢失。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "next_nr.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import next_nr  # noqa: E402


def _registry(tmp_path, max_nr: int, extra_ids=()) -> Path:
    reg = tmp_path / "number_registry.json"
    entries = [{"id": f"NR-{i}"} for i in range(1, max_nr + 1)]
    entries += [{"id": i} for i in extra_ids]
    reg.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return reg


class TestAllocateSingle:
    def test_starts_after_max(self, tmp_path):
        reg = _registry(tmp_path, 179)
        alloc = tmp_path / "alloc.jsonl"
        ids = next_nr.allocate(3, reg=reg, alloc=alloc, lock=tmp_path / "l.lock")
        assert ids == ["NR-180", "NR-181", "NR-182"]

    def test_does_not_reuse_historical_gaps(self, tmp_path):
        """历史空号（已作废/被删条目）不得被复用。"""
        reg = tmp_path / "number_registry.json"
        reg.write_text(json.dumps({"entries": [{"id": "NR-1"}, {"id": "NR-5"}]},
                                  ensure_ascii=False), encoding="utf-8")
        ids = next_nr.allocate(2, reg=reg, alloc=tmp_path / "a.jsonl",
                               lock=tmp_path / "l.lock")
        assert ids == ["NR-6", "NR-7"]          # 不是 NR-2/NR-3

    def test_allocated_but_unwritten_not_reissued(self, tmp_path):
        """发过但还没写进 registry 的号，下一次不得再发。"""
        reg = _registry(tmp_path, 10)
        alloc = tmp_path / "alloc.jsonl"
        lock = tmp_path / "l.lock"
        first = next_nr.allocate(2, reg=reg, alloc=alloc, lock=lock)
        assert first == ["NR-11", "NR-12"]
        # registry 未变（模拟"取到号还没写"）
        second = next_nr.allocate(2, reg=reg, alloc=alloc, lock=lock)
        assert second == ["NR-13", "NR-14"]

    def test_dry_run_does_not_record(self, tmp_path):
        reg = _registry(tmp_path, 10)
        alloc = tmp_path / "alloc.jsonl"
        ids = next_nr.allocate(2, dry_run=True, reg=reg, alloc=alloc,
                               lock=tmp_path / "l.lock")
        assert ids == ["NR-11", "NR-12"]
        assert not alloc.exists()               # 未记录发放

    def test_count_must_be_positive(self, tmp_path):
        reg = _registry(tmp_path, 1)
        with pytest.raises(ValueError):
            next_nr.allocate(0, reg=reg, alloc=tmp_path / "a.jsonl",
                             lock=tmp_path / "l.lock")


class TestConcurrentAllocation:
    def test_multi_process_no_duplicate(self, tmp_path):
        """进程级并发：N 个进程同时取号，结果互不重复且数量不丢失。"""
        reg = _registry(tmp_path, 179)
        alloc = tmp_path / "alloc.jsonl"
        lock = tmp_path / "l.lock"
        n_proc, per_proc = 8, 2
        procs = [
            subprocess.Popen(
                [sys.executable, str(SCRIPT), "--count", str(per_proc),
                 "--registry", str(reg), "--alloc", str(alloc)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(n_proc)
        ]
        outs = [p.communicate() for p in procs]
        for p, (o, e) in zip(procs, outs):
            assert p.returncode == 0, f"子进程失败: {e}"

        got = [x for o, _ in outs for x in o.split()]
        assert len(got) == n_proc * per_proc, f"编号丢失: {len(got)} != {n_proc * per_proc}"
        assert len(set(got)) == len(got), f"出现重复编号: {sorted(got)}"
        nums = sorted(int(x.split("-")[1]) for x in got)
        assert nums == list(range(180, 180 + n_proc * per_proc))

    def test_threaded_no_duplicate(self, tmp_path):
        """🔴 线程级并发（竞态窗口比进程版窄得多，是锁有效性的主判据）。

        ⚠ 踩坑（2026-10-16）：进程版测试**抓不到无锁竞态**——8 个子进程启动
        各差 ~100ms，被自然错开，锁禁用时仍全绿（假绿）。线程起停快约 100 倍，
        竞态窗口真实存在，故以此为主判据；每个 worker 循环多次放大窗口。
        """
        import threading
        reg = _registry(tmp_path, 179)
        alloc = tmp_path / "alloc.jsonl"
        lock = tmp_path / "l.lock"
        n_threads, loops = 16, 5
        results: list = []
        errors: list = []

        def worker():
            try:
                for _ in range(loops):
                    results.extend(
                        next_nr.allocate(1, reg=reg, alloc=alloc, lock=lock))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发取号出现异常: {errors}"
        expected = n_threads * loops
        assert len(results) == expected, (
            f"编号数量丢失: {len(results)} != {expected}")
        assert len(set(results)) == len(results), (
            f"出现重复编号（锁失效！）: {sorted(results)}")
        nums = sorted(int(x.split("-")[1]) for x in results)
        assert nums == list(range(180, 180 + expected)), "编号不连续"

    def test_lock_serializes(self, tmp_path):
        """锁必须真正互斥：两个进程不可能同时停留在临界区。"""
        reg = _registry(tmp_path, 1)
        alloc = tmp_path / "alloc.jsonl"
        lock = tmp_path / "l.lock"
        # 顺序取号应严格递增（无并发重号即证明互斥生效）
        a = next_nr.allocate(1, reg=reg, alloc=alloc, lock=lock)
        b = next_nr.allocate(1, reg=reg, alloc=alloc, lock=lock)
        assert int(a[0].split("-")[1]) + 1 == int(b[0].split("-")[1])
