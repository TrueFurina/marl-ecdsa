"""
MARL-ECDSA 共识链 — 全功能可视化平台 v3.9（共识投票+区块浏览器增强版）

面向 CCF 第五届区块链竞赛国赛线下演示：
- 深色科技感 UI，粒子背景 + 光晕效果
- 9 标签页：总览 | 训练监控 | 对比分析 | 三模式对比 | 区块链 | 共识投票 | 区块浏览器 | 系统 | P2P网络
- v3.9 新增：CW-PBFT共识投票可视化（权重分布+贡献度雷达+三阶段流程）
- v3.9 新增：区块浏览器（区块列表+交易趋势+出块者分布）
- v3.8 新增：子组件流水线 SVG 图（SigningService→ActionRecorder→CooperationDetector→SettlementCoordinator）
- v3.8 新增：4 子组件独立统计卡片 + per-agent 签名/合作状态面板
- **演示模式**：自动轮播标签页（6秒间隔），评委走近即看动画
- **数字滚动动画**：关键指标从 0 渐变到最终值
- **导出报告**：一键生成可打印的 HTML 报告
- **键盘快捷键**：1-9 切换标签，P 开启演示模式，E 导出报告
- 历史数据加载（JSON 文件），支持离线演示

启动：python -c "from visualization.dashboard import start_dashboard; start_dashboard()"
"""
import hashlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger('dashboard')

# 大改后 attack_defense_demo 等脚本迁至 scripts/legacy/{analysis,experiments}/，
# dashboard 攻防演示接口仍按顶层模块名 import。将其目录加入 sys.path 以兼容
#（与 tests/conftest.py 同步）。
for _sub in ("analysis", "experiments"):
    _legacy_dir = str(Path(__file__).resolve().parent.parent / "scripts" / "legacy" / _sub)
    if os.path.isdir(_legacy_dir) and _legacy_dir not in sys.path:
        sys.path.insert(0, _legacy_dir)

try:
    from flask import Flask, render_template, render_template_string, jsonify, request, send_from_directory
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    logger.warning("[Dashboard] Flask未安装，可视化功能不可用。安装: pip install flask")

# 注意：app 在 _create_app() 中创建（含路由和数据注入），此处的 None 占位避免
# Flask 开发服务器自动检测到未配置的裸 Flask 实例
app = None

# 全局数据桥（线程安全，运行时注入）
_dashboard_data: Dict[str, Any] = {
    'episode_rewards': [],
    'cooperation_rates': [],
    'betrayal_rates': [],
    'losses': [],
    'bc_scores_history': [],
    'bc_scores': {},
    'leaderboard': [],
    'settlements': [],
    'config': {},
    'summary': {},
}

# 项目根目录（用于加载历史数据文件）
_BASE_DIR = Path(__file__).resolve().parent.parent


def update_data(stats, trainer=None):
    """更新 Dashboard 实时数据"""
    _dashboard_data['episode_rewards'] = stats.episode_rewards
    _dashboard_data['cooperation_rates'] = stats.cooperation_rates
    _dashboard_data['betrayal_rates'] = stats.betrayal_rates
    _dashboard_data['losses'] = [l for l in stats.losses if l is not None]
    _dashboard_data['bc_scores_history'] = stats.bc_scores_history
    _dashboard_data['summary'] = stats.summary()

    if trainer and trainer.bridge:
        _dashboard_data['bc_scores'] = trainer.bridge.get_bc_scores()
        try:
            _dashboard_data['leaderboard'] = [
                {'agent_id': a, 'score': s}
                for a, s in trainer.incentive_contract.get_leaderboard()
            ]
        except Exception as e:
            logger.warning(f"加载排行榜数据失败: {e}")
            _dashboard_data['leaderboard'] = []
        # v3.3→v3.4: 区块链流水线新增统计字段
        try:
            _dashboard_data['ecdsa_stats'] = {
                'sign_count': trainer.bridge._sign_count,
                'verify_count': trainer.bridge._verify_count,
            }
            _dashboard_data['security_stats'] = trainer.bridge.get_security_stats()
            _dashboard_data['consensus_stats'] = trainer.bridge.get_consensus_stats()
            _dashboard_data['blockchain_stats'] = trainer.bridge.get_blockchain_stats()
        except Exception as e:
            logger.warning(f"加载流水线统计数据失败: {e}")
            _dashboard_data['ecdsa_stats'] = {'sign_count': 0, 'verify_count': 0}
            _dashboard_data['security_stats'] = {}
            _dashboard_data['consensus_stats'] = {}
            _dashboard_data['blockchain_stats'] = {}

        # v3.8: 子组件独立统计（SigningService / ActionRecorder / CooperationDetector / SettlementCoordinator）
        try:
            _dashboard_data['signing_stats'] = trainer.bridge._signing.get_stats()
            _dashboard_data['recorder_stats'] = trainer.bridge._recorder.get_stats()
            _dashboard_data['detector_stats'] = trainer.bridge._detector.get_stats()
            _dashboard_data['settlement_stats'] = trainer.bridge._settlement.get_stats()
        except Exception as e:
            logger.warning(f"加载子组件统计数据失败: {e}")
            _dashboard_data['signing_stats'] = {}
            _dashboard_data['recorder_stats'] = {}
            _dashboard_data['detector_stats'] = {}
            _dashboard_data['settlement_stats'] = {}
    else:
        _dashboard_data['bc_scores'] = {}
        _dashboard_data['leaderboard'] = []
        _dashboard_data['ecdsa_stats'] = {}
        _dashboard_data['security_stats'] = {}
        _dashboard_data['consensus_stats'] = {}
        _dashboard_data['blockchain_stats'] = {}
        _dashboard_data['signing_stats'] = {}
        _dashboard_data['recorder_stats'] = {}
        _dashboard_data['detector_stats'] = {}
        _dashboard_data['settlement_stats'] = {}


def _load_result_file(filename: str) -> Optional[Dict]:
    """加载训练结果 JSON 文件

    大改后 training_results_*.json 迁至 results/legacy_json/，此处支持回退加载：
    先查项目根，再查 results/legacy_json/，保证 dashboard 演示有数据。
    """
    # 1. 项目根（兼容旧路径）
    filepath = _BASE_DIR / filename
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 2. results/legacy_json/ 回退（大改后迁移位置）
    legacy_path = _BASE_DIR / 'results' / 'legacy_json' / filename
    if legacy_path.exists():
        with open(legacy_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


# =============================================================================
# 平台 HTML 已迁移至 templates/dashboard.html (Jinja2 模板分离)
# =============================================================================



# =============================================================================
# Flask 应用
# =============================================================================

# =============================================================================
# 路由处理器（独立函数，每个不超过 40 行）
# =============================================================================

def _route_index():
    """Dashboard 首页：加载训练数据注入模板"""
    def _load(fname):
        data = _load_result_file(fname)
        if data:
            data['_format'] = 'single'
        return data
    pure, bc, selfish = _load('training_results_pure.json'), _load('training_results_bc.json'), _load('training_results_selfish.json')
    return render_template('dashboard.html',
        pure_data_json=json.dumps(pure, ensure_ascii=False) if pure else 'null',
        bc_data_json=json.dumps(bc, ensure_ascii=False) if bc else 'null',
        selfish_data_json=json.dumps(selfish, ensure_ascii=False) if selfish else 'null')

def _route_healthz():
    return jsonify({'status': 'ok', 'service': 'marl-ecdsa-dashboard', 'version': 'v3.9'})

def _route_api_status():
    data = dict(_dashboard_data)
    data['comparison_baseline'] = 'env_reward (不含BC激励，公平口径)'
    return jsonify(data)

def _route_api_data():
    """综合数据接口"""
    status_data = dict(_dashboard_data)
    status_data['comparison_baseline'] = 'env_reward (不含BC激励，公平口径)'
    return jsonify({
        'status': status_data,
        'ecdsa_stats': _dashboard_data.get('ecdsa_stats', {}),
        'security_stats': _dashboard_data.get('security_stats', {}),
        'consensus_stats': _dashboard_data.get('consensus_stats', {}),
        'blockchain_stats': _dashboard_data.get('blockchain_stats', {}),
        'signing_stats': _dashboard_data.get('signing_stats', {}),
        'recorder_stats': _dashboard_data.get('recorder_stats', {}),
        'detector_stats': _dashboard_data.get('detector_stats', {}),
        'settlement_stats': _dashboard_data.get('settlement_stats', {}),
    })

def _route_p2p_stats():
    """P2P网络统计接口"""
    live_weights = _dashboard_data.get('consensus_stats', {}).get('weights', {})
    consensus_rounds = _dashboard_data.get('blockchain_stats', {}).get('height', 0)
    has_live_data = bool(live_weights) or consensus_rounds > 0
    base = {
        'is_simulated': True,
        'note': '当前为模拟数据模式，实际P2P网络数据需启用--use-p2p',
    }
    if not has_live_data:
        return jsonify({**base, 'p2p_enabled': False, 'message': 'P2P 网络未启用',
            'n_nodes': 0, 'nodes': {}, 'total_consensus_rounds': 0, 'total_msg_sent': 0,
            'total_msg_received': 0, 'avg_latency_ms': 'N/A', 'weights': {}, 'recent_log': []})
    return jsonify({**base, 'p2p_enabled': True, 'n_nodes': 3,
        'nodes': {'agent_0': {}, 'agent_1': {}, 'agent_2': {}},
        'total_consensus_rounds': consensus_rounds,
        'total_msg_sent': consensus_rounds * 6, 'total_msg_received': consensus_rounds * 6,
        'avg_latency_ms': '~8', 'weights': live_weights,
        'recent_log': _dashboard_data.get('p2p_log', [])})

def _route_api_load(mode):
    """加载训练结果"""
    mode_map = {'pure': 'pure_marl', 'bc': 'bc_marl', 'selfish': 'selfish'}
    mapped = mode_map.get(mode, mode)
    combined = _load_result_file(str(_BASE_DIR / 'results' / f'training_results_{mapped}_combined.json'))
    if combined and 'episode_rewards_mean' in combined:
        combined['_format'] = 'combined'
        return jsonify(combined)
    fnames = {'pure': 'training_results_pure.json', 'bc': 'training_results_bc.json', 'selfish': 'training_results_selfish.json'}
    fname = fnames.get(mode)
    if fname:
        data = _load_result_file(fname)
        if data:
            data['_format'] = 'single'
            return jsonify(data)
    return jsonify({'error': f'未找到 {mode} 的训练结果'}), 404

def _route_api_compare():
    pure = _load_result_file('training_results_pure.json')
    bc = _load_result_file('training_results_bc.json')
    selfish = _load_result_file('training_results_selfish.json')
    return jsonify({'pure': pure, 'bc': bc, 'selfish': selfish})

def _route_consensus_votes():
    """共识投票可视化数据"""
    bc_data = _load_result_file('training_results_bc.json') or _load_result_file('training_results_bc_marl_combined.json') or {}
    consensus_stats = bc_data.get('consensus_stats', {})
    blockchain_stats = bc_data.get('blockchain_stats', {})
    weights = consensus_stats.get('weights', {}) or {'agent_0': 1.0, 'agent_1': 1.0, 'agent_2': 1.0}
    n_blocks = blockchain_stats.get('height', 0)
    vote_phases = [
        {'phase': 'pre-prepare', 'threshold': '1 (primary)', 'description': '主节点广播提案，进入预准备阶段', 'weights': weights},
        {'phase': 'prepare', 'threshold': '2f+1', 'description': '各节点验证提案并广播准备投票', 'weights': weights},
        {'phase': 'commit', 'threshold': '2f+1', 'description': '收集到2f+1准备投票后，广播提交投票', 'weights': weights},
    ]
    cw = bc_data.get('config', {}).get('contribution_weights', {'task_score': 0.40, 'cooperation_score': 0.35, 'compliance_score': 0.25})
    # 权重展宽纪元数据（NR-83/84 机制）：定稿演示数据为「未开启展宽」的运行，
    # 故按优先级回退到专门的展宽对照运行，并回报数据源文件名（前端如实标注，不混淆口径）。
    wb_stats, wb_source = bc_data.get('weight_broadening_stats'), None
    if wb_stats:
        wb_source = 'training_results_bc.json'
    else:
        for _fname in ('training_results_bc_broadening_omission.json',
                       'training_results_bc_broadening.json'):
            _alt = _load_result_file(_fname)
            if _alt and _alt.get('weight_broadening_stats'):
                wb_stats = _alt['weight_broadening_stats']
                wb_source = _fname
                break
    return jsonify({
        'weights': weights, 'weight_history': consensus_stats.get('weight_history', []),
        'vote_phases': vote_phases, 'n_consensus_rounds': n_blocks,
        'n_transactions': blockchain_stats.get('total_transactions', 0),
        'security_stats': bc_data.get('security_stats', {}),
        'consensus_type': 'CW-PBFT (Contribution-Weighted PBFT)', 'contribution_weights': cw,
        'weight_broadening': wb_stats,
        'weight_broadening_source': wb_source,
    })

def _route_block_explorer():
    """区块浏览器数据

    ⚠️ 诚实契约（09-28 修复）：训练过程**不落盘逐块数据**（training_results 的
    blockchain_stats 仅有 height/total_transactions/latest_hash 等聚合标量），
    因此本接口返回的逐块明细是由聚合值 + 确定性哈希**合成的示意数据**，不是真实链。

    为避免"零校验却显示验证通过"的误导（此前 chain_valid 恒为硬编码 True），
    现统一返回 chain_valid=None + synthetic=True，前端据此标注「示意数据」。
    若将来训练侧落盘真实链，应改为读真链并调用 Blockchain.validate_chain() 后回填。
    """
    bc_data = _load_result_file('training_results_bc.json') or _load_result_file('training_results_bc_marl_combined.json')
    if not bc_data:
        return jsonify({'blocks': [], 'total_blocks': 0, 'total_transactions': 0,
                       'chain_valid': None, 'synthetic': True,
                       'chain_note': '无数据（示意模式）',
                       'ecdsa_stats': {}, 'consensus_stats': {}, 'blockchain_stats': {},
                       'message': 'No data'})
    stats = bc_data.get('blockchain_stats', {})
    n_blocks, n_tx = stats.get('height', 0), stats.get('total_transactions', 0)
    tx_per_block = max(1, n_tx // max(1, n_blocks))
    blocks = [{
        'height': i, 'hash': _demo_hash(f'block-{i}'),
        'prev_hash': _demo_hash(f'block-{i-1}') if i > 0 else '0x' + '0' * 16,
        'timestamp': stats.get('latest_timestamp', 0), 'proposer': f"agent_{i % 3}",
        'tx_count': tx_per_block, 'consensus': 'CW-PBFT',
        'state_root': _compute_merkle_placeholder(i),
    } for i in range(min(n_blocks, 50))]
    blocks.reverse()
    return jsonify({'blocks': blocks, 'total_blocks': n_blocks, 'total_transactions': n_tx,
        'chain_valid': None, 'synthetic': True,
        'chain_note': '示意数据：逐块明细由聚合统计合成（非真实链）；真实聚合值见 blockchain_stats',
        'ecdsa_stats': bc_data.get('ecdsa_stats', {}),
        'consensus_stats': bc_data.get('consensus_stats', {}), 'blockchain_stats': stats})

def _demo_hash(seed: str) -> str:
    """确定性演示哈希（sha256 截断为 16 hex）。

    替代此前的内建 hash()：后者受 PYTHONHASHSEED 随机化影响，**同一区块编号在
    服务重启后会显示成不同哈希**，现场演示重启即穿帮。
    """
    return '0x' + hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]

def _compute_merkle_placeholder(block_idx: int) -> str:
    """区块浏览器中 state_root 的占位显示（实际 state_root 由 Block.finalize() 计算）"""
    return _demo_hash(f'state_{block_idx}')


# =============================================================================
# 一键注入攻击演示（攻防演示标签页）
# =============================================================================

# 攻防演示接口需要切到项目根目录（attack_defense_demo 内部用相对路径找密钥）。
# Flask 多线程下 os.chdir 改全局 CWD 不安全，用此锁串行化该接口（低频操作，不影响性能）。
_attack_inject_lock = threading.Lock()


def _route_api_attack_inject():
    """
    一键注入攻击演示 API
    在网页上模拟各类攻击（观测伪造/消息篡改/重放/女巫/Sybil/签名k重用/长程/拜占庭主节点），
    对比"无区块链基线"与"MARL-ECDSA 区块链防护"的拦截效果。
    """
    attack_type = request.args.get('type', 'all')

    # 攻击演示使用相对密钥目录，统一切到项目根再执行
    # 加锁避免多线程并发请求互相踩全局 CWD
    cwd_backup = os.getcwd()
    with _attack_inject_lock:
        try:
            os.chdir(str(_BASE_DIR))
        except Exception:
            pass

        try:
            if attack_type == 'byzantine':
                from blockchain.consensus.cw_pbft_failover import CWPBFTConsensusWithFailover
                nodes = [f'node_{i}' for i in range(5)]
                sim = CWPBFTConsensusWithFailover(nodes[0], nodes)
                # 受控场景：奇数轮注入拜占庭主节点，验证 CW-PBFT 动态故障切换
                byz_rounds = 0
                recovered_rounds = 0
                records = []
                for r in range(8):
                    h = f'byzantine_demo_{r:04d}'
                    prop = sim.get_primary(r)
                    is_byz = (r % 2 == 1)
                    ok, rec = sim.simulated_consensus_with_failover(
                        h, prop, block_height=r, simulate_byzantine=is_byz,
                    )
                    if is_byz:
                        byz_rounds += 1
                        if rec and rec.consensus_recovered:
                            recovered_rounds += 1
                    if rec:
                        records.append({
                            'round': r, 'failed_primary': rec.failed_primary,
                            'new_primary': rec.new_primary,
                            'latency_ms': rec.failover_latency_ms,
                            'recovered': rec.consensus_recovered,
                        })
                all_recovered = byz_rounds > 0 and recovered_rounds == byz_rounds
                return jsonify({
                    'attack_type': 'byzantine_primary',
                    'no_bc': {
                        'attack_successful': True,
                        'description': '无CW-PBFT动态故障切换：拜占庭主节点反复发起冲突提案，共识被阻塞/分叉',
                    },
                    'with_bc': {
                        'attack_successful': not all_recovered,
                        'description': 'CW-PBFT动态故障切换：检测拜占庭主节点并触发视图更换，共识快速恢复',
                        'byzantine_events': byz_rounds,
                        'successful_failovers': recovered_rounds,
                        'all_recovered': all_recovered,
                    },
                    'details': records[:8],
                })

            import attack_defense_demo as demo
            demos = {
                'observation_forgery': demo.demo_observation_forgery,
                'message_tampering': demo.demo_message_tampering,
                'replay_attack': demo.demo_replay_attack,
                'sybil_attack': demo.demo_sybil_attack,
                'k_reuse_attack': demo.demo_k_reuse_attack,
                'long_range_attack': demo.demo_long_range_attack,
            }
            if attack_type == 'all':
                results = [fn() for fn in demos.values()]
                return jsonify({'attack_type': 'all', 'results': results})
            fn = demos.get(attack_type)
            if fn is None:
                return jsonify({'error': f'未知攻击类型: {attack_type}'}), 400
            return jsonify(fn())
        except Exception as e:
            logger.exception("[Dashboard] 攻击注入失败")
            return jsonify({'error': f'攻击模拟失败: {e}'}), 500
        finally:
            os.chdir(cwd_backup)


# -----------------------------------------------------------------------------
# 口径真值接口：总览页"头号指标"的唯一权威数据源（登记簿驱动，禁手抄）
# -----------------------------------------------------------------------------

#: 登记簿不可读时的兜底值（与 deliverables/number_registry.json 登记值一致）。
#: 仅作断网/缺文件时的兜底；正常情况下返回的 source 会显示真实出处。
_CALIBER_FALLBACK = {
    'NR-1': {'id': 'NR-1', 'improvement_pct': 28.17, 'welch_p': 0.009524,
             'cohens_d': 0.4412, 'n': 71,
             'field': 'summary.avg_env_reward_last_50（末50回合 env_reward，不含BC激励）'},
    'NR-2': {'id': 'NR-2', 'improvement_pct': 7.92, 'welch_p': 5.02e-11,
             'cohens_d': 1.1962, 'n': 71,
             'field': 'summary.avg_env_reward（全程 env_reward，不含BC激励）'},
    'NR-3': {'id': 'NR-3', 'improvement_pct': 1.95, 'welch_p': 7.28e-11,
             'cohens_d': 1.1858, 'n': 71,
             'field': 'summary.avg_cooperation_rate（全程平均合作率）'},
}


def _load_registry_declared():
    """读权威登记簿（工作区 deliverables/ 优先，仓库镜像兜底），返回 (entries, source)。"""
    here = Path(__file__).resolve().parents[1]          # 仓库根 marl-ecdsa-consensus-chain/
    for cand, src in (
            (here.parent / 'deliverables' / 'number_registry.json',
             '权威登记簿 deliverables/number_registry.json'),
            (here / 'number_registry.json',
             '仓库镜像 number_registry.json')):
        try:
            reg = json.loads(Path(cand).read_text(encoding='utf-8'))
            entries = {e.get('id'): (e.get('declared') or {})
                       for e in reg.get('entries', []) if e.get('id')}
            if entries:
                return entries, src
        except Exception:
            continue
    return {}, 'fallback（登记簿不可读，用内置兜底值）'


def _route_api_caliber():
    """总览页头号指标的权威口径（NR-1/NR-2/NR-3），一律程序化读登记簿。"""
    entries, source = _load_registry_declared()
    caliber = {}
    for nid, fb in _CALIBER_FALLBACK.items():
        declared = entries.get(nid) or {}
        item = dict(fb)
        for k in ('improvement_pct', 'welch_p', 'cohens_d'):
            if k in declared:
                item[k] = declared[k]
        if 'n_a' in declared:
            item['n'] = declared['n_a']
        caliber[nid] = item
    return jsonify({
        'source': source,
        'note': 'NR-1（末50回合）与 NR-2（全程）必须同报；主口径 BH-FDR 显著 / Bonferroni '
                '不显著，效应量小-中，不得表述为强证据或证明激励有效。',
        'caliber': caliber,
    })


# =============================================================================
# Flask 应用工厂（注册路由，简洁明了）
# =============================================================================

def _create_app():
    if not HAS_FLASK:
        return None

    flask_app = Flask('marl_dashboard',
                      static_folder=str(_BASE_DIR / 'static'),
                      static_url_path='/static',
                      template_folder=str(_BASE_DIR / 'templates'))

    # 注册路由
    flask_app.add_url_rule('/', 'index', _route_index)
    flask_app.add_url_rule('/healthz', 'healthz', _route_healthz)
    flask_app.add_url_rule('/api/status', 'api_status', _route_api_status)
    flask_app.add_url_rule('/api/data', 'api_data', _route_api_data)
    flask_app.add_url_rule('/api/p2p_stats', 'api_p2p_stats', _route_p2p_stats)
    flask_app.add_url_rule('/api/load/<mode>', 'api_load', _route_api_load)
    flask_app.add_url_rule('/api/compare', 'api_compare', _route_api_compare)
    flask_app.add_url_rule('/api/consensus_votes', 'api_consensus_votes', _route_consensus_votes)
    flask_app.add_url_rule('/api/block_explorer', 'api_block_explorer', _route_block_explorer)
    flask_app.add_url_rule('/api/attack/inject', 'api_attack_inject', _route_api_attack_inject)
    flask_app.add_url_rule('/api/caliber', 'api_caliber', _route_api_caliber)

    return flask_app


def _run_server(host: str = '127.0.0.1', port: int = 9090):
    flask_app = _create_app()
    if flask_app is None:
        logger.error("[Dashboard] Flask不可用")
        return

    logger.info(f"[Dashboard] 启动全功能平台 v3.9 -> http://{host}:{port}")
    flask_app.run(host=host, port=port, debug=False, use_reloader=False)


def start_dashboard(stats=None, trainer=None, host: str = '127.0.0.1', port: int = 9090):
    """
    启动全功能可视化平台 v3.9（共识投票+区块浏览器增强版）

    访问 http://{host}:{port} 即可查看：
    - 总览 / 训练监控 / 对比分析 / 三模式对比 / 区块链 / 系统 / P2P网络（7 标签页）
    - v3.8 新增：子组件流水线 SVG（SigningService→ActionRecorder→CooperationDetector→SettlementCoordinator）
    - v3.8 新增：4 子组件独立统计卡片 + per-agent 签名/合作状态
    - ECDSA签名验证流程动画 + CW-PBFT共识三阶段可视化
    - 安全防护机制面板（k值重用检测 / nonce防重放 / 时间戳验证）
    - 演示模式（P键开启，自动轮播）
    - 导出报告（E键，含ECDSA安全+CW-PBFT共识+子组件详情）
    - 深色科技风 UI，适配线下演示
    """
    if not HAS_FLASK:
        logger.error("[Dashboard] 请安装Flask: pip install flask")
        return

    if stats is not None:
        update_data(stats, trainer)

    # 确保历史数据可加载
    pure_file = _BASE_DIR / 'training_results_pure.json'
    bc_file = _BASE_DIR / 'training_results_bc.json'
    selfish_file = _BASE_DIR / 'training_results_selfish.json'
    if pure_file.exists():
        logger.info(f"[Dashboard] 已检测到 pure_marl 训练结果 ({pure_file.stat().st_size} bytes)")
    if bc_file.exists():
        logger.info(f"[Dashboard] 已检测到 bc_marl 训练结果 ({bc_file.stat().st_size} bytes)")
    if selfish_file.exists():
        logger.info(f"[Dashboard] 已检测到 selfish 训练结果 ({selfish_file.stat().st_size} bytes)")

    thread = threading.Thread(target=_run_server, args=(host, port), daemon=True)
    thread.start()

    import time
    time.sleep(1.5)

    print(f"\n{'='*60}")
    print(f"  MARL-ECDSA 共识链 — 全功能可视化平台 v3.9")
    print(f"  共识投票+区块浏览器增强版 · 三模式数据对比 · 演示模式(P键)")
    print(f"  请在浏览器中打开: http://{host}:{port}")
    print(f"  Ctrl+C 退出")
    print(f"{'='*60}\n")


# =============================================================================
# 直接运行
# =============================================================================
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print("启动 MARL-ECDSA 可视化平台 v3.9...")
    start_dashboard(port=9090)
