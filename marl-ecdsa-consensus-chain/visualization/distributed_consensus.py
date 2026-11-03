"""Local multi-process weighted ECDSA quorum prototype.
Not a production Byzantine-fault-tolerant or CW-PBFT implementation.
Each node is an independent HTTP process and stores a separate journal.
"""
import json,hashlib,os,sys,time,sqlite3,threading,urllib.request,urllib.error,math,random
from pathlib import Path
from contextlib import contextmanager
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))
# F10：节点私钥与 KeyManager 同款加密落盘（读写共用跨重启稳定口令）
from blockchain.crypto.ecdsa_utils import ECDSAUtils, resolve_key_passphrase

BASE=Path(__file__).resolve().parent.parent/'instance'/'quorum_v9'
CONFIG=BASE/'network.json'
HISTORY=BASE/'epochs'
MUTEX=threading.RLock()
def canonical(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def digest(o):return hashlib.sha256(canonical(o)).hexdigest()
def pubkey(key):return key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
def sign(key,obj):return key.sign(canonical(obj),ec.ECDSA(hashes.SHA256())).hex()
def verify(pub,obj,sig):
    try:
        serialization.load_pem_public_key(pub.encode()).verify(bytes.fromhex(sig),canonical(obj),ec.ECDSA(hashes.SHA256()))
        return True
    except (ValueError,TypeError,InvalidSignature,KeyError):return False

# ── F03（2026-11-02 赛后）：BFT 加权 quorum 的权重集中度上限 ──
# 安全论证：两个 >2/3 权重 quorum 的交集权重 **严格大于** 1/3 总权重。
# 只要任一单节点权重 ≤ 总权重/3（f=1 恶意模型下的恶意总权重上界），
# 交集必含诚实节点 ⇒ 恶意节点无法仅凭自身权重对两个冲突提案各凑一张
# 有效 PREPARE 证书（[8667,667,667] 型双签分叉被阻断）。
# 推论（n=3）：cap=total//3 且 sum=total ⇒ 唯一可行解是三分均一，
# quorum 实际退化为"全 3 节点一致"；贡献度差异化赋权需要 ≥4 节点
# （登记为设计边界，见 版本对照表 §八 R3）。
BFT_WEIGHT_TOTAL=9999
def _bft_cap_weights(raw):
    """按贡献比例缩放到 BFT_WEIGHT_TOTAL，并瀑布重分保证任一单节点 ≤ total//3。"""
    cap=BFT_WEIGHT_TOTAL//3
    s=sum(raw) or 1
    w=[max(1,int(round(x*BFT_WEIGHT_TOTAL/s))) for x in raw]
    w[max(range(len(w)),key=lambda i:raw[i])]+=BFT_WEIGHT_TOTAL-sum(w)  # 舍入尾差记到贡献最大者
    for _ in range(len(w)+8):
        over=sum(x-cap for x in w if x>cap)
        if not over:break
        w=[min(x,cap) for x in w]
        room=[cap-x for x in w];rt=sum(room)
        if rt<=0:break
        w=[x+min(r,(over*r+rt-1)//rt) for x,r in zip(w,room)]
    assert sum(w)==BFT_WEIGHT_TOTAL and max(w)<=cap, 'F03 cap 不动点失败'
    return w

def validate_weight_cap(weights):
    """F03 fail-closed 校验：任一单节点权重必须 ≤ 总权重/3，激活前强制。"""
    ws=[int(x) for x in weights]
    if not ws or any(x<1 for x in ws):raise ValueError('weight cap: invalid weights')
    total=sum(ws)
    if max(ws)*3>total:
        raise ValueError(f'weight cap violated: max={max(ws)} > total/3={total//3} —— '
                         '恶意单节点权重超 1/3 时无法排除双签分叉证书（F03）')
    return ws

def init_network():
    BASE.mkdir(parents=True,exist_ok=True)
    if CONFIG.exists():return json.loads(CONFIG.read_text())
    peers=[]
    # F03：静态开发配置同步收紧为 [3,3,3]（总 9，任一节点 = 总/3；旧 [4,3,3] 下
    # node-1 40% 可在 {1,2}/{1,3} 两张证书上双签分叉）。已部署的既有 CONFIG 不变，
    # 历史纪元按旧配置审计不受影响。
    for i,(name,port,weight) in enumerate([('node-1',17401,3),('node-2',17402,3),('node-3',17403,3)]):
        key=ec.generate_private_key(ec.SECP256R1())
        path=BASE/(name+'.pem');path.write_bytes(ECDSAUtils.private_key_to_bytes(key, resolve_key_passphrase()))  # F10：加密落盘
        try:os.chmod(path,0o600)
        except OSError:pass
        peers.append(dict(id=name,host='127.0.0.1',port=port,weight=weight,public_key=pubkey(key)))
    cfg={'version':1,'network':'local-dev-v9','weight_source':'static_development_configuration_not_marl','peers':peers}
    CONFIG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    return cfg

def request(peer,path,payload=None,timeout=1.7):
    url=f"http://127.0.0.1:{peer['port']}{path}"
    req=urllib.request.Request(url,data=canonical(payload) if payload is not None else None,headers={'Content-Type':'application/json'},method='POST' if payload is not None else 'GET')
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)

def snapshot_digest(cfg):
    payload={'network':cfg['network'],'version':cfg.get('version',1),
             'peers':[(n['id'],n['public_key'],n['weight']) for n in cfg['peers']]}
    # V21: also commit to the training provenance, not just the numeric weights.
    # Legacy epochs (which lack a job binding) keep their original digest unchanged.
    proof=cfg.get('training_proof')
    if isinstance(proof,dict) and proof.get('training_binding'):
        payload['training_proof_sha256']=digest(proof)
    return digest(payload)

def _store_epoch(cfg):
    HISTORY.mkdir(parents=True,exist_ok=True)
    fp=HISTORY/(snapshot_digest(cfg)+'.json')
    if fp.exists():
        if json.loads(fp.read_text(encoding='utf-8')) != cfg:raise ValueError('epoch archive changed')
    else:
        tmp=fp.with_suffix('.tmp')
        tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,fp)

def epoch_for_proposal(p,default_cfg=None):
    cfg=default_cfg or init_network()
    if p.get('snapshot')==snapshot_digest(cfg):return cfg
    snap=p.get('snapshot','')
    if not isinstance(snap,str) or len(snap)!=64 or any(c not in '0123456789abcdef' for c in snap):raise ValueError('bad snapshot')
    fp=HISTORY/(snap+'.json')
    if not fp.is_file():raise ValueError('unknown historic epoch')
    old=json.loads(fp.read_text(encoding='utf-8'))
    if snapshot_digest(old)!=snap or old['network']!=cfg['network']:raise ValueError('untrusted epoch archive')
    return old

def epoch_status():
    cfg=init_network()
    history=sorted(HISTORY.glob('*.json')) if HISTORY.is_dir() else []
    return {'current':latest_snapshot(),'archived_epochs':[p.stem for p in history], 'epoch_count':len(history)+1}

def view_message(height,previous,proposal_hash,view,snapshot):
    return {'action':'VIEW-CHANGE','height':height,'previous':previous,'proposal_hash':proposal_hash,'view':view,'snapshot':snapshot}

def view_cert_valid(cfg,p,cert):
    if not isinstance(cert,dict):return False
    view=cert.get('view',0)
    if not isinstance(view,int) or view<1:return False
    msg=view_message(p['height'],p['previous'],digest(p),view,p['snapshot'])
    by_id={n['id']:n for n in cfg['peers']};seen=set();weight=0
    if not isinstance(cert.get('votes'),list):return False
    for v in cert['votes']:
        if not isinstance(v,dict):return False
        node=v.get('node')
        if node in seen or node not in by_id or not verify(by_id[node]['public_key'],msg,v.get('signature','')):return False
        seen.add(node);weight+=by_id[node]['weight']
    return len(seen)>=2 and weight*3>sum(n['weight'] for n in cfg['peers'])*2

def quorum(cfg,votes):
    approved={v['node'] for v in votes}
    total=sum(n['weight'] for n in cfg['peers'])
    return len(approved)>=2 and sum(n['weight'] for n in cfg['peers'] if n['id'] in approved)*3>2*total

def latest_snapshot():
    cfg=init_network()
    return {'version':cfg.get('version',1),'hash':snapshot_digest(cfg),'weight_source':cfg['weight_source'],'peers':[{'node':x['id'],'weight':x['weight']} for x in cfg['peers']]}

def build_contribution_snapshot(file_path,window=20):
    """Compute proposed snapshot, not activated until explicit operator action.
    IDs from trainer may be strings or numbers; exact node mapping by agent order.
    """
    root=(Path(__file__).resolve().parent.parent/'results'/'contribution').resolve()
    target=Path(file_path).resolve()
    try:
        target.relative_to(root)  # Python 3.8 compatible; retains traversal/symlink protection.
    except ValueError:
        raise ValueError('只允许使用 results/contribution 下的训练贡献记录')
    if not target.is_file() or target.suffix != '.json':
        raise ValueError('贡献记录不存在或不是 JSON 文件')
    obj=json.loads(target.read_text(encoding='utf-8'))
    ids=obj.get('agent_ids',[]); rec=obj.get('records',[])
    if len(ids)!=3 or len(rec)<2:raise ValueError('需要至少 2 回合、恰好 3 个智能体的贡献记录')
    rec=rec[-max(2,min(int(window),200)):]
    means=[0.,0.,0.]
    for row in rec:
        shares=row.get('contribution_share')
        if not isinstance(shares,list) or len(shares)!=3 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in shares):raise ValueError('记录包含无效贡献份额')
        positive=[max(0.,float(x)) for x in shares]; total=sum(positive)
        if total<=0:raise ValueError('贡献份额不能全部非正')
        for i,x in enumerate(positive):means[i]+=x/total/len(rec)
    # 20% floor ensures one temporarily weak learner cannot get zero votes.
    raw=[0.2/3+0.8*x for x in means]
    weights=_bft_cap_weights(raw)  # F03：缩放 + 单节点 ≤ total//3 上限（n=3 时退化为均一/unanimity）
    cfg=init_network()
    return {'origin':str(target.relative_to(root)),'origin_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'episodes':len(rec),'agent_mapping':[{'agent':str(ids[i]),'node':cfg['peers'][i]['id'],'weight':weights[i]} for i in range(3)],
            'source':'training_contribution_share_clipped_20pct_floor_bft_third_cap','weights':weights}

def activate_snapshot(candidate):
    """Offline epoch transition; all replicas must agree on height/hash and have no uncommitted votes."""
    with MUTEX:
        cfg=init_network()
        mapping=candidate.get('agent_mapping',[])
        if len(mapping)!=len(cfg['peers']) or len(candidate.get('weights',[]))!=len(cfg['peers']):raise ValueError('invalid mapping')
        if any(mapping[i].get('node')!=p['id'] or int(candidate['weights'][i])<1 or int(mapping[i]['weight'])!=int(candidate['weights'][i]) for i,p in enumerate(cfg['peers'])):raise ValueError('invalid candidate')
        validate_weight_cap(candidate['weights'])  # F03：激活前强制单节点 ≤ 总权重/3（fail-closed）
        if any(x.get('online') for x in statuses()['nodes']):raise ValueError('stop all nodes before epoch activation')
        heads=[]
        for n in cfg['peers']:
            with db_for(n['id']) as db:
                tip=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
                heads.append((tip['height'],tip['hash']) if tip else (0,'0'*64))
                dangling=db.execute('SELECT count(*) FROM votes v WHERE NOT EXISTS (SELECT 1 FROM blocks b WHERE b.txid=v.txid)').fetchone()[0]
                if dangling:raise ValueError('uncommitted votes exist; resolve or reset pending round first')
        if len(set(heads))!=1:raise ValueError('replicas differ; recover and verify before epoch activation')
        # Check all existing blocks against epoch archives before changing current config.
        for n in cfg['peers']:
            with db_for(n['id']) as db:
                prev='0'*64
                for b in db.execute('SELECT * FROM blocks ORDER BY height'):
                    proposal=json.loads(b['proposal']);cert=json.loads(b['certificate'])
                    oldcfg=epoch_for_proposal(proposal,cfg)
                    if proposal['height']!=b['height'] or proposal['previous']!=prev or proposal['transaction']['txid']!=b['txid'] or b['previous']!=prev or b['hash']!=block_hash(b['height'],prev,b['txid']) or not certificate_valid(oldcfg,proposal,cert):raise ValueError('historic chain audit failed')
                    prev=b['hash']
        _store_epoch(cfg)
        new=json.loads(json.dumps(cfg))
        for i,n in enumerate(new['peers']):n['weight']=int(candidate['weights'][i])
        new['version']=cfg.get('version',1)+1
        new['weight_source']='training_contribution_share_snapshot'
        new['training_proof']={k:candidate[k] for k in (
            'origin','origin_sha256','episodes','agent_mapping','source',
            'rounds_sha256','training_binding','training_summary',
            'incentive_scores_sha256','incentive_scores') if k in candidate}
        new['activation_height']=heads[0][0]+1
        tmp=CONFIG.with_suffix('.json.tmp');tmp.write_text(json.dumps(new,ensure_ascii=False,indent=2));os.replace(tmp,CONFIG)
        return {**latest_snapshot(),'activation_height':new['activation_height']}

def _db_has_activity(node):
    with db_for(node) as db:
        return any(db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() for table in ('blocks','votes'))

def _db_height(node):
    with db_for(node) as db:
        r=db.execute('SELECT max(height) FROM blocks').fetchone()
        return r[0] or 0

@contextmanager
def db_for(node):
    db=sqlite3.connect(BASE/(node+'.sqlite3'),timeout=4)
    db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS blocks (height INTEGER PRIMARY KEY, hash TEXT NOT NULL, previous TEXT NOT NULL, txid TEXT UNIQUE NOT NULL, proposal TEXT NOT NULL, certificate TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS votes (txid TEXT PRIMARY KEY, proposal TEXT NOT NULL, signature TEXT NOT NULL)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS votes_height_unique ON votes(json_extract(proposal,"$.height"))')
    try:
        with db:
            yield db
    finally:
        db.close()

def proposal_valid(p):
    try:
        body=p['transaction'];pl=body['payload'];txid=body['txid']
        return isinstance(pl,dict) and digest(pl)==txid and verify(body['public_key'],pl,body['signature']) and len(canonical(pl))<=8192
    except (TypeError,KeyError):return False

def block_hash(height,previous,txid):return digest({'height':height,'previous':previous,'txid':txid})

def vote_message(p):return {'snapshot':p['snapshot'],'phase':p['phase'],'network':p['network'],'height':p['height'],'previous':p['previous'],'txid':p['transaction']['txid'],'proposal_hash':digest(p)}
def certificate_valid(cfg,p,cert):
    if not isinstance(cert,dict) or not isinstance(p,dict):return False
    if p.get('network')!=cfg.get('network') or not proposal_valid(p):return False
    if type(p.get('height')) is not int or p['height']<1 or not isinstance(p.get('previous'),str) or len(p['previous'])!=64:return False
    if cert.get('proposal_hash')!=digest(p) or p.get('snapshot')!=snapshot_digest(cfg) or p.get('phase')!='PREPARE':return False
    view=cert.get('view',0)
    if type(view) is not int or view<0:return False
    if view:
        if not view_cert_valid(cfg,p,cert.get('view_certificate')):return False
    elif 'view_certificate' in cert:return False
    trusted={n['id']:n for n in cfg['peers']}
    votes=cert.get('votes',[])
    if not isinstance(votes,list):return False
    seen=set();weight=0
    for v in votes:
        if not isinstance(v,dict):return False
        if v.get('node') in seen or v.get('node') not in trusted:return False
        n=trusted[v['node']];seen.add(v['node'])
        if not verify(n['public_key'],vote_message(p),v.get('signature','')):return False
        weight+=n['weight']
    total=sum(n['weight'] for n in cfg['peers'])
    return len(seen)>=2 and weight*3>total*2

class NodeServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,peer,cfg):
        self.peer=peer;self.cfg=cfg
        self.key=ECDSAUtils.private_key_from_bytes((BASE/(peer['id']+'.pem')).read_bytes(), resolve_key_passphrase())  # F10：解密；旧明文回退兼容
        super().__init__(('127.0.0.1',peer['port']),NodeHandler)

class NodeHandler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,obj,status=200):
        raw=canonical(obj);self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        with MUTEX,db_for(self.server.peer['id']) as db:
            tip=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
            if self.path=='/status':return self.send({'node':self.server.peer['id'],'height':tip['height'] if tip else 0,'hash':tip['hash'] if tip else '0'*64,'snapshot':snapshot_digest(self.server.cfg)})
            if self.path.startswith('/block/'):
                try:h=int(self.path.rsplit('/',1)[-1])
                except ValueError:return self.send({'error':'height'},400)
                row=db.execute('SELECT * FROM blocks WHERE height=?',(h,)).fetchone()
                return self.send(dict(row) if row else {'error':'not found'},200 if row else 404)
            if self.path=='/pending':  # F04：暴露 tip 之上未提交的投票锁（卡死轮次可见化）
                tip_h=tip['height'] if tip else 0
                rows=db.execute('SELECT txid,proposal FROM votes WHERE json_extract(proposal,"$.height")>?',(tip_h,)).fetchall()
                return self.send({'node':self.server.peer['id'],'tip_height':tip_h,
                                  'dangling':[{'txid':r['txid'],'height':json.loads(r['proposal'])['height']} for r in rows]})
        return self.send({'error':'not found'},404)
    def do_POST(self):
        if self.path not in ('/vote','/commit','/prepare','/recover','/view-change','/abort-pending'):return self.send({'error':'not found'},404)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<18000:raise ValueError('size')
            data=json.loads(self.rfile.read(length))
            if self.path=='/abort-pending':  # F04：协调清障——只删 tip 之上未提交锁
                with MUTEX,db_for(self.server.peer['id']) as db:
                    tip=db.execute('SELECT height FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
                    tip_h=tip[0] if tip else 0
                    cur=db.execute('DELETE FROM votes WHERE json_extract(proposal,"$.height")>?',(tip_h,))
                    return self.send({'node':self.server.peer['id'],'aborted_height':tip_h+1,'aborted':cur.rowcount})
            p=data['proposal'];cfg=self.server.cfg
            if p['network']!=cfg['network'] or not proposal_valid(p):raise ValueError('invalid proposal or signature')
            if self.path!='/recover' and p.get('snapshot')!=snapshot_digest(cfg):raise ValueError('wrong active snapshot')
            with MUTEX,db_for(self.server.peer['id']) as db:
                tip=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
                height=tip['height'] if tip else 0;head=tip['hash'] if tip else '0'*64
                if self.path=='/view-change':
                    view=data.get('view')
                    if not isinstance(view,int) or not 1<=view<=32:raise ValueError('view out of bounds')
                    if p['height']!=height+1 or p['previous']!=head:raise ValueError('stale view')
                    locked=db.execute('SELECT proposal FROM votes WHERE json_extract(proposal,"$.height")=?',(p['height'],)).fetchone()
                    if locked and locked['proposal']!=canonical(p).decode():raise ValueError('locked conflicting proposal')
                    msg=view_message(p['height'],p['previous'],digest(p),view,p['snapshot'])
                    return self.send({'node':self.server.peer['id'],'view':view,'signature':sign(self.server.key,msg)})
                if self.path in ('/vote','/prepare'):
                    old=db.execute('SELECT * FROM votes WHERE txid=?',(p['transaction']['txid'],)).fetchone()
                    if old:
                        if old['proposal']!=canonical(p).decode():raise ValueError('conflicting proposal')
                        sig=old['signature']
                    else:
                        if p.get('snapshot')!=snapshot_digest(cfg) or p.get('phase')!='PREPARE':raise ValueError('epoch/phase mismatch')
                        if p['height']!=height+1 or p['previous']!=head:raise ValueError('chain tip mismatch')
                        sig=sign(self.server.key,vote_message(p))
                        db.execute('INSERT INTO votes VALUES (?,?,?)',(p['transaction']['txid'],canonical(p).decode(),sig))
                    return self.send({'node':self.server.peer['id'],'signature':sig})
                cert=data['certificate']
                if not certificate_valid(epoch_for_proposal(p,cfg),p,cert):raise ValueError('invalid weighted quorum certificate')
                txid=p['transaction']['txid']
                exists=db.execute('SELECT * FROM blocks WHERE txid=?',(txid,)).fetchone()
                if exists:
                    if exists['height']!=p['height'] or exists['hash']!=block_hash(p['height'],p['previous'],txid) or exists['proposal']!=canonical(p).decode() or not certificate_valid(epoch_for_proposal(json.loads(exists['proposal']),cfg),json.loads(exists['proposal']),json.loads(exists['certificate'])):
                        raise ValueError('conflicting already committed transaction')
                    return self.send({'node':self.server.peer['id'],'height':exists['height'],'hash':exists['hash'],'already_committed':True})
                if p['height']!=height+1 or p['previous']!=head:raise ValueError('commit chain tip mismatch')
                locked=db.execute('SELECT proposal FROM votes WHERE json_extract(proposal,"$.height")=?',(p['height'],)).fetchone()
                if locked and locked['proposal']!=canonical(p).decode():raise ValueError('commit conflicts with durable vote lock')
                hh=block_hash(p['height'],p['previous'],txid)
                db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?)',(p['height'],hh,p['previous'],txid,canonical(p).decode(),canonical(cert).decode()))
                return self.send({'node':self.server.peer['id'],'height':p['height'],'hash':hh})
        except (ValueError,TypeError,KeyError,json.JSONDecodeError,sqlite3.IntegrityError) as e:return self.send({'error':str(e)},400)

def serve(node):
    cfg=init_network();peer=next((p for p in cfg['peers'] if p['id']==node),None)
    if not peer:raise ValueError('invalid node name')
    server=NodeServer(peer,cfg);print(f'{node} listening on 127.0.0.1:{peer["port"]}',flush=True)
    server.serve_forever()

def statuses():
    cfg=init_network();out=[]
    for n in cfg['peers']:
        try:
            info=request(n,'/status')
            out.append({**info,'weight':n['weight'],'online':True,'epoch_matched':info.get('snapshot')==snapshot_digest(cfg)})
        except Exception:out.append({'node':n['id'],'weight':n['weight'],'online':False})
    return {'network':cfg['network'],'weight_source':cfg['weight_source'],'snapshot':snapshot_digest(cfg),'nodes':out}

def recover_node(peer, peers):
    """Replay committed blocks from any healthy peer; each block is verified before append."""
    cfg=init_network()
    try: local=request(peer,'/status');h=int(local['height'])
    except Exception:return {'node':peer['id'],'recovered':False,'reason':'offline'}
    healthy=[]
    for p in peers:
        if p['id']==peer['id']:continue
        try:
            status=request(p,'/status')
            if status['height']>h:healthy.append((status['height'],p))
        except Exception:pass
    if not healthy:
        for other in peers:
            if other['id']==peer['id']:continue
            try:
                state=request(other,'/status')
                if state['height']==h and state['hash']!=local['hash']:
                    raise ValueError('divergent history at same height; automatic recovery refused')
            except (urllib.error.URLError,TimeoutError,ConnectionError):continue
        return {'node':peer['id'],'recovered':True,'height':h,'replayed':0}
    healthy.sort(key=lambda x:x[0],reverse=True)
    remote=healthy[0][1];replayed=0
    if h:
        local_tip=request(peer,'/block/'+str(h))
        remote_at_tip=request(remote,'/block/'+str(h))
        if local_tip.get('hash')!=remote_at_tip.get('hash'):
            raise ValueError('divergent history at common height; automatic recovery refused')
    for height in range(h+1,healthy[0][0]+1):
        b=request(remote,'/block/'+str(height))
        proposal=json.loads(b['proposal']);cert=json.loads(b['certificate'])
        if not certificate_valid(epoch_for_proposal(proposal,cfg),proposal,cert) or proposal['height']!=height or b['height']!=height or b['previous']!=proposal['previous'] or b['txid']!=proposal['transaction']['txid'] or b['hash']!=block_hash(height,b['previous'],b['txid']):raise ValueError('untrusted recovery block')
        result=request(peer,'/recover',{'proposal':proposal,'certificate':cert})
        if result.get('hash')!=b['hash']:raise ValueError('recovery hash mismatch')
        replayed+=1
    return {'node':peer['id'],'recovered':True,'replayed':replayed,'height':h+replayed}

def propose(signed_tx, max_views=3, timeout=1.0):
    cfg=init_network();peers=cfg['peers'];states=statuses()['nodes']
    online=[x for x in states if x.get('online') and x.get('epoch_matched')]
    if len(online)<2:raise ValueError('至少需要两个在线节点才能形成独立签名的法定票数')
    # A common maximum-height head is required among online peers; repair lagging peers first.
    best=max((x['height'],x['hash']) for x in online)
    healthy=[x for x in online if (x['height'],x['hash'])==best]
    if len({x['hash'] for x in online if x['height']==best[0]})!=1:raise ValueError('最高高度发生分叉，拒绝提交')
    recovered=[]
    for n in peers:
        x=next((s for s in online if s['node']==n['id']),None)
        if x and x['height']<best[0]:recovered.append(recover_node(n,peers))
    states=statuses()['nodes'];heads={(x['height'],x['hash']) for x in states if x.get('online')}
    if len(heads)!=1:raise ValueError('在线节点账本仍不一致，拒绝提交')
    height,previous=heads.pop()
    p={'network':cfg['network'],'height':height+1,'previous':previous,'transaction':signed_tx,'snapshot':snapshot_digest(cfg),'phase':'PREPARE'}
    if not proposal_valid(p):raise ValueError('交易签名无效')
    votes=[];errors=[];events=[{'phase':'PRE-PREPARE','height':p['height'],'proposal_hash':digest(p)}]
    max_views=max(1,min(6,int(max_views)));timeout=max(.15,min(5.,float(timeout)))
    successful_view=0; successful_view_cert=None
    for view in range(max_views):
        votes=[]
        # The proposal hash does not change across retries/views, respecting durable vote locks.
        if view:
            vc_votes=[]
            for n in peers:
                try:
                    receipt=request(n,'/view-change',{'proposal':p,'view':view},timeout=timeout)
                    if receipt.get('node')==n['id']:vc_votes.append(receipt)
                except Exception as e:errors.append('view-change '+n['id']+': '+str(e))
            viewcert={'view':view,'votes':vc_votes}
            if not view_cert_valid(cfg,p,viewcert):
                events.append({'phase':'VIEW-CHANGE-FAILED','view':view});break
            successful_view=view;successful_view_cert=viewcert
            events.append({'phase':'VIEW-CHANGE','view':view,'leader':peers[view%len(peers)]['id'],'signed_votes':len(vc_votes)})
        for n in peers:
            try:
                v=request(n,'/prepare',{'proposal':p},timeout=timeout)
                if v.get('node')==n['id'] and verify(n['public_key'],vote_message(p),v['signature']):votes.append(v)
                else:errors.append(n['id']+': invalid vote')
            except Exception as e:errors.append(n['id']+': '+str(e))
        if quorum(cfg,votes):break
        events.append({'phase':'TIMEOUT-RETRY','view':view,'votes':len(votes)})
        time.sleep(min(.3,.04*(view+1)))
    cert={'proposal_hash':digest(p),'votes':votes,'weight_source':cfg['weight_source'],'snapshot':p['snapshot'],'view':successful_view}
    if successful_view_cert is not None:cert['view_certificate']=successful_view_cert
    events.append({'phase':'PREPARE','votes':len(votes),'weight':sum(n['weight'] for n in peers if n['id'] in {v['node'] for v in votes})})
    if not certificate_valid(cfg,p,cert):
        # F04：失败轮次的提案原样归还——同 txid 重提是幂等续跑（节点 312–315 返回
        # 存量签名），分叉锁则走 abort_pending_round() 协调清障。
        return {'status':'quorum_failed','votes':votes,'errors':errors,'events':events,'txid':signed_tx['txid'],
                'resumable':True,'pending_proposal':p,
                'resume_hint':'原样重试同一 signed_tx 即续跑（同 txid 幂等）；分叉锁用 abort_pending_round() 清障'}
    commits=[]
    expected_hash=block_hash(p['height'],p['previous'],signed_tx['txid'])
    for n in peers:
        try:
            receipt=request(n,'/commit',{'proposal':p,'certificate':cert})
            if (receipt.get('node')!=n['id'] or type(receipt.get('height')) is not int
                    or receipt['height']!=p['height'] or receipt.get('hash')!=expected_hash):
                raise ValueError('commit receipt does not match proposal')
            commits.append(receipt)
        except Exception as e:errors.append(n['id']+': '+str(e))
    events.append({'phase':'COMMIT','nodes_committed':len(commits)})
    return {'status':'replicated' if len(commits)==len(peers) else ('partially_replicated' if commits else 'commit_unconfirmed'),'txid':signed_tx['txid'],'block_height':p['height'],'block_hash':block_hash(p['height'],p['previous'],signed_tx['txid']),'votes':votes,'weight_approved':sum(n['weight'] for n in peers if n['id'] in {v['node'] for v in votes}),'weight_total':sum(n['weight'] for n in peers),'commits':commits,'errors':errors,'events':events,'recovery':recovered,'snapshot':p['snapshot'],'certificate':cert,'consensus_scope':'weighted_prepare_commit_signed_view_change_and_retry_not_full_pbft'}

def cross_verify(height, deep=None):
    """F14（2026-11-03）：跨节点核验目标块，deep=True 时沿 previous 递归验到创世。

    此前只验目标块与直接父块的哈希链接——中间层被改且同步改写两层哈希时漏检。
    deep 缺省随交易深度走：height<=8 自动全验，更高仅验 target+parent（与旧语义
    等价，避免长链 O(n) 放大）；审计入口显式传 deep=True 获得全链复扫。"""
    cfg=init_network();results=[]
    if deep is None: deep = height <= 8
    for n in cfg['peers']:
        try:
            b=request(n,'/block/'+str(height));p=json.loads(b['proposal']);c=json.loads(b['certificate'])
            ok=(certificate_valid(epoch_for_proposal(p,cfg),p,c) and p['height']==height and b['height']==height and b['previous']==p['previous'] and b['txid']==p['transaction']['txid'] and block_hash(height,p['previous'],b['txid'])==b['hash'])
            if ok and height>1:
                prev=request(n,'/block/'+str(height-1))
                ok=(prev['hash']==p['previous'])
                if ok and deep:
                    cur_p=p
                    for h in range(height-1,0,-1):
                        pb=request(n,'/block/'+str(h));pp=json.loads(pb['proposal'])
                        if not (pp['height']==h and pb['hash']==cur_p['previous']
                                and block_hash(h,pp['previous'],pb['txid'])==pb['hash']):
                            ok=False;break
                        cur_p=pp
            results.append({'node':n['id'],'valid':ok,'hash':b['hash'],'height':height})
        except Exception as e:results.append({'node':n['id'],'valid':False,'error':str(e)})
    hashes={r.get('hash') for r in results}
    return {'height':height,'consistent':all(r['valid'] for r in results) and len(hashes)==1,'nodes':results}

def pending_rounds():
    """F04：跨节点列出 tip 之上未提交的投票锁（卡死轮次可视化）。"""
    cfg=init_network();out=[]
    for n in cfg['peers']:
        try:out.append({**request(n,'/pending'),'node':n['id'],'online':True})
        except Exception as e:out.append({'node':n['id'],'online':False,'error':str(e)})
    dangling=[d for r in out for d in r.get('dangling',[])]
    return {'nodes':out,'stuck':bool(dangling),'heights':sorted({d['height'] for d in dangling})}

def abort_pending_round():
    """F04：协调清障——令所有在线节点删除各自 tip 之上未提交的投票锁。

    安全论证（unanimity 语义下）：quorum=全 3 节点 ⇒ 无证书⇒无提交，故 tip 之上
    的锁不属于任何已提交历史；新证书需全体节点在新提案上重新签名，攻击者持有
    的旧锁副本缺其余诚实节点签名，无法拼装成有效证书 ⇒ 删除锁不引入分叉可能。
    部分失败只会留下剩余锁（活跃度问题，重跑本函数即可），不会变得不安全。
    纪元激活的 dangling 检查（activate_snapshot）在清障前仍会如实拒绝。
    """
    cfg=init_network();results=[];heights=set();ok_count=0
    for n in cfg['peers']:
        try:
            r=request(n,'/abort-pending',{})
            if r.get('node')!=n['id'] or 'aborted_height' not in r:raise ValueError('bad receipt')
            results.append({**r,'online':True});heights.add(r['aborted_height']);ok_count+=1
        except Exception as e:results.append({'node':n['id'],'online':False,'error':str(e)})
    coordinated=ok_count>=2 and len(heights)==1
    return {'coordinated':coordinated,'aborted_height':heights.pop() if len(heights)==1 else None,
            'ok_count':ok_count,'results':results}
