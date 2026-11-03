"""V22 task-centric evidence lifecycle; synthetic BC-MARL training fixtures."""
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from tests import test_v21_collaboration as fixture
from visualization import collaboration_lifecycle as life
from visualization import collaboration_service as cs
from visualization import distributed_consensus as dc
from visualization import business_service as biz

ROOT = Path(__file__).resolve().parents[1]


class TestTaskEvidenceLifecycle(unittest.TestCase):
    setUp = fixture.CollaborationLinkTest.setUp
    tearDown = fixture.CollaborationLinkTest.tearDown

    def test_task_before_epoch_and_account_isolation(self):
        status=life.task_lifecycle(self.uid,self.jid)
        self.assertEqual([x['done'] for x in status['stages']], [True,True,False,False,False])
        self.assertEqual(status['training']['episodes'],3)
        with self.assertRaises(ValueError):
            life.task_lifecycle(self.uid+1,self.jid)

    def test_epoch_without_commit(self):
        cfg=cs.candidate(self.uid,self.jid)
        dc.activate_snapshot(cfg)
        status=life.task_lifecycle(self.uid,self.jid)
        self.assertEqual([x['done'] for x in status['stages']], [True,True,True,False,False])
        self.assertTrue(status['epoch']['active_for_job'])
        self.assertEqual(len(status['epoch']['weights']),3)

    def test_three_nodes_attested_and_traced(self):
        candidate=cs.candidate(self.uid,self.jid)
        dc.activate_snapshot(candidate)
        cfg=dc.init_network()
        for peer in cfg['peers']:
            script=("import sys; from pathlib import Path; "
                   f"sys.path.insert(0,{str(ROOT)!r}); "
                   "from visualization import distributed_consensus as d; "
                   f"d.BASE=Path({str(dc.BASE)!r}); d.CONFIG=d.BASE/'network.json'; d.HISTORY=d.BASE/'epochs'; "
                   f"d.serve({peer['id']!r})")
            self.children.append(subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for _ in range(75):
            if all(node.get('online') for node in dc.statuses()['nodes']):
                break
            time.sleep(.1)
        else:
            self.fail('test peers not online')
        event=cs.attest_event(cfg,self.uid)
        tx=biz.sign_distributed(self.uid,json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(',',':')))
        result=dc.propose(tx,timeout=.8,max_views=2)
        self.assertEqual(result['status'],'replicated')
        state=life.task_lifecycle(self.uid,self.jid)
        self.assertEqual([x['done'] for x in state['stages']], [True]*5)
        self.assertEqual(state['chain']['records'][0]['height'],result['block_height'])
        self.assertTrue(state['chain']['latest_verification']['verified'])
        self.assertEqual(len(life._committed_blocks(dc.init_network(),self.uid,self.jid)),1)
        # A later local file modification cannot alter the historical vote certificate.
        self.contrib_path.write_text(self.contrib_path.read_text(encoding='utf8')+' ',encoding='utf8')
        altered=life.task_lifecycle(self.uid,self.jid)
        self.assertFalse(altered['epoch']['verified_against_source'])
        self.assertFalse(altered['chain']['latest_verification']['verified'])


if __name__ == '__main__':
    unittest.main()
