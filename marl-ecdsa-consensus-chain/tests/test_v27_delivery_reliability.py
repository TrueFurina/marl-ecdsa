"""V27 delivery fixes: account isolation, recovered subprocesses, input constraints."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from visualization import business_service as biz
from visualization import dashboard as dash


class DeliveryReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = biz.DB, biz.LOGS
        biz.DB = Path(self.tmp.name) / 'business.sqlite3'
        biz.LOGS = Path(self.tmp.name) / 'training_logs'
        biz.LOGS.mkdir()
        biz.init()
        self.uid=9402
        self.jid='1'*32
        self.cfg={'mode':'bc_marl','algorithm':'iql','n_episodes':2,'n_agents':3,'max_steps':5,'seed':42}

    def tearDown(self):
        biz.DB,biz.LOGS = self.old
        # F11 缓解（2026-11-02 赛后）：Windows 下 sqlite 连接/子进程的文件句柄
        # 释放晚于 tearDown —— gc + 限时重试清 temp，而非直接 PermissionError。
        import gc as _gc, time as _t
        _gc.collect()
        for _ in range(5):
            try:
                self.tmp.cleanup(); break
            except PermissionError:
                _t.sleep(0.2); _gc.collect()
        else:
            self.tmp.cleanup()

    def add_untracked(self, result=None, pid=999999, status='running'):
        if result is not None:
            (biz.LOGS/(self.jid+'.json')).write_text(json.dumps(result),encoding='utf-8')
        with biz.conn() as db:
            db.execute('INSERT INTO jobs(id,user_id,status,config,log_path,result_path,pid,created_at) VALUES(?,?,?,?,?,?,?,?)',
               (self.jid,self.uid,status,json.dumps(self.cfg),str(biz.LOGS/(self.jid+'.log')),
                str(biz.LOGS/(self.jid+'.json')),pid,time.time()))

    def test_completed_training_survives_dashboard_restart(self):
        self.add_untracked({'config':self.cfg,'episode_rewards':[1,2],'summary':{}})
        result=biz.get_job(self.uid,self.jid)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['exit_code'],0)

    def test_incorrect_training_configuration_not_recovered_as_completed(self):
        incorrect={**self.cfg,'algorithm':'vdn'}
        self.add_untracked({'config':incorrect,'episode_rewards':[1,2],'summary':{}})
        with patch.object(biz.os,'kill',side_effect=ProcessLookupError):
            result=biz.get_job(self.uid,self.jid)
        self.assertEqual(result['status'],'failed')

    def test_dead_worker_no_longer_blocks_training(self):
        self.add_untracked()
        with patch.object(biz.os,'kill',side_effect=ProcessLookupError):
            result=biz.get_job(self.uid,self.jid)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['exit_code'],-1)

    def test_short_bc_training_rejected_before_unusable_contribution(self):
        with self.assertRaisesRegex(ValueError, '至少需要 2'):
            biz.validated_config({'mode':'bc_marl','n_episodes':1})
        self.assertEqual(biz.validated_config({'mode':'pure_marl','n_episodes':1})['n_episodes'],1)

    def test_current_user_cannot_fall_back_to_other_account_archive(self):
        with patch.object(dash,'_latest_completed_training',return_value=None) as latest, \
             patch.object(dash,'_load_result_file',side_effect=AssertionError('archived leak')):
            result=dash._training_result('bc_marl',user_id=self.uid)
        self.assertIsNone(result)
        latest.assert_called_once_with('bc_marl',user_id=self.uid)

if __name__=='__main__':unittest.main()
