"""Task-centred read model for the MARL contribution -> consensus evidence chain.

This module adds no new ledger or fake business state. Every displayed step is
computed from a completed training job, its contribution file, the persisted
epoch configurations, and already-committed node blocks.
"""
import json
from pathlib import Path

from visualization import collaboration_service as cs
from visualization import distributed_consensus as dc


def _proof_for_job(config, uid, job_id):
    proof = config.get('training_proof')
    if not isinstance(proof, dict):
        return False
    binding = proof.get('training_binding')
    return (isinstance(binding, dict) and binding.get('owner_user_id') == uid
            and binding.get('job_id') == job_id)


def _all_epochs(current):
    yield current
    if not dc.HISTORY.is_dir():
        return
    for path in sorted(dc.HISTORY.glob('*.json')):
        try:
            epoch = json.loads(path.read_text(encoding='utf-8'))
            if (dc.snapshot_digest(epoch) == path.stem
                    and epoch.get('network') == current.get('network')):
                yield epoch
        except (ValueError, TypeError, KeyError, OSError):
            continue


def _committed_blocks(current, uid, job_id, limit=150, cap=10):
    """Locate evidence in local node journals; signatures checked before reporting.

    Offline nodes are NOT counted as cross-node replication. Scanning local disk
    is an index, not independent confirmation.

    cap: 展示用默认只回最近 10 条（按高度降序）。attest 去重需扫全链，传 cap=None
    取消截断——否则某任务在低高度已存证、之后高度增长超过 10 条时，去重会漏检而放行
    重复提交（F14）。扫描仍是本地索引，不构成跨节点独立确认。
    """
    candidates = {}
    for peer in current['peers']:
        try:
            with dc.db_for(peer['id']) as db:
                blocks = db.execute('SELECT * FROM blocks WHERE proposal LIKE ? ORDER BY height DESC LIMIT ?', ('%' + job_id + '%', limit)).fetchall()
            for block in blocks:
                try:
                    proposal = json.loads(block['proposal'])
                    content = proposal['transaction']['payload']['content']
                    event = json.loads(content)
                    if (not isinstance(event, dict)
                            or event.get('event') != 'MARL_COLLABORATION_CONTRIBUTION_COMMITMENT'
                            or event.get('training_job_id') != job_id):
                        continue
                    epoch = dc.epoch_for_proposal(proposal, current)
                    if not _proof_for_job(epoch, uid, job_id):
                        continue
                    cert = json.loads(block['certificate'])
                    if not (dc.certificate_valid(epoch, proposal, cert)
                            and proposal.get('height') == block['height']
                            and proposal['transaction']['txid'] == block['txid']
                            and block['previous'] == proposal.get('previous')
                            and block['hash'] == dc.block_hash(block['height'], block['previous'], block['txid'])):
                        continue
                    key = (block['height'], block['txid'])
                    if key not in candidates:
                        candidates[key] = {'height': block['height'], 'txid': block['txid'],
                            'block_hash': block['hash'], 'epoch': epoch['version'],
                            'snapshot_hash': dc.snapshot_digest(epoch),
                            'local_certificate_valid': True}
                except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                    continue
        except (ValueError, OSError):
            continue
    ordered = sorted(candidates.values(), key=lambda x: x['height'], reverse=True)
    return ordered if cap is None else ordered[:cap]


def task_lifecycle(uid, job_id):
    """Authenticated task data, current/archived epoch and signed chain evidence."""
    # Validates user ownership, completion status, file path, mode and digest.
    config, result, result_path, contribution, contribution_path = cs._job_source(uid, job_id)
    current = dc.init_network()
    epochs = [e for e in _all_epochs(current) if _proof_for_job(e, uid, job_id)]
    active = _proof_for_job(current, uid, job_id)
    provenance_reason = ''
    matched_epoch = None
    for epoch in epochs:
        proof = epoch['training_proof']
        try:
            test = cs.candidate(uid, job_id, proof['episodes'])
            keys = ('origin_sha256', 'rounds_sha256', 'agent_mapping',
                    'training_binding', 'incentive_scores_sha256')
            if all(test.get(k) == proof.get(k) for k in keys):
                matched_epoch = epoch
                break
        except (ValueError, TypeError, KeyError, OSError) as exc:
            provenance_reason = str(exc)
    provenance = not epochs or matched_epoch is not None
    if epochs and matched_epoch is None:
        provenance_reason = provenance_reason or '当前训练记录与纪元存档不一致'
    items = _committed_blocks(current, uid, job_id)
    latest = items[0] if items else None
    trace = None
    if latest:
        try:
            trace = cs.trace(latest['height'], uid)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            trace = {'verified': False, 'error': str(exc)}
    nodes = dc.statuses()['nodes']
    all_online = all(n.get('online') and n.get('epoch_matched') for n in nodes)
    stages = [
        {'key': 'training', 'label': '协作训练', 'done': True,
         'detail': '已完成 BC-MARL 训练并生成结果'},
        {'key': 'contribution', 'label': '贡献记录', 'done': True,
         'detail': '贡献文件与训练任务及结果摘要对应'},
        {'key': 'governance', 'label': '纪元治理', 'done': bool(epochs and provenance),
         'detail': '当前纪元' if active else ('历史纪元' if epochs else '尚未激活贡献快照')},
        {'key': 'attestation', 'label': '链上存证', 'done': bool(items),
         'detail': ('发现 %d 条具备有效本地证书的存证' % len(items)) if items else '尚无对应存证区块'},
        {'key': 'verification', 'label': '交叉核验', 'done': bool(trace and trace.get('verified')),
         'detail': '跨节点与本地来源全部匹配' if trace and trace.get('verified') else '未取得全部核验条件'},
    ]
    if not epochs:
        next_action = '请在下方预览本任务的贡献权重，完成停节点纪元激活。'
    elif not provenance:
        next_action = '训练来源与已存档权重不匹配，请检查文件，不要继续提交。'
    elif not items:
        next_action = ('节点已就绪，可提交当前纪元的贡献存证。'
                       if active and all_online else
                       '请核对当前纪元是否属于本任务，再检查共识节点是否在线。')
    elif trace and trace.get('verified'):
        next_action = '该任务的最近一条链上贡献证据已完成核验。'
    else:
        next_action = '已找到链上证据，请检查在线节点、完整复制和训练来源。'
    return {
        'job_id': job_id,
        'training': {'mode': config['mode'], 'algorithm': config['algorithm'],
            'seed': config['seed'], 'episodes': len(result['episode_rewards']),
            'avg_reward': result['summary'].get('avg_reward'),
            'avg_cooperation_rate': result['summary'].get('avg_cooperation_rate'),
            'result_sha256': cs.file_sha256(result_path),
            'contribution_sha256': cs.file_sha256(contribution_path)},
        'epoch': {'active_for_job': active, 'historical_versions': [e['version'] for e in epochs],
            'verified_against_source': provenance, 'provenance_error': provenance_reason,
            'current_epoch': current['version'], 'current_snapshot': dc.snapshot_digest(current),
            'weights': ([{'agent': m['agent'], 'node': m['node'], 'weight': m['weight']}
                        for m in current['training_proof']['agent_mapping']]
                        if active else [])},
        'network': {'all_nodes_online': all_online, 'nodes': nodes},
        'chain': {'records': items, 'latest_verification': trace},
        'stages': stages, 'next_action': next_action,
        'integrity_scope': 'local_artifact_hashes_and_signed_node_certificates;not_training_fairness_or_full_PBFT',
    }


def audit_portfolio(uid, limit=20):
    """Read-only account-scoped audit index; a signed local block is not a live quorum check."""
    available = cs.jobs(uid)['jobs'][:max(1, min(int(limit), 30))]
    cfg = dc.init_network()
    epochs = list(_all_epochs(cfg))
    rows = []
    for job in available:
        jid = job['job_id']
        # History must remain inspectable even when the underlying training file
        # is missing, corrupted or modified. The signed ledger is independent.
        versions = sorted(set(e['version'] for e in epochs if _proof_for_job(e, uid, jid)))
        records = _committed_blocks(cfg, uid, jid, limit=100)
        if not job['eligible']:
            rows.append({'job_id': jid, 'eligible': False,
                         'reason': job.get('reason', '训练来源校验未通过'),
                         'epoch_versions': versions, 'records': records[:5],
                         'status': ('训练来源异常，历史签名证据仍可核验' if records
                                    else '训练来源异常，尚未找到历史存证')})
            continue
        rows.append({'job_id': jid, 'eligible': True,
                     'algorithm': job.get('algorithm'), 'episodes': job.get('episodes'),
                     'epoch_versions': versions, 'active': _proof_for_job(cfg, uid, jid),
                     'records': records[:5],
                     'status': ('已发现签名存证，待在线独立核验' if records else
                                '已绑定历史权重，尚无存证' if versions else
                                '训练有效，尚未形成治理快照')})
    return {'tasks': rows, 'summary': {'eligible': sum(r['eligible'] for r in rows),
            'with_epochs': sum(bool(r['epoch_versions']) for r in rows),
            'with_signed_records': sum(bool(r['records']) for r in rows)},
            'note': '本列表仅索引本地有效签名存证；跨节点在线核验需进入具体任务重新检查'}
