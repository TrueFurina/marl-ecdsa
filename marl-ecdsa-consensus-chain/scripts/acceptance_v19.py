"""V19 browser/API acceptance smoke tests. Run in an isolated COPY of the source_code directory.
Usage: python scripts/acceptance_v19.py
Writes results/v19_acceptance.json. NEVER use against production data.
"""
import json, os, pathlib, secrets, sys, traceback, importlib.util
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
checks=[]
def record(name,ok,details=''):
 checks.append({'name':name,'status':'PASS' if ok else 'FAIL','details':str(details)[:400]})
 print(('[PASS] ' if ok else '[FAIL] ')+name+(' '+str(details)[:160] if details else ''))

def main():
 for name in ('flask','cryptography','numpy','torch','matplotlib','requests'):
  found=importlib.util.find_spec(name) is not None
  record('dependency:'+name,found,'installed' if found else 'missing')
 if not importlib.util.find_spec('flask'):
  return
 try:
  from visualization.dashboard import _create_app
  app=_create_app()
  if app is None: raise RuntimeError('app factory returned None')
  app.config['TESTING']=True
  client=app.test_client()
  res=client.get('/api/me')
  record('anonymous API protected',res.status_code==401,res.status_code)
  res=client.get('/')
  record('anonymous dashboard redirects',res.status_code in (301,302,303),res.status_code)
  username='accept_'+secrets.token_hex(5)
  password=secrets.token_urlsafe(18)+'A1'
  with client.session_transaction() as s:
   csrf=secrets.token_urlsafe(32);s['_csrf']=csrf
  r=client.post('/register',data={'username':username,'password':password,'confirm':password,'csrf_token':csrf})
  record('register',r.status_code in (301,302,303),r.status_code)
  with client.session_transaction() as s:
   csrf=s.get('_csrf') or secrets.token_urlsafe(32);s['_csrf']=csrf
  r=client.post('/login',data={'username':username,'password':password,'csrf_token':csrf})
  record('login',r.status_code in (301,302,303),r.status_code)
  with client.session_transaction() as s: token=s.get('_csrf','');authenticated=bool(s.get('uid'))
  record('authenticated session',authenticated)
  if not authenticated:return
  for endpoint in ('/','/api/me','/api/business/train/jobs','/api/business/transactions','/api/business/chain/audit','/api/business/chain/blocks','/api/distributed/nodes','/api/distributed/snapshot','/api/distributed/epochs'):
   try:
    r=client.get(endpoint)
    record('GET '+endpoint,r.status_code==200,r.status_code)
   except Exception as e:record('GET '+endpoint,False,repr(e))
  r=client.post('/api/business/transactions',json={'content':{'acceptance_test':True}})
  record('POST without CSRF rejected',r.status_code==403,r.status_code)
  try:
   r=client.post('/api/business/transactions',json={'content':{'acceptance_test':True,'nonce':secrets.token_hex(8)}},headers={'X-CSRF-Token':token})
   body=r.get_json(silent=True) or {}
   record('signed local transaction',r.status_code==201,str(body)[:250])
   txid=body.get('txid') or body.get('transaction_id')
   if txid:
    q=client.get('/api/business/transactions/'+txid)
    record('local transaction lookup',q.status_code==200,q.status_code)
    receipt=client.get('/api/business/chain/receipt/'+txid)
    record('local receipt lookup',receipt.status_code==200,receipt.status_code)
  except Exception as e:record('signed local transaction',False,repr(e))
  try:
   r=client.post('/api/p2p/probe',json={'ports':[1]},headers={'X-CSRF-Token':token})
   record('local TCP probe',r.status_code==200,str(r.get_json(silent=True))[:200])
  except Exception as e:record('local TCP probe',False,repr(e))
  try:
   r=client.get('/api/business/train/jobs')
   record('train job list',r.status_code==200,r.status_code)
  except Exception as e:record('train job list',False,repr(e))
  r=client.post('/logout',data={'csrf_token':token})
  record('logout',r.status_code in (301,302,303),r.status_code)
  record('logged out API blocked',client.get('/api/me').status_code==401)
 except Exception as exc:
  record('acceptance harness fatal error',False,repr(exc))
  traceback.print_exc()

if __name__=='__main__':
 try:main()
 finally:
  out=ROOT/'results'/'v19_acceptance.json';out.parent.mkdir(exist_ok=True)
  out.write_text(json.dumps({'executed_in':'local_install','checks':checks,'passed':sum(c['status']=='PASS' for c in checks),'failed':sum(c['status']=='FAIL' for c in checks)},ensure_ascii=False,indent=2),encoding='utf-8')
  print('Report:',out)
  if any(c['status']=='FAIL' for c in checks):sys.exit(1)
