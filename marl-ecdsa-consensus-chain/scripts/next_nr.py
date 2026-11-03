#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
next_nr.py — 登记编号原子分配器（2026-10-16，多会话协作防撞号）
================================================================
背景（本次事故）：本项目有多个并行会话同时往 number_registry.json 追加条目，
硬编码编号导致**静默覆盖他人条目**与**同 ID 重复**：
  - E41 登记硬编码 NR-174 ⇒ 覆盖他人的「CW-PBFT 阈值正确性验证」
  - 改投 NR-176 ⇒ 与他人 E33 QMIX 撞号，同一 ID 出现两条
  - 并行会话的写回还把 NR-174 抹掉

本脚本把「取编号」变成**跨进程原子操作**：
  1) 文件锁（Windows msvcrt / POSIX fcntl）保证同一时刻只有一个进程在分配
  2) 已占用集合 = registry 现有 ID ∪ allocations 记录里**已发放但尚未写入
     registry** 的编号 ⇒ 后者防止「A 取到号还没写，B 也取到同一号」
  3) 取号后立即把发放记录 append 到 allocations 文件（同一次锁内）
  4) 纯标准库，无第三方依赖

用法：
  python scripts/next_nr.py --count 2          # 取 2 个编号
  python scripts/next_nr.py --count 1 --dry-run  # 只看会发什么，不记录

登记脚本的正确写法（见 register_e41_longrun.py）：
    ids = allocate()                # 取号（原子）
    ...构造条目...
    write_registry(ids)             # 写回前再校验目标号仍归自己所有
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
REG = _REPO_ROOT.parent / "deliverables" / "number_registry.json"
ALLOC = _REPO_ROOT.parent / "deliverables" / "number_registry_allocations.jsonl"
LOCK = _REPO_ROOT.parent / "deliverables" / ".number_registry_allocations.lock"


@contextmanager
def exclusive_lock(path: Path, timeout: float = 30.0):
    """跨进程独占锁（Windows msvcrt / POSIX fcntl，纯标准库）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    t0 = time.time()
    while True:
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() - t0 > timeout:
                os.close(fd)
                raise TimeoutError(f"获取锁超时（{timeout}s）：{path}")
            time.sleep(0.05)
    try:
        yield fd
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)


def _used_ids(reg: Path = REG) -> set:
    used = set()
    if reg.exists():
        try:
            reg = json.loads(reg.read_text(encoding="utf-8"))
            for e in reg.get("entries", []):
                if isinstance(e, dict) and isinstance(e.get("id"), str):
                    used.add(e["id"])
        except (OSError, json.JSONDecodeError):
            # registry 正在被他人写入/损坏时，保守起见把 allocations 全量纳入
            pass
    return used


def _allocated_ids(alloc: Path = ALLOC) -> set:
    out = set()
    if alloc.exists():
        for line in alloc.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            for n in rec.get("allocated", []):
                out.add(f"NR-{n}")
    return out


def allocate(count: int = 1, dry_run: bool = False,
             reg: Path = REG, alloc: Path = ALLOC, lock: Path = LOCK) -> list:
    """原子分配 count 个编号，返回形如 ['NR-180', 'NR-181']。

    :param reg:   登记表路径（读取现有 ID）
    :param alloc: 发放记录路径（append-only）
    :param lock:  锁文件路径
    """
    if count < 1:
        raise ValueError("count 必须 ≥ 1")
    with exclusive_lock(lock):
        taken = _used_ids(reg) | _allocated_ids(alloc)
        # ⚠ 从「当前最大编号 + 1」开始发，**不复用历史空号**（NR-46~50/61/88 等
        # 是已作废或被删条目留下的空号，复用会与历史材料混淆，也让人误以为
        # 那些条目复活）。
        nums = [int(x.split("-")[1]) for x in taken if x.split("-")[1].isdigit()]
        n = (max(nums) + 1) if nums else 1
        result = []
        while len(result) < count:
            cand = f"NR-{n}"
            if cand not in taken:
                result.append(cand)
                taken.add(cand)
            n += 1
        if not dry_run:
            rec = {
                "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "pid": os.getpid(),
                "allocated": [int(x.split("-")[1]) for x in result],
            }
            with open(alloc, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description="登记编号原子分配器")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="只预览，不记录发放")
    ap.add_argument("--registry", default=None, help="登记表路径（测试用）")
    ap.add_argument("--alloc", default=None, help="发放记录路径（测试用）")
    args = ap.parse_args()
    ids = allocate(
        args.count, args.dry_run,
        reg=Path(args.registry) if args.registry else REG,
        alloc=Path(args.alloc) if args.alloc else ALLOC,
    )
    print(" ".join(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
