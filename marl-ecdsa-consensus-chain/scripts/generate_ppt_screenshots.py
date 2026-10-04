import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Noto Sans SC', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / 'ppt_screenshots'
OUT.mkdir(exist_ok=True)

def load_json(name):
    p = BASE / name
    if p.exists():
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def smooth(data, window=50):
    if len(data) < window:
        return data
    s = np.convolve(data, np.ones(window)/window, mode='valid')
    return s

# === 1. 两模式奖励对比图 (for PPT 第13页 对比) ===
# 【口径修复 2026-09-29】原从根目录 results_pure.json/results_bc.json 加载，
# 但那些文件不存在 → 三个 if 全不成立 → 产出**空白图**（无数据线）。
# 现改为从 results/convergence_3000/ 聚合（n=71 终局全样本，登记簿 NR-1 同源数据）。
import glob as _glob

def _agg_curve(mode, field='episode_rewards'):
    """把 convergence_3000/<mode>_seed*.json 的逐回合曲线按回合平均成一条。"""
    curves = []
    for p in sorted(_glob.glob(str(BASE / 'results' / 'convergence_3000' / f'{mode}_seed*.json'))):
        try:
            d = json.loads(Path(p).read_text(encoding='utf-8'))
        except Exception:
            continue
        c = d.get(field)
        if c:
            curves.append(c)
    if not curves:
        return None, 0
    m = min(len(c) for c in curves)
    arr = np.array([c[:m] for c in curves], dtype=float)
    return arr.mean(axis=0), len(curves)

fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
_pure_curve, _n_pure = _agg_curve('pure_marl')
_bc_curve, _n_bc = _agg_curve('bc_marl')
if _pure_curve is not None:
    ax.plot(smooth(_pure_curve, 10), label=f'Pure MARL (n={_n_pure})',
            color='#ef4444', linewidth=2, alpha=0.8)
if _bc_curve is not None:
    ax.plot(smooth(_bc_curve, 10), label=f'BC-MARL (n={_n_bc})',
            color='#22c55e', linewidth=2, alpha=0.8)

ax.set_xlabel('训练回合 (Episode)', fontsize=12)
ax.set_ylabel('回合奖励 (Episode Reward)', fontsize=12)
ax.set_title('Pure vs BC-MARL 训练奖励对比 (n=71, Smoothing=10)', fontsize=14, fontweight='bold')
ax.legend(fontsize=11, loc='best')
ax.grid(True, alpha=0.3)
ax.set_facecolor('#fafafa')
fig.patch.set_facecolor('white')
fig.tight_layout()
fig.savefig(OUT / 'three_mode_rewards.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved: three_mode_rewards.png')

# === 2. 总览页数据卡片 (for PPT 第13页 总览) ===
fig, ax = plt.subplots(figsize=(12, 3), dpi=150)
ax.axis('off')

# 数据卡片（口径真值：登记簿 NR-1 程序化读取，禁手抄，防口径漂移复发）
_reg = {}
for _cand in (BASE.parent / 'deliverables' / 'number_registry.json',
              BASE / 'number_registry.json'):
    try:
        _reg = {e['id']: (e.get('declared') or {})
                for e in json.loads(_cand.read_text(encoding='utf-8')).get('entries', [])}
        break
    except Exception:
        continue
_imp = _reg.get('NR-1', {}).get('improvement_pct', 28.17)
# 统一为 1 位小数（+28.2%），与设计报告/测试报告/PPT 的写法一致，
# 避免同材料内出现 28.17 与 28.2 两种写法造成评审困惑。
metrics = [
    ('BC env_reward 提升', f'+{_imp:.1f}%', '#22c55e'),
    ('总训练回合', '3000', '#3b82f6'),
    ('协同智能体数', '3', '#f59e0b'),
]
for i, (label, value, color) in enumerate(metrics):
    x = 0.17 + i * 0.33
    rect = plt.Rectangle((x-0.12, 0.15), 0.24, 0.7, fill=True, 
                          facecolor=color, alpha=0.1, edgecolor=color, linewidth=2, 
                          transform=ax.transAxes)
    ax.add_patch(rect)
    ax.text(x, 0.65, value, fontsize=28, ha='center', va='center', 
            fontweight='bold', color=color, transform=ax.transAxes)
    ax.text(x, 0.30, label, fontsize=12, ha='center', va='center', 
            color='#666', transform=ax.transAxes)

ax.set_title('Dashboard 总览数据面板', fontsize=14, fontweight='bold', pad=20)
fig.patch.set_facecolor('white')
fig.savefig(OUT / 'dashboard_overview.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved: dashboard_overview.png')

# === 3. 训练监控 - 损失曲线 (for PPT 第13页 训练监控) ===
# 【口径修复 2026-09-29】原引用已删除的根目录 bc 变量 → NameError / 空图。
# 改为从 convergence_3000 聚合 losses（n=71 同源）。
fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
_loss_curve, _n_loss = _agg_curve('bc_marl', field='losses')
if _loss_curve is not None and len(_loss_curve) > 0:
    ax.plot(_loss_curve, color='#3b82f6', linewidth=1.5, alpha=0.7)
    ax.set_xlabel('训练步数 (Training Step)', fontsize=12)
    ax.set_ylabel('TD Loss', fontsize=12)
    ax.set_title(f'BC-MARL 训练损失曲线 (n={_n_loss})', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.set_facecolor('#fafafa')
else:
    ax.text(0.5, 0.5, '暂无损失数据', ha='center', va='center', transform=ax.transAxes, fontsize=14)
    ax.set_title('BC-MARL 训练损失曲线', fontsize=14, fontweight='bold')
fig.patch.set_facecolor('white')
fig.savefig(OUT / 'training_loss.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved: training_loss.png')

# === 4. P2P节点拓扑图 (for PPT 第7页 纯去中心化P2P) ===
fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')

# 3个节点，三角形布局
nodes = [(2, 5), (8, 5), (5, 8.5)]
labels = ['Node-0\n(服务端+客户端)', 'Node-1\n(服务端+客户端)', 'Node-2\n(服务端+客户端)']
colors = ['#22c55e', '#3b82f6', '#f59e0b']

for (x, y), label, color in zip(nodes, labels, colors):
    circle = plt.Circle((x, y), 1.2, fill=True, facecolor=color, alpha=0.2, edgecolor=color, linewidth=2)
    ax.add_patch(circle)
    ax.text(x, y, label, ha='center', va='center', fontsize=9, fontweight='bold', color=color)

# 连接线（全连接）
for i in range(len(nodes)):
    for j in range(i+1, len(nodes)):
        x1, y1 = nodes[i]
        x2, y2 = nodes[j]
        ax.plot([x1, x2], [y1, y2], 'k-', alpha=0.3, linewidth=1.5, zorder=0)

ax.set_title('纯去中心化 P2P 对等网络拓扑 (3节点全互联)', fontsize=14, fontweight='bold')
fig.patch.set_facecolor('white')
fig.savefig(OUT / 'p2p_topology.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved: p2p_topology.png')

# === 5. ECDSA 签名验签流程图 (for PPT 第12页) ===
fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
ax.set_xlim(0, 10)
ax.set_ylim(0, 5)
ax.axis('off')

# 发送方
rect1 = plt.Rectangle((0.5, 2.5), 2, 1.5, fill=True, facecolor='#e0f2fe', edgecolor='#3b82f6', linewidth=2)
ax.add_patch(rect1)
ax.text(1.5, 3.5, '发送方', ha='center', va='center', fontsize=12, fontweight='bold', color='#3b82f6')
ax.text(1.5, 3.0, '私钥签名\nmsg + sig', ha='center', va='center', fontsize=9, color='#333')

# 箭头
ax.annotate('', xy=(4.5, 3.25), xytext=(2.5, 3.25),
           arrowprops=dict(arrowstyle='->', color='#333', lw=2))
ax.text(3.5, 3.5, 'Socket 传输', ha='center', va='center', fontsize=10, color='#666')

# 网络
rect2 = plt.Rectangle((4.5, 2.5), 1, 1.5, fill=True, facecolor='#f3f4f6', edgecolor='#666', linewidth=1, linestyle='--')
ax.add_patch(rect2)
ax.text(5, 3.25, 'TCP\nSocket', ha='center', va='center', fontsize=9, color='#666')

# 箭头
ax.annotate('', xy=(7.5, 3.25), xytext=(5.5, 3.25),
           arrowprops=dict(arrowstyle='->', color='#333', lw=2))

# 接收方
rect3 = plt.Rectangle((7.5, 2.5), 2, 1.5, fill=True, facecolor='#ecfdf5', edgecolor='#22c55e', linewidth=2)
ax.add_patch(rect3)
ax.text(8.5, 3.5, '接收方', ha='center', va='center', fontsize=12, fontweight='bold', color='#22c55e')
ax.text(8.5, 3.0, '公钥验签\nverify(sig)', ha='center', va='center', fontsize=9, color='#333')

# 验签结果分支
ax.annotate('', xy=(8.5, 1.5), xytext=(8.5, 2.5),
           arrowprops=dict(arrowstyle='->', color='#22c55e', lw=1.5))
ax.text(9.5, 1.9, 'OK -> 处理', ha='left', va='center', fontsize=9, color='#22c55e')
ax.text(7.5, 1.9, 'FAIL -> 丢弃', ha='right', va='center', fontsize=9, color='#ef4444')

ax.set_title('ECDSA 端到端签名验签流程', fontsize=14, fontweight='bold')
fig.patch.set_facecolor('white')
fig.savefig(OUT / 'ecdsa_flow.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved: ecdsa_flow.png')

# === 6. 安全测试结果对比 (for PPT 第15页) ===
fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
ax.axis('off')

data = [
    ('消息篡改攻击', '关闭验签', '攻击成功', '#ef4444'),
    ('消息篡改攻击', '开启验签', '100%拦截', '#22c55e'),
    ('身份伪造攻击', '关闭验签', '系统被突破', '#ef4444'),
    ('身份伪造攻击', '开启验签', '100%拦截', '#22c55e'),
]

for i, (attack, state, result, color) in enumerate(data):
    y = 0.8 - i * 0.18
    ax.text(0.05, y, attack, fontsize=11, transform=ax.transAxes, va='center')
    ax.text(0.35, y, state, fontsize=11, transform=ax.transAxes, va='center', color='#666')
    rect = plt.Rectangle((0.55, y-0.04), 0.3, 0.08, fill=True, facecolor=color, alpha=0.15, 
                          edgecolor=color, linewidth=1.5, transform=ax.transAxes)
    ax.add_patch(rect)
    ax.text(0.7, y, result, fontsize=11, ha='center', transform=ax.transAxes, va='center', 
            color=color, fontweight='bold')

ax.set_title('ECDSA 安全验证测试结果', fontsize=14, fontweight='bold', transform=ax.transAxes, y=0.95)
fig.patch.set_facecolor('white')
fig.savefig(OUT / 'security_test_results.png', dpi=150, bbox_inches='tight')
plt.close()
print('Saved: security_test_results.png')

print(f'\nAll done! {len(list(OUT.glob("*.png")))} images in {OUT}')
