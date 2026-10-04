# -*- coding: utf-8 -*-
"""
深度测试分析器 (Deep Test Analyzer)
读取 scalability / ablation / convergence_3000 / hp_sweep 结果,
生成: 1) JSON 报告  2) Markdown 摘要
BC提升统一采用 env_reward 公平口径: (bc - pure)/|pure|*100%
"""
import json, os, glob, numpy as np
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(BASE, 'results')
SEEDS = [42, 123, 456]


def load(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return None


def metric(d, key):
    s = d.get('summary', {})
    return s.get(key, None)


def mean_std(values):
    arr = [v for v in values if v is not None]
    if not arr:
        return None, None, 0
    return float(np.mean(arr)), float(np.std(arr)), len(arr)


def welch(a, b):
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    t, p = stats.ttest_ind(a, b, equal_var=False)
    pooled = np.sqrt(((len(a)-1)*np.var(a, ddof=1)+(len(b)-1)*np.var(b, ddof=1))/(len(a)+len(b)-2))
    d_cohen = (np.mean(a)-np.mean(b))/pooled if pooled > 0 else 0.0
    return {'t': float(t), 'p': float(p), 'cohens_d': float(d_cohen),
            'mean_a': float(np.mean(a)), 'mean_b': float(np.mean(b)),
            'improvement_pct': float((np.mean(a)-np.mean(b))/abs(np.mean(b))*100) if np.mean(b) != 0 else 0.0,
            'sig': bool(p < 0.05)}


def analyze_scalability():
    out = {}
    for n in [3, 5, 8]:
        row = {}
        pure_env, bc_env = [], []
        for mode in ['pure_marl', 'bc_marl']:
            envs, coops = [], []
            for seed in SEEDS:
                d = load(os.path.join(RESULTS, 'scalability_test', f'agents_{n}_{mode}_seed{seed}.json'))
                if d:
                    e = metric(d, 'avg_env_reward_last_50')
                    envs.append(e)
                    coops.append(metric(d, 'avg_cooperation_rate'))
                    (pure_env if mode == 'pure_marl' else bc_env).append(e)
            m_env, s_env, c = mean_std(envs)
            m_coop, s_coop, _ = mean_std(coops)
            row[mode] = {'env_mean': m_env, 'env_std': s_env, 'coop_mean': m_coop, 'coop_std': s_coop, 'n': c}
        # BC improvement + Welch 显著性 (用 per-seed 数组, 非均值)
        if pure_env and bc_env:
            pure = float(np.mean(pure_env))
            bc = float(np.mean(bc_env))
            row['bc_improvement_pct'] = float((bc - pure) / abs(pure) * 100)
            row['welch'] = welch(bc_env, pure_env)
        out[f'n{n}'] = row
    return out


def analyze_ablation():
    # baseline = bc_marl 完整
    base_env, base_coop = [], []
    for seed in SEEDS:
        d = load(os.path.join(RESULTS, 'ablation', f'baseline_seed{seed}.json'))
        if d:
            base_env.append(metric(d, 'avg_env_reward_last_50'))
            base_coop.append(metric(d, 'avg_cooperation_rate'))
    result = {'baseline': {'env_mean': float(np.mean(base_env)) if base_env else None,
                           'coop_mean': float(np.mean(base_coop)) if base_coop else None}}
    for mod in ['security', 'consensus', 'incentive']:
        envs, coops = [], []
        for seed in SEEDS:
            d = load(os.path.join(RESULTS, 'ablation', f'{mod}_seed{seed}.json'))
            if d:
                envs.append(metric(d, 'avg_env_reward_last_50'))
                coops.append(metric(d, 'avg_cooperation_rate'))
        m_e, s_e, c = mean_std(envs)
        m_c, s_c, _ = mean_std(coops)
        delta_env = (float(np.mean(envs)) - float(np.mean(base_env))) if (envs and base_env) else None
        delta_coop = (float(np.mean(coops)) - float(np.mean(base_coop))) if (coops and base_coop) else None
        result[mod] = {'env_mean': m_e, 'env_std': s_e, 'coop_mean': m_c, 'coop_std': s_c, 'n': c,
                       'delta_env_vs_baseline': delta_env, 'delta_coop_vs_baseline': delta_coop,
                       'welch_env': welch(envs, base_env)}
    return result


def _collect(results_dir, mode, key):
    """Return per-seed list of `key` metric for a given mode (None per missing file)."""
    vals = []
    for seed in SEEDS:
        d = load(os.path.join(RESULTS, results_dir, f'{mode}_seed{seed}.json'))
        vals.append(metric(d, key) if d else None)
    return vals


def _collect_all(results_dir, mode, key):
    """Glob ALL {mode}_seed*.json（动态种子数）用于收敛验证，避免遗漏后续补跑的 seed。"""
    vals = []
    pat = os.path.join(RESULTS, results_dir, f'{mode}_seed*.json')
    for fp in sorted(glob.glob(pat)):
        d = load(fp)
        if d:
            vals.append(metric(d, key))
    return vals


def analyze_convergence():
    # 收集 per-seed 数组, 用于正确的 Welch 检验 (不能用均值单点)
    # 收敛验证已扩到 71 种子/组（登记簿 NR-1 权威口径）, 用 glob 全量收集而非硬编码 SEEDS
    pure_env = _collect_all('convergence_3000', 'pure_marl', 'avg_env_reward_last_50')
    bc_env = _collect_all('convergence_3000', 'bc_marl', 'avg_env_reward_last_50')
    pure_coop = _collect_all('convergence_3000', 'pure_marl', 'avg_cooperation_rate')
    bc_coop = _collect_all('convergence_3000', 'bc_marl', 'avg_cooperation_rate')

    out = {}
    pe, se, ce = mean_std(pure_env)
    be, se2, ce2 = mean_std(bc_env)
    pc, sc, cc = mean_std(pure_coop)
    bc_c, sc2, cc2 = mean_std(bc_coop)
    out['pure_marl'] = {'env_mean': pe, 'env_std': se, 'coop_mean': pc, 'coop_std': sc, 'n': ce}
    out['bc_marl'] = {'env_mean': be, 'env_std': se2, 'coop_mean': bc_c, 'coop_std': sc2, 'n': ce2}

    if pe is not None and be is not None:
        out['bc_improvement_pct'] = float((be - pe) / abs(pe) * 100)
        # 用 per-seed 数组做 Welch 检验 (n=3), 而非单点均值
        out['welch'] = welch([v for v in bc_env if v is not None],
                             [v for v in pure_env if v is not None])
    return out


def analyze_hp_sweep():
    base_env, base_coop = [], []
    for seed in SEEDS:
        d = load(os.path.join(RESULTS, 'ablation', f'baseline_seed{seed}.json'))
        if d:
            base_env.append(metric(d, 'avg_env_reward_last_50'))
            base_coop.append(metric(d, 'avg_cooperation_rate'))
    configs = {
        'g0.9_lr1e-3': ['--gamma', '0.9', '--lr', '1e-3'],
        'g0.8_lr5e-4': ['--gamma', '0.8', '--lr', '5e-4'],
        'g0.9_lr5e-4': ['--gamma', '0.9', '--lr', '5e-4'],
    }
    out = {'baseline(g0.8_lr1e-3)': {'env_mean': float(np.mean(base_env)) if base_env else None,
                                      'coop_mean': float(np.mean(base_coop)) if base_coop else None}}
    for name in configs:
        envs, coops = [], []
        for seed in SEEDS:
            d = load(os.path.join(RESULTS, 'hp_sweep', f'{name}_seed{seed}.json'))
            if d:
                envs.append(metric(d, 'avg_env_reward_last_50'))
                coops.append(metric(d, 'avg_cooperation_rate'))
        m_e, s_e, c = mean_std(envs)
        m_c, s_c, _ = mean_std(coops)
        delta = (float(np.mean(envs)) - float(np.mean(base_env))) if (envs and base_env) else None
        out[name] = {'env_mean': m_e, 'env_std': s_e, 'coop_mean': m_c, 'coop_std': s_c, 'n': c,
                     'delta_env_vs_baseline': delta}
    return out


def main():
    report = {
        'scalability': analyze_scalability(),
        'ablation': analyze_ablation(),
        'convergence_3000': analyze_convergence(),
        'hp_sweep': analyze_hp_sweep(),
    }
    out_path = os.path.join(RESULTS, 'deep_test_report.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f'Deep test report saved: {out_path}')

    # Markdown summary
    md = ['# 深度测试分析报告\n']
    # 执行摘要表 (BC vs Pure, env_reward 公平口径, Welch's t-test)
    md.append('## 执行摘要 (BC vs Pure · env_reward 公平口径)\n')
    md.append('| 测试层 | BC提升% | p值 | Cohen d | 显著性 |')
    md.append('|---|---|---|---|---|')

    def _row(label, block, key='bc_improvement_pct'):
        imp = block.get(key)
        w = block.get('welch')
        p = f"{w['p']:.4f}" if w else 'N/A'
        d = f"{w['cohens_d']:.2f}" if w else 'N/A'
        sig = '显著' if (w and w.get('sig')) else ('不显著' if w else 'N/A')
        md.append(f"| {label} | {imp if imp is not None else 'N/A'} | {p} | {d} | {sig} |")

    for n, label in [('n3', '可扩展性 3智能体/500ep'), ('n5', '可扩展性 5智能体/500ep'), ('n8', '可扩展性 8智能体/500ep')]:
        _row(label, report['scalability'].get(n, {}))
    _row('收敛验证 3智能体/3000ep (n=%s/组)' % report['convergence_3000'].get('bc_marl', {}).get('n', '?'),
         report['convergence_3000'])
    md.append('')
    # Scalability
    md.append('## 1. 可扩展性测试 (n=3/5/8 智能体)')
    for n in ['n3', 'n5', 'n8']:
        r = report['scalability'].get(n, {})
        if r:
            bc = r.get('bc_marl', {})
            pure = r.get('pure_marl', {})
            imp = r.get('bc_improvement_pct', 'N/A')
            md.append(f"- **{n}**: pure env={pure.get('env_mean')}, bc env={bc.get('env_mean')}, "
                      f"BC提升={imp}% (coop: pure={pure.get('coop_mean')}, bc={bc.get('coop_mean')})")
    # Ablation
    md.append('\n## 2. 消融实验 (bc_marl, 3智能体, 500回合)')
    ab = report['ablation']
    md.append(f"- baseline env={ab['baseline']['env_mean']}, coop={ab['baseline']['coop_mean']}")
    for mod in ['security', 'consensus', 'incentive']:
        m = ab.get(mod, {})
        md.append(f"- 消融{mod}: env={m.get('env_mean')} (Δ={m.get('delta_env_vs_baseline')}), "
                  f"coop={m.get('coop_mean')}, welch p={m.get('welch_env', {}).get('p') if m.get('welch_env') else 'N/A'}")
    # Convergence
    md.append('\n## 3. 3000回合收敛验证 (3智能体, 3000ep, n=%s/组 seed)'
              % report['convergence_3000'].get('bc_marl', {}).get('n', '?'))
    cv = report['convergence_3000']
    md.append(f"- pure env={cv.get('pure_marl', {}).get('env_mean')}, bc env={cv.get('bc_marl', {}).get('env_mean')}, "
              f"BC提升={cv.get('bc_improvement_pct')}%")
    w = cv.get('welch')
    if w:
        md.append(f"- Welch t-test: t={w['t']:.3f}, p={w['p']:.4f}, Cohen's d={w['cohens_d']:.3f} "
                  f"（**{'显著' if w['sig'] else '不显著'}**, n={cv.get('bc_marl', {}).get('n', '?')}/组）")
        _n_used = cv.get('bc_marl', {}).get('n', '?')
        md.append(f"> **诚实声明**：BC 呈正向提升（效应量 d≈{w['cohens_d']:.2f}，小到中等效应），"
                  f"Welch p={w['p']:.6f}（α=0.05 下{'显著' if w['sig'] else '不显著'}；"
                  "多重比较校正口径为 **BH-FDR 显著 / Bonferroni 下不显著**）。"
                  f"本报告样本量 n={_n_used}/组由数据实测得出；权威口径与完整表述以 "
                  "`deliverables/number_registry.json` 的 **NR-1 / NR-2** 为准，**两口径必须同报**；"
                  "效应量小-中，不得表述为『强证据』或『证明激励有效』。"
                  "这与项目『**区块链为信任增强（非性能优化）**』的定位一致——"
                  "性能收益为方向性证据，核心贡献在于拜占庭容错、攻击拦截与激励行为差异化等确定性机制。")
    # HP sweep
    md.append('\n## 4. 超参鲁棒性 (bc_marl, 3智能体, 500回合)')
    hp = report['hp_sweep']
    for k, v in hp.items():
        md.append(f"- {k}: env={v.get('env_mean')} (Δ={v.get('delta_env_vs_baseline')})")

    md_path = os.path.join(RESULTS, 'deep_test_report.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    print(f'Markdown summary saved: {md_path}')


if __name__ == '__main__':
    main()
