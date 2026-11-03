"""Invariant regression tests for V12 (no additional protocol features)."""
import json
import unittest
from unittest.mock import patch
from tests.test_v11_epoch_view import ConsensusV11
from visualization import distributed_consensus as dc

class ConsensusV12(ConsensusV11):
    def test_commit_receipt_must_match_real_node_and_block(self):
        self.start()
        actual=dc.request
        def misleading(peer,path,payload=None,timeout=1.7):
            result=actual(peer,path,payload,timeout)
            if path=='/commit' and peer['id']=='node-3':
                return {'node':'node-3','height':999,'hash':'0'*64}
            return result
        with patch.object(dc,'request',side_effect=misleading):
            result=dc.propose(self.tx('receipt-check'))
        self.assertEqual(result['status'],'partially_replicated')
        self.assertEqual(len(result['commits']),2)
        self.assertTrue(dc.cross_verify(1)['consistent'])

    def test_conflicting_durable_vote_rejects_commit(self):
        self.start()
        cfg=dc.init_network();p={'network':cfg['network'],'height':1,'previous':'0'*64,'transaction':self.tx('other'), 'snapshot':dc.snapshot_digest(cfg),'phase':'PREPARE'}
        dc.request(cfg['peers'][0],'/prepare',{'proposal':p})
        res=dc.propose(self.tx('different'))
        self.assertNotEqual(res['status'],'replicated')
        self.assertEqual(res['status'],'quorum_failed')
        self.assertEqual(dc.statuses()['nodes'][0]['height'],0)

    def test_invalid_certificate_and_view_structures(self):
        cfg=dc.init_network();p={'network':cfg['network'],'height':1,'previous':'0'*64,'transaction':self.tx('x'),'snapshot':dc.snapshot_digest(cfg),'phase':'PREPARE'}
        self.assertFalse(dc.certificate_valid(cfg,p,{'proposal_hash':dc.digest(p),'votes':[None]}))
        self.assertFalse(dc.view_cert_valid(cfg,p,{'view':1,'votes':[None]}))
        self.assertFalse(dc.certificate_valid(cfg,p,{'proposal_hash':dc.digest(p),'view':1,'votes':[]}))

    def test_recovery_detects_same_height_fork(self):
        self.start()
        cfg=dc.init_network()
        with patch.object(dc,'request',side_effect=lambda peer,path,payload=None,timeout=1.7: {'height':1,'hash': ('a'*64 if peer['id']=='node-1' else 'b'*64)} if path=='/status' else {}):
            with self.assertRaisesRegex(ValueError,'divergent history'):
                dc.recover_node(cfg['peers'][0],cfg['peers'])

if __name__=='__main__':unittest.main()
