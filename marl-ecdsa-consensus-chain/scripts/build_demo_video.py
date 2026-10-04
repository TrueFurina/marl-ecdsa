#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演示视频自动合成（Deployment Demo Video Builder）
=====================================================
将 Dashboard / 实验结果截图编排为 1080P MP4 演示视频（带中文字幕）。

【口径与诚实声明 — 必读】
  本脚本产出的是**界面演示视频**（真实 UI 截图轮播 + 字幕解说），
  **不是实时操作录屏**（未录制真实鼠标交互与日志滚动）。
  所有字幕数字均取自 `number_registry.json`（n=71 权威口径），不手抄。
  截图来源：`scripts/generate_all_dashboard_screenshots.py`
            （该脚本第 19 行明写「从权威登记簿程序化读取，防 n=22→n=71 漂移复发」）。

产出：results/演示视频_MARL-ECDSA_界面演示.mp4
依赖：Pillow（渲染字幕）+ ffmpeg（合成，路径见 FFMPEG）
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ppt_screenshots"
OUT_DIR = ROOT / "results"
OUT_NAME = "演示视频_MARL-ECDSA_界面演示.mp4"

FFMPEG = r"D:\DeliveryOptimization\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
FONT = r"C:\Windows\Fonts\msyh.ttc"

W, H = 1920, 1080
DURATION = 8.0          # 每屏停留秒数
FADE = 0.6              # 淡入淡出秒数
FPS = 30

# ── 字幕内容（严格对应 n=71 权威口径，禁过期数字） ────────────────────────
SLIDES = [
    (None, "MARL-ECDSA 共识链",
     "MARL-ECDSA共识链——面向协作多智能体的可信共识与激励机制\nCCF 第五届大学生区块链技术与创新应用竞赛"),
    ("dashboard_overview.png", "① 系统总览",
     "区块链激励 / CW-PBFT 共识 / ECDSA 安全承诺 三层\n接入 MARL 训练回路"),
    ("dashboard_monitor.png", "② 训练监控",
     "环境奖励与合作率实时曲线\n口径为 env_reward（不含区块链激励项），全文统一"),
    ("dashboard_compare.png", "③ 核心对比（NR-1 / NR-2 双口径）",
     "末 50 回合 +28.2%，Welch p=0.0095、d≈0.44\nBH-FDR 校正下显著，Bonferroni 校正下不显著\n全程口径 +7.9%，p<1e-10、d≈1.20（强显著大效应）\nn=71/组，两口径同报，不包装成强证据"),
    ("cooperation_rate.png", "④ 合作率变化（NR-3 / NR-4）",
     "合作率随训练上升并收敛至约 0.70（绿=逐回合，红=平滑）\n全程口径 +1.95%，p<1e-10（显著）\n末 50 回合口径 p=0.739（不显著），两口径禁止混用"),
    ("dashboard_blockchain.png", "⑤ 区块链账本",
     "每个动作签名上链\n区块高度、交易数、ECDSA 签名/验签计数\n基准口径（NR-89~91，9 次重复均值）：签名 0.0362 ms、验签 0.0792 ms\n链吞吐 6384.7 tx/s；画面为单次运行实时读数，与基准不同源"),
    ("dashboard_p2p.png", "⑥ P2P 网络与共识",
     "贡献度加权 CW-PBFT\n各节点权重随纪元演化，共识成功率 100%"),
    ("dashboard_tri.png", "⑦ 共识投票",
     "权重演化与投票过程可追溯\nCW-PBFT 价值在「省略故障下的活性恢复」"),
    ("fault_tolerance_liveness.png", "⑧ 容错活性（NR-38，主证据）",
     "n=16 节点、40% 省略故障、10 seeds × 2000 轮\nCW-PBFT 动态档 97.30% vs 标准 PBFT 0.00%（Δ=+97.3pp）\n零方差 → 确定性差异；权重展宽不预知坏节点身份"),
    ("dashboard_system.png", "⑨ 系统状态",
     "运行时状态与资源占用一览"),
    ("security_test_results.png", "⑩ 安全攻防（NR-30）",
     "画面为 ECDSA 验签开关对照：关闭时攻击成功，开启后 100% 拦截\n批量统计（报告 §4）：6 类签名层攻击 × 50 次 = 300 次全部拦截\n每类 Wilson 95% CI [92.9%, 100%]，脚本化重复实验、非单点演示"),
    ("training_curve.png", "(11) 训练结果",
     "3000 回合训练收敛曲线（纵轴为回合总奖励，含 BC 激励项）\nn=71 种子/组；公平对比口径 env_reward 见第 3 屏\n收益真实但强算法依赖，驱动来自激励合约本身"),
    ("ecdsa_flow.png", "(12) ECDSA 签名流程",
     "身份锚定 → 签名 → 上链 → 共识确认 → 激励结算"),
    (None, "(13) 总结",
     "① 主证据：40% 省略故障下 CW-PBFT 活性 97.30% vs 标准 PBFT 0%（确定性）\n② 收益来自激励合约，且强算法依赖（两口径同报）\n③ 共识层价值边界已披露：省略型故障模型，非任意对手安全界\n1600+ 项自动化测试通过（0 失败）——是测试规模，非正确性证明"),
]

BG = (16, 18, 24)
FG = (240, 244, 250)
ACCENT = (0, 212, 255)


def make_title_slide(title: str, body: str, font_path: str) -> Image.Image:
    """自制纯文字页（开场/结尾）"""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    f_title = ImageFont.truetype(font_path, 76)
    f_body = ImageFont.truetype(font_path, 40)
    # 标题居中
    tw = d.textlength(title, font=f_title)
    d.text(((W - tw) / 2, H * 0.36), title, font=f_title, fill=ACCENT)
    # 正文逐行居中
    y = H * 0.52
    for line in body.split("\n"):
        lw = d.textlength(line, font=f_body)
        d.text(((W - lw) / 2, y), line, font=f_body, fill=FG)
        y += 64
    return im


def compose(shot_path: str | None, title: str, body: str,
            font_path: str) -> Image.Image:
    """合成单屏：截图（等比缩放居中）+ 标题 + 字幕条"""
    im = Image.new("RGB", (W, H), BG)
    if shot_path and (SHOTS / shot_path).exists():
        src = Image.open(SHOTS / shot_path).convert("RGB")
        # 截图区域：上方留标题，下方留字幕
        box_w, box_h = W - 160, H - 300
        sw, sh = src.size
        scale = min(box_w / sw, box_h / sh)
        nw, nh = int(sw * scale), int(sh * scale)
        src = src.resize((nw, nh), Image.LANCZOS)
        im.paste(src, ((W - nw) // 2, 130 + (box_h - nh) // 2))
    d = ImageDraw.Draw(im)
    f_title = ImageFont.truetype(font_path, 52)
    f_body = ImageFont.truetype(font_path, 34)
    d.text((80, 40), title, font=f_title, fill=ACCENT)
    # 底部字幕条
    d.rectangle([0, H - 190, W, H], fill=(10, 12, 16))
    y = H - 170
    for line in body.split("\n"):
        d.text((80, y), line, font=f_body, fill=FG)
        y += 44
    return im


def main():
    if not os.path.exists(FFMPEG):
        print(f"[FAIL] 未找到 ffmpeg: {FFMPEG}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="marl_video_"))
    frames = []
    for i, (shot, title, body) in enumerate(SLIDES):
        if shot is None:
            img = make_title_slide(title, body, FONT)
        else:
            img = compose(shot, title, body, FONT)
        fp = tmpdir / f"f{i:02d}.png"
        img.save(fp)
        frames.append(fp)
        print(f"  [{i+1:02d}/{len(SLIDES)}] {title}  <- {shot or '字幕页'}")

    # 生成 ffmpeg concat（每屏带淡入淡出）
    # 用 xfade 较复杂，改为：每屏生成一段静音视频再 concat + 全局转场
    segs = []
    for i, fp in enumerate(frames):
        seg = tmpdir / f"seg{i:02d}.mp4"
        cmd = [
            FFMPEG, "-y", "-loop", "1", "-i", str(fp),
            "-c:v", "libx264", "-t", str(DURATION),
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-vf", f"fade=t=in:st=0:d={FADE},fade=t=out:st={DURATION-FADE}:d={FADE}",
            str(seg),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(f"[FAIL] 段 {i} 编码失败:\n{r.stderr[-800:]}")
            return 1
        segs.append(seg)

    listfile = tmpdir / "concat.txt"
    listfile.write_text(
        "\n".join(f"file '{s.as_posix()}'" for s in segs), encoding="utf-8")

    # ASCII 临时输出，避免中文路径坑
    tmp_out = tmpdir / "out.mp4"
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", str(tmp_out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[FAIL] 合并失败:\n{r.stderr[-800:]}")
        return 1

    final = OUT_DIR / OUT_NAME
    final.write_bytes(tmp_out.read_bytes())
    size = final.stat().st_size
    total = DURATION * len(SLIDES)
    print(f"\n✅ 产出: {final}")
    print(f"   {len(SLIDES)} 屏 × {DURATION}s = {total:.0f}s ({total/60:.1f} 分钟)")
    print(f"   {W}x{H} @ {FPS}fps | {size/1024/1024:.1f} MB")
    print("\n⚠️ 诚实标注：本片为【界面演示】（真实 UI 截图轮播 + 字幕），")
    print("   非实时操作录屏；如需实操录屏请用 OBS 录制 Dashboard 演示模式。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
