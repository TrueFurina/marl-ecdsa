# -*- coding: utf-8 -*-
"""F04 负测（2026-11-02 赛后）：卡死轮次的可见化、同 txid 幂等续跑、协调清障。

反例背景（engineering_findings F04）：quorum_failed 后投票锁持久存在，而业务层
每次重试生成新 txid → 撞 votes_height_unique → 永久 quorum_failed，且没有任何
正常恢复出口（epoch 激活也被 dangling 检查挡住）。
修复：失败时归还 pending_proposal（同 txid 重提=幂等续跑）+ /pending 可视化 +
abort_pending_round() 协调清障（安全性：unanimity 下无证书⇒无提交，删锁不引入
分叉可能；部分失败只是剩余锁的活跃度问题）。
"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

from visualization import distributed_consensus as dc
from tests.test_v11_epoch_view import isolate_consensus_ports


class RoundRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.original = (dc.BASE, dc.CONFIG, dc.HISTORY)
        dc.BASE = self.base
        dc.CONFIG = self.base / 'network.json'
        dc.HISTORY = self.base / 'epochs'
        self.cfg = isolate_consensus_ports(dc.init_network())
        self.ps = []

    def tearDown(self):
        self.stop()
        dc.BASE, dc.CONFIG, dc.HISTORY = self.original
        self.tmp.cleanup()

    def start(self, names=('node-1', 'node-2', 'node-3')):
        root = str(Path(__file__).resolve().parents[1])
        path = str(self.base)
        for n in names:
            code = (f'import sys;sys.path.insert(0,{root!r});from pathlib import Path;'
                    f'from visualization import distributed_consensus as d;'
                    f'd.BASE=Path({path!r});d.CONFIG=d.BASE/"network.json";'
                    f'd.HISTORY=d.BASE/"epochs";d.serve({n!r})')
            self.ps.append(subprocess.Popen([sys.executable, '-c', code],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        # 2026-11-03：原判据是「在线节点**个数** ≥ len(names)」，在已经跑着 node-1/2
        # 的情况下，`start(names=('node-3',))` 的 `>= 1` 立刻成立 —— 根本没等 node-3
        # 起来就开始 propose。本机（没装 torch，子进程 import 快）恰好赶得上；CI 上
        # （装了 torch，`visualization.distributed_consensus` 的导入要几秒）稳定失败：
        # 第二次 propose 只打到 2 个节点 → quorum_failed ≠ replicated。
        # 改为等**指定的这几个节点各自** online（按 `node` 字段精确匹配）。
        want = set(names)
        online = set()
        for _ in range(200):          # 16s，给慢环境留余量
            online = {x.get('node') for x in dc.statuses()['nodes'] if x.get('online')}
            if want <= online:
                return
            time.sleep(.08)
        raise AssertionError(f'nodes not ready: want={sorted(want)} online={sorted(online)}')

    def stop(self):
        for p in self.ps:
            if p.poll() is None:
                p.terminate()
        for p in self.ps:
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
        self.ps = []

    def tx(self, text):
        key = ec.generate_private_key(ec.SECP256R1())
        pl = {'content': text}
        return {'payload': pl, 'txid': dc.digest(pl),
                'public_key': dc.pubkey(key), 'signature': dc.sign(key, pl)}

    def test_transient_failure_resume_same_txid(self):
        """瞬时故障（第 3 节点离线）→ quorum_failed 带可续跑提案 → 节点回归后
        原样重提同一 signed_tx 即完成（同 txid 幂等续跑，无需清障）。"""
        self.start(names=('node-1', 'node-2'))
        tx = self.tx('resume-me')
        r1 = dc.propose(tx, max_views=1, timeout=.5)
        self.assertEqual(r1['status'], 'quorum_failed')
        self.assertTrue(r1['resumable'])
        self.assertIn('pending_proposal', r1)
        self.assertEqual(r1['pending_proposal']['transaction']['txid'], tx['txid'])
        self.start(names=('node-3',))
        r2 = dc.propose(r1['pending_proposal']['transaction'], max_views=1, timeout=1.0)
        self.assertEqual(r2['status'], 'replicated')
        self.assertEqual(r2['txid'], tx['txid'])
        self.assertEqual(r2['block_height'], 1)

    def test_split_locks_abort_then_fresh_commit(self):
        """分叉锁（1 号锁 A、2 号锁 B）→ 新提案永久撞锁 → 协调清障 → 新提案成交。"""
        self.start()
        a, b, c = self.tx('side-A'), self.tx('side-B'), self.tx('side-C')
        cfg = self.cfg
        for node, tx in (('node-1', a), ('node-2', b)):
            p = {'network': cfg['network'], 'height': 1, 'previous': '0' * 64,
                 'transaction': tx, 'snapshot': dc.snapshot_digest(cfg), 'phase': 'PREPARE'}
            with dc.db_for(node) as db:
                db.execute('INSERT INTO votes VALUES (?,?,?)',
                           (tx['txid'], dc.canonical(p).decode(), dc.sign(self.keys(node), dc.vote_message(p))))
        st = dc.pending_rounds()
        self.assertTrue(st['stuck'])
        self.assertEqual(st['heights'], [1])
        r1 = dc.propose(c, max_views=1, timeout=.5)
        self.assertEqual(r1['status'], 'quorum_failed')  # 修复前：永久卡死于此
        ab = dc.abort_pending_round()
        self.assertTrue(ab['coordinated'])
        self.assertEqual(ab['aborted_height'], 1)
        self.assertGreaterEqual(ab['ok_count'], 2)
        self.assertFalse(dc.pending_rounds()['stuck'])
        r2 = dc.propose(c, max_views=1, timeout=1.0)
        self.assertEqual(r2['status'], 'replicated')
        self.assertEqual(r2['block_height'], 1)

    def keys(self, node):
        """分叉锁夹具密钥：votes 表内容在协议里只用于冲突检测（proposal 比对），
        直接插入的锁签名不参与证书校验，故用测试自生成密钥即可。"""
        if not hasattr(self, '_keycache'):
            self._keycache = {'node-1': ec.generate_private_key(ec.SECP256R1()),
                              'node-2': ec.generate_private_key(ec.SECP256R1()),
                              'node-3': ec.generate_private_key(ec.SECP256R1())}
        return self._keycache[node]

    def test_partial_abort_is_retryable_not_unsafe(self):
        """单节点残留锁 → 协调清障覆盖全部节点 → pending 清空。"""
        self.start()
        a = self.tx('stuck-A')
        p = {'network': self.cfg['network'], 'height': 1, 'previous': '0' * 64,
             'transaction': a, 'snapshot': dc.snapshot_digest(self.cfg), 'phase': 'PREPARE'}
        with dc.db_for('node-1') as db:
            db.execute('INSERT INTO votes VALUES (?,?,?)',
                       (a['txid'], dc.canonical(p).decode(),
                        dc.sign(self.keys('node-1'), dc.vote_message(p))))
        ab = dc.abort_pending_round()
        self.assertTrue(ab['coordinated'])
        self.assertFalse(dc.pending_rounds()['stuck'])


if __name__ == '__main__':
    unittest.main()
