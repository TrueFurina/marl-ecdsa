"""Authenticated single-node ECDSA ledger and subprocess training service.
Single-node persistence is NOT a CW-PBFT network consensus certificate.
"""
import hashlib, json, os, sqlite3, subprocess, sys, threading, time, uuid
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# F10：用户私钥与 KeyManager 同款加密落盘（口令跨重启稳定：env MARL_ECDSA_KEY_PASSPHRASE 或公开的 DEFAULT）
from blockchain.crypto.ecdsa_utils import ECDSAUtils, resolve_key_passphrase
DATA = ROOT / 'instance'
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'business.sqlite3'
LOGS = DATA / 'training_logs'; LOGS.mkdir(exist_ok=True)
LOCK = threading.RLock()
PROCESSES = {}

def conn():
    db=sqlite3.connect(DB,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db

def init():
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS user_keys (user_id INTEGER PRIMARY KEY, private_pem TEXT NOT NULL, public_pem TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS transactions (txid TEXT PRIMARY KEY, user_id INTEGER NOT NULL, payload TEXT NOT NULL, signature TEXT NOT NULL, public_key TEXT NOT NULL, block_height INTEGER NOT NULL, created_at REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS blocks (height INTEGER PRIMARY KEY, hash TEXT NOT NULL, prev_hash TEXT NOT NULL, txid TEXT NOT NULL, created_at REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, pid INTEGER, status TEXT NOT NULL, config TEXT NOT NULL, log_path TEXT NOT NULL, result_path TEXT NOT NULL, exit_code INTEGER, created_at REAL NOT NULL, finished_at REAL)')

def canonical(data): return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(data):return hashlib.sha256(data).hexdigest()

def _pid_alive(pid):
    """F11：安全存活探测——绝不向目标进程发送任何信号。
    Windows 上 os.kill(pid,0) 并非 POSIX 式空信号语义，可能走 TerminateProcess，
    用只读探测替代：优先 psutil（pid_exists 且非僵尸）；无 psutil 时 Windows 用
    kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)+GetExitCodeProcess，
    POSIX 回退 os.kill(pid,0)。pid 复用无法在此判别，故仅"确证存活"返回 True。"""
    if not (isinstance(pid, int) and pid > 0):
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        pass
    if os.name == 'nt':
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return True
            finally:
                k32.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


# F11：持有 Job Object 句柄至本（Web）进程退出；句柄全关时内核杀掉 Job 内训练子进程
_JOB_HANDLES = set()


def _win_job_kill_on_close(proc):
    """F11：Windows 把训练子进程放入 KILL_ON_JOB_CLOSE 的 Job Object。
    Web（唯一句柄持有者）无论正常退出还是崩溃（os._exit/被杀），内核都自动终止
    训练子进程——消除"Web 重启后 train.py 孤儿继续写结果文件"的竞态。
    非 Windows / 任何失败静默回退，不阻断训练启动（best-effort）。"""
    if os.name != 'nt' or proc is None or not getattr(proc, 'pid', None):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        # 64 位下必须显式设 restype/argtypes，否则句柄按 c_int 截断
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        JobObjectExtendedLimitInformation = 9
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                         'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

        class _BASIC(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', wintypes.LARGE_INTEGER),
                        ('PerJobUserTimeLimit', wintypes.LARGE_INTEGER),
                        ('LimitFlags', wintypes.DWORD),
                        ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t),
                        ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.POINTER(wintypes.ULONG)),
                        ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class _EXT(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', _BASIC), ('IoInfo', _IO_COUNTERS),
                        ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]

        h_job = k32.CreateJobObjectW(None, None)
        if not h_job:
            return None
        info = _EXT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(h_job, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(h_job)
            return None
        h_proc = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(proc.pid))
        if not h_proc:
            k32.CloseHandle(h_job)
            return None
        try:
            if not k32.AssignProcessToJobObject(h_job, h_proc):
                k32.CloseHandle(h_job)
                return None
        finally:
            k32.CloseHandle(h_proc)
        _JOB_HANDLES.add(h_job)   # 持有到本进程退出（含 os._exit 崩溃：内核关句柄→杀 Job）
        return h_job
    except Exception:
        return None

def key_for(db, uid):
    passph = resolve_key_passphrase()
    row = db.execute('SELECT private_pem,public_pem FROM user_keys WHERE user_id=?', (uid,)).fetchone()
    if row:
        pem_bytes = row['private_pem'].encode()
        key = ECDSAUtils.private_key_from_bytes(pem_bytes, passph)  # 加密；旧明文自动回退兼容
        if b"ENCRYPTED PRIVATE KEY" not in pem_bytes:              # F10：存量明文 → 加密原地迁移
            enc = ECDSAUtils.private_key_to_bytes(key, passph).decode()
            db.execute('UPDATE user_keys SET private_pem=? WHERE user_id=?', (enc, uid))
        return key, row['public_pem']
    key = ec.generate_private_key(ec.SECP256R1())
    priv = ECDSAUtils.private_key_to_bytes(key, passph).decode()   # F10：加密落盘（BestAvailableEncryption）
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    db.execute('INSERT INTO user_keys VALUES (?,?,?)', (uid, priv, pub))
    return key, pub

def verify_record(tx):
    try:
        public=serialization.load_pem_public_key(tx['public_key'].encode())
        public.verify(bytes.fromhex(tx['signature']),canonical(json.loads(tx['payload'])),ec.ECDSA(hashes.SHA256()))
        return True
    except (ValueError, InvalidSignature, TypeError, KeyError):return False

def submit(uid, content):
    if not isinstance(content,str) or not 1<=len(content)<=2048:raise ValueError('交易内容长度须为 1–2048 字符')
    payload={'creator':uid,'content':content,'nonce':uuid.uuid4().hex,'timestamp_ms':int(time.time()*1000)}
    raw=canonical(payload);txid=sha(raw)
    with LOCK,conn() as db:
        db.execute('BEGIN IMMEDIATE')
        key,pub=key_for(db,uid)
        sig=key.sign(raw,ec.ECDSA(hashes.SHA256())).hex()
        previous=db.execute('SELECT height,hash FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
        height=(previous['height']+1) if previous else 1
        prev_hash=previous['hash'] if previous else '0'*64
        stamp=time.time()
        header={'height':height,'prev_hash':prev_hash,'txid':txid,'created_at':stamp}
        block_hash=sha(canonical(header))
        db.execute('INSERT INTO blocks VALUES (?,?,?,?,?)',(height,block_hash,prev_hash,txid,stamp))
        db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)',(txid,uid,raw.decode(),sig,pub,height,stamp))
        db.commit()
    return {'txid':txid,'block_height':height,'block_hash':block_hash,'status':'locally_committed','consensus':'single_node_only'}

def lookup(uid,txid):
    with conn() as db:
        row=db.execute('SELECT * FROM transactions WHERE txid=? AND user_id=?',(txid,uid)).fetchone()
        if row is None:return None
        tx=dict(row); block=db.execute('SELECT * FROM blocks WHERE height=?',(tx['block_height'],)).fetchone()
        header={'height':block['height'],'prev_hash':block['prev_hash'],'txid':block['txid'],'created_at':block['created_at']}
        prev=db.execute('SELECT hash FROM blocks WHERE height=?',(block['height']-1,)).fetchone()
        return {'txid':txid,'payload':json.loads(tx['payload']),'signature':tx['signature'],'public_key':tx['public_key'], 'signature_valid':verify_record(tx) and sha(tx['payload'].encode())==txid,'block_height':block['height'],'block_hash':block['hash'],'block_hash_valid':sha(canonical(header))==block['hash'],'previous_link_valid':block['prev_hash']==(prev['hash'] if prev else '0'*64),'status':'locally_committed','consensus':'single_node_only'}

def recent(uid):
    with conn() as db:
        rows=db.execute('SELECT txid,block_height,created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(uid,)).fetchall()
        return [dict(x) for x in rows]

ALLOWED_MODES={'pure_marl','bc_marl'}
ALLOWED_ALGOS={'iql','vdn','qmix'}

def validated_config(data):
    if not isinstance(data,dict):raise ValueError('配置格式错误')
    mode=data.get('mode','bc_marl');algo=data.get('algorithm','iql')
    if mode not in ALLOWED_MODES or algo not in ALLOWED_ALGOS:raise ValueError('训练模式或算法无效')
    def integer(key,default,lo,hi):
        value=data.get(key,default)
        if isinstance(value,bool):raise ValueError(key+' 必须是整数')
        try:v=int(value)
        except (ValueError,TypeError):raise ValueError(key+' 必须是整数')
        if not lo<=v<=hi:raise ValueError(key+' 超出范围')
        return v
    episodes=integer('n_episodes',30,1,10000)
    if mode=='bc_marl' and episodes<2:
        raise ValueError('BC-MARL 贡献治理至少需要 2 个训练回合')
    return {'mode':mode,'algorithm':algo,'n_episodes':episodes,'n_agents':integer('n_agents',3,2,12),'max_steps':integer('max_steps',25,1,200),'seed':integer('seed',42,0,2**31-1)}

def start(uid,config):
    config=validated_config(config)
    # Reconcile jobs orphaned by a dashboard restart before checking for conflicts.
    with conn() as db:
        stale_ids=[r['id'] for r in db.execute("SELECT id FROM jobs WHERE user_id=? AND status IN ('starting','running','stopping')",(uid,))]
    for old_jid in stale_ids:
        get_job(uid,old_jid)
    with LOCK,conn() as db:
        running=db.execute("SELECT id FROM jobs WHERE user_id=? AND status IN ('starting','running','stopping')",(uid,)).fetchone()
        if running:raise ValueError('已有训练任务运行中，请先停止')
        jid=uuid.uuid4().hex
        log=str(LOGS/(jid+'.log')); result=str(LOGS/(jid+'.json'))
        cmd=[sys.executable,'-u',str(ROOT/'train.py'),'--mode',config['mode'],'--algorithm',config['algorithm'],'--n_episodes',str(config['n_episodes']),'--n_agents',str(config['n_agents']),'--max_steps',str(config['max_steps']),'--seed',str(config['seed']),'--save',result]
        db.execute('INSERT INTO jobs (id,user_id,status,config,log_path,result_path,created_at) VALUES (?,?,?,?,?,?,?)',(jid,uid,'starting',json.dumps(config),log,result,time.time()))
        db.commit()
        try:
            logfile=open(log,'w',encoding='utf-8')
            try:proc=subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
            finally:logfile.close()
        except Exception as e:
            db.execute('UPDATE jobs SET status=?,finished_at=? WHERE id=?',('failed',time.time(),jid));db.commit()
            raise ValueError('训练进程启动失败：'+str(e))
        PROCESSES[jid]=proc
        _win_job_kill_on_close(proc)   # F11：Web 崩溃时内核自动杀训练子进程（best-effort）
        db.execute('UPDATE jobs SET pid=?, status=? WHERE id=?',(proc.pid,'running',jid));db.commit()
    return {'job_id':jid,'status':'running','config':config}

def get_job(uid,jid):
    with LOCK,conn() as db:
        row=db.execute('SELECT * FROM jobs WHERE id=? AND user_id=?',(jid,uid)).fetchone()
        if not row:return None
        job=dict(row);proc=PROCESSES.get(jid)
        if job['status'] in ('starting','running','stopping'):
            if proc:
                exit_code=proc.poll()
                if exit_code is not None:
                    status='stopped' if job['status']=='stopping' else ('completed' if exit_code==0 else 'failed')
                    db.execute('UPDATE jobs SET status=?,exit_code=?,finished_at=? WHERE id=?',(status,exit_code,time.time(),jid));db.commit()
                    job['status']=status;job['exit_code']=exit_code;PROCESSES.pop(jid,None)
            else:
                # A previous dashboard process may have exited while train.py continued.
                # A fully written result with matching mode/episode count is recoverable.
                completed=False
                try:
                    cfg=json.loads(job['config'])
                    allowed_root=LOGS.resolve()
                    candidate=(LOGS / (jid+'.json')).resolve()
                    candidate.relative_to(allowed_root)
                    obj=json.loads(candidate.read_text(encoding='utf-8'))
                    completed=(job['status']!='stopping' and isinstance(obj,dict)
                        and isinstance(obj.get('config'),dict)
                        and all(obj['config'].get(k)==cfg[k] for k in
                                ('mode','algorithm','n_episodes','n_agents','max_steps','seed'))
                        and isinstance(obj.get('episode_rewards'),list)
                        and len(obj['episode_rewards'])==cfg['n_episodes']
                        and isinstance(obj.get('summary'),dict))
                except (OSError,ValueError,TypeError,KeyError,AttributeError):
                    pass
                if completed:
                    db.execute('UPDATE jobs SET status=?,exit_code=?,finished_at=? WHERE id=?',('completed',0,time.time(),jid))
                    db.commit();job['status']='completed';job['exit_code']=0
                else:
                    alive = _pid_alive(job.get('pid'))   # F11：只读探测，不发信号
                    if not alive:
                        new_status='stopped' if job['status']=='stopping' else 'failed'
                        db.execute('UPDATE jobs SET status=?,exit_code=?,finished_at=? WHERE id=?',(new_status,-1,time.time(),jid))
                        db.commit();job['status']=new_status;job['exit_code']=-1
        job.pop('log_path');job.pop('result_path');job['config']=json.loads(job['config'])
        job['result_available']=Path(row['result_path']).exists()
        return job

def jobs(uid):
    with conn() as db:
        ids=[r['id'] for r in db.execute('SELECT id FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 20',(uid,))]
    return [get_job(uid,i) for i in ids]

def stop(uid,jid):
    with LOCK,conn() as db:
        row=db.execute('SELECT status,pid FROM jobs WHERE user_id=? AND id=?',(uid,jid)).fetchone()
        if not row:return None
        proc=PROCESSES.get(jid)
        if row['status']=='running' and proc and proc.poll() is None:
            proc.terminate()
            db.execute("UPDATE jobs SET status='stopping' WHERE id=?",(jid,));db.commit()
        elif row['status']=='running' and row['pid']:
            # F11（2026-11-03）：Web 重启后 PROCESSES 已空，按 DB pid 兜底停止。
            # 用只读探活确证后经 psutil 终止（含子进程树），不向未知进程发信号。
            pid=int(row['pid'])
            if _pid_alive(pid):
                try:
                    import psutil
                    target=psutil.Process(pid)
                    for child in target.children(recursive=True):
                        try:child.terminate()
                        except Exception:pass
                    target.terminate()
                    db.execute("UPDATE jobs SET status='stopping' WHERE id=?",(jid,));db.commit()
                except Exception:
                    pass  # pid 已死/复用不可判——保持 running，由 get_job 对账收敛
    return get_job(uid,jid)

def logs(uid,jid):
    with conn() as db:
        row=db.execute('SELECT log_path FROM jobs WHERE id=? AND user_id=?',(jid,uid)).fetchone()
    if row is None:return None
    path=Path(row['log_path'])
    if not path.exists():return ''
    with path.open('rb') as f:
        f.seek(0,2);f.seek(max(0,f.tell()-32768));return f.read().decode('utf-8',errors='replace')[-20000:]
init()


# Blockchain transparency and independent local verification. No consensus certificate is fabricated.
def _audit(db, limit=10000):
    rows=db.execute('SELECT * FROM blocks ORDER BY height ASC LIMIT ?', (limit,)).fetchall()
    previous='0'*64; checked=[]; valid=True
    for expected,r in enumerate(rows,1):
        b=dict(r)
        tx=db.execute('SELECT * FROM transactions WHERE txid=?', (b['txid'],)).fetchone()
        signature_valid=bool(tx) and verify_record(tx) and sha(tx['payload'].encode('utf-8'))==b['txid']
        header={'height':b['height'],'prev_hash':b['prev_hash'],'txid':b['txid'],'created_at':b['created_at']}
        hash_valid=sha(canonical(header))==b['hash']
        link_valid=b['prev_hash']==previous and b['height']==expected
        tx_height_valid=bool(tx) and tx['block_height']==b['height']
        ok=bool(signature_valid and hash_valid and link_valid and tx_height_valid)
        checked.append({'height':b['height'],'hash':b['hash'],'txid':b['txid'],'hash_valid':hash_valid,'link_valid':link_valid,'signature_valid':signature_valid,'tx_height_valid':tx_height_valid,'valid':ok})
        valid=valid and ok;previous=b['hash']
    total=db.execute('SELECT COUNT(*) FROM blocks').fetchone()[0]
    total_tx=db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    orphan_tx=db.execute('SELECT COUNT(*) FROM transactions t LEFT JOIN blocks b ON b.txid=t.txid WHERE b.txid IS NULL').fetchone()[0]
    extra_blocks=total>len(rows)
    return {'valid':valid and not extra_blocks and not orphan_tx and total==total_tx,'checked_blocks':len(rows),'total_blocks':total,'total_transactions':total_tx,'orphan_transactions':orphan_tx,'truncated':extra_blocks,'blocks':checked,'verification_scope':'local_sqlite_hash_chain_and_ecdsa','consensus_verified':False}

def audit(uid):
    with conn() as db:
        result=_audit(db)
        # Per-user transaction list is private; global block integrity report is shared.
        result['blocks']=result['blocks'][-100:]
        return result

def blocks(uid, limit=50):
    limit=max(1,min(int(limit),100))
    with conn() as db:
        rows=db.execute('SELECT * FROM blocks ORDER BY height DESC LIMIT ?', (limit,)).fetchall()
        return [{'height':r['height'],'hash':r['hash'],'prev_hash':r['prev_hash'],'txid':r['txid'],'created_at':r['created_at'],'owner':bool(db.execute('SELECT 1 FROM transactions WHERE txid=? AND user_id=?',(r['txid'],uid)).fetchone())} for r in rows]

def receipt(uid,txid):
    detail=lookup(uid,txid)
    if not detail:return None
    with conn() as db:
        row=db.execute('SELECT created_at,prev_hash FROM blocks WHERE height=?',(detail['block_height'],)).fetchone()
    detail['block_timestamp']=row['created_at']
    detail['previous_hash']=row['prev_hash']
    detail['proof_type']='single_transaction_per_block_direct_inclusion'
    detail['inclusion_valid']=detail['block_hash_valid'] and detail['signature_valid'] and detail['previous_link_valid']
    detail['consensus_certificate']=None
    detail['verification_explanation']='单笔交易区块包含证明；验证交易摘要、ECDSA 签名、区块头哈希与父区块链接，不代表多节点共识。'
    return detail

def simulate_tamper(uid,txid,modified_content):
    if not isinstance(modified_content,str) or not modified_content or len(modified_content)>2048:raise ValueError('请输入 1–2048 字符的篡改内容')
    with conn() as db:
        tx=db.execute('SELECT * FROM transactions WHERE txid=? AND user_id=?',(txid,uid)).fetchone()
        if not tx:return None
        altered=dict(tx);payload=json.loads(tx['payload']);payload['content']=modified_content;altered['payload']=canonical(payload).decode('utf-8')
        return {'original_valid':verify_record(tx) and sha(tx['payload'].encode())==txid,'tampered_signature_valid':verify_record(altered),'tampered_hash_matches_txid':sha(altered['payload'].encode())==txid,'data_modified':payload['content']!=json.loads(tx['payload'])['content'],'database_modified':False}


# ── F04（2026-11-02 赛后）：quorum_failed 的待续跑存证登记 ──
# 同一用户最多一笔 pending（业务层本就限制一账户一任务）；resume 复用原 txid
# 走同 txid 幂等续跑，与"重复点击生成新 nonce"有本质区别。
_PENDING_SUBMITS: dict = {}
_PENDING_LOCK = threading.Lock()

def remember_pending_submit(uid, tx, result):
    with _PENDING_LOCK:
        _PENDING_SUBMITS[str(uid)] = {'tx': tx, 'txid': result.get('txid'),
                                      'at': time.time(), 'status': result.get('status')}

def pop_pending_submit(uid):
    with _PENDING_LOCK:
        return _PENDING_SUBMITS.pop(str(uid), None)

def get_pending_submit(uid):
    with _PENDING_LOCK:
        return _PENDING_SUBMITS.get(str(uid))

def sign_distributed(uid,content):
    if not isinstance(content,str) or not 1<=len(content)<=2048:raise ValueError('交易内容长度须为 1–2048 字符')
    payload={'creator':uid,'content':content,'nonce':uuid.uuid4().hex,'timestamp_ms':int(time.time()*1000)}
    with LOCK,conn() as db:
        key,pub=key_for(db,uid)
        signature=key.sign(canonical(payload),ec.ECDSA(hashes.SHA256())).hex()
    return {'txid':sha(canonical(payload)),'payload':payload,'signature':signature,'public_key':pub}
