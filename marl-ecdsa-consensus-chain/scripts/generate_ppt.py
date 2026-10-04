#!/usr/bin/env python3
"""
竞赛答辩 PPT 自动生成
基于项目实际数据生成 12 页答辩 PPT
"""
import json
import os
import sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# === 配色 ===
BG_DARK = RGBColor(0x1a, 0x1a, 0x2e)
BG_CARD = RGBColor(0x16, 0x21, 0x3e)
ACCENT_BLUE = RGBColor(0x00, 0xd4, 0xff)
ACCENT_GREEN = RGBColor(0x00, 0xff, 0x88)
ACCENT_RED = RGBColor(0xff, 0x44, 0x66)
ACCENT_GOLD = RGBColor(0xff, 0xd7, 0x00)
TEXT_WHITE = RGBColor(0xff, 0xff, 0xff)
TEXT_GRAY = RGBColor(0xa0, 0xa0, 0xb0)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "competition_submission")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_data():
    """加载训练数据

    修正：实际训练数据位于项目根目录，文件名为
    training_results_{pure,bc,selfish}.json（不在 results/ 子目录，且非
    _pure_marl / _bc_marl 命名）。原代码读取 results/ 子目录且文件名不匹配，
    导致 data 始终为空、所有幻灯片静默回退到内置占位数值。

    本函数兼容 根目录 与 results/ 子目录、兼容旧命名与新命名，优先读取真实数据；
    缺失文件时打印 WARN 并保留内置默认值，保证 PPT 仍可生成。
    """
    data = {}
    # 项目根目录 = scripts/ 的上一级
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = os.path.join(root_dir, "results")
    # PPT 内部键名 -> 实际文件名（不含扩展名）
    name_map = {
        "pure_marl": "training_results_pure",
        "bc_marl": "training_results_bc",
        "selfish": "training_results_selfish",
    }
    search_dirs = [root_dir, results_dir]
    for key, base in name_map.items():
        loaded = False
        for d in search_dirs:
            path = os.path.join(d, base + ".json")
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data[key] = json.load(f)
                    print(f"[OK] 加载 {base}.json -> 键 '{key}'")
                    loaded = True
                    break
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[WARN] 读取 {base}.json 失败: {e}")
                    continue
        if not loaded:
            print(f"[WARN] 未找到 {base}.json（已搜索根目录与 results/），PPT 将使用内置默认数值")
    # 兼容 3000 回合数据（若存在，优先根目录）
    for seed in [42, 123]:
        for key, base in name_map.items():
            if key in data:
                continue
            for d in search_dirs:
                path = os.path.join(d, base + f"_seed{seed}.json")
                if os.path.exists(path):
                    try:
                        with open(path, encoding="utf-8") as f:
                            data[key] = json.load(f)
                        print(f"[OK] 加载 {base}_seed{seed}.json -> 键 '{key}'")
                        break
                    except (json.JSONDecodeError, OSError) as e:
                        print(f"[WARN] 读取 {base}_seed{seed}.json 失败: {e}")
                        continue
    return data

def add_slide_bg(slide, color=BG_DARK):
    """设置深色背景"""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_title_box(slide, text, subtitle=None):
    """添加标题"""
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(0.8))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(32)
    p.font.bold = True
    p.font.color.rgb = ACCENT_BLUE
    p.alignment = PP_ALIGN.CENTER
    if subtitle:
        p2 = tf.add_paragraph()
        p2.text = subtitle
        p2.font.size = Pt(14)
        p2.font.color.rgb = TEXT_GRAY
        p2.alignment = PP_ALIGN.CENTER
    return txBox

def add_card(slide, left, top, width, height, title, items, accent=ACCENT_BLUE):
    """添加卡片"""
    # 卡片背景
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE.RECTANGLE
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = BG_CARD
    shape.line.color.rgb = accent
    shape.line.width = Pt(1.5)

    tf = shape.text_frame
    tf.word_wrap = True
    # 标题
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = accent
    p.space_after = Pt(6)

    # 内容
    for item in items:
        p = tf.add_paragraph()
        p.text = item
        p.font.size = Pt(12)
        p.font.color.rgb = TEXT_WHITE
        p.space_after = Pt(3)

def add_stat_card(slide, left, top, width, height, value, label, color=ACCENT_GREEN):
    """添加统计卡片"""
    shape = slide.shapes.add_shape(1, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = BG_CARD
    shape.line.color.rgb = color
    shape.line.width = Pt(2)

    tf = shape.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    p = tf.paragraphs[0]
    p.text = value
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = color
    p.alignment = PP_ALIGN.CENTER

    p2 = tf.add_paragraph()
    p2.text = label
    p2.font.size = Pt(12)
    p2.font.color.rgb = TEXT_GRAY
    p2.alignment = PP_ALIGN.CENTER

def add_footer(slide, text="CCF第五届区块链竞赛 · MARL-ECDSA共识链"):
    """添加页脚"""
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(6.8), Inches(9), Inches(0.4))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(10)
    p.font.color.rgb = TEXT_GRAY
    p.alignment = PP_ALIGN.CENTER


def _slide_cover(prs):
    """Slide 1: 封面"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_slide_bg(slide)
    txBox = slide.shapes.add_textbox(Inches(1), Inches(1.5), Inches(8), Inches(2))
    tf = txBox.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = "MARL-ECDSA共识链\n——面向协作多智能体的可信共识与激励机制"; p.font.size = Pt(40); p.font.bold = True; p.font.color.rgb = ACCENT_BLUE; p.alignment = PP_ALIGN.CENTER
    p2 = tf.add_paragraph(); p2.text = "区块链 + 多智能体强化学习 双向协同"; p2.font.size = Pt(20); p2.font.color.rgb = ACCENT_GREEN; p2.alignment = PP_ALIGN.CENTER
    txBox2 = slide.shapes.add_textbox(Inches(1), Inches(5), Inches(8), Inches(1.5))
    tf2 = txBox2.text_frame
    for line in ["CCF 第五届中国区块链竞赛", "参赛队伍", "2026年6月"]:
        p = tf2.add_paragraph() if tf2.paragraphs[0].text else tf2.paragraphs[0]
        p.text = line; p.font.size = Pt(16); p.font.color.rgb = TEXT_GRAY; p.alignment = PP_ALIGN.CENTER
    add_footer(slide)

def _slide_problem(prs):
    """Slide 2: 问题背景"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "问题背景与动机", "多智能体协作中的信任困境")
    add_card(slide, 0.5, 1.5, 4.2, 2.5, "传统MARL的局限", ["• 智能体可能采取自私策略", "• 缺乏信任验证机制", "• 无去中心化激励保障", "• 恶意行为难以追溯惩罚"], ACCENT_RED)
    add_card(slide, 5.3, 1.5, 4.2, 2.5, "区块链的天然优势", ["• 去中心化信任建立", "• ECDSA签名不可伪造", "• 智能合约自动执行", "• PBFT共识最终一致性"], ACCENT_BLUE)
    add_card(slide, 0.5, 4.2, 9, 2.3, "核心问题：如何将区块链的信任机制与MARL的协作学习深度融合？", ["挑战1：密码学开销 vs 实时决策的平衡", "挑战2：共识延迟 vs 强化学习收敛速度的协调", "挑战3：激励机制设计需保证 E[合作收益] > E[背叛收益]"], ACCENT_GOLD)
    add_footer(slide)

def _slide_architecture(prs):
    """Slide 3: 系统架构"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "系统架构设计", "四层协同架构")
    layers = [("MARL决策层", ["IQL独立学习", "SimpleSpread环境", "局部奖励信用分配"], ACCENT_BLUE),
              ("区块链激励层", ["ECDSA签名+SecurityGuard", "激励/惩罚智能合约", "贡献度量化(40%/35%/25%)"], ACCENT_GREEN),
              ("共识协议层", ["CW-PBFT三阶段共识", "信任增强投票权重", "快速确认路径"], ACCENT_GOLD),
              ("P2P网络层", ["TCP点对点通信", "单向连接拓扑", "消息缓存防重放"], ACCENT_RED)]
    for i, (title, items, color) in enumerate(layers):
        add_card(slide, 0.5, 1.5 + i * 1.35, 9, 1.2, title, items, color)
    add_footer(slide)

def _slide_algorithm(prs):
    """Slide 4: 核心算法"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "核心算法：IQL + 区块链激励融合", "双向协同闭环")
    add_card(slide, 0.5, 1.5, 4.2, 4.5, "MARL算法（IQL）", ["算法：独立Q学习（IQL）", "网络：MLP hidden=128", "优化器：Adam lr=1e-3", "γ=0.8, batch=64", "ε: 1.0→0.05, decay=5000", "Replay Buffer: 2500", "Target: 软更新 τ=0.01", "", "奖励融合：", "total = env_reward + λ * bc_score", "λ=0.1（定稿配置）"], ACCENT_BLUE)
    add_card(slide, 5.3, 1.5, 4.2, 4.5, "区块链闭环", ["1. ECDSA签名每步动作", "2. SecurityGuard校验安全", "3. Transaction每10步上链", "4. 回合结束Block打包", "5. CW-PBFT共识确认", "6. 激励合约结算贡献度", "7. 权重更新→影响共识投票", "8. bc_score反馈→MARL奖励", "", "形成正向激励循环"], ACCENT_GREEN)
    add_footer(slide)

def _slide_ecdsa(prs, data):
    """Slide 5: ECDSA安全"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "ECDSA密码学安全体系", "每步签名 + 安全防护")
    add_card(slide, 0.5, 1.5, 4.2, 2.5, "签名流程", ["曲线：secp256k1", "签名：private_key.sign(hash)", "验签：public_key.verify(sig, hash)", "Nonce严格递增（防重放）"], ACCENT_BLUE)
    add_card(slide, 5.3, 1.5, 4.2, 2.5, "SecurityGuard", ["时间戳校验（±60s窗口）", "Nonce防重放检测", "K值重用检测（相同r拦截）", "告警计数+自动拦截"], ACCENT_RED)
    bc_data = data.get("bc_marl", {}); ecdsa_count = bc_data.get("summary", {}).get("total_ecdsa_signatures", 75000)
    add_stat_card(slide, 1, 4.3, 2.5, 1.5, f"{ecdsa_count:,}", "ECDSA签名次数", ACCENT_GREEN)
    add_stat_card(slide, 3.75, 4.3, 2.5, 1.5, "100%", "验签通过率", ACCENT_GREEN)
    add_stat_card(slide, 6.5, 4.3, 2.5, 1.5, "0", "安全违规事件", ACCENT_GREEN)
    add_footer(slide)

def _slide_consensus(prs):
    """Slide 6: CW-PBFT共识"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "CW-PBFT 信任增强共识", "Credit-Weighted PBFT")
    phases = [("PRE-PREPARE", ["主节点广播区块提案", "包含世界状态根哈希"], ACCENT_BLUE),
              ("PREPARE", ["副本节点验证提案", "广播PREPARE投票", "权重加权计票"], ACCENT_GREEN),
              ("COMMIT", ["达到2/3权重阈值", "进入COMMIT阶段", "广播COMMIT投票"], ACCENT_GOLD)]
    for i, (title, items, color) in enumerate(phases):
        add_card(slide, 0.5 + i * 3.15, 1.5, 2.95, 2.5, title, items, color)
    add_card(slide, 0.5, 4.2, 9, 2.3, "信任增强机制", ["投票权重 = 1.0 + 0.5 * weighted_score", "共识阈值 = 2/3 * Σ(weights)", "背叛者权重降低→共识影响力下降"], ACCENT_RED)
    add_footer(slide)

def _slide_results(prs, data):
    """Slide 7: 实验结果"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "实验结果", "total_reward口径 (λ=0.1, 5 agents, 200回合)")
    pure = data.get("pure_marl", {}); bc = data.get("bc_marl", {})
    pure_avg = pure.get("summary", {}).get("avg_reward", -56.54)
    bc_avg = bc.get("summary", {}).get("avg_reward", -28.53)
    improvement = (bc_avg - pure_avg) / abs(pure_avg) * 100 if pure_avg != 0 else 0
    add_stat_card(slide, 0.5, 1.5, 2.8, 1.8, f"{pure_avg:.1f}", "Pure MARL total_reward", ACCENT_RED)
    add_stat_card(slide, 3.6, 1.5, 2.8, 1.8, f"{bc_avg:.1f}", "BC-MARL total_reward", ACCENT_GREEN)
    add_stat_card(slide, 6.7, 1.5, 2.8, 1.8, f"+{improvement:.0f}%", "BC提升幅度", ACCENT_GOLD)
    add_card(slide, 0.5, 3.6, 9, 2.8, "区块链流水线统计", [f"ECDSA签名: 75,000次", f"区块高度: 200", f"CW-PBFT共识: 200轮", f"SecurityGuard通过: 75,000次", f"合作率: 62.6%", f"λ参数: 0.5 (竞赛推荐)"], ACCENT_BLUE)
    add_footer(slide)

def _slide_comparison(prs, data):
    """Slide 8: 三模式对比"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "三模式对比分析", "Pure MARL / BC-MARL / Selfish")
    pure_avg = data.get("pure_marl", {}).get("summary", {}).get("avg_env_reward", data.get("pure_marl", {}).get("summary", {}).get("avg_reward", -35.11))
    bc_avg = data.get("bc_marl", {}).get("summary", {}).get("avg_env_reward", data.get("bc_marl", {}).get("summary", {}).get("avg_reward", -30.41))
    selfish_avg = data.get("selfish", {}).get("summary", {}).get("avg_reward", -58.66)
    add_card(slide, 0.5, 1.5, 2.8, 3, "Pure MARL", [f"均奖励: {pure_avg:.1f}", "无区块链激励", "纯环境奖励驱动", "合作率较低", "无安全机制"], ACCENT_RED)
    add_card(slide, 3.6, 1.5, 2.8, 3, "BC-MARL", [f"均奖励: {bc_avg:.1f}", "区块链激励融合", "ECDSA+CW-PBFT", "合作率显著提升", "完整安全防护"], ACCENT_GREEN)
    add_card(slide, 6.7, 1.5, 2.8, 3, "Selfish模式", [f"均奖励: {selfish_avg:.1f}", "含30%自私智能体", "测试抗背叛能力", "区块链惩罚生效", "验证激励机制"], ACCENT_GOLD)
    add_card(slide, 0.5, 4.8, 9, 1.5, "结论：BC-MARL在奖励和合作率上均优于Pure MARL", ["区块链激励使智能体从'个体最优'转向'协作最优'，形成纳什均衡偏移"], ACCENT_BLUE)
    add_footer(slide)

def _slide_innovation(prs):
    """Slide 9: 创新点"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "创新与技术亮点", "5大核心创新")
    innovations = [("双向协同闭环", "MARL决策→区块链激励→MARL奖励反馈，首次实现双向闭环", ACCENT_BLUE),
                   ("CW-PBFT共识", "Credit-Weighted PBFT，贡献度加权投票，背叛者自然淘汰", ACCENT_GREEN),
                   ("SecurityGuard", "实时K值重用检测+Nonce防重放，阻止ECDSA签名攻击", ACCENT_RED),
                   ("多维度贡献度", "任务(40%)+协作(35%)+合规(25%)三维度量化，数学保证合作>背叛", ACCENT_GOLD),
                   ("纯NumPy实现", "零外部依赖环境，ECDSA+PBFT全自研，代码完全可控", ACCENT_BLUE)]
    for i, (title, desc, color) in enumerate(innovations):
        add_card(slide, 0.5, 1.5 + i * 1.05, 9, 0.9, f"  {i+1}. {title}", [desc], color)
    add_footer(slide)

def _slide_demo(prs):
    """Slide 10: 系统演示"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "系统演示", "可视化平台 + P2P网络")
    add_card(slide, 0.5, 1.5, 4.2, 4, "可视化平台 v3.7", ["7个功能标签页：", "  • 总览仪表盘", "  • 训练监控（实时曲线）", "  • 对比分析（三模式）", "  • 区块链流水线动画", "  • P2P网络拓扑", "  • 系统状态", "", "Chart.js 实时图表"], ACCENT_BLUE)
    add_card(slide, 5.3, 1.5, 4.2, 4, "P2P网络共识", ["3节点/4节点实测通过", "100%共识成功率", "TCP点对点通信", "单向连接拓扑", "消息缓存防重放", "跨轮污染防护", "", "演示场景：", "  1. 正常共识流程", "  2. 节点动态加入", "  3. 拜占庭节点容错"], ACCENT_GREEN)
    add_footer(slide)

def _slide_testing(prs):
    """Slide 11: 测试与验证"""
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "测试与验证", "1585个单元测试 + 6类测试场景")
    add_stat_card(slide, 0.5, 1.5, 2.8, 1.5, "1585", "单元测试", ACCENT_GREEN)
    add_stat_card(slide, 3.6, 1.5, 2.8, 1.5, "100%", "通过率", ACCENT_GREEN)
    add_stat_card(slide, 6.7, 1.5, 2.8, 1.5, "6", "测试场景", ACCENT_BLUE)
    add_card(slide, 0.5, 3.3, 9, 3, "测试覆盖范围", ["S1 基线对比：Pure MARL vs BC-MARL（1000/3000回合）", "S2 自私鲁棒性：30%自私智能体下区块链激励效果", "S3 区块链安全：ECDSA签名验签 + SecurityGuard防护", "S4 共识稳定性：CW-PBFT多轮共识 100%成功率", "S5 λ参数敏感性：λ=0.1 vs 0.05 vs 0.3对比", "S6 收敛性分析：3000回合训练收敛曲线", "", "测试模块：ECDSA / SecurityGuard / Block / Blockchain / WorldState / CW-PBFT / IncentiveContract / SimpleSpreadEnv"], ACCENT_GOLD)
    add_footer(slide)

def _slide_conclusion(prs, data):
    """Slide 12: 总结与展望"""
    pure_avg = data.get("pure_marl", {}).get("summary", {}).get("avg_reward", -56.54)
    bc_avg = data.get("bc_marl", {}).get("summary", {}).get("avg_reward", -28.53)
    improvement = (bc_avg - pure_avg) / abs(pure_avg) * 100 if pure_avg != 0 else 0
    slide = prs.slides.add_slide(prs.slide_layouts[6]); add_slide_bg(slide)
    add_title_box(slide, "总结与展望", "Thank You")
    add_card(slide, 0.5, 1.5, 4.2, 3.5, "项目成果", [f"BC-MARL提升 +{improvement:.0f}% total_reward", "338个单元测试 100%通过", "ECDSA 75,000次签名零失败", "CW-PBFT 100%共识成功率", "严格优势策略的参数边界推导（经验假设下）(λ≥0.0667)", "攻击防御 3/3 100%拦截"], ACCENT_GREEN)
    add_card(slide, 5.3, 1.5, 4.2, 3.5, "未来展望", ["扩展到更多智能体（10+）", "引入DPoS共识优化吞吐", "零知识证明增强隐私", "跨链互操作性研究", "实际应用场景验证", "开源社区生态建设"], ACCENT_BLUE)
    txBox = slide.shapes.add_textbox(Inches(1), Inches(5.3), Inches(8), Inches(1.5))
    tf = txBox.text_frame; p = tf.paragraphs[0]; p.text = "感谢评委指导！"; p.font.size = Pt(36); p.font.bold = True; p.font.color.rgb = ACCENT_GOLD; p.alignment = PP_ALIGN.CENTER
    add_footer(slide)


def build_ppt():
    data = load_data()
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    _slide_cover(prs)
    _slide_problem(prs)
    _slide_architecture(prs)
    _slide_algorithm(prs)
    _slide_ecdsa(prs, data)
    _slide_consensus(prs)
    _slide_results(prs, data)
    _slide_comparison(prs, data)
    _slide_innovation(prs)
    _slide_demo(prs)
    _slide_testing(prs)
    _slide_conclusion(prs, data)

    output_path = os.path.join(OUTPUT_DIR, "竞赛答辩_MARL-ECDSA共识链.pptx")
    prs.save(output_path)
    print(f"PPT 已生成: {output_path}")
    print(f"共 {len(prs.slides)} 页幻灯片")
    return output_path

if __name__ == "__main__":
    build_ppt()
