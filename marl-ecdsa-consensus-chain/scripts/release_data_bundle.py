"""
P0-12 可复现性数据包构建器（工程交付，非提交物打包）

问题：公开仓库 .gitignore 把 results/ 全部排除，评委 clone 后无法复算任何 NR 数字。
修复：把**真实**的逐种子实验结果打包成 tar.gz，由维护者挂到 GitHub Release。
      评审判官解压到仓库根目录后即可一键复算。包含两组数据：
      - results/convergence_3000/*.json   —— 主实验（n=71/臂，NR-1~NR-4 等主口径）
      - results/training_broadening_e2e/*.json —— 训练级权重展宽（NR-83/NR-84）

安全铁律：
- 本脚本**绝不编造数据**。只打包磁盘上真实存在的实验结果文件。
- 若 results/convergence_3000 缺失或为空，直接拒绝退出（exit 2），不生成空包。
- results/training_broadening_e2e 缺失时同样拒绝构建（exit 2）——宁可不发包，
  也不发一个"正文引用了却复现不出"的包。
- 不改动 .gitignore，不触碰冻结的提交物；产物落在 release_artifacts/（应 gitignore）。
- 不依赖任何合成/随机生成；与 scripts/generate_complete_data.py（合成数据，已弃用）绝缘。

用法：
  python scripts/release_data_bundle.py                # 构建默认 tar.gz
  python scripts/release_data_bundle.py --check-only  # 仅校验源数据完整性，不写包
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "results", "convergence_3000")
# 训练级权重展宽实验（NR-83/NR-84 数据源）：共识活性 90% vs 0%、诚实份额 94.40% vs 60%
SRC_DIR_BROAD = os.path.join(ROOT, "results", "training_broadening_e2e")
OUT_DIR = os.path.join(ROOT, "release_artifacts")
OUT_NAME = "marl_ecdsa_repro_data.tar.gz"


def _sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def collect():
    if not os.path.isdir(SRC_DIR):
        print(f"[bundle] 源目录不存在：{SRC_DIR}", file=sys.stderr)
        print("[bundle] 拒绝构建空包。请确认真实实验数据已落盘。", file=sys.stderr)
        sys.exit(2)
    files = sorted(
        f for f in os.listdir(SRC_DIR)
        if f.endswith(".json") and (f.startswith("bc_marl_seed") or f.startswith("pure_marl_seed"))
    )
    if not files:
        print(f"[bundle] 源目录为空：{SRC_DIR}", file=sys.stderr)
        sys.exit(2)
    bc = [f for f in files if f.startswith("bc_marl_seed")]
    pure = [f for f in files if f.startswith("pure_marl_seed")]
    print(f"[bundle] 扫描到 {len(files)} 个真实种子文件：bc={len(bc)} pure={len(pure)}")

    # 训练级权重展宽（NR-83/NR-84）：缺失或为空同样拒绝构建，避免发出不可复现的包
    if not os.path.isdir(SRC_DIR_BROAD):
        print(f"[bundle] 权重展宽源目录不存在：{SRC_DIR_BROAD}", file=sys.stderr)
        print("[bundle] 拒绝构建不完整包。", file=sys.stderr)
        sys.exit(2)
    broad = sorted(
        f for f in os.listdir(SRC_DIR_BROAD)
        if f.endswith(".json") and (f.startswith("on_seed") or f.startswith("off_seed"))
    )
    if not broad:
        print(f"[bundle] 权重展宽源目录为空：{SRC_DIR_BROAD}", file=sys.stderr)
        sys.exit(2)
    print(f"[bundle] 扫描到 {len(broad)} 个权重展宽种子文件（NR-83/NR-84 数据源）")
    return files, bc, pure, broad


def build(check_only=False):
    files, bc, pure, broad = collect()
    total_bytes = 0
    manifest_files = []
    for f in files:
        p = os.path.join(SRC_DIR, f)
        sz = os.path.getsize(p)
        total_bytes += sz
        manifest_files.append({"name": f, "bytes": sz, "sha256": _sha256(p)})

    broadening_files = []
    for f in broad:
        p = os.path.join(SRC_DIR_BROAD, f)
        sz = os.path.getsize(p)
        total_bytes += sz
        broadening_files.append({"name": f, "bytes": sz, "sha256": _sha256(p)})

    manifest = {
        "artifact": "MARL-ECDSA reproducibility data (convergence_3000 + training_broadening_e2e)",
        "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "source_commit": _git_commit(),
        "n_bc": len(bc),
        "n_pure": len(pure),
        "n_broad": len(broad),
        "total_files": len(files) + len(broad),
        "total_bytes": total_bytes,
        "caliber": "n=71/arm, env_reward (不含 BC 激励), lambda_weight=0.1, 3000 episodes, iql, 3 agents",
        "datasets": {
            "results/convergence_3000/": {
                "files": len(files),
                "covers": "主实验口径（NR-1~NR-4 等 n=71 相关条目）",
            },
            "results/training_broadening_e2e/": {
                "files": len(broad),
                "covers": "训练级权重展宽（NR-83 共识活性 90.0% vs 0.0%；NR-84 诚实份额 94.40% vs 60.00%）",
            },
        },
        "files": manifest_files,
        "broadening_files": broadening_files,
        "coverage_note": (
            "本包**不含** champion_20260919（879 MB）与 dispatch_20260921（229 MB）等历史中间数据，"
            "依赖这些目录的早期 NR 条目无法仅凭本包复算；如需可应评审要求单独提供。"
        ),
        "verify_command": "python scripts/verify_numbers.py --registry number_registry.json --data-root results",
        "one_click_command": "python scripts/one_click_reproduce.py",
    }

    reproduce_md = (
        "# 可复现性数据包\n\n"
        "本包包含 MARL-ECDSA 共识链两组**真实**逐种子实验输出：\n\n"
        "### 1) 主实验 `results/convergence_3000/`\n"
        f"- bc_marl 种子数：{len(bc)}\n"
        f"- pure_marl 种子数：{len(pure)}\n"
        "- 每臂 n=71；口径：env_reward（不含 BC 激励），lambda_weight=0.1，3000 回合，IQL，3 智能体。\n"
        "- 覆盖：NR-1~NR-4 等 n=71 相关条目。\n\n"
        "### 2) 训练级权重展宽 `results/training_broadening_e2e/`\n"
        f"- 开展宽（on）{len([f for f in broad if f.startswith('on_seed')])} 个种子、未开展宽（off）"
        f"{len([f for f in broad if f.startswith('off_seed')])} 个种子，共 {len(broad)} 个文件。\n"
        "- 覆盖：NR-83（共识成功率 90.0% vs 0.0%）、NR-84（诚实方权重占比 94.40% vs 60.00%，Welch p=2.76e-05）。\n\n"
        "## 使用方法\n\n"
        "1. 将本包解压到仓库根目录（会重建 `results/convergence_3000/` 与 `results/training_broadening_e2e/`）：\n"
        "   ```bash\n"
        "   tar -xzf marl_ecdsa_repro_data.tar.gz -C <repo-root>\n"
        "   ```\n"
        "2. 复算所有 NR 数字（与 number_registry.json 声明逐一比对）：\n"
        "   ```bash\n"
        "   python scripts/verify_numbers.py --registry number_registry.json --data-root results\n"
        "   ```\n"
        "   退出码语义：`0` 全部通过；`1` 存在数字不符（阻断）；`3` 存在「数据源缺失」条目。\n"
        "   若仅解压本数据包，会有部分条目标记 `DATA_MISSING` 并返回 3 —— 这是预期结果，\n"
        "   含义是「本包不含该条目所需数据」，**不代表数字算错**；可复算条目见输出明细。\n"
        "3. 或一键复现（含测试 + 数字校验）：\n"
        "   ```bash\n"
        "   python scripts/one_click_reproduce.py\n"
        "   ```\n\n"
        "## 口径说明\n\n"
        "- 主结局 NR-1（末 50 回合 env_reward）：bc=-6.66 vs pure=-9.27，Welch p=0.0095，Cohen's d=0.441，n=71/臂。\n"
        "- NR-2（全程 env_reward）：+7.9%，p<1e-10，d=1.20。\n"
        "- NR-3（全程合作率）：0.6246 vs 0.6127，+1.95%，p<1e-10。\n"
        "- 双口径必须同报；BH-FDR 显著、Bonferroni 不显著，已如实披露。\n"
        "- 末 50 合作率（NR-4）不显著（p=0.739），BC 的协作增益主要在训练早期。\n\n"
        "## 覆盖范围（诚实声明）\n\n"
        f"- 本包共 {len(files) + len(broad)} 个数据文件。\n"
        "- **不含** `champion_20260919`（879 MB）与 `dispatch_20260921`（229 MB）等历史中间数据；\n"
        "  依赖这些目录的早期 NR 条目**无法仅凭本包复算**，如需可应评审要求单独提供。\n"
        "- 因此本包可复算范围 = n=71 主口径条目 + NR-83/NR-84，并非「全部 NR 条目」。\n"
    )

    if check_only:
        print(f"[bundle] check-only：源数据完整（{len(files) + len(broad)} 文件，{total_bytes/1e6:.1f} MB）")
        print(f"[bundle] 解压后复算命令：{manifest['verify_command']}")
        return manifest

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, OUT_NAME)

    # 写 manifest / reproduce 到临时文件，一并打进包
    manifest_path = os.path.join(OUT_DIR, "MANIFEST.json")
    reproduce_path = os.path.join(OUT_DIR, "REPRODUCE.md")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(reproduce_path, "w", encoding="utf-8") as f:
        f.write(reproduce_md)

    print(f"[bundle] 正在打包 {len(files) + len(broad)} 文件（主实验 {len(files)} + 权重展宽 {len(broad)}）→ {out_path}")
    with tarfile.open(out_path, "w:gz") as tar:
        # 数据：保持 results/convergence_3000/... 相对仓库根的路径
        for f in files:
            tar.add(os.path.join(SRC_DIR, f), arcname=os.path.join("results", "convergence_3000", f))
        # 训练级权重展宽（NR-83/NR-84 数据源）
        for f in broad:
            tar.add(os.path.join(SRC_DIR_BROAD, f), arcname=os.path.join("results", "training_broadening_e2e", f))
        # 文档：放在包根目录，便于评委解压到仓库根后立即查阅（与 REPRODUCE.md 指引一致）
        tar.add(manifest_path, arcname="MANIFEST.json")
        tar.add(reproduce_path, arcname="REPRODUCE.md")

    out_sz = os.path.getsize(out_path)
    print(f"[bundle] 完成：{out_path}（{out_sz/1e6:.1f} MB）")
    print(f"[bundle] 维护者请将其作为 GitHub Release 附件上传；评委按 REPRODUCE.md 复算。")
    # 清理临时文件
    os.remove(manifest_path)
    os.remove(reproduce_path)
    return manifest


def main():
    ap = argparse.ArgumentParser(description="构建 P0-12 可复现性数据包（仅打包真实实验数据）")
    ap.add_argument("--check-only", action="store_true", help="仅校验源数据完整性，不写包")
    args = ap.parse_args()
    build(check_only=args.check_only)


if __name__ == "__main__":
    main()
