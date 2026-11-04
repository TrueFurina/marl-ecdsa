"""Run: python -m unittest tests.test_v11_epoch_view"""
import unittest,tempfile,subprocess,time,sys,os,json
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import ec
from visualization import distributed_consensus as dc

def isolate_consensus_ports(cfg):
 """把 init_network() 硬编码的 17401–17403 换成本机空闲端口（测试专用）。

 dc.serve() 从 network.json 读端口；多个测试会话（或本机已在跑的产品节点）并发时
 会争抢同一批固定端口 → 节点起不来，用例以 'nodes unavailable' / '至少需要两个在线
 节点' / sqlite 被占用 等形式假失败，与被测共识逻辑无关（2026-11-03 实测：同机另一
 会话跑同一批用例即稳定触发）。端口不参与 snapshot_digest（只含 id/public_key/weight），
 故所有断言结果不变。
 """
 import socket
 for peer in cfg['peers']:
  with socket.socket() as s:
   s.bind(('127.0.0.1',0));peer['port']=s.getsockname()[1]
 dc.CONFIG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
 return cfg

class _ConsensusHarness:
 """节点生命周期与提案构造夹具。**刻意不继承 unittest.TestCase**。

 pytest 收集规则：`python_classes` 的 `Test*` 前缀过滤只作用于普通类，
 `unittest.TestCase` 子类**无条件收集**。所以「继承 TestCase 的夹具基类」
 一旦被别的模块 import，就会在那个模块里再收集一遍。

 2026-11-04 实测的代价：test_v12_consensus_invariants.py 既 `import ConsensusV11`
 （模块命名空间里被收集）又 `class ConsensusV12(ConsensusV11)`（继承再收集），
 结果是 4 条用例各跑 3 遍 —— 60s + 60s 纯重复，占整套 ~120s（21.6%），
 而 dc 是无状态模块、setUp 每次新建临时目录，重复执行零新增覆盖。

 夹具不持有断言，子类各自补自己的用例；这样跨模块复用夹具不再附带执行。
 """
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
  self.original=(dc.BASE,dc.CONFIG,dc.HISTORY)
  dc.BASE=self.base;dc.CONFIG=self.base/'network.json';dc.HISTORY=self.base/'epochs'
  self.cfg=isolate_consensus_ports(dc.init_network());self.ps=[]
 def tearDown(self):
  self.stop();dc.BASE,dc.CONFIG,dc.HISTORY=self.original;self.tmp.cleanup()
 def start(self,names=('node-1','node-2','node-3')):
  # 2026-11-03 flaky 根治：全量负载下 3 个子进程节点 45×0.08s≈3.6s 启动预算不够
  #（实测「至少需要两个在线节点」×6），放宽到 150×0.08s≈12s；启动前先清残留会话。
  self.stop()
  root=str(Path(__file__).resolve().parents[1]);path=str(self.base)
  for n in names:
   code=f'import sys;sys.path.insert(0,{root!r});from pathlib import Path;from visualization import distributed_consensus as d;d.BASE=Path({path!r});d.CONFIG=d.BASE/"network.json";d.HISTORY=d.BASE/"epochs";d.serve({n!r})'
   proc=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   self.ps.append(proc)
  for _ in range(150):
   if sum(x.get('online',False) for x in dc.statuses()['nodes'])>=len(names):return
   time.sleep(.08)
  raise AssertionError('nodes unavailable '+str(dc.statuses()))
 def stop(self):
  for p in self.ps:
   if p.poll() is None:p.terminate()
  for p in self.ps:
   try:p.wait(timeout=2)
   except subprocess.TimeoutExpired:p.kill()
  self.ps=[]
  # 2026-11-03 flaky 根治：等子进程节点真正下线再返回——否则下一个测试的
  # activate_snapshot 会被残留在线节点误拦（实测 "stop all nodes before
  # epoch activation" 误报 ×2），propose 也会数到僵尸节点。
  for _ in range(60):
   try:
    if not any(x.get('online') for x in dc.statuses()['nodes']):return
   except Exception:return
   time.sleep(.08)
 def tx(self,text):
  key=ec.generate_private_key(ec.SECP256R1());pl={'content':text}
  return {'payload':pl,'txid':dc.digest(pl),'public_key':dc.pubkey(key),'signature':dc.sign(key,pl)}
 def candidate(self):
  return {'weights':[3333,3333,3333], 'origin':'verified-training.json','origin_sha256':'e'*64,'episodes':3,'source':'training_contribution_share_clipped_20pct_floor_bft_third_cap','agent_mapping':[{'agent':str(i),'node':f'node-{i+1}','weight':w} for i,w in enumerate([3333,3333,3333])]}

class ConsensusV11(_ConsensusHarness,unittest.TestCase):
 def test_epoch_reconfiguration_old_certificate(self):
  self.start();r=dc.propose(self.tx('epoch0'));self.assertEqual(r['status'],'replicated');self.assertTrue(dc.cross_verify(1)['consistent']);self.stop()
  snap=dc.activate_snapshot(self.candidate());self.assertEqual(snap['version'],2)
  self.start();r=dc.propose(self.tx('epoch1'));self.assertEqual(r['status'],'replicated');self.assertTrue(dc.cross_verify(1)['consistent']);self.assertTrue(dc.cross_verify(2)['consistent'])
  self.assertEqual(dc.epoch_status()['epoch_count'],2)
 def test_conflicting_pending_vote_blocks_transition(self):
  with dc.db_for('node-1') as db:db.execute('INSERT INTO votes VALUES (?,?,?)',('x','{}','abc'))
  with self.assertRaisesRegex(ValueError,'uncommitted votes'):dc.activate_snapshot(self.candidate())
 def test_signed_view_change_and_retry(self):
  self.start();cfg=dc.init_network();real=dc.request;attempt=[0]
  def delayed(peer,path,payload=None,timeout=1.7):
   if path=='/prepare' and attempt[0]<3:
    attempt[0]+=1;raise TimeoutError('injected coordinator timeout')
   return real(peer,path,payload,timeout)
  with patch.object(dc,'request',side_effect=delayed):r=dc.propose(self.tx('retry'),max_views=3,timeout=.25)
  self.assertEqual(r['status'],'replicated',r)
  self.assertTrue(any(e['phase']=='VIEW-CHANGE' for e in r['events']))
  self.assertTrue(dc.cross_verify(1)['consistent'])
 def test_view_certificate_tamper(self):
  self.start();cfg=dc.init_network();p={'network':cfg['network'],'height':1,'previous':'0'*64,'transaction':self.tx('proof'),'snapshot':dc.snapshot_digest(cfg),'phase':'PREPARE'}
  votes=[dc.request(n,'/view-change',{'proposal':p,'view':1}) for n in cfg['peers']]
  c={'view':1,'votes':votes};self.assertTrue(dc.view_cert_valid(cfg,p,c))
  c['votes'][0]['signature']='00';self.assertFalse(dc.view_cert_valid(cfg,p,c))

if __name__=='__main__':unittest.main()
