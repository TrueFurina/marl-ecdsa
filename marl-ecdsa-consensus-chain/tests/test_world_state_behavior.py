"""
WorldState 行为记录边界测试（RalphLoop 原子任务 X）
覆盖：record_action、行为哈希累积、背叛轮次、注册时初始化
通过标准：新增 ≥6 项测试全过
"""
import logging

import pytest

from blockchain.ledger.world_state import WorldState

logging.basicConfig(level=logging.CRITICAL)


@pytest.fixture
def ws():
    state = WorldState()
    state.register_agent("agent_0", "0x" + "ab" * 32)
    state.register_agent("agent_1", "0x" + "cd" * 32)
    return state


class TestRecordAction:
    def test_record_action_appends_hash(self, ws):
        ws.record_action("agent_0", "hash_1", 5)
        assert ws._behaviors["agent_0"].action_hashes == ["hash_1"]

    def test_record_action_multiple(self, ws):
        for h in ["h1", "h2", "h3"]:
            ws.record_action("agent_0", h, 1)
        assert len(ws._behaviors["agent_0"].action_hashes) == 3

    def test_record_action_updates_last_active_block(self, ws):
        ws.record_action("agent_0", "h1", 10)
        ws.record_action("agent_0", "h2", 20)
        assert ws._behaviors["agent_0"].last_active_block == 20

    def test_record_action_unregistered_noop(self, ws):
        """未注册智能体记录行为不崩溃、无副作用"""
        ws.record_action("ghost", "h1", 1)  # 不抛异常


class TestBehaviorInit:
    def test_register_initializes_behavior(self, ws):
        behavior = ws._behaviors["agent_0"]
        assert behavior.action_hashes == []
        assert behavior.betrayal_rounds == []
        assert behavior.last_active_block == 0


class TestBetrayalRounds:
    def test_record_betrayal_appends_round(self, ws):
        ws.record_betrayal("agent_0", 7)
        assert ws._behaviors["agent_0"].betrayal_rounds == [7]

    def test_record_betrayal_increments_score(self, ws):
        before = ws._scores["agent_0"].betrayal_count
        ws.record_betrayal("agent_0", 3)
        assert ws._scores["agent_0"].betrayal_count == before + 1

    def test_record_betrayal_unregistered_noop(self, ws):
        ws.record_betrayal("ghost", 1)  # 不抛异常


class TestCooperationRounds:
    def test_record_cooperation_increments(self, ws):
        ws.record_cooperation("agent_0")
        assert ws._scores["agent_0"].cooperation_rounds == 1

    def test_record_cooperation_unregistered_noop(self, ws):
        ws.record_cooperation("ghost")  # 不抛异常


class TestGetAllAgentIds:
    def test_get_all_agent_ids(self, ws):
        ids = ws.get_all_agent_ids()
        assert set(ids) == {"agent_0", "agent_1"}

    def test_get_all_agent_ids_empty(self):
        empty = WorldState()
        assert empty.get_all_agent_ids() == []
