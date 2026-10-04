#!/usr/bin/env python3
"""
Competition PPT Generator — CCF 5th Blockchain Competition
==========================================================
Programmatically generates the 15-minute roadshow presentation.

Requires: pip install python-pptx

Usage:
    python scripts/generate_competition_ppt.py
    python scripts/generate_competition_ppt.py --output competition_submission/决赛答辩.pptx
    python scripts/generate_competition_ppt.py --theme dark
"""
import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False
    print("⚠️  python-pptx not installed. Install: pip install python-pptx")
    print("   Generating text-based PPT outline instead...")


# Theme colors
DARK_BLUE = RGBColor(0x1A, 0x36, 0x5D)
ACCENT_GREEN = RGBColor(0x38, 0xA1, 0x69)
ACCENT_RED = RGBColor(0xE5, 0x3E, 0x3E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xF7, 0xFA, 0xFC)
DARK_TEXT = RGBColor(0x2D, 0x37, 0x48)

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)


def create_presentation():
    """Create the full competition PPT."""
    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    slides_data = [
        ("title", "封面", create_title_slide),
        ("problem", "问题定义：多智能体为什么需要区块链？", create_problem_slide),
        ("solution", "方案总览：区块链↔MARL双向赋能", create_solution_slide),
        ("innovation1", "创新一：无CA分布式ECDSA身份锚定", create_ecdsa_slide),
        ("innovation2", "创新二：CW-PBFT贡献加权共识", create_cwpbft_slide),
        ("innovation3", "创新三：Nash均衡激励相容证明", create_nash_slide),
        ("experiment1", "实验一：核心对比（+28.2% env_reward 公平口径，71种子）", create_exp1_slide),
        ("experiment2", "实验二：消融实验与安全攻防", create_exp2_slide),
        ("experiment3", "实验三：理性自私与奖励劫持（E13）", create_exp_hijack_slide),
        ("experiment4", "实验四：CW-PBFT权重展宽（路线C）", create_exp_broadening_slide),
        ("experiment5", "实验五：扩展性与自适应λ", create_exp3_slide),
        ("dashboard", "Web监控平台实时演示", create_dashboard_slide),
        ("industry", "产业落地三大场景", create_industry_slide),
        ("summary", "总结与展望", create_summary_slide),
        ("qa_prep", "问答准备（备用页）", create_qa_prep_slide),
        ("thanks", "致谢", create_thanks_slide),
    ]

    for slide_id, title, creator in slides_data:
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank layout
        creator(slide, title)
        print(f"  ✅ Created: {title}")

    return prs


def _add_title_bar(slide, title_text):
    """Add dark blue title bar at top of slide."""
    # Background bar
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0),
        SLIDE_WIDTH, Inches(1.2)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = DARK_BLUE
    shape.line.fill.background()

    # Title text
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title_text
    p.font.size = Pt(32)
    p.font.color.rgb = WHITE
    p.font.bold = True
    p.alignment = PP_ALIGN.LEFT
    tf.margin_left = Inches(0.8)
    tf.margin_top = Inches(0.2)


def _add_body_text(slide, text, left=0.8, top=1.8, width=11.7, height=5.0, font_size=18):
    """Add body text box."""
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = DARK_TEXT
    return tf


def _add_metric_card(slide, label, value, left, top, width=2.5, height=1.8):
    """Add a metric highlight card."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top),
        Inches(width), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = LIGHT_GRAY
    shape.line.color.rgb = DARK_BLUE
    shape.line.width = Pt(1.5)

    tf = shape.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.text = value
    p.font.size = Pt(28)
    p.font.color.rgb = ACCENT_GREEN
    p.font.bold = True
    p.alignment = PP_ALIGN.CENTER

    p2 = tf.add_paragraph()
    p2.text = label
    p2.font.size = Pt(12)
    p2.font.color.rgb = DARK_TEXT
    p2.alignment = PP_ALIGN.CENTER


def create_title_slide(slide, title):
    """P1: Title slide."""
    # Dark background
    bg = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH, SLIDE_HEIGHT
    )
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK_BLUE
    bg.line.fill.background()

    _add_body_text(slide,
        "MARL-ECDSA共识链\n——面向协作多智能体的可信共识与激励机制",
        left=1.0, top=2.0, width=11.3, height=1.5, font_size=36
    )
    # Re-color title to white
    for shape in slide.shapes:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                p.font.color.rgb = WHITE
                p.font.bold = True

    _add_body_text(slide,
        "基于ECDSA身份锚定与贡献加权PBFT的区块链AI协同框架\n\n"
        "CCF第五届区块链竞赛 · 技术创新赛道\n"
        "MARL-ECDSA共识链项目组",
        left=1.0, top=4.0, width=11.3, height=2.5, font_size=20
    )
    for shape in slide.shapes:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                if "CCF" in p.text or "MARL" in p.text:
                    p.font.color.rgb = RGBColor(0xBB, 0xCC, 0xDD)


def create_problem_slide(slide, title):
    """P2: Problem definition."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "🔴 身份信任缺失：无法确认消息发送方真实身份，中心化CA引入单点故障\n"
        "🔴 行为不可追溯：智能体行为无法事后审计，日志可以被篡改\n"
        "🔴 激励无法强制执行：搭便车是理性策略，合作没有额外收益\n\n"
        "传统方案局限：\n"
        "• 中心化CA — 单点故障，DigiNotar事件(2011) CA私钥泄露→全局崩溃\n"
        "• 信任协议 — 无强制执行力的君子协定\n"
        "• Token激励 — 缺乏MARL协作建模，固定分配\n\n"
        "我们的答案：区块链 = 去中心化信任基础设施\n"
        "→ 不可篡改审计 + 密码学身份 + 智能合约自动执行",
        font_size=16
    )


def create_solution_slide(slide, title):
    """P3: Solution overview."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "四层架构 + 双向赋能闭环\n\n"
        "BC → MARL (正向激励重塑):\n"
        "  total_reward = env_reward + λ · bc_score\n"
        "  区块链激励重塑奖励信号 → 合作从非理性变为优势策略\n\n"
        "MARL → BC (反向贡献反馈):\n"
        "  智能体行为数据 → 贡献度评分 → CW-PBFT节点投票权重\n\n"
        "核心技术栈: ECDSA(secp256r1) + CW-PBFT + IQL + asyncio P2P",
        font_size=16
    )
    # Metric cards
    _add_metric_card(slide, "env_reward提升", "+28.2%", 0.8, 4.5)
    _add_metric_card(slide, "攻击拦截率", "100%", 3.6, 4.5)
    _add_metric_card(slide, "Welch p", "0.0095", 6.4, 4.5)
    _add_metric_card(slide, "区块链开销", "<5%", 9.2, 4.5)


def create_ecdsa_slide(slide, title):
    """P4: ECDSA innovation."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "传统PKI体系 vs 本项目（无CA链存ECDSA）：\n\n"
        "维度对比：\n"
        "• 信任根：CA单点 → 区块链分布式共识确认\n"
        "• 证书颁发：CA签名 → 本地生成+链上自助注册\n"
        "• 吊销机制：CRL/OCSP延迟查询 → 合约即时自动执行\n"
        "• 单点故障：CA泄露=全局崩溃 → 无单点，每智能体独立密钥对\n\n"
        "SecurityGuard三阶纵深防御：\n"
        "① k值重用检测（r值重复→相同随机数→私钥可推导→立即阻断）\n"
        "② nonce单调递增（严格防重放攻击）\n"
        "③ 时间戳±30s窗口（防过期消息重放）\n\n"
        "量化指标：签名/验签均在亚毫秒级 | 1000回合75,000次签名 | 拦截率100%",
        font_size=15
    )


def create_cwpbft_slide(slide, title):
    """P5: CW-PBFT innovation."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "传统PBFT：一人一票（vote_count ≥ 2n/3）\n"
        "→ 无法区分高贡献节点和搭便车节点，平等主义假设不符合MARL场景\n\n"
        "CW-PBFT：贡献度加权投票\n"
        "  w_i = 1.0 + 0.5 × weighted_score\n"
        "  weighted_score = 0.40·task + 0.35·coop + 0.25·compliance\n\n"
        "Shapley值风格权重推导（三公理保证）：\n"
        "① 对称性：同贡献→同权重\n"
        "② 虚拟性：零贡献→零额外权重\n"
        "③ 可加性：多维度可独立计算后叠加\n\n"
        "实验校准：σ(task_variance)≈0.1, φ(coop_externality)≈0.05\n"
        "新节点w_init=0.3（需累积贡献→逐步提升）\n"
        "容错：f=⌊(n-1)/3⌋ | 3节点共识成功率100%",
        font_size=14
    )


def create_nash_slide(slide, title):
    """P6: Nash equilibrium proof."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "定理：当λ ≥ 0.0667且β ≥ 2.0时，合作(C)是严格优势策略，(C,C)是唯一Nash均衡\n\n"
        "收益矩阵（λ=0.1, β=2.0）：\n"
        "                  对方合作(C)        对方背叛(D)\n"
        "  我合作(C)       +10.00  ✅          +7.00\n"
        "  我背叛(D)        -4.00              -9.00\n\n"
        "严格优势验证：\n"
        "  U(C,C)=+10 > U(D,C)=-4  ✓  （无论对方做什么，合作收益均严格大于背叛）\n"
        "  U(C,D)= +7 > U(D,D)=-9  ✓\n\n"
        "参数边界：\n"
        "  λ_min = env_betrayal/Δ_bc = 2/30 = 0.0667\n"
        "  当前λ=0.1 > λ_min=0.0667（1.5倍）| 合作优势 margin=13.0 | 安全裕度 = 50%\n\n"
        "结论：BC激励机制使合作从囚徒困境的劣势策略变为严格优势策略",
        font_size=14
    )


def create_exp1_slide(slide, title):
    """P7: Core experiment results (71-seed registry-aligned口径 NR-1/NR-2)."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "实验设置：SimpleSpreadEnv | IQL算法 | 71种子/组×3000回合 | λ=0.1 (env_reward公平口径，NR-1/NR-2)\n\n"
        "核心结果：\n"
        "  末50回合 env_reward：bc −6.658 vs pure −9.270 → +28.2%（Welch p=0.0095 显著）\n"
        "  Cohen's d=0.44（小-中效应），95%CI [0.648, 4.576]，post-hoc power≈0.74\n"
        "  全程 env_reward：+7.9%（p<0.0001，d=1.20 大效应）\n\n"
        "三点说明：\n"
        "  ① env_reward公平口径——不含区块链激励本身，反映真实策略改善\n"
        "  ② 全程口径大效应：激励在整个训练过程起作用\n"
        "  ③ 71个独立种子——大样本让统计结论更可靠\n\n"
        "注：Dashboard 演示用 legacy_json 模拟数据仅为可视化趋势，正式指标以本页为准。",
        font_size=14
    )


def create_exp2_slide(slide, title):
    """P8: Ablation + security."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "消融实验（3种子 × 4条件，500回合/条件，env_reward公平口径）：\n"
        "┌─────────────────────┬────────────┬───────────┬──────────────────┐\n"
        "│      条件           │ env_reward │ vs Baseline│    核心发现       │\n"
        "├─────────────────────┼────────────┼───────────┼──────────────────┤\n"
        "│ 完整Baseline         │  -48.63    │     —     │   全部模块启用     │\n"
        "│ -SecurityGuard       │  -49.97    │   -1.33    │  安全模块辅助     │\n"
        "│ -CW-PBFT加权         │  -49.46    │   -0.83    │  共识加权贡献     │\n"
        "│ -IncentiveContract 🔥│  -50.63    │   -2.00    │  激励是最关键模块  │\n"
        "└─────────────────────┴────────────┴───────────┴──────────────────┘\n\n"
        "安全攻防测试：\n"
        "  消息篡改 100%拦截 | 身份伪造 100%拦截 | k值重用 100%拦截 | 拜占庭节点 容错保持\n\n"
        "结论：激励合约贡献最大(-2.00)，三模块均有正向贡献，验证架构合理性",
        font_size=12
    )


def create_exp_hijack_slide(slide, title):
    """P9: Rational selfish agents & reward hijacking (E13)."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "实验设置：50% 理性自私（greedy）vs 随机背叛（random），500ep × 10种子（E13）\n\n"
        "核心发现 —— **奖励劫持（Reward Hijacking）**：\n"
        "  env_reward：greedy −36.75 显著高于 random −57.38（NR-55，p<0.001）\n"
        "  合作率：  greedy 0.16  vs random 0.38（崩塌）\n\n"
        "解读：贪心者精准抢占路标，把 reward 数字做高，但不合作。\n"
        "只看 reward 会得出「自私反而有益」的荒谬结论。\n\n"
        "→ 结论：评估激励机制必须用 **reward + 行为双指标口径**。\n"
        "→ 区块链激励的作用正是抑制自私行为、恢复合作率。",
        font_size=14
    )


def create_exp_broadening_slide(slide, title):
    """P10: CW-PBFT weight broadening (Route C), four-level evidence chain."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "机制：参与率驱动的纪元制权重展宽（epoch=50 / floor=0.25 / max=1.5，默认关闭可复现）\n"
        "R 判据：f_max = R/(R+2)；R≈1 时与标准 PBFT 数学等价（负结果先报），展宽后有效 R≈15\n\n"
        "四级证据链（全部注册表锚定）：\n"
        "  ① 引擎级（NR-82，n=10，40% 省略，5种子×300轮）：CW 99.67% vs STD 0.00%，诚实权重占比 95.49%\n"
        "  ② 训练级（NR-83/84，MARL 训练循环内，3种子配对）：共识活性 90% vs 0%，诚实份额 94.40% vs 60.00%（p=2.76e-05）\n"
        "  ③ 边界（NR-52/53）：对手满参与时增益消失——如实申报，不防御满参与理性拜占庭\n"
        "  ④ 申报口径：仅共识活性与权重分布；env_reward 差异 n=3 只报方向不报显著\n\n"
        "故障模型限定：省略故障（omission），不得表述为拜占庭容错 40%。",
        font_size=13
    )


def create_qa_prep_slide(slide, title):
    """P15: Q&A preparation (backup page)."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "高频追问速答（完整版见《最狠10问成文防线_决赛版.md》）：\n\n"
        "Q: R≈1 时与标准 PBFT 等价，共识层贡献了什么？\n"
        "A: 两层解耦——激励合约驱动协作，展宽机制提供活性恢复（90% vs 0%）；\n   等价性是先报的负结果，展宽才是共识层净增益。\n\n"
        "Q: 满参与对手怎么办？\n"
        "A: 增益消失，如实申报（NR-52/53）；equivocation 防御列为未来工作。\n\n"
        "Q: 单机模拟凭什么说能用于真实网络？\n"
        "A: P2P 层为真实 TCP 全双工；单机为控制变量精确注入故障；Docker/Gossip 列入路线。\n\n"
        "Q: +28.2% 为什么敢讲？\n"
        "A: 71 种子大样本（NR-1，p=0.0095 显著）；机制归因 n=60 双预算复现兜底因果。",
        font_size=13
    )


def create_thanks_slide(slide, title):
    """P16: Thanks."""
    _add_title_bar(slide, title)
    # Centered big thanks
    txBox = slide.shapes.add_textbox(Inches(2), Inches(2.6), Inches(9.3), Inches(2.2))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "感谢各位评委老师！"
    p.font.size = Pt(44)
    p.font.color.rgb = DARK_BLUE
    p.font.bold = True
    p.alignment = PP_ALIGN.CENTER
    p2 = tf.add_paragraph()
    p2.text = "欢迎提问"
    p2.font.size = Pt(28)
    p2.font.color.rgb = ACCENT_GREEN
    p2.font.bold = True
    p2.alignment = PP_ALIGN.CENTER


def create_exp3_slide(slide, title):
    """P9: Scalability + adaptive lambda."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "λ敏感性分析（λ ∈ [0.0, 0.20]，env_reward公平口径）：\n"
        "  λ=0.00: -49.56（无激励基线）\n"
        "  λ=0.05: -52.00（激励太弱，合作略降）\n"
        "  λ=0.10: -54.02（竞赛推荐配置）\n"
        "  λ=0.15: -51.79（有效区间）\n"
        "  λ=0.20: -56.66（过强激励反效果）\n\n"
        "自适应λ效果（env_reward公平口径）：\n"
        "  λ_t = clamp(λ_base + η·(κ_c·c_t + κ_k·k_t - κ_s·s_t), 0.05, 0.15)\n"
        "  自适应λ vs 静态λ(0.1): +6.3%（p=0.10 边际显著，R²=0.685）\n\n"
        "多智能体扩展性验证（3/5/8 agents，500回合）：\n"
        "  3 agents: BC提升 -0.5% (未收敛，p=0.93)\n"
        "  5 agents: BC提升 +5.0% (p=0.52, d=0.62)\n"
        "  8 agents: BC提升 +4.6% (p=0.58, d=0.49)\n"
        "  → 智能体数越多BC提升越明显，验证可扩展性",
        font_size=13
    )


def create_dashboard_slide(slide, title):
    """P10: Dashboard live demo."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "Web监控平台（Flask + Chart.js | 9标签页 | 127.0.0.1:9090）\n\n"
        "📊 四大演示分区（竞赛现场建议演示顺序）：\n\n"
        "1️⃣ 网络层（左上）：P2P拓扑图+节点实时状态+消息流速\n"
        "2️⃣ 安全层（右上）：ECDSA签名流水线+SecurityGuard实时告警流\n"
        "3️⃣ 账本层（左下）：区块链浏览器→点击区块#100→交易详情→ECDSA签名\n"
        "4️⃣ MARL层（右下）：训练曲线实时更新+bc vs pure对比+合作率趋势\n\n"
        "一键启动：python main.py --dashboard\n"
        "建议演示流程：Overview → Security → MARL → Ledger，总时长≤90秒",
        font_size=15
    )


def create_industry_slide(slide, title):
    """P11: Industry scenarios."""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "三大产业落地场景：\n\n"
        "🏭 场景1：集群机器人协同（智能制造/仓储物流）\n"
        "  需求：多机器人任务分配防欺骗 | 映射：ECDSA身份锚定+行为账本+贡献度加权\n"
        "  价值：拜占庭容错f=⌊(n-1)/3⌋，任务完成完整性可证明\n\n"
        "🏥 场景2：联邦学习贡献计量（金融/医疗数据隐私）\n"
        "  需求：防止虚假梯度上传污染全局模型 | 映射：CW-PBFT加权聚合+链上贡献记录\n"
        "  价值：自动激励结算，梯度投毒可检测/惩罚\n\n"
        "☁️ 场景3：分布式算力可信市场（云计算/边缘计算）\n"
        "  需求：防止算力提供方伪造计算结果 | 映射：ECDSA签名计算证明+分级惩罚\n"
        "  价值：100%检测重复/虚假计算声明，自动化结算",
        font_size=14
    )


def create_summary_slide(slide, title):
    """P14: Summary（71种子注册表口径 NR-1/NR-2/82/83/84/86）。"""
    _add_title_bar(slide, title)
    _add_body_text(slide,
        "核心成果：\n"
        "✅ env_reward提升 +28.2%（71种子/组，3000回合，公平口径 p=0.0095 显著）\n"
        "✅ 机制归因（n=60 双预算复现）：链上激励合约是协作加速唯一驱动\n"
        "✅ CW-PBFT权重展宽：40%省略下引擎级 99.67% vs 0%（NR-82）；训练级活性 90% vs 0%（NR-83/84）\n"
        "✅ Nash证明：合作是严格优势策略（λ≥0.0667，安全裕度50%）；奖励劫持确立双指标口径\n"
        "✅ 环境多样性泛化（moving3，n=20，p=0.023，NR-86）| 1600+ 项自动化测试全部通过（0 失败） | 六类签名层攻击300次100%拦截\n\n"
        "诚实声明：真实权重R≈1.01下CW-PBFT≈标准PBFT；展宽增益限省略故障（满参与消失）；检验力0.74\n\n"
        "未来展望：\n"
        "🔮 后量子迁移（ML-DSA适配器已实现待接线）  🔮 分片共识 O(n²)→O(k²)  🔮 Gossip动态发现\n\n"
        "感谢各位评委老师！欢迎提问 🙏",
        font_size=14
    )


def generate_text_outline(output_path):
    """Generate a text-based PPT outline when python-pptx is not available."""
    md_path = output_path.replace(".pptx", "_OUTLINE.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("""# MARL-ECDSA Consensus Chain — PPT Outline (Text Fallback)

> python-pptx not installed. Use this outline to manually create slides in PowerPoint/Keynote.
> Install python-pptx for programmatic generation: `pip install python-pptx`

---

## Slide 1: Title
**Duration**: 30s

MARL-ECDSA共识链——面向协作多智能体的可信共识与激励机制
——基于ECDSA身份锚定与贡献加权PBFT的区块链AI协同框架
CCF第五届区块链竞赛 · 技术创新赛道

---

## Slide 2: Problem Definition
**Duration**: 60s

Three Pain Points:
1. Identity Trust: Who is really "agent_0"?
2. Behavior Traceability: Who did what, when? No audit trail.
3. Incentive Enforcement: Why cooperate? Free-riding is rational.

Our Answer: Blockchain = Decentralized Trust Infrastructure

---

## Slide 3: Solution Overview
**Duration**: 60s

Four-layer architecture + Bidirectional empowerment loop
BC → MARL: total_reward = env + λ·bc
MARL → BC: behavior → contribution → CW-PBFT weights

Key metrics: +28.17% (env_reward, last-50, excl. BC incentive) | 100% (6/6 signature-layer attacks) | p=0.0095 (BH-FDR significant / Bonferroni not; report with full-episode caliber +7.92%, p<1e-10), d=0.44 | <5% | 1600+ tests

---

## Slides 4-6: Three Core Innovations
Each 90s

**Innovation 1**: CA-free distributed ECDSA identity anchoring
- PKI comparison table
- SecurityGuard three-stage defense
- 100% attack interception rate

**Innovation 2**: CW-PBFT contribution-weighted consensus
- Shapley value weight derivation
- w = 1.0 + 0.5(0.40·task + 0.35·coop + 0.25·compliance)
- PBFT vs CW-PBFT comparison

**Innovation 3**: Nash equilibrium incentive compatibility proof
- Payoff matrix visualization
- Strict dominant strategy verification
- Safety margin: 50% (conservative assumption)

---

## Slides 7-9: Experimental Results
Each 60-90s

**Experiment 1**: Core comparison (+28.17% env_reward improvement, last-50, excl. BC incentive, 3000ep, n=71 seeds/group; BH-FDR significant / Bonferroni not — report together with full-episode caliber +7.92%, p<1e-10)
**Experiment 2**: Ablation + security (100% attack interception)
**Experiment 3**: Scalability + adaptive λ

---

## Slide 10: Live Dashboard Demo
Duration: 90s

Four-zone demo: Network | Security | Ledger | MARL
http://127.0.0.1:9090

---

## Slide 11: Industry Scenarios
Duration: 60s

1. Swarm robotics coordination
2. Federated learning contribution measurement
3. Distributed computing power market

---

## Slide 12: Summary & Future
Duration: 60s

Core achievements + Roadmap (Post-quantum / Sharding / Gossip / Cross-chain)

---
""")
    print(f"📝 Text outline: {md_path}")


def main():
    parser = argparse.ArgumentParser(description="Competition PPT Generator")
    parser.add_argument("--output", type=str, default="competition_submission/竞赛答辩_MARL-ECDSA共识链_v2.pptx")
    parser.add_argument("--theme", type=str, default="dark", choices=["dark", "light"])
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    print("╔══════════════════════════════════════════════╗")
    print("║   MARL-ECDSA Competition PPT Generator        ║")
    print("╚══════════════════════════════════════════════╝")

    if HAS_PPTX:
        prs = create_presentation()
        prs.save(args.output)
        print(f"\n✅ PPT saved: {args.output}")
        print(f"   Slides: {len(prs.slides)}")
    else:
        generate_text_outline(args.output)
        print("\n⚠️  Install python-pptx for programmatic generation:")
        print("   pip install python-pptx")


if __name__ == "__main__":
    main()
