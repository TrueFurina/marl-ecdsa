"""
答辩演练辅助脚本
================
1. 15分钟路演计时器（按逐页讲稿分配时间）
2. 50问抽问模拟（随机抽取问题，显示标准答案）

用法:
  python scripts/defense_rehearsal.py timer     # 计时器模式
  python scripts/defense_rehearsal.py quiz       # 抽问模式
  python scripts/defense_rehearsal.py quiz --n 5 # 抽5题
"""
import sys
import os
import time
import random
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


# 15分钟路演时间分配（按逐页讲稿）
ROADSHOW_TIMELINE = [
    (0, 60, "封面 + 自我介绍", "项目名 + 团队 + 一句话定位"),
    (60, 150, "问题定义", "多智能体为什么需要区块链？3个核心挑战"),
    (150, 270, "方案总览", "四层架构 + 双向赋能闭环图"),
    (270, 390, "创新一：ECDSA身份锚定", "无CA分布式 + RFC6979 + STRIDE"),
    (390, 510, "创新二：CW-PBFT共识", "贡献加权 + Shapley推导 + vs标准PBFT"),
    (510, 630, "创新三：Nash均衡", "激励相容证明 + 安全裕度50%（λ=0.1，λ_min=0.0667）"),
    (630, 750, "实验一：核心对比", "🏆 +28.17% env_reward（末50回合、不含BC激励）, d=0.44 小到中等效应（n=71/组；BH-FDR 显著/Bonferroni 不显著，须与全程口径 +7.92% 同报）"),
    (750, 840, "实验二：消融+攻防", "激励模块贡献最大 + 100%防护"),
    (840, 900, "实验三：扩展性+λ灵敏度", "3/5/8智能体 + λ扫描非单调（各档不显著）"),
    (900, 960, "Dashboard演示", "9标签页 + P键演示模式"),
    (960, 1020, "产业落地", "仓储/供应链/医疗 3场景"),
    (1020, 1080, "总结展望", "核心成果4条 + 未来3方向"),
    (1080, 1140, "Q&A缓冲", "评委提问预留"),
]


def cmd_timer():
    """15分钟路演计时器"""
    print("=" * 60)
    print("15分钟路演计时器（按逐页讲稿分配时间）")
    print("按 Enter 开始，每页结束按 Enter 跳转下一页")
    print("=" * 60)
    input("准备就绪后按 Enter 开始...")
    
    for i, (start, end, title, desc) in enumerate(ROADSHOW_TIMELINE):
        duration = end - start
        print(f"\n{'='*60}")
        print(f"📍 [{i+1}/{len(ROADSHOW_TIMELINE)}] {title}")
        print(f"   时长: {duration}s ({start//60}:{start%60:02d} - {end//60}:{end%60:02d})")
        print(f"   要点: {desc}")
        print(f"{'='*60}")
        
        for remaining in range(duration, 0, -1):
            mm, ss = divmod(remaining, 60)
            sys.stdout.write(f"\r⏱  剩余 {mm}:{ss:02d}  ")
            sys.stdout.flush()
            time.sleep(1)
        
        print(f"\n✅ {title} 完成!")
        if i < len(ROADSHOW_TIMELINE) - 1:
            input("按 Enter 进入下一页...")
    
    print(f"\n{'='*60}")
    print("🎉 路演完成！总用时 19 分钟（含 Q&A 缓冲）")
    print(f"{'='*60}")


# 50问核心题库（精简版）
QUIZ_BANK = [
    ("BC提升的头号指标是多少？用什么口径？", "3000回合收敛验证，env_reward last50公平口径（不含BC激励），BC提升+28.17%（n=71/组，末50回合），Cohen's d=0.44（小到中等效应），Welch p=0.0095（BH-FDR 下显著、Bonferroni 下不显著）。必须与全程口径同报：全程平均 env_reward +7.92%（Welch p<1e-10，d=1.20，检验力≈1.0）；全程平均合作率 +1.95%（p<1e-10）。诚实定位：主口径效应量小-中，不得表述为『强证据』或『证明激励有效』。早期 3 种子小样本估计 +46.4%、22 种子中期口径 +29.2%（p=0.126 不显著）**均已作废**——系样本量不足所致，现以登记簿 NR-1/NR-2（n=71/组）为唯一权威口径。"),
    ("为什么500回合和3000回合的BC提升差距这么大？", "500回合时agent尚未充分收敛，BC激励的长期塑形效果未显现；3000回合收敛后为+28.17%（n=71/组，env_reward 公平口径、末50回合；全程口径 +7.92% 须同报）。⚠ 注意：早期提到的『500回合 +13.4%』在 `deliverables/number_registry.json` 中**无出处记录**，答辩时**不得作为申报数字引用**，如需引用须先复算并回填注册表。这说明BC激励是长期协作塑形信号，需充分训练才能体现——这是科学发现，不是数据矛盾。"),
    ("Cohen's d=0.44意味着什么？", "Cohen's d是效应量指标：0.2小、0.5中、0.8大。本项目主口径（末50回合、不含BC激励）实测 d=0.44，落在小到中等效应区间；Welch p=0.0095 在 BH-FDR 校正下显著、Bonferroni 下不显著——故如实呈现『主口径效应量小-中、多重校正结论敏感』；同时全程口径 d=1.20（大效应、p<1e-10）必须与主口径同报。据此不做『BC显著提升性能』的单点因果归因，定位为信任增强而非性能优化。"),
    ("CARS共识感知塑形为什么是负结果？", "CARS的Potential函数用'到最近路标距离'作为空间势能，而环境奖励基于'到分配路标距离'。当智能体被分配到非最近路标时，两者方向相反，产生系统性冲突。大样本受控扫描（E3，n=30/组，η∈{0,0.02,…,0.20}，3000回合）实测：在极小剂量 η=0.02 即触发协作崩溃（baseline −6.95 → −73.02，Cohen d≈−13，p<1e-50），且 η 继续增大不再恶化——属**剂量无关的结构性冲突**而非可调参数。这是诚实负结果，给出了'共识感知奖励塑形何时有害'的可证伪判据。⚠ 早期『η=0.10 退化 24.2%』系 n=1 单次观测，已被本受控大样本取代，不得作为申报数字。"),
    ("CW-PBFT相比标准PBFT的优势是什么？", "诚实结论：在**真实 MARL 行为导出的贡献度权重**下（权重比 R≈1.007），CW-PBFT 与标准 PBFT **完全等价**，没有性能优势——这是数学必然：安全条件为 b < n/(2R+1)，代入 R≈1.007 得 b < n/3.014，即约等于标准 PBFT 的 n/3。早期报告的『33% 拜占庭 +10-23%、40% 超极限 +67-71%』源于 legacy 权重里编码了答案（预先知道哪些节点是坏的），属**实验假象，已作废，不得引用**。CW-PBFT 的实际贡献是：提供『行为→贡献度→投票权重』的可审计映射，以及安全条件 b < n/(2R+1) 这一设计准则。"),
    ("ECDSA签名用什么曲线？为什么不用RSA？", "NIST secp256r1 (P-256)。椭圆曲线密钥更短（256bit vs RSA 3072bit等效），签名更快，适合高频交易场景。已实现RFC6979确定性k值生成防重用。"),
    ("自适应λ相比静态λ提升多少？", "口径结论：各档静态 λ 下 env 口径差异**小于种子标准差、均未达统计显著**，即调高 λ 对协作**无显著增益**（甚至略有损害）。⚠ 早期『自适应 λ +6.3%（p=0.10）』与『±12.5% 鲁棒性（R²=0.685）』在 `deliverables/number_registry.json` 中**无出处记录**，答辩时**不得引用**，如需引用须先复算并回填注册表。λ_t = clamp(λ_base + η·(κ_c·c_t + κ_k·k_t - κ_s·s_t), 0.05, 0.15)。"),
    ("消融实验哪个模块最重要？", "IncentiveContract（激励合约）贡献最大，消融后env_reward下降2.00。SecurityGuard和CW-PBFT加权各有正向贡献（-1.33/-0.83）。三模块均有贡献，验证架构合理性。"),
    ("攻击防御怎么实现100%拦截？", "SecurityGuard三阶防护：观测校验→消息ECDSA验签→重放检测，叠加贡献度门控与纪元绑定。六类签名层攻击（观测伪造/消息篡改/重放/女巫Sybil/k值重用/长程）全部被区块链层拦截（6/6=100%，依据 results/attack_defense_report.json）。拜占庭主节点由 CW-PBFT failover 独立覆盖，不计入六类。"),
    ("测试覆盖了多少用例？", "1600+ 项自动化测试全部通过（0 失败；采用下限式表述，精确值以登记簿 NR-19 的 declared 为准），覆盖共识/密码学/MARL/网络/Dashboard全模块。使用pytest框架，CI流水线持续验证。"),
    ("主口径效应量只有小到中等，为什么还值得一等奖？", "因为本项目定位是**信任增强**而非性能优化，价值不在性能数字的堆砌，而在可解释的边界与设计准则：(1) 主口径（末50回合）+28.17%、d=0.44（BH-FDR 显著/Bonferroni 不显著），同数据全程口径 +7.92%（p<1e-10、d=1.20、检验力≈1.0）为强显著正结果，且全程合作率 +1.95%（p<1e-10）——链上激励在长期行为塑形上确有可验证效果；(2) 三算法大样本（E1，n=30）进一步揭示 QMIX 显著受益（p=0.00064、d=0.93），证明激励效果具算法依赖性而非普适宣称；(3) 负面结果本身有科学价值——C2 奖励塑形的剂量无关崩溃、C3 贡献度加权无增益的数学必然，都给出了可证伪的设计判据；(4) 六类签名层攻击 100% 拦截 + 拜占庭容错 + 激励公平可验证，是可审计的信任底座。综上，这是『诚实边界 + 机制洞察』型的一等奖候选，而非『性能刷榜』型。"),
]


def cmd_quiz(n=5):
    """抽问模拟"""
    print("=" * 60)
    print(f"答辩抽问模拟（{n}题）")
    print("每题先显示问题，思考后按 Enter 看答案")
    print("=" * 60)
    
    questions = random.sample(QUIZ_BANK, min(n, len(QUIZ_BANK)))
    score = 0
    
    for i, (q, a) in enumerate(questions, 1):
        print(f"\n{'='*60}")
        print(f"📝 问题 {i}/{len(questions)}:")
        print(f"   {q}")
        print(f"{'='*60}")
        input("\n思考完毕后按 Enter 看标准答案...")
        
        print(f"\n💡 标准答案:")
        print(f"   {a}")
        
        # 自评
        while True:
            rating = input("\n自评（1=完全不会 2=不完整 3=基本ok 4=流畅）: ").strip()
            if rating in ['1','2','3','4']:
                score += int(rating)
                break
            print("请输入 1-4")
    
    print(f"\n{'='*60}")
    print(f"📊 演练结束！总分 {score}/{len(questions)*4}")
    avg = score / len(questions)
    if avg >= 3.5:
        print("🎉 优秀！答辩准备充分")
    elif avg >= 2.5:
        print("👍 良好，继续练习薄弱环节")
    else:
        print("⚠️ 需要加强练习，重点复习标准答案")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="答辩演练辅助")
    parser.add_argument("mode", choices=["timer", "quiz"], help="timer=路演计时器, quiz=抽问模拟")
    parser.add_argument("--n", type=int, default=5, help="抽问题数（默认5）")
    args = parser.parse_args()
    
    if args.mode == "timer":
        cmd_timer()
    elif args.mode == "quiz":
        cmd_quiz(args.n)


if __name__ == '__main__':
    main()
