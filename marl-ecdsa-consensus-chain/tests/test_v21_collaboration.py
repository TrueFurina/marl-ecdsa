"""Controlled multi-process integration for training-to-chain provenance.
Test fixture data are synthetic; a separate train.py execution verifies real artifact creation.
Run: python -m unittest tests.test_v21_collaboration -v
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from visualization import business_service as biz
from visualization import distributed_consensus as dc
from visualization import collaboration_service as cs
from tests.test_v11_epoch_view import isolate_consensus_ports


class CollaborationLinkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.old_db = biz.DB
        self.old_net = (dc.BASE, dc.CONFIG, dc.HISTORY)
        biz.DB = self.dir / 'business.sqlite3'
        biz.init()
        dc.BASE = self.dir / 'nodes'
        dc.CONFIG = dc.BASE / 'network.json'
        dc.HISTORY = dc.BASE / 'epochs'
        isolate_consensus_ports(dc.init_network())  # 端口隔离：见 test_v11_epoch_view.isolate_consensus_ports
        self.uid = 77
        self.jid = uuid.uuid4().hex
        self.result_path = cs.TRAIN_LOGS / (self.jid + '.json')
        self.contrib_path = cs.CONTRIB / ('contribution_log_' + self.jid + '_99999.json')
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        self.contrib_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg = {'mode':'bc_marl','algorithm':'iql','n_episodes':3,'n_agents':3,'max_steps':5,'seed':123}
        self.result_path.write_text(json.dumps({'config':self.cfg,'summary':{'avg_reward':-1,'avg_cooperation_rate':0.5},'episode_rewards':[-1,-2,0.5]},ensure_ascii=False),encoding='utf-8')
        self.contrib_path.write_text(json.dumps({
            'n_agents':3,'agent_ids':['agent_0','agent_1','agent_2'],
            'run_tag':self.jid,'training_result_sha256':cs.file_sha256(self.result_path),
            'records':[{'episode':i+1,'contribution_share':[.5,.3,.2]} for i in range(3)]
        }),encoding='utf-8')
        with biz.conn() as db:
            db.execute('INSERT INTO jobs (id,user_id,status,config,log_path,result_path,exit_code,created_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (self.jid,self.uid,'completed',json.dumps(self.cfg),str(self.dir/'dummy.log'),str(self.result_path),0,time.time(),time.time()))
        self.children = []

    def tearDown(self):
        for process in self.children:
            if process.poll() is None:
                process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill()
        for path in (self.result_path, self.contrib_path):
            if path.exists(): path.unlink()
        biz.DB = self.old_db
        dc.BASE,dc.CONFIG,dc.HISTORY = self.old_net
        # F11 缓解（2026-11-02 赛后）：Windows 句柄释放晚于 tearDown —— gc+限时重试
        import gc as _gc, time as _t
        _gc.collect()
        for _ in range(5):
            try:
                self.temp.cleanup(); break
            except PermissionError:
                _t.sleep(0.2); _gc.collect()
        else:
            self.temp.cleanup()

    def test_job_source_and_hash_tampering(self):
        rows=cs.jobs(self.uid)['jobs']
        self.assertTrue(any(x['job_id']==self.jid and x['eligible'] for x in rows))
        with self.assertRaises(ValueError): cs.candidate(self.uid+1,self.jid)
        c=cs.candidate(self.uid,self.jid)
        self.assertEqual(c['episodes'],3)
        self.assertEqual(sum(c['weights']), 9999)
        dc.activate_snapshot(c)
        self.assertEqual(cs.attest_event(dc.init_network(),self.uid)['training_job_id'],self.jid)
        self.result_path.write_text(self.result_path.read_text(encoding='utf-8')+' ',encoding='utf-8')
        with self.assertRaises(ValueError): cs.attest_event(dc.init_network(),self.uid)

    def test_f12_result_config_mismatch_rejected(self):
        # 合法：结果 config 与提交 config 一致 → 候选可生成
        ok = cs.candidate(self.uid, self.jid)
        self.assertEqual(ok['training_binding']['algorithm'], self.cfg['algorithm'])
        # 伪造：仅把结果文件的 algorithm 改成与提交配置不符，并同步刷新贡献摘要，
        # 使失败只能来自逐项 config 比对（F12），而非结果摘要不符
        tampered = dict(self.cfg, algorithm='qmix')
        self.result_path.write_text(json.dumps(
            {'config': tampered,
             'summary': {'avg_reward': -1, 'avg_cooperation_rate': 0.5},
             'episode_rewards': [-1, -2, 0.5]}, ensure_ascii=False), encoding='utf-8')
        self.contrib_path.write_text(json.dumps({
            'n_agents': 3, 'agent_ids': ['agent_0', 'agent_1', 'agent_2'],
            'run_tag': self.jid, 'training_result_sha256': cs.file_sha256(self.result_path),
            'records': [{'episode': i + 1, 'contribution_share': [.5, .3, .2]} for i in range(3)]
        }), encoding='utf-8')
        with self.assertRaises(ValueError) as ctx:
            cs.candidate(self.uid, self.jid)
        self.assertIn('algorithm', str(ctx.exception))

    def test_live_replication_and_trace(self):
        c=cs.candidate(self.uid,self.jid)
        dc.activate_snapshot(c)
        cfg=dc.init_network()
        for peer in cfg['peers']:
            code=("import sys; from pathlib import Path; "
                  f"sys.path.insert(0,{str(ROOT)!r}); "
                  "from visualization import distributed_consensus as d; "
                  f"d.BASE=Path({str(dc.BASE)!r}); d.CONFIG=d.BASE/'network.json'; d.HISTORY=d.BASE/'epochs'; "
                  f"d.serve({peer['id']!r})")
            proc=subprocess.Popen([sys.executable,'-c',code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.children.append(proc)
        for _ in range(90):
            if all(x.get('online') for x in dc.statuses()['nodes']):break
            time.sleep(.1)
        else: self.fail('three local node processes did not respond')
        event=cs.attest_event(cfg,self.uid)
        signed=biz.sign_distributed(self.uid,json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(',',':')))
        committed=dc.propose(signed,timeout=.8,max_views=2)
        self.assertEqual(committed['status'],'replicated',committed)
        trace=cs.trace(committed['block_height'],self.uid)
        self.assertTrue(trace['verified'],trace)
        self.assertTrue(trace['training_artifacts_match'])
        self.assertTrue(trace['cross_node_consistent'])
        with self.assertRaises(ValueError):cs.trace(committed['block_height'],self.uid+1)
        # Modifying a local file invalidates the training-origin portion, not old signatures.
        self.contrib_path.write_text(self.contrib_path.read_text(encoding='utf-8')+' ',encoding='utf-8')
        trace=cs.trace(committed['block_height'],self.uid)
        self.assertTrue(trace['certificate_valid'])
        self.assertFalse(trace['training_artifacts_match'])
        self.assertFalse(trace['verified'])

if __name__ == '__main__':
    unittest.main()
