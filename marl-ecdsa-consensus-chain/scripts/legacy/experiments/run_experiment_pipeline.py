"""
实验报告自动生成流水线

一键运行全部实验并生成竞赛报告:
    python run_experiment_pipeline.py --quick   # 快速模式（200回合×3种子）
    python run_experiment_pipeline.py --full    # 完整模式（500回合×5种子）
"""

# ===== 自动注入: 仓库根路径 (legacy 移动兼容) =====
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = str(_Path(__file__).resolve().parent.parent.parent.parent)
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)
# ===== 自动注入结束 =====

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 仓库根（原为 Path(__file__).parent → legacy/experiments）
ROOT = Path(_REPO_ROOT)
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('pipeline')


def step(name: str, func, *args, **kwargs):
    """执行一个实验步骤并计时"""
    logger.info(f"{'='*60}")
    logger.info(f"步骤: {name}")
    logger.info(f"{'='*60}")
    t0 = time.time()
    result = func(*args, **kwargs)
    elapsed = time.time() - t0
    logger.info(f"完成: {name} ({elapsed:.1f}s)")
    return result


def run_scale_experiment(episodes: int, seeds: int):
    """运行多智能体规模实验"""
    logger.info("运行多智能体规模实验...")
    from run_scale_experiment import run_scale_experiment as run_scale

    _ep, _sd = episodes, seeds
    class Args:
        agents = [3, 5]
        episodes = _ep
        seeds = _sd
        seed_list = [42, 123, 456][:_sd]
        lambda_weight = 0.1
        output = f'results/scale_experiment_{_ep}ep.json'

    run_scale(Args)
    return Args.output


def run_ablation(episodes: int, seeds: int):
    """运行消融实验"""
    logger.info("运行消融实验...")
    seed_list = [42, 123, 456][:seeds]
    from train import TrainingConfig, MARLBlockchainTrainer
    import numpy as np

    results = {}
    for condition in ['baseline', 'ablate_security', 'ablate_consensus', 'ablate_incentive']:
        vals = []
        for seed in seed_list:
            config = TrainingConfig(
                n_agents=3, n_episodes=episodes, mode='bc_marl',
                lambda_weight=0.1, seed=seed,
                ablate_security=(condition == 'ablate_security'),
                ablate_consensus=(condition == 'ablate_consensus'),
                ablate_incentive=(condition == 'ablate_incentive'),
            )
            trainer = MARLBlockchainTrainer(config)
            stats = trainer.train()
            vals.append(stats.summary()['avg_env_reward'])
        results[condition] = {
            'mean': float(np.mean(vals)),
            'std': float(np.std(vals)),
            'values': vals,
        }
        logger.info(f"  {condition}: {results[condition]['mean']:.2f}±{results[condition]['std']:.2f}")

    path = ROOT / 'results' / f'ablation_pipeline_{episodes}ep.json'
    with open(path, 'w') as f:
        json.dump(results, f, indent=2)
    return str(path)


def generate_report(input_files: list, output_name: str, out_dir=None):
    """生成综合报告

    out_dir: 报告落盘目录。默认 None → ROOT/'results'（历史行为，保持向后兼容）。
             调用方（尤其测试）可传入临时目录，避免把报告写进 results/ 数据根目录。
    """
    from analyze_all_experiments import generate_markdown_report as gen_md_report
    logger.info("生成综合实验报告...")
    # 收集所有结果
    all_data = {}
    for f in input_files:
        path = ROOT / f
        if path.exists():
            with open(path) as fh:
                all_data[path.stem] = json.load(fh)
    # 生成 Markdown 报告
    md_lines = [
        f"# 综合实验报告",
        f"",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 流水线: auto",
        f"",
        f"## 实验配置",
        f"",
        f"| 实验 | 涉及文件 |",
        f"|------|---------|",
    ]
    for f in input_files:
        md_lines.append(f"| {f} | {'✅ 已包含' if (ROOT/f).exists() else '❌ 未找到'} |")

    md_lines.extend([
        "",
        "## 多智能体规模实验",
        "",
        "| 智能体数 | 模式 | env_reward | 合作率 | BC提升 |",
        "|---------|------|-----------|--------|--------|",
    ])

    # P3-4修复: input_files 可能为空/长度不足，访问前需加保护（此前空列表 IndexError）
    if len(input_files) > 0:
        scale_path = ROOT / input_files[0]
        if scale_path.exists():
            with open(scale_path) as fh:
                scale_data = json.load(fh)
            for n in [3, 5]:
                for mode in ['pure_marl', 'bc_marl']:
                    key = f"{mode}_n{n}"
                    if key in scale_data:
                        r = scale_data[key]
                        impr_key = f"bc_improvement_n{n}"
                        impr = f"{scale_data[impr_key]['improvement_pct']:+.1f}%" if impr_key in scale_data else ""
                        env = f"{r['env_reward_mean']:.1f}±{r['env_reward_std']:.1f}"
                        coop = f"{r['coop_rate_mean']:.1%}"
                        if mode == 'pure_marl':
                            md_lines.append(f"| {n} | {mode} | {env} | {coop} | {impr} |")
                        else:
                            md_lines.append(f"| | {mode} | {env} | {coop} | |")

    md_lines.extend([
        "",
        "## 消融实验",
        "",
        "| 条件 | env_reward | vs baseline |",
        "|------|-----------|-------------|",
    ])

    if len(input_files) > 1:
        abl_path = ROOT / input_files[1]
        if abl_path.exists():
            with open(abl_path) as fh:
                abl_data = json.load(fh)
            baseline = abl_data.get('baseline', {}).get('mean', 0)
            for cond, vals in abl_data.items():
                impr = f"{(vals['mean'] - baseline) / max(0.001, abs(baseline)) * 100:+.1f}%"
                md_lines.append(f"| {cond} | {vals['mean']:.2f}±{vals['std']:.2f} | {impr} |")

    md_lines.append("")
    md_lines.append("---")
    md_lines.append(f"*报告由 auto-pipeline 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    report_dir = Path(out_dir) if out_dir is not None else (ROOT / 'results')
    report_dir.mkdir(parents=True, exist_ok=True)
    md_report = report_dir / f'{output_name}.md'
    with open(md_report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines))

    logger.info(f"报告已生成: {md_report}")
    return str(md_report)


def main():
    parser = argparse.ArgumentParser(description='实验报告自动生成流水线')
    parser.add_argument('--quick', action='store_true', help='快速模式 (200回合×3种子)')
    parser.add_argument('--full', action='store_true', help='完整模式 (500回合×5种子)')
    parser.add_argument('--skip-scale', action='store_true', help='跳过规模实验')
    parser.add_argument('--skip-ablation', action='store_true', help='跳过消融实验')
    args = parser.parse_args()

    if not args.quick and not args.full:
        args.quick = True

    episodes = 500 if args.full else 200
    seeds = 5 if args.full else 3

    logger.info(f"实验模式: {'完整' if args.full else '快速'} ({episodes}回合×{seeds}种子)")
    logger.info(f"预计耗时: 约 {episodes * seeds * 2 * 0.05:.0f}s (规模实验) + {episodes * seeds * 4 * 0.05:.0f}s (消融)")

    input_files = []

    if not args.skip_scale:
        scale_output = step("多智能体规模实验", run_scale_experiment, episodes, seeds)
        input_files.append(scale_output)

    if not args.skip_ablation:
        abl_output = step("消融实验", run_ablation, episodes, seeds)
        input_files.append(abl_output)

    if input_files:
        report_name = f"experiment_report_{datetime.now().strftime('%Y%m%d_%H%M')}"
        step("生成综合报告", generate_report, input_files, report_name)

    logger.info("=" * 60)
    logger.info("流水线完成!")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()