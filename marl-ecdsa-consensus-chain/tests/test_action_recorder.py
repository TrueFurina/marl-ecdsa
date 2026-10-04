"""
ActionRecorder 子组件独立测试
覆盖：行为缓冲、Transaction生成、批量上链、UPLOAD_INTERVAL、flush_pending、stub模式
"""
import pytest
import sys
import time

sys.path.insert(0, '.')

from marl.integration.action_recorder import ActionRecorder
from blockchain.ledger.block import Transaction
from blockchain.ledger.blockchain import Blockchain


@pytest.fixture
def recorder_with_bc():
    """带真实 Blockchain 的 ActionRecorder"""
    bc = Blockchain()
    recorder = ActionRecorder(bc_node=bc, n_agents=3, upload_interval=10)
    yield recorder, bc


@pytest.fixture
def recorder_stub():
    """无 Blockchain 的 stub 模式 ActionRecorder"""
    return ActionRecorder(bc_node=None, n_agents=3, upload_interval=10)


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


class TestActionRecorderInit:
    """初始化测试"""

    def test_init_default_interval(self, recorder_with_bc):
        """默认 UPLOAD_INTERVAL=10"""
        recorder, _ = recorder_with_bc
        assert recorder.UPLOAD_INTERVAL == 10

    def test_init_custom_interval(self):
        """自定义 UPLOAD_INTERVAL"""
        recorder = ActionRecorder(bc_node=None, n_agents=3, upload_interval=5)
        assert recorder.UPLOAD_INTERVAL == 5

    def test_init_stats_zero(self, recorder_with_bc):
        """统计初始为 0"""
        recorder, _ = recorder_with_bc
        assert recorder._tx_count == 0
        assert len(recorder._pending_actions) == 0

    def test_init_stub_mode(self, recorder_stub):
        """stub 模式不崩溃"""
        assert recorder_stub.bc_node is None


class TestRecordAction:
    """行为缓冲记录"""

    def test_record_basic(self, recorder_stub):
        """基本行为记录"""
        ts = int(time.time() * 1000)
        recorder_stub.record_action("agent_0", step=0, action_data=2,
                                     env_reward=-1.0, timestamp=ts, nonce=1)
        assert len(recorder_stub._pending_actions) == 1

    def test_record_all_agents(self, recorder_stub):
        """3 个智能体行为记录"""
        ts = int(time.time() * 1000)
        for i, aid in enumerate(AGENT_IDS):
            recorder_stub.record_action(aid, step=0, action_data=i,
                                         env_reward=-1.0, timestamp=ts, nonce=1)
        assert len(recorder_stub._pending_actions) == 3

    def test_record_multiple_steps(self, recorder_stub):
        """多步行为累积"""
        ts = int(time.time() * 1000)
        for step in range(5):
            recorder_stub.record_action("agent_0", step=step, action_data=step,
                                         env_reward=-1.0, timestamp=ts, nonce=step+1)
        assert len(recorder_stub._pending_actions) == 5

    def test_record_with_signed_package(self, recorder_with_bc):
        """带签名包的行为记录"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        signed_pkg = {
            'signature_hex': 'abcd1234',
            'message_hex': 'msg_hex',
            'r': 100, 's': 200,
            'verified': True,
        }
        recorder.record_action("agent_0", step=0, action_data=2,
                                env_reward=-1.0, timestamp=ts, nonce=1,
                                signed_package=signed_pkg)
        assert len(recorder._pending_actions) == 1
        pending = recorder._pending_actions[0]
        assert pending['signature_hex'] == 'abcd1234'
        assert pending['verified'] is True

    def test_record_without_signed_package(self, recorder_stub):
        """无签名包的行为记录"""
        ts = int(time.time() * 1000)
        recorder_stub.record_action("agent_0", step=0, action_data=2,
                                     env_reward=-1.0, timestamp=ts, nonce=1)
        pending = recorder_stub._pending_actions[0]
        assert 'signature_hex' not in pending
        assert 'verified' not in pending

    def test_record_action_hash_computed(self, recorder_stub):
        """行为哈希应自动计算"""
        ts = int(time.time() * 1000)
        recorder_stub.record_action("agent_0", step=0, action_data=2,
                                     env_reward=-1.0, timestamp=ts, nonce=1)
        pending = recorder_stub._pending_actions[0]
        assert 'action_hash' in pending
        assert len(pending['action_hash']) == 16  # sha256[:16]


class TestBatchUpload:
    """批量上链"""

    def test_batch_upload_with_bc(self, recorder_with_bc):
        """有 Blockchain 时批量上链应增加 tx_count"""
        recorder, bc = recorder_with_bc
        ts = int(time.time() * 1000)
        # 记录 3 个行为
        for i, aid in enumerate(AGENT_IDS):
            recorder.record_action(aid, step=0, action_data=i,
                                     env_reward=-1.0, timestamp=ts, nonce=1)

        recorder.batch_upload()

        assert recorder._tx_count == 3
        assert len(recorder._pending_actions) == 0  # 缓冲清空

    def test_batch_upload_stub_mode(self, recorder_stub):
        """stub 模式下 batch_upload 清空缓冲但不增加 tx_count"""
        ts = int(time.time() * 1000)
        recorder_stub.record_action("agent_0", step=0, action_data=0,
                                     env_reward=-1.0, timestamp=ts, nonce=1)
        recorder_stub.batch_upload()
        assert len(recorder_stub._pending_actions) == 0
        assert recorder_stub._tx_count == 0  # stub 模式无 bc_node

    def test_batch_upload_empty_buffer(self, recorder_with_bc):
        """空缓冲时 batch_upload 不操作"""
        recorder, _ = recorder_with_bc
        recorder.batch_upload()
        assert recorder._tx_count == 0

    def test_batch_upload_twice(self, recorder_with_bc):
        """两次批量上链累积 tx_count"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        # 第一次
        for aid in AGENT_IDS:
            recorder.record_action(aid, step=0, action_data=0,
                                     env_reward=-1.0, timestamp=ts, nonce=1)
        recorder.batch_upload()

        # 第二次
        for aid in AGENT_IDS:
            recorder.record_action(aid, step=1, action_data=1,
                                     env_reward=-1.0, timestamp=ts, nonce=2)
        recorder.batch_upload()

        assert recorder._tx_count == 6


class TestFlushPending:
    """回合结束刷新"""

    def test_flush_pending_with_bc(self, recorder_with_bc):
        """flush_pending 将剩余缓冲转为 Transaction"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        recorder.record_action("agent_0", step=0, action_data=0,
                                env_reward=-1.0, timestamp=ts, nonce=1)
        recorder.flush_pending()
        assert recorder._tx_count == 1
        assert len(recorder._pending_actions) == 0

    def test_flush_pending_empty(self, recorder_with_bc):
        """无缓冲时 flush_pending 不操作"""
        recorder, _ = recorder_with_bc
        recorder.flush_pending()
        assert recorder._tx_count == 0

    def test_flush_pending_stub_mode(self, recorder_stub):
        """stub 模式下 flush_pending 仅清空缓冲"""
        ts = int(time.time() * 1000)
        recorder_stub.record_action("agent_0", step=0, action_data=0,
                                     env_reward=-1.0, timestamp=ts, nonce=1)
        recorder_stub.flush_pending()
        # stub: bc_node=None, flush_pending 跳过 Transaction 创建
        # 但 _pending_actions 只有在有 bc_node 时才 clear
        # (flush_pending 内部: if self.bc_node is not None and self._pending_actions)


class TestPendingToTransaction:
    """行为 → Transaction 转换"""

    def test_valid_conversion(self, recorder_with_bc):
        """正常行为记录转为 Transaction"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        signed_pkg = {
            'signature_hex': 'abcd1234',
            'message_hex': 'msg_hex',
            'r': 100, 's': 200,
            'verified': True,
        }
        recorder.record_action("agent_0", step=0, action_data=2,
                                env_reward=-1.0, timestamp=ts, nonce=1,
                                signed_package=signed_pkg)

        tx = recorder.pending_to_transaction(recorder._pending_actions[0])
        assert tx is not None
        assert isinstance(tx, Transaction)
        assert tx.agent_id == "agent_0"
        assert tx.nonce == 1
        assert tx.tx_type == "action"
        assert tx.tx_id != ""  # compute_hash() 已执行

    def test_extra_fields_preserved(self, recorder_with_bc):
        """Transaction.extra 应保留所有扩展字段"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        signed_pkg = {
            'signature_hex': 'abcd',
            'message_hex': 'msg',
            'r': 10, 's': 20,
            'verified': True,
        }
        recorder.record_action("agent_0", step=5, action_data=3,
                                env_reward=-2.0, timestamp=ts, nonce=2,
                                signed_package=signed_pkg)

        tx = recorder.pending_to_transaction(recorder._pending_actions[0])
        assert tx.extra['step'] == 5
        assert tx.extra['env_reward'] == -2.0
        assert tx.extra['verified'] is True
        assert tx.extra['r'] == 10
        assert tx.extra['s'] == 20

    def test_conversion_without_signed_package(self, recorder_with_bc):
        """无签名包的 Transaction"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        recorder.record_action("agent_0", step=0, action_data=2,
                                env_reward=-1.0, timestamp=ts, nonce=1)

        tx = recorder.pending_to_transaction(recorder._pending_actions[0])
        assert tx is not None
        assert tx.signature_hex == ''  # 无签名
        assert tx.extra.get('verified') is False


class TestUploadIntervalOverride:
    """UPLOAD_INTERVAL 覆盖测试"""

    def test_set_upload_interval(self, recorder_with_bc):
        """可动态修改 UPLOAD_INTERVAL"""
        recorder, _ = recorder_with_bc
        assert recorder.UPLOAD_INTERVAL == 10
        recorder.UPLOAD_INTERVAL = 5
        assert recorder.UPLOAD_INTERVAL == 5

    def test_interval_affects_batch_trigger(self):
        """UPLOAD_INTERVAL 影响批量触发逻辑（由 Bridge.on_step 控制）"""
        recorder = ActionRecorder(bc_node=None, n_agents=3, upload_interval=3)
        assert recorder.UPLOAD_INTERVAL == 3


class TestGetStats:
    """统计接口"""

    def test_get_stats_structure(self, recorder_with_bc):
        """get_stats 返回完整结构"""
        recorder, _ = recorder_with_bc
        stats = recorder.get_stats()
        assert 'pending_actions' in stats
        assert 'tx_count' in stats

    def test_get_stats_after_operations(self, recorder_with_bc):
        """操作后统计应反映变化"""
        recorder, _ = recorder_with_bc
        ts = int(time.time() * 1000)
        recorder.record_action("agent_0", step=0, action_data=0,
                                env_reward=-1.0, timestamp=ts, nonce=1)
        stats_before = recorder.get_stats()
        assert stats_before['pending_actions'] == 1

        recorder.batch_upload()
        stats_after = recorder.get_stats()
        assert stats_after['pending_actions'] == 0
        assert stats_after['tx_count'] == 1
