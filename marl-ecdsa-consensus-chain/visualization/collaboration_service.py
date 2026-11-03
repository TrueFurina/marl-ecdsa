"""Bind authenticated BC-MARL training jobs to contribution epochs and chain evidence.

The binding proves consistency of local artifacts, not fairness of the contribution
estimator or Byzantine fault tolerance of the underlying prototype.
"""
import hashlib
import json
import math
from pathlib import Path

from visualization import business_service as biz
from visualization import distributed_consensus as dc

ROOT = Path(__file__).resolve().parent.parent
CONTRIB = (ROOT / 'results' / 'contribution').resolve()
TRAIN_LOGS = biz.LOGS.resolve()


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def confined(path, root):
    path = Path(path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError('训练文件超出允许的项目目录')
    if path.suffix.lower() != '.json' or not path.is_file():
        raise ValueError('训练结果文件不存在或格式错误')
    return path


def _job_source(uid, jid):
    if not isinstance(jid, str) or len(jid) != 32 or not all(c in '0123456789abcdef' for c in jid):
        raise ValueError('请选择有效的训练任务')
    # Reading through the job service updates the completed/failed status of subprocesses.
    biz.get_job(uid, jid)
    with biz.conn() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=? AND user_id=?', (jid, uid)).fetchone()
    if row is None:
        raise ValueError('无权查看该训练任务')
    if row['status'] != 'completed' or row['exit_code'] != 0:
        raise ValueError('只允许使用已成功完成的训练任务')
    config = json.loads(row['config'])
    if config.get('mode') != 'bc_marl' or config.get('n_agents') != 3:
        raise ValueError('贡献治理需要三智能体 BC-MARL 训练结果')
    try:
        result_path = confined(row['result_path'], TRAIN_LOGS)
    except ValueError:
        # A copied V20 instance DB may contain an absolute path from the old
        # project folder. Only allow the exact current job-ID file under LOGS.
        result_path = confined(TRAIN_LOGS / (jid + '.json'), TRAIN_LOGS)
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if (not isinstance(result, dict) or result.get('config', {}).get('mode') != 'bc_marl'
            or not isinstance(result.get('summary'), dict)
            or not isinstance(result.get('episode_rewards'), list)
            or not result['episode_rewards']):
        raise ValueError('训练结果数据不完整或模式不匹配')
    if len(result['episode_rewards']) != config['n_episodes']:
        raise ValueError('训练结果回合数与提交配置不一致')
    # F12：逐项绑定提交配置与结果文件配置，堵住「结果文件 config 与 DB 承诺不一致」
    # 的伪造/错绑路径。candidate 用 digest(config) 承诺训练配置，而 training_result_sha256
    # 承诺结果文件——若不逐项比对，二者可各自声称不同的算法/种子/规模。仅比对治理相关
    # 且双方均携带的公共字段；结果缺字段（历史件）保持兼容，不一致则拒。
    result_cfg = result.get('config', {}) or {}
    for _k in ('algorithm', 'seed', 'n_agents', 'n_landmarks', 'max_steps'):
        if _k in result_cfg and _k in config and result_cfg[_k] != config[_k]:
            raise ValueError(f'训练结果的 {_k}={result_cfg[_k]} 与提交配置 {_k}={config[_k]} 不一致')
    files = sorted(CONTRIB.glob('contribution_log_' + jid + '_*.json'),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise ValueError('该任务缺少同一运行标识的贡献记录；不能使用其他任务的文件替代')
    for path in files:
        path = confined(path, CONTRIB)
        obj = json.loads(path.read_text(encoding='utf-8'))
        if (isinstance(obj, dict) and obj.get('agent_ids') == ['agent_0', 'agent_1', 'agent_2']
                and isinstance(obj.get('records'), list)
                and len(obj['records']) == config['n_episodes']
                and (obj.get('run_tag') in (None, jid))
                and (obj.get('training_result_sha256') in (None, file_sha256(result_path)))):
            return config, result, result_path, obj, path
    raise ValueError('贡献记录与训练任务的回合数、智能体或结果摘要不匹配')


def jobs(uid):
    biz.jobs(uid)
    with biz.conn() as db:
        rows = db.execute('SELECT id,config,finished_at FROM jobs WHERE user_id=? AND status=? '
                          'AND exit_code=0 ORDER BY finished_at DESC LIMIT 40',
                          (uid, 'completed')).fetchall()
    out = []
    for row in rows:
        try:
            config, result, result_path, obj, path = _job_source(uid, row['id'])
            out.append({'job_id': row['id'], 'seed': config['seed'],
                        'episodes': len(obj['records']), 'algorithm': config['algorithm'],
                        'contribution_file': path.name, 'eligible': True,
                        'summary': {'avg_reward': result['summary'].get('avg_reward'),
                                    'avg_cooperation_rate': result['summary'].get('avg_cooperation_rate')}})
        except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
            out.append({'job_id': row['id'], 'eligible': False, 'reason': str(exc)})
    return {'jobs': out}


def candidate(uid, jid, window=20):
    config, result, result_path, obj, path = _job_source(uid, jid)
    candidate = dc.build_contribution_snapshot(path, window)
    last_records = obj['records'][-candidate['episodes']:]
    candidate['rounds_sha256'] = dc.digest({'agent_ids': obj['agent_ids'], 'records': last_records})
    candidate['training_binding'] = {
        'job_id': jid,
        'owner_user_id': uid,
        'training_mode': 'bc_marl',
        'algorithm': config['algorithm'],
        'seed': config['seed'],
        'training_result_sha256': file_sha256(result_path),
        'training_config_sha256': dc.digest(config),
        'training_episodes': config['n_episodes'],
        'source_binding': 'job_id_filename_plus_training_result_digest',
    }
    candidate['training_summary'] = {
        'avg_reward': result['summary'].get('avg_reward'),
        'avg_cooperation_rate': result['summary'].get('avg_cooperation_rate')
    }
    scores = result.get('bc_scores_final')
    if isinstance(scores, dict) and all(isinstance(scores.get('agent_'+str(i)), (int,float))
                                        and not isinstance(scores.get('agent_'+str(i)),bool)
                                        and math.isfinite(scores['agent_'+str(i)])
                                        for i in range(3)):
        candidate['incentive_scores'] = [
            {'agent':'agent_'+str(i),'node':candidate['agent_mapping'][i]['node'],
             'bc_score':float(scores['agent_'+str(i)])}
            for i in range(3)]
    else:
        candidate['incentive_scores'] = []
    candidate['incentive_scores_sha256'] = dc.digest(candidate['incentive_scores'])
    return candidate


def validate_active_evidence(cfg, uid=None):
    """Revalidate the artifacts immediately before an on-chain attestation."""
    proof = cfg.get('training_proof')
    if cfg.get('weight_source') != 'training_contribution_share_snapshot' or not isinstance(proof, dict):
        raise ValueError('当前纪元并非由已完成的 BC-MARL 训练贡献激活')
    binding = proof.get('training_binding')
    if not isinstance(binding, dict):
        raise ValueError('该纪元没有绑定训练任务，请使用新版训练贡献重新激活')
    if uid is not None and binding.get('owner_user_id') != uid:
        raise ValueError('当前纪元绑定其他账户的训练记录')
    check = candidate(binding['owner_user_id'], binding['job_id'], proof['episodes'])
    for key in ('origin_sha256', 'agent_mapping', 'weights', 'rounds_sha256', 'training_binding', 'incentive_scores_sha256'):
        expected = proof['agent_mapping'] if key == 'weights' else proof.get(key)
        if key == 'weights':
            expected = [item['weight'] for item in proof['agent_mapping']]
        if check.get(key) != expected:
            raise ValueError('训练贡献来源或权重发生变化，拒绝存证')
    for i, peer in enumerate(cfg['peers']):
        if check['agent_mapping'][i]['node'] != peer['id'] or check['weights'][i] != peer['weight']:
            raise ValueError('训练贡献和当前投票权重不一致')
    return check


def attest_event(cfg, uid):
    candidate_info = validate_active_evidence(cfg, uid)
    binding = candidate_info['training_binding']
    return {
        'event': 'MARL_COLLABORATION_CONTRIBUTION_COMMITMENT',
        'schema_version': 2,
        'network': cfg['network'],
        'epoch': cfg['version'],
        'snapshot_hash': dc.snapshot_digest(cfg),
        'training_job_id': binding['job_id'],
        'training_result_sha256': binding['training_result_sha256'],
        'training_config_sha256': binding['training_config_sha256'],
        'contribution_sha256': candidate_info['origin_sha256'],
        'episode_window_sha256': candidate_info['rounds_sha256'],
        'episodes_in_window': candidate_info['episodes'],
        'agent_node_weights': candidate_info['agent_mapping'],
        'weight_method': candidate_info['source'],
        'incentive_scores_sha256': candidate_info['incentive_scores_sha256'],
        'incentive_scope': 'BC_score_commitment_only_no_token_payment',
    }


def trace(height, uid):
    """Independently compare an on-chain attestation with its job and training files."""
    cfg = dc.init_network()
    cross = dc.cross_verify(height)
    verified_block = None
    for peer in cfg['peers']:
        try:
            b = dc.request(peer, '/block/' + str(height))
            p, cert = json.loads(b['proposal']), json.loads(b['certificate'])
            historical = dc.epoch_for_proposal(p, cfg)
            if (dc.certificate_valid(historical, p, cert)
                    and b['hash'] == dc.block_hash(height, p['previous'], b['txid'])):
                verified_block = (p, historical)
                break
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    if verified_block is None:
        raise ValueError('没有找到可验证签名证书的对应区块')
    p, historical = verified_block
    try:
        event = json.loads(p['transaction']['payload']['content'])
    except (TypeError, KeyError, ValueError, json.JSONDecodeError):
        raise ValueError('这不是结构化的协作贡献存证交易')
    if not isinstance(event, dict) or event.get('event') != 'MARL_COLLABORATION_CONTRIBUTION_COMMITMENT':
        raise ValueError('区块交易不是协作贡献存证事件')
    proof = historical.get('training_proof') or {}
    binding = proof.get('training_binding') or {}
    if binding.get('owner_user_id') != uid:
        raise ValueError('该存证不属于当前账户的训练任务')
    expected = {
        'network': historical['network'],
        'epoch': historical['version'],
        'snapshot_hash': dc.snapshot_digest(historical),
        'training_job_id': binding.get('job_id'),
        'training_result_sha256': binding.get('training_result_sha256'),
        'training_config_sha256': binding.get('training_config_sha256'),
        'contribution_sha256': proof.get('origin_sha256'),
        'episode_window_sha256': proof.get('rounds_sha256'),
        'episodes_in_window': proof.get('episodes'),
        'agent_node_weights': proof.get('agent_mapping'),
        'weight_method': proof.get('source'),
        'incentive_scores_sha256': proof.get('incentive_scores_sha256'),
        'incentive_scope': 'BC_score_commitment_only_no_token_payment',
    }
    metadata_matches = event.get('schema_version') == 2 and all(event.get(k) == v for k, v in expected.items())
    source_matches = False
    source_error = None
    try:
        validate_active = candidate(uid, binding['job_id'], proof['episodes'])
        source_matches = all(validate_active.get(k) == proof.get(k) for k in (
            'origin_sha256', 'rounds_sha256', 'agent_mapping', 'training_binding', 'incentive_scores_sha256'))
    except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError) as exc:
        source_error = str(exc)
    return {
        'height': height, 'txid': p['transaction']['txid'],
        'training_job_id': binding.get('job_id'),
        'epoch': expected['epoch'], 'snapshot_hash': expected['snapshot_hash'],
        'certificate_valid': True, 'cross_node_consistent': cross['consistent'],
        'evidence_fields_match_epoch': metadata_matches,
        'training_artifacts_match': source_matches,
        'verified': bool(cross['consistent'] and metadata_matches and source_matches),
        'verification_scope': 'signed_votes_and_block_hashes_plus_local_training_artifact_digests',
        'nodes': cross['nodes'], 'source_error': source_error,
        'evidence': event,
    }
