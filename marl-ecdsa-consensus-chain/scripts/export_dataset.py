"""
MARL + 区块链训练数据集导出脚本（增量创新 #3）
来源启发：EquiChain 公开 PBFT 数据集（Kaggle）

将本地训练结果 JSON 标准化导出为 CSV/JSON 数据集，供 Kaggle/HuggingFace 公开。
导出内容：
- 训练曲线（回合、奖励、合作率、背叛率）
- 区块链流水线（签名数、验证数、共识轮次、区块高度）
- 三模式对比（pure_marl / bc_marl / selfish）

用法：python scripts/export_dataset.py [--outdir data/dataset]
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'data' / 'dataset'


def _load_json(rel_path: str):
    p = ROOT / rel_path
    if not p.exists():
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def export_training_curve(data: dict, outdir: Path) -> int:
    """导出训练曲线 CSV（回合、奖励、合作率、背叛率、损失）"""
    rows = 0
    for mode_key, mode_name in [('bc', 'bc_marl'), ('pure', 'pure_marl'), ('selfish', 'selfish')]:
        d = _load_json(f'training_results_{mode_key}.json') or _load_json(f'training_results_{mode_name}.json')
        if not d:
            continue
        ep_rewards = d.get('episode_rewards') or d.get('episode_rewards_mean') or []
        coop = d.get('cooperation_rates') or []
        betray = d.get('betrayal_rates') or []
        losses = d.get('losses') or d.get('td_losses') or []
        n = max(len(ep_rewards), len(coop), len(betray), len(losses))
        if n == 0:
            continue
        fname = outdir / f'training_curve_{mode_name}.csv'
        with open(fname, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['episode', 'reward', 'cooperation_rate', 'betrayal_rate', 'td_loss'])
            for i in range(n):
                w.writerow([
                    i,
                    _idx(ep_rewards, i),
                    _idx(coop, i),
                    _idx(betray, i),
                    _idx(losses, i),
                ])
                rows += 1
    return rows


def _idx(arr, i):
    return arr[i] if i < len(arr) else ''


def export_blockchain_stats(outdir: Path) -> int:
    """导出区块链流水线统计 CSV（签名/验证/共识/区块）"""
    d = _load_json('training_results_bc.json')
    if not d:
        return 0
    bc_stats = d.get('blockchain_stats', {})
    consensus_stats = d.get('consensus_stats', {})
    ecdsa = d.get('ecdsa_stats', {})
    rows = [{
        'metric': 'block_height', 'value': bc_stats.get('height', 0),
    }, {
        'metric': 'total_transactions', 'value': bc_stats.get('total_transactions', 0),
    }, {
        'metric': 'consensus_rounds', 'value': consensus_stats.get('rounds', bc_stats.get('height', 0)),
    }, {
        'metric': 'sign_count', 'value': ecdsa.get('sign_count', 0),
    }, {
        'metric': 'verify_count', 'value': ecdsa.get('verify_count', 0),
    }, {
        'metric': 'security_alerts', 'value': len(d.get('security_stats', {}).get('alerts', [])) if isinstance(d.get('security_stats'), dict) else 0,
    }]
    fname = outdir / 'blockchain_pipeline.csv'
    with open(fname, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['metric', 'value'])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def export_mode_comparison(outdir: Path) -> int:
    """导出三模式对比汇总 JSON（KPI + 配置参数）"""
    modes = []
    for mode_key, mode_name in [('pure', 'pure_marl'), ('bc', 'bc_marl'), ('selfish', 'selfish')]:
        d = _load_json(f'training_results_{mode_key}.json') or _load_json(f'training_results_{mode_name}.json')
        if not d:
            continue
        rewards = d.get('episode_rewards') or d.get('episode_rewards_mean') or []
        coop = d.get('cooperation_rates') or []
        betray = d.get('betrayal_rates') or []
        modes.append({
            'mode': mode_name,
            'episodes': len(rewards),
            'mean_reward': round(sum(rewards) / len(rewards), 4) if rewards else None,
            'last_50_reward': round(sum(rewards[-50:]) / min(50, len(rewards)), 4) if rewards else None,
            'mean_cooperation_rate': round(sum(coop) / len(coop), 4) if coop else None,
            'mean_betrayal_rate': round(sum(betray) / len(betray), 4) if betray else None,
            'config': d.get('config', {}),
        })
    if not modes:
        return 0
    out = {'dataset_name': 'MARL-ECDSA Consensus Chain Training Data',
           'description': 'Multi-agent reinforcement learning + blockchain consensus collaboration dataset (CCF competition)',
           'license': 'CC BY 4.0', 'version': '1.0.0', 'modes': modes}
    fname = outdir / 'mode_comparison.json'
    with open(fname, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return len(modes)


def main():
    ap = argparse.ArgumentParser(description='Export MARL+Blockchain training dataset')
    ap.add_argument('--outdir', default=str(DEFAULT_OUT))
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    n_curve = export_training_curve(None, outdir)
    n_bc = export_blockchain_stats(outdir)
    n_mode = export_mode_comparison(outdir)

    files = sorted(p.name for p in outdir.iterdir())
    print(f'[Export] 输出目录: {outdir}')
    print(f'[Export] 训练曲线行数: {n_curve} | 区块链统计行数: {n_bc} | 模式对比数: {n_mode}')
    print(f'[Export] 文件: {files}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
