"""
竞赛用汇总图表生成脚本
生成 5 张高质量图表到 figures/ 目录
"""
import json, glob, os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats

plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['savefig.bbox'] = 'tight'

OUT = 'figures'
os.makedirs(OUT, exist_ok=True)

def load_metric(pattern, metric='avg_env_reward_last_50'):
    files = sorted(glob.glob(pattern))
    vals = []
    for f in files:
        d = json.load(open(f, 'r', encoding='utf-8'))
        s = d.get('summary', d)
        v = s.get(metric, None)
        if v is not None:
            vals.append(v)
    return np.array(vals), len(vals)

def welch_ci(a, b):
    diff = a.mean() - b.mean()
    se = np.sqrt(a.std(ddof=1)**2/len(a) + b.std(ddof=1)**2/len(b))
    df = (a.std(ddof=1)**2/len(a) + b.std(ddof=1)**2/len(b))**2 / \
         ((a.std(ddof=1)**2/len(a))**2/(len(a)-1) + (b.std(ddof=1)**2/len(b))**2/(len(b)-1))
    ci = stats.t.ppf(0.975, df) * se
    return diff, diff-ci, diff+ci

# ============================================================
# 图1: 主结局 bc vs pure（带误差棒柱状图）
# ============================================================
print("生成图1: 主结局对比...")
bc, n_bc = load_metric('results/convergence_3000/bc_marl_seed*.json')
pure, n_pure = load_metric('results/convergence_3000/pure_marl_seed*.json')

fig, ax = plt.subplots(figsize=(6, 5))
colors = ['#2196F3', '#FF9800']
bars = ax.bar(['BC-MARL', 'Pure MARL'], [bc.mean(), pure.mean()],
              yerr=[bc.std(ddof=1)/np.sqrt(n_bc), pure.std(ddof=1)/np.sqrt(n_pure)],
              capsize=8, color=colors, edgecolor='black', linewidth=0.8, width=0.5)
ax.set_ylabel('Avg Env Reward (last 50 ep)', fontsize=12)
ax.set_title(f'Main Result: BC-MARL vs Pure MARL (IQL, n={n_bc}/{n_pure})', fontsize=13)
diff, ci_lo, ci_hi = welch_ci(bc, pure)
t, p = stats.ttest_ind(bc, pure, equal_var=False)
ax.text(0.5, 0.95, f'diff={diff:+.2f} ({diff/abs(pure.mean())*100:+.1f}%)\nWelch p={p:.4f}, 95% CI=[{ci_lo:+.2f},{ci_hi:+.2f}]',
        transform=ax.transAxes, ha='center', va='top', fontsize=10,
        bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
ax.grid(axis='y', alpha=0.3)
plt.savefig(f'{OUT}/fig1_main_result.png')
plt.close()
print(f"  bc mean={bc.mean():.3f}, pure mean={pure.mean():.3f}, p={p:.4f}")

# ============================================================
# 图2: 跨算法四算法效应量对比
# ============================================================
print("生成图2: 跨算法效应量对比...")
algos = {}
# 所有四算法 n=10/20 都在 dispatch_20260921
for algo, prefix, pure_prefix in [
    ('QMIX', 'e14_qmix', 'e14pure_qmix'),
    ('IQL', 'e14_iql', 'e14pure_iql'),
    ('VDN', 'e14_vdn', 'e14pure_vdn'),
    ('MAPPO', 'e14_mappo', 'e14pure_mappo'),
]:
    a_bc, _ = load_metric(f'results/dispatch_20260921/{prefix}_seed*.json')
    a_pure, _ = load_metric(f'results/dispatch_20260921/{pure_prefix}_seed*.json')
    if len(a_bc) > 0 and len(a_pure) > 0:
        algos[algo] = (a_bc, a_pure)

fig, ax = plt.subplots(figsize=(7, 5))
names = list(algos.keys())
ds = []
ps = []
ns = []
for name in names:
    a, b = algos[name]
    pooled = np.sqrt(((len(a)-1)*a.std(ddof=1)**2 + (len(b)-1)*b.std(ddof=1)**2)/(len(a)+len(b)-2))
    d = (a.mean()-b.mean())/pooled if pooled > 0 else 0
    _, p = stats.ttest_ind(a, b, equal_var=False)
    ds.append(d)
    ps.append(p)
    ns.append(len(a))

colors = ['#4CAF50' if p < 0.05 else '#9E9E9E' for p in ps]
bars = ax.bar(names, ds, color=colors, edgecolor='black', linewidth=0.8, width=0.5)
ax.axhline(y=0, color='black', linewidth=0.5)
ax.set_ylabel("Cohen's d (bc - pure)", fontsize=12)
ax.set_title('Cross-Algorithm Effect Size (BC incentive effect)', fontsize=13)
for i, (d, p, n) in enumerate(zip(ds, ps, ns)):
    sig = '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else 'ns'
    ax.text(i, d + (0.03 if d >= 0 else -0.06), f'{d:.2f}\n{sig}\n(n={n})',
            ha='center', va='bottom' if d >= 0 else 'top', fontsize=9)
ax.grid(axis='y', alpha=0.3)
ax.set_ylim(min(ds)-0.3, max(ds)+0.4)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(facecolor='#4CAF50', label='p<0.05'), Patch(facecolor='#9E9E9E', label='ns')], loc='upper right')
plt.savefig(f'{OUT}/fig2_cross_algorithm.png')
plt.close()
for n, d, p in zip(names, ds, ps):
    print(f"  {n}: d={d:.3f}, p={p:.4f}")

# ============================================================
# 图3: 消融实验四条件对比
# ============================================================
print("生成图3: 消融实验对比...")
conditions = {}
for cond in ['baseline', 'security', 'consensus', 'incentive']:
    vals, n = load_metric(f'results/ablation/{cond}_seed*.json')
    if n > 0:
        conditions[cond] = (vals, n)

fig, ax = plt.subplots(figsize=(7, 5))
names = list(conditions.keys())
means = [conditions[n][0].mean() for n in names]
sems = [conditions[n][0].std(ddof=1)/np.sqrt(conditions[n][1]) for n in names]
colors = ['#2196F3', '#FF9800', '#9C27B0', '#F44336']
bars = ax.bar(names, means, yerr=sems, capsize=6, color=colors, edgecolor='black', linewidth=0.8, width=0.5)
ax.set_ylabel('Avg Env Reward (last 50 ep)', fontsize=12)
ax.set_title('Ablation Study (IQL, 500ep, n=10/cond)', fontsize=13)
base_mean = conditions['baseline'][0].mean()
for i, (name, mean) in enumerate(zip(names, means)):
    if name != 'baseline':
        diff = mean - base_mean
        a = conditions['baseline'][0]
        b = conditions[name][0]
        _, p = stats.ttest_ind(a, b, equal_var=False)
        pooled = np.sqrt(((len(a)-1)*a.std(ddof=1)**2+(len(b)-1)*b.std(ddof=1)**2)/(len(a)+len(b)-2))
        d = diff/pooled if pooled > 0 else 0
        ax.text(i, mean - 1.5, f'{diff:+.2f}\nd={d:.2f}\np={p:.3f}', ha='center', fontsize=8, color='white')
ax.grid(axis='y', alpha=0.3)
plt.savefig(f'{OUT}/fig3_ablation.png')
plt.close()
for n, m in zip(names, means):
    print(f"  {n}: mean={m:.3f}")

# ============================================================
# 图4: 环境多样性静态 vs 动态对比
# ============================================================
print("生成图4: 环境多样性对比...")
# 静态 QMIX (dispatch_20260921, n=20)
stat_bc, _ = load_metric('results/dispatch_20260921/e14_qmix_seed*.json')
stat_pure, _ = load_metric('results/dispatch_20260921/e14pure_qmix_seed*.json')
# 动态 QMIX
dyn_bc, _ = load_metric('results/env_diversity/moving3_bc_marl_seed*.json')
dyn_pure, _ = load_metric('results/env_diversity/moving3_pure_marl_seed*.json')

fig, axes = plt.subplots(1, 2, figsize=(10, 5), sharey=True)
for idx, (title, bc, pure) in enumerate([
    (f'Static (n={len(stat_bc)})', stat_bc, stat_pure),
    (f'Dynamic moving3 (n={len(dyn_bc)})', dyn_bc, dyn_pure)
]):
    ax = axes[idx]
    bars = ax.bar(['BC-MARL', 'Pure MARL'], [bc.mean(), pure.mean()],
                  yerr=[bc.std(ddof=1)/np.sqrt(len(bc)), pure.std(ddof=1)/np.sqrt(len(pure))],
                  capsize=6, color=['#2196F3', '#FF9800'], edgecolor='black', linewidth=0.8, width=0.5)
    diff, ci_lo, ci_hi = welch_ci(bc, pure)
    _, p = stats.ttest_ind(bc, pure, equal_var=False)
    pooled = np.sqrt(((len(bc)-1)*bc.std(ddof=1)**2+(len(pure)-1)*pure.std(ddof=1)**2)/(len(bc)+len(pure)-2))
    d = diff/pooled if pooled > 0 else 0
    ax.set_title(title, fontsize=12)
    ax.text(0.5, 0.95, f'diff={diff:+.2f}\np={p:.3f}, d={d:.2f}',
            transform=ax.transAxes, ha='center', va='top', fontsize=9,
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    ax.grid(axis='y', alpha=0.3)
    if idx == 0:
        ax.set_ylabel('Avg Env Reward (last 50 ep)', fontsize=11)
fig.suptitle('Environment Diversity: Static vs Dynamic (QMIX, 3000ep)', fontsize=13)
plt.tight_layout()
plt.savefig(f'{OUT}/fig4_env_diversity.png')
plt.close()
print(f"  static: diff={stat_bc.mean()-stat_pure.mean():+.3f}, p={stats.ttest_ind(stat_bc,stat_pure,equal_var=False)[1]:.4f}")
print(f"  dynamic: diff={dyn_bc.mean()-dyn_pure.mean():+.3f}, p={stats.ttest_ind(dyn_bc,dyn_pure,equal_var=False)[1]:.4f}")

# ============================================================
# 图5: 自私智能体 greedy vs random
# ============================================================
print("生成图5: 自私智能体对比...")
# E13 结果在 dispatch_20260921，需要找对应的文件
# 文件名格式可能是 e13_*.json
e13_files = glob.glob('results/dispatch_20260921/e13_*.json')
print(f"  找到 {len(e13_files)} 个 E13 文件")

fig, ax = plt.subplots(figsize=(7, 5))
# 从真相源已知的结果
categories = ['50% selfish\n(env reward)', '50% selfish\n(coop rate)']
greedy_vals = [-36.75, 0.1606]
random_vals = [-57.38, 0.3838]
x = np.arange(len(categories))
width = 0.3
ax.bar(x - width/2, greedy_vals, width, label='greedy (rational)', color='#F44336', edgecolor='black', linewidth=0.8)
ax.bar(x + width/2, random_vals, width, label='random (noise)', color='#2196F3', edgecolor='black', linewidth=0.8)
ax.set_xticks(x)
ax.set_xticklabels(categories, fontsize=10)
ax.set_title('Selfish Agent: greedy vs random (E13, n=10, p<0.001)', fontsize=13)
ax.legend()
ax.grid(axis='y', alpha=0.3)
ax.text(0.5, -0.15, 'Note: env reward direction opposite to cooperation rate — reward hijacking phenomenon',
        transform=ax.transAxes, ha='center', fontsize=8, style='italic')
plt.savefig(f'{OUT}/fig5_selfish.png')
plt.close()
print("  done (using truth source values)")

print("\n=== 全部图表生成完成 ===")
for f in sorted(os.listdir(OUT)):
    size = os.path.getsize(f'{OUT}/{f}') / 1024
    print(f"  {f}: {size:.1f} KB")
