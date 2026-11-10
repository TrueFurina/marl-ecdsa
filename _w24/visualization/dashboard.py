"""MARL-ECDSA V27 dashboard. Account-scoped training, dynamic governance, three-node evidence and audit."""
import hashlib
import time
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger('dashboard')

# F14（2026-11-03）：贡献存证去重的进程级互斥——「扫全链查重」与「签名+propose」
# 必须原子，否则两个并发请求都能通过查重、以不同 nonce 各自出块造成同纪元重复存证。
# 单 Web（run_simple 串行）本无并发，但库/多线程入口仍需该锁兜底。
_ATTEST_MUTEX = threading.Lock()

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




def _latest_completed_training(mode: str, user_id=None):
    """Read real, completed training from the authenticated user's tasks."""
    import sqlite3
    dbpath = _BASE_DIR / 'instance' / 'business.sqlite3'
    root = (_BASE_DIR / 'instance' / 'training_logs').resolve()
    if not dbpath.is_file():
        return None
    try:
        with sqlite3.connect(str(dbpath), timeout=3) as db:
            if user_id is None:
                rows = db.execute("SELECT id,config,result_path,exit_code FROM jobs WHERE status='completed' ORDER BY finished_at DESC,created_at DESC LIMIT 300").fetchall()
            else:
                rows = db.execute("SELECT id,config,result_path,exit_code FROM jobs WHERE status='completed' AND user_id=? ORDER BY finished_at DESC,created_at DESC LIMIT 300", (user_id,)).fetchall()
    except sqlite3.Error as exc:
        logger.warning('训练任务查询失败：%s', exc)
        return None
    for jid, config_json, stored_path, exit_code in rows:
        try:
            cfg = json.loads(config_json)
            if exit_code != 0 or cfg.get('mode') != mode:
                continue
            path = Path(stored_path).resolve()
            if os.path.commonpath([str(path), str(root)]) != str(root) or path.suffix.lower() != '.json' or not path.is_file():
                # Support a safely relocated copied V20 database. Never read the old outside path.
                path = (root / (jid + '.json')).resolve()
            if os.path.commonpath([str(path), str(root)]) != str(root) or not path.is_file():
                continue
            with path.open(encoding='utf-8') as stream:
                data = json.load(stream)
            if (isinstance(data,dict) and isinstance(data.get('summary'),dict)
                    and isinstance(data.get('episode_rewards'),list)
                    and data.get('config',{}).get('mode') == mode):
                data['_format']='single'
                data['_source']='completed_training_job'
                return data
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            logger.warning('跳过无效训练任务 %s：%s', jid, exc)
    return None


def _training_result(mode: str, user_id=None):
    """Runtime training output first (user-scoped), then shared demo fallback, then legacy files.
    Never fabricate data: the fallback only reuses real completed training jobs."""
    result = _latest_completed_training(mode, user_id=user_id)
    if result is not None:
        return result
    # 当前用户无已完成训练：回退到全局首个真实已完成训练（用于演示/展示），
    # 并明确标注来源，前端如实展示，不冒充本人数据。
    shared = _latest_completed_training(mode, user_id=None)
    if shared is not None:
        shared = dict(shared)
        shared['_source'] = 'shared_demo_fallback'
        shared['_scoped_to_user'] = False
        return shared
    # 未认证/旧工具：回退历史归档文件（仅限显式无作用域的遗留工具）。
    if user_id is None:
        aliases = {'pure_marl':'pure', 'bc_marl':'bc', 'selfish':'selfish'}
        alias = aliases.get(mode,mode)
        combined = _load_result_file(f'results/training_results_{mode}_combined.json')
        if combined and isinstance(combined, dict) and 'episode_rewards_mean' in combined:
            combined['_format'] = 'combined'
            combined['_source'] = 'archived_experiment'
            return combined
        legacy = _load_result_file(f'training_results_{alias}.json')
        if legacy and isinstance(legacy,dict) and isinstance(legacy.get('summary'),dict):
            legacy['_format'] = 'single'
            legacy['_source'] = 'historical_result'
            return legacy
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
    from flask import session
    uid = session['uid']
    pure, bc, selfish = (_training_result('pure_marl', user_id=uid),
                         _training_result('bc_marl', user_id=uid),
                         _training_result('selfish', user_id=uid))
    return render_template('dashboard.html', username=session.get('username',''), csrf=session.get('_csrf',''),
        pure_data_json=json.dumps(pure, ensure_ascii=False) if pure else 'null',
        bc_data_json=json.dumps(bc, ensure_ascii=False) if bc else 'null',
        selfish_data_json=json.dumps(selfish, ensure_ascii=False) if selfish else 'null')

def _route_healthz():
    return jsonify({'status': 'ok', 'service': 'marl-ecdsa-dashboard', 'version': 'v27'})

def _route_favicon():
    """站点图标。

    Flask 的 static 路由只响应 /static/favicon.ico；浏览器（以及部分抓取器）
    仍会直接探测根路径 /favicon.ico —— 不显式处理就会 404（实测 exe 日志里出现过）。
    这里直接回静态目录里的同一份文件，避免 404 与重复拷贝。
    """
    return send_from_directory(str(_BASE_DIR / 'static'), 'favicon.ico')

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
    """Read-only P2P view. Historical consensus statistics do not prove live P2P connectivity."""
    consensus = _dashboard_data.get('consensus_stats', {}) or {}
    log = _dashboard_data.get('p2p_log', []) or []
    network = _dashboard_data.get('p2p_stats', {}) or {}
    if not isinstance(network, dict):
        network = {}
    live = network.get('p2p_enabled') is True
    # Only report connectivity metrics if an actual network collector supplied them.
    return jsonify({
        'p2p_enabled': live,
        'is_simulated': not live or bool(network.get('is_simulated', False)),
        'note': '仅展示原始网络采集数据；训练权重不能证明 P2P 已启用',
        'n_nodes': network.get('n_nodes', 0) if live else 0,
        'nodes': network.get('nodes', {}) if live else {},
        'connections': network.get('connections', []) if live else [],
        'total_consensus_rounds': network.get('total_consensus_rounds') if live else None,
        'total_msg_sent': network.get('total_msg_sent') if live else None,
        'total_msg_received': network.get('total_msg_received') if live else None,
        'avg_latency_ms': network.get('avg_latency_ms') if live else None,
        'weights': network.get('weights', consensus.get('weights', {})),
        'recent_log': network.get('recent_log', log),
    })

def _route_api_load(mode):
    """Latest completed real job, then archived data, with a precise missing-data response."""
    mapping = {'pure':'pure_marl','bc':'bc_marl','selfish':'selfish'}
    if mode not in mapping:
        return jsonify({'error':'不支持的训练模式'}),400
    from flask import session
    result = _training_result(mapping[mode], user_id=session['uid'])
    if result is None:
        return jsonify({'error':'暂无已完成的该模式训练数据','mode':mode,'available':False}),404
    return jsonify(result)

def _route_api_compare():
    from flask import session
    return jsonify({'pure':_training_result('pure_marl', user_id=session['uid']),
                    'bc':_training_result('bc_marl', user_id=session['uid']),
                    'selfish':_training_result('selfish', user_id=session['uid'])})

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
            if attack_type in ('byzantine', 'byzantine_primary'):
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
    'NR-1': {'id': 'NR-1', 'improvement_pct': 25.75, 'welch_p': 0.003348,
             'cohens_d': 0.4179, 'n': 101,
             'field': 'summary.avg_env_reward_last_50（末50回合 env_reward，不含BC激励）',
             'role': '首轮机制读数（赛后 λ 进梯度修复后同种子收敛，不作主口径）'},
    'NR-2': {'id': 'NR-2', 'improvement_pct': 7.7, 'welch_p': 1.142e-14,
             'cohens_d': 1.1749, 'n': 101,
             'field': 'summary.avg_env_reward（全程 env_reward，不含BC激励）',
             'role': '主口径：全程协作增益'},
    'NR-3': {'id': 'NR-3', 'improvement_pct': 1.92, 'welch_p': 1.504e-14,
             'cohens_d': 1.1691, 'n': 101,
             'field': 'summary.avg_cooperation_rate（全程平均合作率）'},
    # 跨种子稳健读数（决策 A：全程口径跨两批独立种子收敛于 +6.5~6.6%，这是对外主读数）
    'NR-202': {'id': 'NR-202', 'improvement_pct': 6.54, 'welch_p': 6.85e-11,
               'cohens_d': 0.9705, 'n': 202,
               'field': '全程 env_reward（同种子机制修复后复现，202 运行）',
               'role': '主口径稳健性：同种子修复后复现'},
    'NR-203': {'id': 'NR-203', 'improvement_pct': 6.61, 'welch_p': 8.21e-12,
               'cohens_d': 1.0294, 'n': 200,
               'field': '全程 env_reward（跨种子 301–400 泛化，200 运行）',
               'role': '主口径稳健性：跨种子泛化'},
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
        'note': '主口径=全程协作增益（NR-2 +7.7% 原初批；NR-202 +6.54% 同种子修复后复现；'
                'NR-203 +6.61% 跨种子泛化），三批方向一致、稳健显著。NR-1 末50 +25.75% 为'
                '首轮机制读数，赛后 λ 进梯度修复后同种子收敛，故不作主口径。单点不得宣称'
                '“证明激励有效”，效应量与口径边界如实同报。',
        'caliber': caliber,
    })


def _load_persistent_secret():
    import secrets
    secret_file = _BASE_DIR / 'instance' / 'session_secret'
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    if secret_file.exists():
        return secret_file.read_text(encoding='utf-8').strip()
    value = secrets.token_hex(32)
    try:
        with secret_file.open('x', encoding='utf-8') as f:
            f.write(value)
    except FileExistsError:
        return secret_file.read_text(encoding='utf-8').strip()
    try:
        secret_file.chmod(0o600)
    except OSError:
        pass
    return value


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

    # 站内账户：SQLite 存储密码哈希，不影响现有实验 API 和匿名演示。
    import os
    from flask import session, redirect, url_for, flash
    from werkzeug.security import generate_password_hash, check_password_hash
    import sqlite3, secrets
    from threading import Lock
    users_db = _BASE_DIR / 'instance' / 'accounts.sqlite3'
    users_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(users_db) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    flask_app.secret_key = os.environ.get('MARL_DASHBOARD_SECRET') or _load_persistent_secret()
    flask_app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    db_lock = Lock()
    @flask_app.before_request
    def require_account():
        # Static assets and login/registration remain public; all dashboard APIs require login.
        if request.endpoint in ('static', 'favicon', 'healthz', 'login', 'register'):
            return None
        if session.get('uid') is None:
            if request.path.startswith('/api/'):
                return jsonify({'error': '请先登录', 'login_url': '/login'}), 401
            return redirect(url_for('login'))
        # On authenticated POST endpoints with side effects verify CSRF.
        if request.method == 'POST' and request.endpoint != 'logout':
            token = request.headers.get('X-CSRF-Token', '')
            if not secrets.compare_digest(token, session.get('_csrf', '')):
                return jsonify({'error': 'CSRF 校验失败'}), 403


    def csrf_token():
        if '_csrf' not in session: session['_csrf'] = secrets.token_urlsafe(32)
        return session['_csrf']
    flask_app.jinja_env.globals['csrf_token'] = csrf_token

    @flask_app.route('/login', methods=['GET','POST'])
    def login():
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf_token',''), csrf_token()):
                flash('请求已失效，请刷新页面重试。', 'error')
            else:
                name = request.form.get('username','').strip()
                password = request.form.get('password','')
                with sqlite3.connect(users_db) as conn:
                    row = conn.execute('SELECT id,password_hash FROM users WHERE username=?',(name,)).fetchone()
                if row and check_password_hash(row[1],password):
                    session.clear(); session['uid']=row[0]; session['username']=name; csrf_token()
                    return redirect(url_for('index'))
                flash('账号或密码错误。','error')
        if session.get('uid'):
            return redirect(url_for('index'))
        return render_template('auth.html', mode='login')

    @flask_app.route('/register', methods=['GET','POST'])
    def register():
        if request.method == 'POST':
            name = request.form.get('username','').strip()
            password = request.form.get('password','')
            confirm = request.form.get('confirm','')
            if not secrets.compare_digest(request.form.get('csrf_token',''),csrf_token()):
                flash('请求已失效，请刷新页面重试。','error')
            elif not (3 <= len(name) <= 32) or not all(c.isascii() and (c.isalnum() or c in '_-') for c in name):
                flash('账号需要 3–32 位英文字母、数字、下划线或连字符。','error')
            elif len(password)<10 or len(password)>128 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
                flash('密码须为 10–128 位，并包含字母与数字。','error')
            elif password != confirm:
                flash('两次输入的密码不一致。','error')
            else:
                try:
                    with db_lock, sqlite3.connect(users_db) as conn:
                        conn.execute('INSERT INTO users(username,password_hash) VALUES(?,?)',(name,generate_password_hash(password)))
                    flash('注册成功，请登录。','success')
                    return redirect(url_for('login'))
                except sqlite3.IntegrityError: flash('该账号已存在。','error')
        if session.get('uid'):
            return redirect(url_for('index'))
        return render_template('auth.html',mode='register')

    @flask_app.route('/logout', methods=['POST'])
    def logout():
        if not secrets.compare_digest(request.form.get('csrf_token',''),csrf_token()):
            return 'Invalid CSRF token', 400
        session.clear()
        return redirect(url_for('login'))

    @flask_app.route('/api/me')
    def api_me():
        return jsonify({'authenticated': bool(session.get('uid')), 'username':session.get('username')})

    @flask_app.route('/api/evidence/verify-ledger', methods=['POST'])
    def api_verify_ledger():
        from visualization.evidence_verifier import verify_export
        if request.content_length is not None and request.content_length > 8_000_000:
            return jsonify({'valid': False, 'error': '文件大小超过 8MB'}), 413
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({'valid': False, 'error': '请提交 JSON 格式的账本数据'}), 400
        return jsonify(verify_export(payload))

    @flask_app.route('/api/p2p/probe', methods=['POST'])
    def api_p2p_probe():
        import socket, time
        values = request.get_json(silent=True) or {}
        try:
            ports = values.get('ports', [])
            if not isinstance(ports, list) or not 1 <= len(ports) <= 12:
                raise ValueError('请选择 1—12 个本机端口')
            ports = [int(x) for x in ports]
            if any(port < 1 or port > 65535 for port in ports):
                raise ValueError('端口必须在 1—65535 之间')
        except (ValueError, TypeError) as e:
            return jsonify({'error': str(e)}), 400
        results = []
        for port in ports:
            started = time.monotonic()
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.35):
                    reachable = True
            except OSError:
                reachable = False
            results.append({'host': '127.0.0.1', 'port': port,
                            'reachable': reachable,
                            'elapsed_ms': round((time.monotonic()-started)*1000, 2)})
        return jsonify({'results': results, 'scope': 'local_tcp_port_probe'})

    from visualization import business_service as biz

    @flask_app.route('/api/business/transactions', methods=['GET', 'POST'])
    def business_transactions():
        uid=session['uid']
        if request.method=='GET': return jsonify({'transactions':biz.recent(uid)})
        data=request.get_json(silent=True) or {}
        try:return jsonify(biz.submit(uid,data.get('content'))),201
        except ValueError as e:return jsonify({'error':str(e)}),400

    @flask_app.route('/api/business/transactions/<txid>')
    def business_transaction(txid):
        result=biz.lookup(session['uid'],txid)
        return (jsonify(result),200) if result else (jsonify({'error':'交易不存在'}),404)

    @flask_app.route('/api/business/train/jobs', methods=['GET','POST'])
    def business_jobs():
        if request.method=='GET':return jsonify({'jobs':biz.jobs(session['uid'])})
        try:return jsonify(biz.start(session['uid'],request.get_json(silent=True))),201
        except ValueError as e:return jsonify({'error':str(e)}),400

    @flask_app.route('/api/business/train/jobs/<jid>')
    def business_job(jid):
        job=biz.get_job(session['uid'],jid)
        return (jsonify(job),200) if job else (jsonify({'error':'任务不存在'}),404)

    @flask_app.route('/api/business/train/jobs/<jid>/stop', methods=['POST'])
    def business_stop(jid):
        job=biz.stop(session['uid'],jid)
        return (jsonify(job),200) if job else (jsonify({'error':'任务不存在'}),404)

    @flask_app.route('/api/business/train/jobs/<jid>/logs')
    def business_logs(jid):
        log=biz.logs(session['uid'],jid)
        return (jsonify({'logs':log}),200) if log is not None else (jsonify({'error':'任务不存在'}),404)

    @flask_app.route('/api/business/chain/audit')
    def business_chain_audit():
        return jsonify(biz.audit(session['uid']))

    @flask_app.route('/api/business/chain/blocks')
    def business_chain_blocks():
        return jsonify({'blocks':biz.blocks(session['uid'])})

    @flask_app.route('/api/business/chain/receipt/<txid>')
    def business_chain_receipt(txid):
        import re
        if not re.fullmatch(r'[0-9a-f]{64}',txid):return jsonify({'error':'交易哈希无效'}),400
        result=biz.receipt(session['uid'],txid)
        return jsonify(result) if result else (jsonify({'error':'交易不存在或无权访问'}),404)

    @flask_app.route('/api/business/chain/tamper-check', methods=['POST'])
    def business_chain_tamper_check():
        import re
        data=request.get_json(silent=True) or {}
        txid=data.get('txid','')
        if not isinstance(txid,str) or not re.fullmatch(r'[0-9a-f]{64}',txid):return jsonify({'error':'交易哈希无效'}),400
        try:result=biz.simulate_tamper(session['uid'],txid,data.get('content'))
        except ValueError as e:return jsonify({'error':str(e)}),400
        return jsonify(result) if result else (jsonify({'error':'交易不存在或无权访问'}),404)

    @flask_app.route('/api/distributed/snapshot', methods=['GET'])
    def distributed_snapshot():
        from visualization import distributed_consensus as dc
        return jsonify(dc.latest_snapshot())

    @flask_app.route('/api/distributed/collaboration/jobs')
    def distributed_collaboration_jobs():
        from visualization import collaboration_service as cs
        return jsonify(cs.jobs(session['uid']))

    @flask_app.route('/api/distributed/collaboration/task/<job_id>/lifecycle')
    def distributed_task_lifecycle(job_id):
        """Unified, account-scoped evidence state for one BC-MARL task."""
        from visualization import collaboration_lifecycle as lifecycle
        try:
            return jsonify(lifecycle.task_lifecycle(session['uid'], job_id))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return jsonify({'error': str(exc)}), 400

    @flask_app.route('/api/distributed/collaboration/audit')
    def distributed_collaboration_audit():
        from visualization import collaboration_lifecycle as lifecycle
        try:
            return jsonify(lifecycle.audit_portfolio(session['uid']))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return jsonify({'error': str(exc)}), 400

    @flask_app.route('/api/distributed/contribution/preview', methods=['POST'])
    def distributed_contribution_preview():
        from visualization import collaboration_service as cs
        body=request.get_json(silent=True) or {}
        try:
            return jsonify(cs.candidate(session['uid'], body.get('job_id'), body.get('window',20)))
        except (ValueError, OSError, TypeError, KeyError) as e:
            return jsonify({'error':str(e)}),400

    @flask_app.route('/api/distributed/contribution/activate',methods=['POST'])
    def distributed_contribution_activate():
        from visualization import collaboration_service as cs
        from visualization import distributed_consensus as dc
        body=request.get_json(silent=True) or {}
        try:
            candidate=cs.candidate(session['uid'],body.get('job_id'),body.get('window',20))
            if (candidate['origin_sha256']!=body.get('origin_sha256') or
                    candidate['training_binding']['training_result_sha256']!=body.get('training_result_sha256') or
                    candidate['rounds_sha256']!=body.get('rounds_sha256')):
                raise ValueError('贡献来源或训练结果已变化，请重新预览')
            return jsonify(dc.activate_snapshot(candidate))
        except (ValueError,OSError,TypeError,KeyError) as e:
            return jsonify({'error':str(e)}),400

    @flask_app.route('/api/distributed/recover',methods=['POST'])
    def distributed_recover():
        from visualization import distributed_consensus as dc
        body=request.get_json(silent=True) or {}
        cfg=dc.init_network()
        node=next((x for x in cfg['peers'] if x['id']==body.get('node')),None)
        if node is None:return jsonify({'error':'未知节点'}),400
        try:return jsonify(dc.recover_node(node,cfg['peers']))
        except (ValueError,OSError,KeyError) as e:return jsonify({'error':str(e)}),400

    @flask_app.route('/api/distributed/epochs')
    def distributed_epochs():
        from visualization import distributed_consensus as dc
        return jsonify(dc.epoch_status())

    @flask_app.route('/api/distributed/nodes')
    def distributed_nodes():
        from visualization import distributed_consensus as dc
        return jsonify(dc.statuses())

    @flask_app.route('/api/distributed/submit',methods=['POST'])
    def distributed_submit():
        from visualization import distributed_consensus as dc
        body=request.get_json(silent=True) or {}
        try:
            tx=biz.sign_distributed(session['uid'],body.get('content'))
            result=dc.propose(tx,max_views=body.get("max_views",3),timeout=body.get("timeout",1.0))
            if result.get('status')=='quorum_failed':
                # F04：失败现场登记——resume 端点用原 txid 幂等续跑
                biz.remember_pending_submit(session['uid'],tx,result)
            return jsonify(result), (201 if result['status']=='replicated' else 202)
        except ValueError as ex:return jsonify({'error':str(ex)}),400

    @flask_app.route('/api/distributed/pending',methods=['GET'])
    def distributed_pending():
        """F04：网络卡死轮次可视化 + 当前用户的待续跑存证。"""
        from visualization import distributed_consensus as dc
        st=dc.pending_rounds()
        mine=biz.get_pending_submit(session['uid'])
        return jsonify({'network':st,'my_pending':(
            {'txid':mine['txid'],'age_s':round(time.time()-mine['at'],1),
             'status':mine['status']} if mine else None)})

    @flask_app.route('/api/distributed/resume',methods=['POST'])
    def distributed_resume():
        """F04：同 txid 幂等续跑——不再生成新 nonce（与重复点击提交的本质区别）。"""
        from visualization import distributed_consensus as dc
        mine=biz.get_pending_submit(session['uid'])
        if not mine:return jsonify({'error':'无可续跑的存证'}),404
        result=dc.propose(mine['tx'],max_views=3,timeout=1.0)
        if result.get('status')=='replicated':
            biz.pop_pending_submit(session['uid'])
        else:
            biz.remember_pending_submit(session['uid'],mine['tx'],result)
        return jsonify(result), (201 if result['status']=='replicated' else 202)

    @flask_app.route('/api/distributed/abort-pending',methods=['POST'])
    def distributed_abort_pending():
        """F04：协调清障（网络级操作，与停节点/换纪元同信任级）+ 清除本用户 pending。"""
        from visualization import distributed_consensus as dc
        outcome=dc.abort_pending_round()
        biz.pop_pending_submit(session['uid'])
        return jsonify(outcome), (200 if outcome.get('coordinated') else 409)

    @flask_app.route('/api/distributed/contribution/attest', methods=['POST'])
    def distributed_contribution_attest():
        """Attest a verified BC-MARL job's contribution weights on the active epoch."""
        from visualization import distributed_consensus as dc
        from visualization import collaboration_service as cs
        body=request.get_json(silent=True) or {}
        try:
            cfg=dc.init_network()
            evidence=cs.attest_event(cfg, session['uid'])
            # V25: a task-level commit must match the job explicitly chosen in the UI.
            selected_job=body.get('job_id')
            if selected_job is not None and selected_job!=evidence['training_job_id']:
                raise ValueError('所选训练任务与当前激活的贡献纪元不一致，请核对权重快照')
            # A contribution/epoch commitment is a unique governance event.
            # Do not sign a new transaction if this snapshot is already on a
            # signed local chain, even if replicas have not fully caught up.
            # F14：去重扫全链（cap=None），而非展示用的最近 10 条，避免历史存证被挤出漏检。
            # F14 原子化：查重→签名→propose 全程持锁，堵并发双提交窗口。
            from visualization import collaboration_lifecycle as lifecycle
            with _ATTEST_MUTEX:
                existing=next((r for r in lifecycle._committed_blocks(
                    cfg, session['uid'], evidence['training_job_id'], cap=None)
                    if r['snapshot_hash'] == evidence['snapshot_hash']), None)
                if existing:
                    verification=dc.cross_verify(existing['height'], deep=True)
                    return jsonify({'status':'already_attested',
                        'block_height':existing['height'], 'txid':existing['txid'],
                        'snapshot':existing['snapshot_hash'],
                        'replication_confirmed':verification['consistent'],
                        'message':'该训练任务在当前纪元已有签名存证，请核验或恢复落后节点，勿重复提交'}),200
                raw=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                if len(raw)>2048:
                    raise ValueError('贡献事件超出交易长度限制')
                signed=biz.sign_distributed(session['uid'],raw)
                result=dc.propose(signed,max_views=body.get("max_views",3),timeout=body.get("timeout",1.0))
            if result.get('status')=='quorum_failed':
                # F04：失败现场登记——resume 端点用原 txid 幂等续跑
                biz.remember_pending_submit(session['uid'],signed,result)
            result['evidence']=evidence
            result['evidence_sha256']=hashlib.sha256(raw.encode()).hexdigest()
            result['evidence_status']='replicated' if result['status']=='replicated' else 'not_fully_replicated'
            return jsonify(result), (201 if result['status']=='replicated' else 202)
        except (ValueError,TypeError,KeyError,OSError) as e:
            return jsonify({'error':str(e)}),400

    @flask_app.route('/api/distributed/collaboration/trace/<int:height>')
    def distributed_collaboration_trace(height):
        from visualization import collaboration_service as cs
        try:
            if height < 1:
                raise ValueError('区块高度必须大于零')
            return jsonify(cs.trace(height, session['uid']))
        except (ValueError,TypeError,KeyError,OSError) as e:
            return jsonify({'error':str(e)}),400

    @flask_app.route('/api/distributed/verify/<int:height>')
    def distributed_verify(height):
        from visualization import distributed_consensus as dc
        if height<1:return jsonify({'error':'无效高度'}),400
        return jsonify(dc.cross_verify(height))

    # 注册路由
    flask_app.add_url_rule('/', 'index', _route_index)
    flask_app.add_url_rule('/healthz', 'healthz', _route_healthz)
    flask_app.add_url_rule('/favicon.ico', 'favicon', _route_favicon)
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
