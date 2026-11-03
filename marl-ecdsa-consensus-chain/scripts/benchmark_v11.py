"""Short reproducible local integration benchmark, NOT a security proof.
Run from source_code: python scripts/benchmark_v11.py
Requires actual train.py contribution logs in results/contribution.
"""
import json,sys,time,tempfile,subprocess,statistics,hashlib
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from visualization import distributed_consensus as dc

def scenario(file,variant):
 with tempfile.TemporaryDirectory() as td:
  orig=(dc.BASE,dc.CONFIG,dc.HISTORY);dc.BASE=Path(td);dc.CONFIG=dc.BASE/'network.json';dc.HISTORY=dc.BASE/'epochs'
  procs=[]
  def start(names):
   for name in names:
    script=f'import sys;sys.path.insert(0,{str(ROOT)!r});from pathlib import Path;from visualization import distributed_consensus as m;m.BASE=Path({td!r});m.CONFIG=m.BASE/"network.json";m.HISTORY=m.BASE/"epochs";m.serve({name!r})'
    procs.append((name,subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)))
   for _ in range(70):
    if sum(bool(x.get('online')) for x in dc.statuses()['nodes'])>=len(names):break
    time.sleep(.06)
   else:raise RuntimeError('nodes failed to start')
  def stop():
   for _,p in procs:
    if p.poll() is None:p.terminate()
   for _,p in procs:
    try:p.wait(timeout=2)
    except subprocess.TimeoutExpired:p.kill()
   procs.clear()
  def tx(content):
   k=ec.generate_private_key(ec.SECP256R1());payload={'content':content}
   return {'payload':payload,'txid':dc.digest(payload),'public_key':dc.pubkey(k),'signature':dc.sign(k,payload)}
  try:
   dc.init_network();snap=dc.build_contribution_snapshot(file,window=12)
   if variant=='contribution':dc.activate_snapshot(snap)
   start(['node-1','node-2','node-3'])
   durations=[];blocks=[]
   for i in range(5):
    began=time.perf_counter();r=dc.propose(tx('trial-%s-%s-%s'%(file.stem,variant,i)),timeout=.3);durations.append((time.perf_counter()-began)*1000)
    assert r['status']=='replicated',r
    blocks.append(bool(dc.cross_verify(i+1)['consistent']))
   # Fault tolerance means node-3 can be absent only if remaining weighted quorum meets threshold.
   for name,p in procs:
    if name=='node-3':p.terminate();p.wait(timeout=2)
   began=time.perf_counter();fault=dc.propose(tx('fault-%s-%s'%(file.stem,variant)),timeout=.3,max_views=2)
   fault_ms=(time.perf_counter()-began)*1000
   stop();start(['node-1','node-2','node-3'])
   recovery=dc.recover_node(dc.init_network()['peers'][2],dc.init_network()['peers'])
   consistent=dc.cross_verify(6)['consistent'] if fault.get('status') in ('replicated','partially_replicated') else None
   return {'file':file.name,'training_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'variant':variant,'weights':dc.latest_snapshot()['peers'],'latency_ms':{'median':round(statistics.median(durations),2),'p95_observed':round(sorted(durations)[-1],2)},'normal_commits':len(blocks),'normal_consistent':all(blocks),'fault_status':fault.get('status'),'fault_ms':round(fault_ms,2),'recovery':recovery,'fault_height_consistent':consistent,'sample_count':5,'fault_count':1}
  finally:stop();dc.BASE,dc.CONFIG,dc.HISTORY=orig

def main():
 files=sorted((ROOT/'results/contribution').glob('contribution_log_v11_train_seed*.json'))
 by_seed={}
 for f in files:
  # take latest file per seed, consistent 12 episodes
  k=f.stem.split('seed')[-1].split('_')[0]
  if len(json.loads(f.read_text())['records'])==12:by_seed[k]=f
 if len(by_seed)<3:raise SystemExit('Need three real 12-episode seed files. See README.')
 results=[]
 for seed,f in sorted(by_seed.items()):
  for variant in ('static','contribution'):
   item=scenario(f,variant);item['seed']=int(seed);results.append(item)
   print(seed,variant,item['latency_ms'],item['fault_status'],flush=True)
 out=ROOT/'results'/'v11_benchmark.json';out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps({'scope':'3 independent local-loopback HTTP processes; 12-episode training per seed; NOT full Byzantine safety or network benchmark','results':results},ensure_ascii=False,indent=2),encoding='utf-8')
 print('Saved',out)
if __name__=='__main__':main()
