#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目录结构守卫 — pre-commit 门禁
用法：python scripts/pre-commit/structure_guard.py [--all] [--strict] [--self-test]
退出码：0=通过，1=命中违规 / 零文件（--strict），2=环境错误（git 不可用）

规则来源：西湖论剑 CTF-Agent _structure_guard.py（通用化）

默认只检查本次**变更**的文件（新增 / 复制 / 修改 / 重命名），不误伤未动的既有文件。

2026-11-06 修的三处「查了等于没查」：
  1. git 调用失败（不在仓库里 / git 不在 PATH）时打印一句警告就 ``return 0`` ——
     自带注释写明是「fail-open for self」。可这类失败意味着**一个文件都没检查**，
     不是「本次改动都合规」。改为退出码 2，并把 git 的真实错误行带出来。
  2. 只取 ``--diff-filter=A``（新增）：把 ``docs/report.md`` 用 ``git mv`` 挪到根级
     是 ``R``（重命名），git 认为「没有新增文件」，守卫于是放行 —— 而「根级平铺」
     恰恰最常由搬运既有文件产生。改为 ``ACMR``（新增/复制/修改/重命名）。
  3. 输出按行切分：文件名含换行（Linux 下合法）会把一条路径切成两条不存在的路径。
     改用 ``-z`` 按 NUL 切。
"""
import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# 受管后缀（这些类型的散落文件必须归位）
MANAGED_EXT = {"md", "txt", "html", "json", "csv", "pdf", "png", "jpg", "jpeg", "xlsx", "yml", "yaml"}

# 根级白名单（各项目可按需修改此集合）
ROOT_ALLOW = {
    "README.md", "README.zh.md", "README_EN.md", "CLAUDE.md", "AGENTS.md",
    "LICENSE", "requirements.txt", "requirements.lock.txt", "package.json", "pyproject.toml",
    "setup.py", "Dockerfile", "docker-compose.yml", ".gitignore",
    ".pre-commit-config.yaml", "CHANGELOG.md", "Makefile",
    # 以下两个不是"散落"，而是**工具链按仓库根硬编码读取**的：
    #   * config.json          —— blockchain/consensus/factory.py:29 拼 <repo>/config.json
    #   * number_registry.json —— scripts/check_registry_mirror.py 默认镜像路径 <repo>/number_registry.json
    #                              （工作区 deliverables/ 那份才是权威源，仓库内这份是只读镜像）
    # 移动它们会直接打断代码与守门器，故列入白名单。
    "config.json", "number_registry.json",
}

#: 根级**存量**文件冻结豁免（2026-11-03 登记；只减不增）。
#:
#: 两类，都是"平铺在仓库根、且被按裸相对路径引用"的历史文件：
#:
#: 1) V18–V27 等说明文档 —— 从 V18 起就平铺在根，被 README / thesis / 演示脚本
#:    以相对路径引用。一次性搬进 docs/ 会同时打断这些引用。
#:
#: 2) `training_results_pure.json` / `training_results_bc.json` —— 训练结果数据，
#:    被**按裸文件名从项目根读取**的位置至少 4 处：
#:      * `visualization/dashboard.py:302/317`（仪表盘主数据源）
#:      * `scripts/export_dataset.py:67`、`scripts/generate_all_dashboard_screenshots.py:78-79`
#:      * `scripts/generate_complete_data.py:344-345`、`scripts/generate_ppt.py:44-45`
#:    搬进 results/ 就等于同时改这些调用点，属独立的、需要回归的任务。
#:
#: 因此把它们**登记冻结**而不是删除或假装合规：
#:   * 新增的根级受管文件仍然会被拦（本集合是常量，不随仓库内容变化）；
#:   * `main()` 每次都会把这些条目作为「待归位存量」打印出来，不静默腐烂。
#:
#: 注：`V18_σèƒΦâ╜σñìµá╕µèÑσæè.md` 的文件名本身就是**乱码**（UTF-8 文件名被按
#: CP437 解释后的产物，原意为「V18_功能复核报告.md」）。重命名属破坏性操作，
#: 此处如实按现有字节登记，问题本身记录在案待单独处理。
LEGACY_ROOT_FILES = {
    "CCF2026_SHOWCASE_GUIDE.md",
    "FRONTEND_REDESIGN_2026.md",
    "training_results_bc.json",
    "training_results_pure.json",
    "V18_σèƒΦâ╜σñìµá╕µèÑσæè.md",
    "V19_验收结果与运行说明.md",
    "V20_贡献与共识业务联动说明.md",
    "V21_协作多智能体与区块链融合说明.md",
    "V21_测试记录.md",
    "V22_多智能体与区块链联动说明.md",
    "V23_登录注册界面重设计说明.md",
    "V24_统一图标主题说明.md",
    "V25_共识精简与功能联动说明.md",
    "V26_可信协作流程可视化与审计中心说明.md",
    "V27_全模块系统审查与验收说明.md",
}

#: 视为「变更」的 diff 类型：新增 / 复制 / 修改 / 重命名。
#: 只取 A 会漏掉 `git mv docs/x.md ./x.md`（R）——而这正是根级平铺最常见的成因。
DIFF_FILTER = "ACMR"


def split_z(raw: bytes) -> List[str]:
    """解析 ``git ... -z`` 的 NUL 分隔输出。文件名可含空格、制表符甚至换行。"""
    text = raw.decode("utf-8", "surrogateescape")
    return [item for item in text.split("\0") if item]


def _git(args: List[str], cwd: Optional[str] = None) -> Tuple[List[str], str]:
    """跑 git 并返回 ``(路径列表, 错误说明)``。错误说明非空 ⇒ 调用方必须判失败。

    此前用 ``subprocess.check_output(..., stderr=DEVNULL)`` 再把异常一口吞掉，
    stderr 被扔掉后连「not a git repository」都看不到。
    """
    cmd = ["git", "-c", "core.quotePath=false"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, cwd=cwd)
    except OSError as exc:
        return [], f"无法执行 git：{exc}"
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.decode("utf-8", "replace").splitlines()
                 if ln.strip()]
        # git 的用法提示会刷几十行，真正的原因在 "fatal:"/"error:" 那行
        detail = next((ln for ln in lines if ln.startswith(("fatal:", "error:"))),
                      lines[0] if lines else "无错误输出")
        return [], f"git 退出码 {proc.returncode}：{detail}"
    return split_z(proc.stdout), ""


def staged_changed_files(cwd: Optional[str] = None) -> Tuple[List[str], str]:
    """本次暂存的变更文件（新增/复制/修改/重命名），相对仓库根。"""
    return _git(["diff", "--cached", "--name-only", "-z", f"--diff-filter={DIFF_FILTER}"], cwd=cwd)


def all_tracked_files(cwd: Optional[str] = None) -> Tuple[List[str], str]:
    return _git(["ls-files", "-z"], cwd=cwd)


def normalize(path: str) -> str:
    """统一分隔符并去掉 ``./`` 前缀 —— 否则 ``./stray.md`` 会被当成「在子目录里」。"""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def violations_for(path: str) -> Optional[str]:
    """返回违规描述，None=合规。"""
    p = normalize(path)
    if "/" not in p:
        # 根级平铺文件
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
        if ext in MANAGED_EXT and p not in ROOT_ALLOW and p not in LEGACY_ROOT_FILES:
            return f"根级平铺文件 {p!r} 不在白名单，请移入对应子目录（docs/ deliverables/ data/ 等）"
    return None


def decide_exit(files: List[str], error: str, strict: bool) -> Tuple[int, str]:
    """唯一的判定入口（纯函数，便于自证与变异测试）。"""
    if error:
        return 2, f"环境错误：{error} —— 一个文件都没检查，不等于结构合规"
    if not files:
        if strict:
            return 2, "零个文件被检查 —— 什么都没查不等于通过（--strict）"
        return 0, "零个变更文件（未启用 --strict，不判失败）"
    return 0, ""


# --------------------------------------------------------------------------- #
# 自证：临时目录现造样本，证明三处失明都被堵上
# --------------------------------------------------------------------------- #
def run_self_test(verbose: bool = True) -> int:
    import tempfile

    failures: List[str] = []
    passed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            if verbose:
                print(f"[自证] {name:<28} → ok {detail}")
        else:
            failures.append(f"{name}: {detail or '断言失败'}")
            print(f"[自证] {name:<28} → FAIL {detail}")

    # ① 根级判定
    check("root_flat_violation", violations_for("stray_notes.md") is not None)
    check("dot_slash_still_flat", violations_for("./stray_notes.md") is not None)
    check("allowlist_pass", violations_for("README.md") is None)
    check("legacy_pass", violations_for("V19_验收结果与运行说明.md") is None)
    check("subdir_pass", violations_for("docs/notes.md") is None)
    check("unmanaged_ext_pass", violations_for("run.py") is None)

    # ② NUL 切分：含换行的文件名不得被切成两条
    got = split_z("a\nb.md\0c.md\0".encode("utf-8"))
    check("z_split_keeps_newline", got == ["a\nb.md", "c.md"], str(got))

    # ③ 真跑 git：重命名到根级必须被看见
    with tempfile.TemporaryDirectory(prefix="structure_guard_selftest_") as tmp:
        root = Path(tmp)
        ok_env = True
        for c in (["git", "init", "-q"],
                  ["git", "config", "user.email", "selftest@example.invalid"],
                  ["git", "config", "user.name", "selftest"]):
            proc = subprocess.run(c, cwd=str(root), capture_output=True)
            if proc.returncode != 0:
                ok_env = False
                break
        check("git_available", ok_env, "" if ok_env else "git 不可用（本机/CI 缺 git）")

        if ok_env:
            (root / "data").mkdir()
            (root / "data" / "report.md").write_text("# 报告\n", encoding="utf-8")
            for c in (["git", "add", "-A"], ["git", "commit", "-qm", "add data/report.md"]):
                subprocess.run(c, cwd=str(root), capture_output=True)
            mv = subprocess.run(["git", "mv", "data/report.md", "report.md"],
                                cwd=str(root), capture_output=True)
            check("git_mv_ok", mv.returncode == 0,
                  mv.stderr.decode("utf-8", "replace").strip()[:60])

            staged, err = staged_changed_files(cwd=str(root))
            check("rename_into_root_seen",
                  not err and staged == ["report.md"], str(staged))
            check("rename_into_root_is_violation",
                  any(violations_for(f) for f in staged), str(staged))

            # 「只取 A」的旧规则看到的文件数（回归对照：0 个）
            only_a, _ = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=A"],
                             cwd=str(root))
            check("a_only_would_miss", only_a == [], str(only_a))

    # ④ 环境错误必须判失败（退出码 2，不再是 0）
    check("git_error_blocks", decide_exit([], "fatal: not a git repository", False)[0] == 2)
    check("strict_zero_blocks", decide_exit([], "", True)[0] == 2)
    check("zero_nonstrict_passes", decide_exit([], "", False)[0] == 0)
    check("clean_passes", decide_exit(["docs/a.md"], "", True)[0] == 0)

    total = passed + len(failures)
    if failures:
        for item in failures:
            print(f"❌ [自证失败] {item}")
        print(f"❌ 自证失败 {len(failures)}/{total} 项")
        return 1
    print(f"✅ 自证通过 {passed}/{total}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="目录结构守卫（fail-closed）")
    parser.add_argument("--all", action="store_true", help="检查全部已跟踪文件（默认只查本次变更）")
    parser.add_argument("--strict", action="store_true", help="零个文件被检查时判失败")
    parser.add_argument("--self-test", action="store_true", help="内置夹具自证")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    files, error = all_tracked_files() if args.all else staged_changed_files()
    files = [normalize(f) for f in files]

    code, msg = decide_exit(files, error, args.strict)
    if code:
        print(f"❌ 结构守卫：{msg}")
        return code
    if not files:
        print(f"✅ 结构守卫通过（{msg}）")
        return 0

    bad = []
    for f in files:
        v = violations_for(f)
        if v:
            bad.append(v)

    legacy = sorted(f for f in files if f in LEGACY_ROOT_FILES)
    scope = "全部已跟踪文件" if args.all else "本次变更文件"

    if bad:
        print(f"❌ 目录结构守卫：以下文件违规平铺（检查范围：{scope} {len(files)} 个）")
        for v in bad:
            print(f"  {v}")
        return 1

    # 存量不静默：每次都报出来，避免"登记完就忘"
    if legacy:
        print(f"⚠️ 根级存量文档 {len(legacy)} 个（已冻结豁免，待归位 docs/）：")
        for f in legacy:
            print(f"  {f}")

    print(f"✅ 结构守卫通过（检查范围：{scope} {len(files)} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
