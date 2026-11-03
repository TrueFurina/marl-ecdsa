"""V26 read-only audit index: never infer cross-node confirmation from local index."""
import unittest
from unittest.mock import patch
from visualization import collaboration_lifecycle as lc


class TestAuditPortfolio(unittest.TestCase):
    def setUp(self):
        self.uid='owner-a'
        self.good={'job_id':'a'*32,'eligible':True,'algorithm':'iql','episodes':30}
        self.bad={'job_id':'b'*32,'eligible':False,'reason':'缺少贡献记录'}
        self.active={'network':'testnet','version':4,'training_proof':{
            'training_binding':{'owner_user_id':self.uid,'job_id':self.good['job_id']}}}
        self.old={'network':'testnet','version':3,'training_proof':{
            'training_binding':{'owner_user_id':'other','job_id':self.good['job_id']}}}

    def test_index_uses_only_own_epoch_and_marks_local_evidence(self):
        with patch.object(lc.cs,'jobs',return_value={'jobs':[self.good,self.bad]}) as jobs, \
             patch.object(lc.dc,'init_network',return_value=self.active), \
             patch.object(lc,'_all_epochs',return_value=[self.active,self.old]), \
             patch.object(lc,'_committed_blocks',side_effect=lambda current,uid,jid,limit=150:[{'height':2,'txid':'f'*64}] if jid==self.good['job_id'] else []) as blocks:
            r=lc.audit_portfolio(self.uid)
        jobs.assert_called_once_with(self.uid)
        self.assertEqual(blocks.call_count,2)
        self.assertEqual(r['summary'],{'eligible':1,'with_epochs':1,'with_signed_records':1})
        self.assertEqual(r['tasks'][0]['epoch_versions'],[4])
        self.assertIn('待在线独立核验',r['tasks'][0]['status'])
        self.assertFalse(r['tasks'][1]['eligible'])
        self.assertEqual(r['tasks'][1]['records'],[])

    def test_corrupt_source_retains_existing_signed_evidence_for_audit(self):
        with patch.object(lc.cs,'jobs',return_value={'jobs':[self.bad]}), \
             patch.object(lc.dc,'init_network',return_value=self.active), \
             patch.object(lc,'_all_epochs',return_value=[self.active]), \
             patch.object(lc,'_committed_blocks',return_value=[{'height':7,'txid':'a'*64}]):
            r=lc.audit_portfolio(self.uid)
        self.assertFalse(r['tasks'][0]['eligible'])
        self.assertEqual(r['tasks'][0]['records'][0]['height'],7)
        self.assertIn('历史签名证据',r['tasks'][0]['status'])
        self.assertEqual(r['summary']['with_signed_records'],1)

    def test_empty_index_is_explicit_not_sample_data(self):
        with patch.object(lc.cs,'jobs',return_value={'jobs':[]}), \
             patch.object(lc.dc,'init_network',return_value=self.active), \
             patch.object(lc,'_all_epochs',return_value=[self.active]):
            data=lc.audit_portfolio(self.uid)
        self.assertEqual(data['tasks'],[])
        self.assertEqual(data['summary']['with_signed_records'],0)


if __name__=='__main__':unittest.main()
