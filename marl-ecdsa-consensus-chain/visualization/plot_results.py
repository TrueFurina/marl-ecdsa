"""
实验结果可视化
从 training_results.json / experiment_results.json 生成对比图表

输出图表：
1. 训练奖励曲线（纯MARL vs BC-MARL）
2. 合作率对比
3. 积分排行榜
4. 自私比例影响
"""
import json
import logging
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')

# logger 必须在 basicConfig 之前定义（P1-6 修复：原代码 L36 使用 logger 但 L48 才定义）
logger = logging.getLogger('plot')

# 设置中文字体（国赛演示必需）
_MPL_CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', '.matplotlib')
os.makedirs(_MPL_CONFIG_DIR, exist_ok=True)
os.environ['MPLCONFIGDIR'] = _MPL_CONFIG_DIR

import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Any

# 配置中文字体
_CN_FONT_CANDIDATES = ['Noto Sans SC', 'Microsoft JhengHei', 'SimHei', 'STZhongsong', 'SimSun', 'WenQuanYi Micro Hei']
_CN_FONT = None
for _f in _CN_FONT_CANDIDATES:
    try:
        matplotlib.font_manager.findfont(_f, fallback_to_default=False)
        _CN_FONT = _f
        break
    except (ValueError, RuntimeError) as e:
        logger.debug(f"字体搜索跳过: {e}")
        continue

if _CN_FONT:
    plt.rcParams['font.sans-serif'] = [_CN_FONT, 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    logger.info(f"[Plot] 中文字体已配置: {_CN_FONT}")
else:
    logger.warning("[Plot] 未找到中文字体，图表中文将显示为方框")

logging.basicConfig(level=logging.INFO, format='%(message)s')


def plot_training_curve(results: Dict, output_path: str = 'training_curve.png'):
    """绘制训练奖励曲线"""
    episode_rewards = results.get('episode_rewards', [])
    if not episode_rewards:
        logger.warning("无训练数据")
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(episode_rewards, label='回合总奖励', color='#1a1a2e', alpha=0.7)

    # 平滑曲线
    window = min(50, len(episode_rewards))
    if len(episode_rewards) >= window:
        smoothed = np.convolve(episode_rewards, np.ones(window)/window, mode='valid')
        ax.plot(
            range(window-1, len(episode_rewards)),
            smoothed,
            label=f'平滑({window})',
            color='#e94560', linewidth=2
        )

    ax.set_xlabel('训练回合')
    ax.set_ylabel('总奖励')
    ax.set_title('MARL-ECDSA 训练奖励曲线')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    logger.info(f"训练曲线已保存: {output_path}")


def plot_cooperation_rate(results: Dict, output_path: str = 'cooperation_rate.png'):
    """绘制合作率变化"""
    rates = results.get('cooperation_rates', [])
    if not rates:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(rates, color='#52c41a', alpha=0.7, label='合作率')

    window = min(50, len(rates))
    if len(rates) >= window:
        smoothed = np.convolve(rates, np.ones(window)/window, mode='valid')
        ax.plot(range(window-1, len(rates)), smoothed, color='#e94560', linewidth=2, label=f'平滑({window})')

    ax.set_xlabel('训练回合')
    ax.set_ylabel('合作率')
    ax.set_title('合作率变化曲线')
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    logger.info(f"合作率曲线已保存: {output_path}")


def plot_experiment_comparison(exp_results: Dict, output_dir: str = '.'):
    """绘制对照实验对比图"""
    Path(output_dir).mkdir(exist_ok=True)
    experiments = exp_results.get('experiments', [])

    for exp in experiments:
        exp_name = exp.get('name', 'unknown')
        exp_data = exp.get('results', {})

        # 提取各组的平均奖励
        labels = []
        avg_rewards = []
        coop_rates = []

        for key, summary in exp_data.items():
            if key == 'comparison':
                continue
            labels.append(key)
            avg_rewards.append(summary.get('avg_reward', 0))
            coop_rates.append(summary.get('avg_cooperation_rate', 0) * 100)

        if not labels:
            continue

        # 图1：平均奖励对比
        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.bar(labels, avg_rewards, color=['#1a1a2e', '#0f3460', '#533483', '#e94560'][:len(labels)])
        ax.set_ylabel('平均回合奖励')
        ax.set_title(f'{exp_name}\n平均奖励对比')
        ax.grid(True, alpha=0.3, axis='y')
        for bar, val in zip(bars, avg_rewards):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{val:.1f}', ha='center', va='bottom', fontsize=9)
        plt.tight_layout()
        plt.savefig(f'{output_dir}/exp_{len(labels)}_{exp_name[:10]}_reward.png', dpi=150)

        # 图2：合作率对比
        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.bar(labels, coop_rates, color=['#52c41a', '#faad14', '#e94560', '#f39c12'][:len(labels)])
        ax.set_ylabel('合作率 (%)')
        ax.set_title(f'{exp_name}\n合作率对比')
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.3, axis='y')
        for bar, val in zip(bars, coop_rates):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{val:.1f}%', ha='center', va='bottom', fontsize=9)
        plt.tight_layout()
        plt.savefig(f'{output_dir}/exp_{len(labels)}_{exp_name[:10]}_coop.png', dpi=150)

        logger.info(f"实验对比图已保存: {exp_name}")


def plot_leaderboard(results: Dict, output_path: str = 'leaderboard.png'):
    """绘制积分排行榜"""
    leaderboard = results.get('leaderboard', [])
    if not leaderboard:
        return

    agents = [x['agent_id'] for x in leaderboard]
    scores = [x['score'] for x in leaderboard]

    fig, ax = plt.subplots(figsize=(8, max(4, len(agents)*0.5)))
    colors = ['#52c41a' if s >= 0 else '#e94560' for s in scores]
    ax.barh(agents, scores, color=colors)
    ax.set_xlabel('链上积分')
    ax.set_title('智能体积分排行榜')
    ax.grid(True, alpha=0.3, axis='x')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    logger.info(f"排行榜已保存: {output_path}")


def generate_all_plots(results_path: str = 'training_results.json', output_dir: str = 'plots'):
    """一键生成所有图表"""
    Path(output_dir).mkdir(exist_ok=True)

    # P3-9修复: 缺失结果文件时降级返回（此前 open 直接抛 FileNotFoundError）
    if not os.path.exists(results_path):
        logger.warning(f"[PlotResults] 结果文件不存在: {results_path}，跳过图表生成")
        return None

    with open(results_path, 'r', encoding='utf-8') as f:
        results = json.load(f)

    plot_training_curve(results, f'{output_dir}/training_curve.png')
    plot_cooperation_rate(results, f'{output_dir}/cooperation_rate.png')
    plot_leaderboard(results, f'{output_dir}/leaderboard.png')

    logger.info(f"所有图表已保存到 {output_dir}/")


def _plot_reward_comparison(pure_r, bc_r, window, output_dir):
    """图1：奖励曲线对比（50回合平滑）"""
    fig, ax = plt.subplots(figsize=(12, 5))
    if len(pure_r) >= window and len(bc_r) >= window:
        pure_sm = np.convolve(pure_r, np.ones(window)/window, mode='valid')
        bc_sm = np.convolve(bc_r, np.ones(window)/window, mode='valid')
        x = range(window, len(pure_r) + 1)
        ax.plot(x, pure_sm, color='#94a3b8', linewidth=2, label='Pure MARL', alpha=0.85)
        ax.plot(x, bc_sm, color='#38bdf8', linewidth=2, label='BC-MARL', alpha=0.9)
        ax.fill_between(x, pure_sm, bc_sm, where=(np.array(bc_sm) > np.array(pure_sm[:len(bc_sm)])),
                        color='#34d399', alpha=0.08, label='BC 优势区域')
    _set_chart_style(ax, '训练回合', '回合总奖励（50回合平滑）', 'MARL-ECDSA 训练奖励对比：Pure MARL vs BC-MARL')
    plt.savefig(f'{output_dir}/comparison_reward.png', dpi=200, bbox_inches='tight')
    plt.close()
    logger.info(f"奖励对比图已保存: {output_dir}/comparison_reward.png")


def _plot_cooperation_comparison(pure_c, bc_c, output_dir):
    """图2：合作率对比"""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(pure_c, color='#94a3b8', linewidth=1.5, label='Pure MARL 合作率', alpha=0.7)
    ax.plot(bc_c, color='#34d399', linewidth=1.5, label='BC-MARL 合作率', alpha=0.7)
    ax.set_ylim(0, 1.05)
    _set_chart_style(ax, '训练回合', '合作率', '合作率对比：Pure MARL vs BC-MARL')
    plt.savefig(f'{output_dir}/comparison_coop.png', dpi=200, bbox_inches='tight')
    plt.close()
    logger.info(f"合作率对比图已保存: {output_dir}/comparison_coop.png")


def _plot_reward_distribution(pure_r, bc_r, output_dir):
    """图3：奖励分布箱线图"""
    fig, ax = plt.subplots(figsize=(8, 5))
    # matplotlib >=3.9 将 boxplot 的 labels= 重命名为 tick_labels=，3.11 起彻底移除
    # labels=。为兼容锁定版(3.11.0)与更旧环境，按版本动态选择关键字。
    import matplotlib as _mpl
    _box_kw = 'tick_labels' if _mpl.__version_info__ >= (3, 9) else 'labels'
    bp = ax.boxplot(
        [pure_r[-200:], bc_r[-200:]],
        **{_box_kw: ['Pure MARL', 'BC-MARL']},
        patch_artist=True, widths=0.5,
    )
    bp['boxes'][0].set_facecolor('#94a3b8'); bp['boxes'][1].set_facecolor('#38bdf8')
    for box in bp['boxes']: box.set_alpha(0.5)
    ax.set_ylabel('回合总奖励', fontsize=11)
    ax.set_title('后200回合奖励分布对比', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.2, axis='y')
    plt.tight_layout()
    plt.savefig(f'{output_dir}/comparison_boxplot.png', dpi=200, bbox_inches='tight')
    plt.close()
    logger.info(f"奖励分布图已保存: {output_dir}/comparison_boxplot.png")


def _plot_bc_score_trend(bc, output_dir):
    """图4：BC 积分趋势"""
    bc_scores_hist = bc.get('bc_scores_history', [])
    if not bc_scores_hist:
        return
    fig, ax = plt.subplots(figsize=(12, 5))
    agents = list(bc_scores_hist[0].keys())
    colors = ['#38bdf8', '#f87171', '#34d399']
    for i, aid in enumerate(agents):
        vals = [h.get(aid, 0) for h in bc_scores_hist]
        ax.plot(vals, color=colors[i % 3], linewidth=1.8, label=aid)
    _set_chart_style(ax, '训练回合', '链上累计积分', '智能体链上积分变化趋势（BC-MARL）')
    plt.savefig(f'{output_dir}/bc_scores.png', dpi=200, bbox_inches='tight')
    plt.close()
    logger.info(f"BC积分图已保存: {output_dir}/bc_scores.png")


def _plot_dashboard_overview(pure_r, bc_r, pure_c, bc_c, pure, bc, bc_scores_hist, window, output_dir):
    """图5：综合对比仪表盘（四合一）"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    _plot_dashboard_reward(axes[0, 0], pure_r, bc_r, window)
    _plot_dashboard_coop(axes[0, 1], pure_c, bc_c)
    _plot_dashboard_bc_score(axes[1, 0], bc_scores_hist)
    _plot_dashboard_metrics(axes[1, 1], pure, bc)
    plt.suptitle('MARL-ECDSA 共识链 — 训练结果综合仪表盘', fontsize=14, fontweight='bold', y=1.01)
    plt.tight_layout()
    plt.savefig(f'{output_dir}/dashboard_overview.png', dpi=200, bbox_inches='tight')
    plt.close()
    logger.info(f"综合仪表盘已保存: {output_dir}/dashboard_overview.png")


def _plot_dashboard_reward(ax, pure_r, bc_r, window):
    if len(pure_r) >= window and len(bc_r) >= window:
        pure_sm = np.convolve(pure_r, np.ones(window)/window, mode='valid')
        bc_sm = np.convolve(bc_r, np.ones(window)/window, mode='valid')
        x = range(window, len(pure_r) + 1)
        ax.plot(x, pure_sm, color='#94a3b8', linewidth=2, label='Pure MARL')
        ax.plot(x, bc_sm, color='#38bdf8', linewidth=2, label='BC-MARL')
    _set_chart_style(ax, '回合', '奖励', '训练奖励对比', fontsize=9)


def _plot_dashboard_coop(ax, pure_c, bc_c):
    ax.plot(pure_c, color='#94a3b8', linewidth=1.2, label='Pure', alpha=0.7)
    ax.plot(bc_c, color='#34d399', linewidth=1.2, label='BC', alpha=0.7)
    _set_chart_style(ax, '回合', '合作率', '合作率对比', fontsize=9)


def _plot_dashboard_bc_score(ax, bc_scores_hist):
    if bc_scores_hist:
        agents = list(bc_scores_hist[0].keys())
        colors = ['#38bdf8', '#f87171', '#34d399']
        for i, aid in enumerate(agents):
            vals = [h.get(aid, 0) for h in bc_scores_hist]
            ax.plot(vals, color=colors[i % 3], linewidth=1.5, label=aid)
    _set_chart_style(ax, '回合', '积分', 'BC积分趋势', fontsize=9)


def _plot_dashboard_metrics(ax, pure, bc):
    ps, bs = pure['summary'], bc['summary']
    metrics = ['avg_reward', 'avg_reward_last_50']
    labels = ['全程平均奖励', '后50回合均奖励']
    x_pos = np.arange(len(metrics))
    w = 0.35
    ax.bar(x_pos - w/2, [ps[m] for m in metrics], w, color='#94a3b8', alpha=0.7, label='Pure')
    ax.bar(x_pos + w/2, [bs[m] for m in metrics], w, color='#38bdf8', alpha=0.7, label='BC')
    ax.set_xticks(x_pos); ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('奖励', fontsize=9); ax.set_title('关键指标对比', fontsize=11, fontweight='bold')
    ax.legend(fontsize=8); ax.grid(True, alpha=0.2, axis='y')
    ax.axhline(y=0, color='#475569', linestyle='--', linewidth=0.8)


def _set_chart_style(ax, xlabel, ylabel, title, fontsize=11):
    """统一图表样式"""
    ax.set_xlabel(xlabel, fontsize=fontsize)
    ax.set_ylabel(ylabel, fontsize=fontsize)
    ax.set_title(title, fontsize=fontsize + 2, fontweight='bold')
    ax.legend(fontsize=fontsize - 2)
    ax.grid(True, alpha=0.2)


def plot_pure_vs_bc_comparison(
    pure_path: str = 'training_results_pure.json',
    bc_path: str = 'training_results_bc.json',
    output_dir: str = 'plots'
):
    """生成 pure_marl vs bc_marl 全面对比图表（国赛演示专用）"""
    Path(output_dir).mkdir(exist_ok=True)
    with open(pure_path, 'r', encoding='utf-8') as f: pure = json.load(f)
    with open(bc_path, 'r', encoding='utf-8') as f: bc = json.load(f)

    pure_r = pure.get('episode_rewards', []); bc_r = bc.get('episode_rewards', [])
    pure_c = pure.get('cooperation_rates', []); bc_c = bc.get('cooperation_rates', [])
    window = 50

    _plot_reward_comparison(pure_r, bc_r, window, output_dir)
    _plot_cooperation_comparison(pure_c, bc_c, output_dir)
    _plot_reward_distribution(pure_r, bc_r, output_dir)
    _plot_bc_score_trend(bc, output_dir)
    _plot_dashboard_overview(pure_r, bc_r, pure_c, bc_c, pure, bc,
                             bc.get('bc_scores_history', []), window, output_dir)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=str, default='training_results.json')
    parser.add_argument('--output_dir', type=str, default='plots')
    parser.add_argument('--experiment', type=str, default='experiment_results.json')
    args = parser.parse_args()

    # 训练结果图表
    if Path(args.results).exists():
        generate_all_plots(args.results, args.output_dir)

    # 对照实验图表
    if Path(args.experiment).exists():
        with open(args.experiment, 'r', encoding='utf-8') as f:
            exp_results = json.load(f)
        plot_experiment_comparison(exp_results, args.output_dir)

    logger.info("图表生成完成")
