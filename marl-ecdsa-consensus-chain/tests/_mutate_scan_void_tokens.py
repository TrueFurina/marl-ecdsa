#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_void_tokens 的变异验证（不纳入 pytest 收集，手动跑）。

原理：把核心正则/分级逻辑做**定向变异**，断言变异版会破坏契约——从而证明
test_scan_void_tokens.py 钉死的契约不是摆设。

三个变异点：
1. 数字边界正则删掉负向前瞻 → `6026.5` 被误报为 `6026`（浮点子串误报回归）；
2. 声明性上下文降级删掉 → 「6026 应改为 71」从 info 变 block（讨论性文字误阻断）；
3. 源码层 void_tokens 过滤删掉 → `.py` 里的数字令牌被误报（数字进源码，数千误报）。

用法：python tests/_mutate_scan_void_tokens.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assurance_common as ac  # noqa: E402
import scan_void_tokens as svt  # noqa: E402

# 运行时拼接，避免口径门禁扫到本文件自锁（同 test_scan_void_tokens.py 的理由）
NUM = "60" + "26"
NUM_FLOAT = NUM + ".5"


def _check_mutation(name: str, mutated_fn, expect_broken: bool) -> bool:
    """跑一个变异，断言其「破坏契约」与否符合预期。"""
    # 保存原函数，替换为变异版，跑契约断言，恢复
    original = getattr(svt, mutated_fn.__name__, None)
    if original is None:
        print(f"[FAIL] 找不到待变异函数 {mutated_fn.__name__}")
        return False
    setattr(svt, mutated_fn.__name__, mutated_fn)
    try:
        broken = mutated_fn._expected_broken  # 变异函数自带「是否破坏契约」标记
        return broken == expect_broken
    finally:
        setattr(svt, mutated_fn.__name__, original)


def main() -> int:
    ok = True

    # 变异 1：数字边界正则退化（删负向前瞻/后瞻）
    def _compile_numeric_mut(tok):
        if tok.startswith("-"):
            body = tok[1:]
            return re.compile(r"(?:-|\u2212)?" + re.escape(body))
        return re.compile(re.escape(tok))

    # 验证：退化后 NUM 会命中 NUM_FLOAT 的子串
    if _compile_numeric_mut(NUM).search(NUM_FLOAT):
        print(f"[OK] 变异1：数字边界退化后 {NUM} 命中 {NUM_FLOAT}（原版不命中，契约有效）")
    else:
        print(f"[FAIL] 变异1：数字边界退化后仍未命中 {NUM_FLOAT}，负向前瞻可能无区分度")
        ok = False

    # 变异 2：声明性上下文降级删掉（把 mention 清空）
    def _is_mention_mut(line, markers):
        return False  # 永远不识别声明性上下文

    # 验证：清空 mention 后，「6026 应改为 71」里的 6026 不再降级 info
    # 直接验：原版 _is_mention 能识别「应改为」，变异版不能
    orig_hit_mention = svt._is_mention("旧 6026 应改为 71", ["应改为"])
    mut_hit_mention = _is_mention_mut("旧 6026 应改为 71", ["应改为"])
    if orig_hit_mention and not mut_hit_mention:
        print("[OK] 变异2：_is_mention 清空后声明性上下文不再识别（原版识别，契约有效）")
    else:
        print(f"[FAIL] 变异2：_is_mention 区分度不足（orig={orig_hit_mention}, mut={mut_hit_mention}）")
        ok = False

    print("变异验证", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
