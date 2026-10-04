# -*- coding: utf-8 -*-
"""
生成 Dashboard 7个标签页 + plots 目录图片的 PPT 截图
模拟深色科技感 UI 风格
"""
import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Noto Sans SC', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / 'ppt_screenshots'
OUT.mkdir(exist_ok=True)

# ---- 口径真值：从权威登记簿程序化读取，禁手抄（防 n=22→n=71 口径漂移复发）----
def _registry_declared(nid, fallback):
    """读登记簿 declared；优先权威源（工作区 deliverables/），仓库镜像兜底。"""
    for cand in (BASE.parent / 'deliverables' / 'number_registry.json',
                 BASE / 'number_registry.json'):
        try:
            reg = json.loads(cand.read_text(encoding='utf-8'))
            for e in reg.get('entries', []):
                if e.get('id') == nid:
                    return {**fallback, **(e.get('declared') or {})}, 'registry'
        except Exception:
            continue
    return dict(fallback), 'fallback（登记簿不可读）'

_CAL, _CAL_SRC = _registry_declared('NR-1', {
    'improvement_pct': 28.17, 'welch_p': 0.009524, 'cohens_d': 0.4412,
    'mean_a': -6.6584, 'sd_a': 6.0447, 'mean_b': -9.2703, 'sd_b': 5.7916, 'n_a': 71})
_CAL3, _ = _registry_declared('NR-3', {
    'improvement_pct': 1.95, 'mean_a': 0.6246, 'mean_b': 0.6127, 'n_a': 71})

# 加载数据
PLOT_DIR = BASE / 'plots'

def load_json(name):
    p = BASE / name
    if p.exists():
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def smooth(data, window=50):
    if len(data) < window:
        return data
    return np.convolve(data, np.ones(window)/window, mode='valid')

# 加载训练数据
pure = load_json('training_results_pure.json')
bc = load_json('training_results_bc.json')
selfish = load_json('training_results_selfish.json')

# 如果 training_results 为空，回退到 results_*.json
if pure and not pure.get('episodes_rewards'):
    pure = load_json('results_pure.json') or pure
if bc and not bc.get('episodes_rewards'):
    bc = load_json('results_bc.json') or bc
if selfish and not selfish.get('episodes_rewards'):
    selfish = load_json('smoke_test_results.json') or selfish

# ---- 回退数据源：results/convergence_3000 聚合（诚实口径，n=71 收敛验证，登记簿 NR-1）----
def _agg_convergence(prefix):
    """把 results/convergence_3000/<prefix>_seed*.json 逐回合聚合为一条平均曲线。"""
    import glob as _glob
    fs = sorted(_glob.glob(str(BASE / 'results' / 'convergence_3000' / (prefix + '_seed*.json'))))
    if not fs:
        return None
    bucket = {}
    for f in fs:
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for k in ('episode_rewards', 'env_rewards', 'cooperation_rates', 'betrayal_rates', 'losses'):
            if isinstance(d.get(k), list) and d[k]:
                bucket.setdefault(k, []).append([v for v in d[k] if v is not None])
    if not bucket:
        return None
    out = {}
    for k, arrs in bucket.items():
        L = min(len(a) for a in arrs)
        if L == 0:
            continue
        out[k] = [float(np.mean([a[i] for a in arrs])) for i in range(L)]
    return {
        'episodes_rewards': out.get('episode_rewards', []),
        'cooperation_rates': out.get('cooperation_rates', []),
        'betrayal_rates': out.get('betrayal_rates', []),
        'losses': out.get('losses', []),
    }

if not (pure and pure.get('episodes_rewards')):
    _p = _agg_convergence('pure_marl')
    if _p:
        pure = _p
if not (bc and bc.get('episodes_rewards')):
    _b = _agg_convergence('bc_marl')
    if _b:
        bc = _b

# 统一提取奖励数据
pure_rewards = pure.get('episodes_rewards', pure.get('episode_rewards', [])) if pure else []
bc_rewards = bc.get('episodes_rewards', bc.get('episode_rewards', [])) if bc else []
selfish_rewards = selfish.get('episodes_rewards', selfish.get('episode_rewards', [])) if selfish else []

# ============================================================
# 1. 总览页 (Overview)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#040810')

# 顶栏
rect = mpatches.FancyBboxPatch((0, 7.4), 14, 0.6, boxstyle="round,pad=0.02", 
                                facecolor='#0a1020', edgecolor='none')
ax.add_patch(rect)
ax.text(0.5, 7.7, 'MARL-ECDSA 共识链 — 国赛演示平台 v3.4', fontsize=14, fontweight='bold', 
        color='#38bdf8', ha='left', va='center')
ax.text(13.5, 7.7, 'BC-MARL 模式', fontsize=10, color='#38bdf8', ha='right', va='center',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#38bdf8', alpha=0.1, edgecolor='#38bdf8'))

# Hero 标题
ax.text(7, 6.5, '多智能体强化学习 × 区块链双向协同', fontsize=20, fontweight='bold', 
        color='#f1f5f9', ha='center', va='center')
ax.text(7, 6.0, 'Blockchain-AI Collaborative Consensus for Multi-Agent Reinforcement Learning', 
        fontsize=10, color='#64748b', ha='center', va='center')

# 数据卡片
metrics = [
    (f"+{_CAL['improvement_pct']:.2f}%", 'BC env_reward 提升', '#22c55e'),
    ('3000', '总训练回合', '#3b82f6'),
    ('3', '协同智能体数', '#f59e0b'),
    ('1,000', 'CW-PBFT 共识轮次', '#818cf8'),
]
for i, (value, label, color) in enumerate(metrics):
    x = 1.5 + i * 3.2
    rect = mpatches.FancyBboxPatch((x-1.3, 3.8), 2.6, 1.6, boxstyle="round,pad=0.15",
                                    facecolor='#0c1428', edgecolor=color, alpha=0.6, linewidth=1.5)
    ax.add_patch(rect)
    ax.text(x, 4.8, value, fontsize=22, ha='center', va='center', fontweight='bold', color=color)
    ax.text(x, 4.2, label, fontsize=10, ha='center', va='center', color='#94a3b8')

# 实验结论表格
ax.text(7, 3.2, '实验结论对比', fontsize=14, fontweight='bold', color='#f1f5f9', ha='center')

# 表头
colors_header = '#1e293b'
rect = mpatches.FancyBboxPatch((1, 2.2), 12, 0.4, boxstyle="round,pad=0.02",
                                facecolor=colors_header, edgecolor='none')
ax.add_patch(rect)
headers = ['指标', 'Pure MARL', 'BC-MARL', 'Selfish', 'BC 提升']
for j, h in enumerate(headers):
    x = 1.5 + j * 2.5
    ax.text(x, 2.4, h, fontsize=9, ha='center', va='center', color='#94a3b8', fontweight='bold')

# 数据行
rows = [
    ['后50回合 env_reward', f"{_CAL['mean_b']:.2f}±{_CAL['sd_b']:.2f}", f"{_CAL['mean_a']:.2f}±{_CAL['sd_a']:.2f}", '—', f"+{_CAL['improvement_pct']:.2f}%"],
    ['合作率(全程)', f"{_CAL3['mean_b']*100:.1f}%", f"{_CAL3['mean_a']*100:.1f}%", '—', f"+{_CAL3['improvement_pct']:.2f}%"],
    ['背叛率', '0%', '0%', '—', '—'],
    ['Welch p-value', f"{_CAL['welch_p']:.4f}", '-', '-', f"BH-FDR显著(n={_CAL['n_a']})"],
]
for i, row in enumerate(rows):
    y = 1.8 - i * 0.35
    bg = '#0f172a' if i % 2 == 0 else '#1e293b'
    rect = mpatches.FancyBboxPatch((1, y-0.15), 12, 0.35, boxstyle="round,pad=0.02",
                                    facecolor=bg, edgecolor='none', alpha=0.5)
    ax.add_patch(rect)
    for j, val in enumerate(row):
        x = 1.5 + j * 2.5
        color = '#22c55e' if j == 2 and i < 2 else '#f1f5f9'
        if j == 4:
            color = '#22c55e'
        ax.text(x, y, val, fontsize=9, ha='center', va='center', color=color)

# 底部提示
ax.text(7, 0.2, f'注：数据基于 {_CAL["n_a"]} 种子 × 3000 回合 收敛验证（env_reward 公平口径，末50回合，不含BC激励）；'
                f'Welch p={_CAL["welch_p"]:.4f}（BH-FDR 显著 / Bonferroni 下不显著），须与全程口径 NR-2（+7.92%，p<1e-10）同报；'
                f'口径出处：{_CAL_SRC}', fontsize=8,
        color='#64748b', ha='center', va='center')

fig.savefig(OUT / 'dashboard_overview.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 2. 训练监控页 (Monitor)
# ============================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 9), dpi=150)
fig.patch.set_facecolor('#040810')

# 2a. 奖励曲线
ax = axes[0, 0]
ax.set_facecolor('#0c1428')
if pure_rewards:
    ax.plot(smooth(pure_rewards, 50), label='Pure MARL', color='#ef4444', linewidth=2, alpha=0.8)
if bc_rewards:
    ax.plot(smooth(bc_rewards, 50), label='BC-MARL', color='#22c55e', linewidth=2, alpha=0.8)
if selfish_rewards:
    ax.plot(smooth(selfish_rewards, 50), label='Selfish', color='#f59e0b', linewidth=2, alpha=0.8)
ax.set_xlabel('训练回合', color='#94a3b8')
ax.set_ylabel('回合奖励', color='#94a3b8')
ax.set_title('训练奖励曲线', color='#f1f5f9', fontweight='bold', fontsize=12)
ax.legend(facecolor='#0c1428', edgecolor='none', labelcolor='#94a3b8')
ax.tick_params(colors='#94a3b8')
ax.grid(True, alpha=0.2, color='#334155')
ax.spines[:].set_color('#334155')

# 2b. 损失曲线
ax = axes[0, 1]
ax.set_facecolor('#0c1428')
if bc and bc.get('losses'):
    losses = [l for l in bc['losses'] if l is not None]
    if losses:
        ax.plot(losses, color='#3b82f6', linewidth=1.5, alpha=0.7)
ax.set_xlabel('训练步数', color='#94a3b8')
ax.set_ylabel('TD Loss', color='#94a3b8')
ax.set_title('BC-MARL 训练损失曲线', color='#f1f5f9', fontweight='bold', fontsize=12)
ax.tick_params(colors='#94a3b8')
ax.grid(True, alpha=0.2, color='#334155')
ax.spines[:].set_color('#334155')

# 2c. 合作率
ax = axes[1, 0]
ax.set_facecolor('#0c1428')
if pure and pure.get('cooperation_rates'):
    rates = pure['cooperation_rates']
    ax.plot(smooth(rates, 50), color='#ef4444', linewidth=2, alpha=0.8, label='Pure')
if bc and bc.get('cooperation_rates'):
    rates = bc['cooperation_rates']
    ax.plot(smooth(rates, 50), color='#22c55e', linewidth=2, alpha=0.8, label='BC-MARL')
ax.axhline(y=0.5, color='#64748b', linestyle='--', alpha=0.5, label='阈值')
ax.set_xlabel('训练回合', color='#94a3b8')
ax.set_ylabel('合作率', color='#94a3b8')
ax.set_title('合作率变化趋势', color='#f1f5f9', fontweight='bold', fontsize=12)
ax.legend(facecolor='#0c1428', edgecolor='none', labelcolor='#94a3b8')
ax.tick_params(colors='#94a3b8')
ax.grid(True, alpha=0.2, color='#334155')
ax.spines[:].set_color('#334155')

# 2d. 背叛率
ax = axes[1, 1]
ax.set_facecolor('#0c1428')
if selfish and selfish.get('betrayal_rates'):
    rates = selfish['betrayal_rates']
    ax.plot(rates, color='#f59e0b', linewidth=2, alpha=0.8)
ax.set_xlabel('训练回合', color='#94a3b8')
ax.set_ylabel('背叛率', color='#94a3b8')
ax.set_title('Selfish 模式背叛率', color='#f1f5f9', fontweight='bold', fontsize=12)
ax.tick_params(colors='#94a3b8')
ax.grid(True, alpha=0.2, color='#334155')
ax.spines[:].set_color('#334155')

fig.tight_layout(pad=3.0)
fig.savefig(OUT / 'dashboard_monitor.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 3. 对比分析页 (Compare)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#040810')

ax.text(7, 7.5, '对比分析 — Pure MARL vs BC-MARL', fontsize=18, fontweight='bold', 
        color='#f1f5f9', ha='center')

# 三列卡片
# 【口径修复 2026-09-29】原为硬编码 '-8.64'/'-6.12'（n=22 旧口径，源自 _CAL_SRC 之外的漏网手抄）
# 现改为从登记簿 NR-1 程序化取数：mean_a=BC-MARL、mean_b=Pure-MARL（n=71 终局全样本）
cards = [
    ('Pure MARL', f"{_CAL['mean_b']:.2f}", '#ef4444', ['无区块链激励', '纯环境奖励驱动', '信用分配困难', '收敛较慢']),
    ('BC-MARL', f"{_CAL['mean_a']:.2f}", '#22c55e', ['ECDSA签名认证', 'CW-PBFT共识', '贡献度加权奖励', '协作塑形趋势']),
    ('Selfish(对照)', '—', '#f59e0b', ['部分智能体背叛', '区块链惩罚背叛', '激励抑制自私', '系统鲁棒性验证']),
]
for i, (title, reward, color, features) in enumerate(cards):
    x = 2.3 + i * 4.0
    # 卡片背景
    rect = mpatches.FancyBboxPatch((x-1.8, 1.5), 3.6, 4.8, boxstyle="round,pad=0.15",
                                    facecolor='#0c1428', edgecolor=color, alpha=0.8, linewidth=2)
    ax.add_patch(rect)
    # 标题
    ax.text(x, 5.8, title, fontsize=14, ha='center', va='center', fontweight='bold', color=color)
    # 奖励值
    ax.text(x, 5.2, reward, fontsize=28, ha='center', va='center', fontweight='bold', color=color)
    ax.text(x, 4.7, '后50回合 env_reward', fontsize=9, ha='center', va='center', color='#94a3b8')
    # 特性列表
    for j, feat in enumerate(features):
        ax.text(x, 4.0 - j*0.4, f'• {feat}', fontsize=9, ha='center', va='center', color='#cbd5e1')

fig.savefig(OUT / 'dashboard_compare.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 4. 三模式对比页 (Tri-mode)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#040810')

ax.text(7, 7.5, '三模式训练对比 — 详细数据', fontsize=18, fontweight='bold', color='#f1f5f9', ha='center')

# 柱状图模拟（诚实口径：仅 BC / Pure 具备收敛数据；均值±std 取自登记簿 NR-1）
modes = ['Pure\nMARL', 'BC-MARL']
means = [_CAL['mean_b'], _CAL['mean_a']]
stds = [_CAL['sd_b'], _CAL['sd_a']]
colors_bar = ['#ef4444', '#22c55e']

# 绘制柱状图（手动matplotlib style）
bars_x = [5, 9]
for x, mean, std, color in zip(bars_x, means, stds, colors_bar):
    # 柱子
    h = abs(mean) / 10 * 4  # 归一化高度（env_reward 量级）
    rect = mpatches.FancyBboxPatch((x-0.6, 2), 1.2, h, boxstyle="round,pad=0.05",
                                    facecolor=color, alpha=0.3, edgecolor=color, linewidth=2)
    ax.add_patch(rect)
    ax.text(x, 2 + h + 0.2, f'{mean:.1f}±{std:.1f}', fontsize=12, ha='center', va='bottom', 
            color=color, fontweight='bold')
    ax.text(x, 1.5, modes[bars_x.index(x)], fontsize=11, ha='center', va='center', color='#94a3b8')

# Y轴标签
for y in range(2, 7):
    val = -(y-2) / 4 * 10
    ax.text(1.2, y, f'{val:.0f}', fontsize=8, color='#64748b', ha='right', va='center')
    ax.plot([1.4, 1.5], [y, y], color='#334155', linewidth=0.5)
ax.text(0.5, 4.5, '平均奖励', fontsize=9, color='#64748b', ha='center', va='center', rotation=90)

# 统计显著性标注（诚实口径）
ax.annotate('', xy=(9, 6.5), xytext=(5, 6.5), arrowprops=dict(arrowstyle='->', color='#22c55e', lw=1.5))
ax.text(7, 6.7, f'Welch p={_CAL["welch_p"]:.4f} (n={_CAL["n_a"]}, BH-FDR显著/Bonferroni不显著)',
        fontsize=10, ha='center', color='#22c55e', fontweight='bold')

fig.savefig(OUT / 'dashboard_tri.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 5. 区块链页 (Blockchain)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#040810')

ax.text(7, 7.5, '区块链流水线 — 完整数据追踪', fontsize=18, fontweight='bold', color='#f1f5f9', ha='center')

# ECDSA 签名流程
steps = [
    ('ECDSA\n签名', '75,000次', '#3b82f6'),
    ('Security\nGuard', '100%通过', '#22c55e'),
    ('Transaction\n上链', '批量打包', '#f59e0b'),
    ('Block\n打包', '1,000个', '#818cf8'),
    ('CW-PBFT\n共识', '1,000轮', '#34d399'),
    ('链式\n追加', '不可逆', '#ef4444'),
]
for i, (step, detail, color) in enumerate(steps):
    x = 1.2 + i * 2.2
    # 圆角矩形
    rect = mpatches.FancyBboxPatch((x-0.8, 4.5), 1.6, 1.8, boxstyle="round,pad=0.1",
                                    facecolor='#0c1428', edgecolor=color, linewidth=2, alpha=0.8)
    ax.add_patch(rect)
    ax.text(x, 5.6, step, fontsize=10, ha='center', va='center', fontweight='bold', color=color)
    ax.text(x, 5.0, detail, fontsize=9, ha='center', va='center', color='#94a3b8')
    # 箭头
    if i < len(steps) - 1:
        ax.annotate('', xy=(x+0.9, 5.4), xytext=(x+0.9, 5.4),
                   arrowprops=dict(arrowstyle='->', color='#64748b', lw=1.5))
        ax.plot([x+0.8, x+1.4], [5.4, 5.4], color='#64748b', linewidth=1.5)

# 验签徽章
ax.text(7, 3.5, '验签徽章', fontsize=14, fontweight='bold', color='#f1f5f9', ha='center')
badges = [
    ('ECDSA 签名验证', '75,000 / 75,000', '#22c55e'),
    ('SecurityGuard 校验', '75,000 / 75,000', '#22c55e'),
    ('k值重攻击检测', '0 次触发', '#3b82f6'),
    ('Nonce 重放检测', '0 次触发', '#3b82f6'),
]
for i, (label, val, color) in enumerate(badges):
    x = 1.5 + i * 3.2
    rect = mpatches.FancyBboxPatch((x-1.2, 2.0), 2.4, 1.0, boxstyle="round,pad=0.1",
                                    facecolor='#0c1428', edgecolor=color, alpha=0.6, linewidth=1.5)
    ax.add_patch(rect)
    ax.text(x, 2.7, label, fontsize=9, ha='center', va='center', color='#cbd5e1')
    ax.text(x, 2.3, val, fontsize=10, ha='center', va='center', fontweight='bold', color=color)

ax.text(7, 0.8, '注：流水线统计为 V2（1000 回合，λ=0.1）单次运行示例', fontsize=8, color='#64748b', ha='center')
fig.savefig(OUT / 'dashboard_blockchain.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 6. 系统页 (System)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#040810')

ax.text(7, 7.5, '系统架构 — 四层协同设计', fontsize=18, fontweight='bold', color='#f1f5f9', ha='center')

layers = [
    ('应用层', 'Flask Dashboard + Chart.js 可视化', '#22c55e', 5.5),
    ('智能体层', 'IQL 多智能体强化学习', '#3b82f6', 4.5),
    ('区块链层', 'ECDSA + SecurityGuard + CW-PBFT + Block', '#f59e0b', 3.5),
    ('网络层', 'asyncio TCP P2P 对等网络', '#818cf8', 2.5),
]
for name, desc, color, y in layers:
    rect = mpatches.FancyBboxPatch((1, y-0.3), 12, 0.6, boxstyle="round,pad=0.1",
                                    facecolor='#0c1428', edgecolor=color, alpha=0.8, linewidth=2)
    ax.add_patch(rect)
    ax.text(1.5, y, name, fontsize=12, ha='left', va='center', fontweight='bold', color=color)
    ax.text(4.5, y, desc, fontsize=10, ha='left', va='center', color='#94a3b8')
    # 向下箭头
    if y > 2.5:
        ax.annotate('', xy=(7, y-0.4), xytext=(7, y-0.6),
                   arrowprops=dict(arrowstyle='->', color='#64748b', lw=1.5))

fig.savefig(OUT / 'dashboard_system.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 7. P2P网络页 (P2P)
# ============================================================
fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8)
ax.axis('off')
fig.patch.set_facecolor('#040810')

ax.text(7, 7.5, 'P2P 网络 — 纯去中心化共识演示', fontsize=18, fontweight='bold', color='#f1f5f9', ha='center')

# 3节点拓扑
nodes = [(4, 5), (10, 5), (7, 7.5)]
labels = ['Node-0\n(Primary)', 'Node-1\n(Replica)', 'Node-2\n(Replica)']
colors = ['#22c55e', '#3b82f6', '#f59e0b']
for (x, y), label, color in zip(nodes, labels, colors):
    circle = plt.Circle((x, y), 1.0, fill=True, facecolor=color, alpha=0.2, edgecolor=color, linewidth=2)
    ax.add_patch(circle)
    ax.text(x, y, label, ha='center', va='center', fontsize=9, fontweight='bold', color=color)

# 全连接
for i in range(len(nodes)):
    for j in range(i+1, len(nodes)):
        x1, y1 = nodes[i]
        x2, y2 = nodes[j]
        ax.plot([x1, x2], [y1, y2], color='#334155', linewidth=1.5, alpha=0.6, zorder=0)

# CW-PBFT 三阶段
phases = [
    ('PRE-PREPARE', '主节点广播提案', '#22c55e', 2),
    ('PREPARE', '副本节点验证并投票', '#3b82f6', 5),
    ('COMMIT', '确认并写入区块链', '#f59e0b', 8),
]
for name, desc, color, x in phases:
    rect = mpatches.FancyBboxPatch((x-1.2, 1.0), 2.4, 1.0, boxstyle="round,pad=0.1",
                                    facecolor='#0c1428', edgecolor=color, alpha=0.8, linewidth=2)
    ax.add_patch(rect)
    ax.text(x, 1.6, name, fontsize=9, ha='center', va='center', fontweight='bold', color=color)
    ax.text(x, 1.2, desc, fontsize=8, ha='center', va='center', color='#94a3b8')
    # 箭头
    if x < 8:
        ax.plot([x+1.2, x+1.8], [1.5, 1.5], color='#64748b', linewidth=1.5)
        ax.annotate('', xy=(x+1.8, 1.5), xytext=(x+1.2, 1.5),
                   arrowprops=dict(arrowstyle='->', color='#64748b', lw=1.5))

fig.savefig(OUT / 'dashboard_p2p.png', dpi=150, bbox_inches='tight', facecolor='#040810')
plt.close()

# ============================================================
# 8. 复制 plots 目录的图片到 ppt_screenshots
# ============================================================
import shutil
plot_images = []
for img in sorted(PLOT_DIR.glob('*.png')):
    dst = OUT / img.name
    shutil.copy2(img, dst)
    plot_images.append(img.name)

# ============================================================
# 总结
# ============================================================
print(f'\n已生成所有截图到: {OUT}')
print('\n=== Dashboard 标签页截图 ===')
dashboard_imgs = ['dashboard_overview.png', 'dashboard_monitor.png', 'dashboard_compare.png',
                  'dashboard_tri.png', 'dashboard_blockchain.png', 'dashboard_system.png', 'dashboard_p2p.png']
for img in dashboard_imgs:
    p = OUT / img
    print(f'  [✓] {img} ({p.stat().st_size/1024:.1f} KB)')

print('\n=== plots 目录图片 (已复制) ===')
for img in plot_images:
    p = OUT / img
    print(f'  [✓] {img} ({p.stat().st_size/1024:.1f} KB)')
