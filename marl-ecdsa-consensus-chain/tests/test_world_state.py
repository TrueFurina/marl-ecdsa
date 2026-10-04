"""WorldState 模块单元测试"""
import pytest
from blockchain.ledger.world_state import (
    WorldState, AgentStatus, AgentIdentity, AgentScore, AgentBehavior
)

class TestWorldStateRegistration:
    def test_register_new_agent(self):
        ws = WorldState()
        assert ws.register_agent("agent_0", "pubkey_hex_0")
        assert ws.is_registered("agent_0")

    def test_register_duplicate_fails(self):
        ws = WorldState()
        ws.register_agent("agent_0", "pubkey_hex_0")
        assert not ws.register_agent("agent_0", "pubkey_hex_0_v2")

    def test_get_public_key(self):
        ws = WorldState()
        ws.register_agent("agent_0", "0xabcd1234")
        assert ws.get_public_key("agent_0") == "0xabcd1234"
        assert ws.get_public_key("unknown") is None

    def test_is_registered_unregistered(self):
        ws = WorldState()
        assert not ws.is_registered("ghost")

    def test_is_active_banned(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        assert ws.is_active("agent_0")
        # Banned agents are not active
        ws.set_agent_status("agent_0", AgentStatus.BANNED)
        assert not ws.is_active("agent_0")


class TestWorldStateScore:
    def test_add_score_positive(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.add_score("agent_0", 10.0)
        assert ws.get_score("agent_0") == 10.0

    def test_add_score_negative(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.add_score("agent_0", -5.0)
        assert ws.get_score("agent_0") == -5.0

    def test_get_score_unregistered_raises(self):
        ws = WorldState()
        with pytest.raises(KeyError):
            ws.get_score("ghost")

    def test_add_score_unregistered_noop(self):
        ws = WorldState()
        ws.add_score("ghost", 10.0)  # Should not raise

    def test_get_all_scores(self):
        ws = WorldState()
        ws.register_agent("a", "ka")
        ws.register_agent("b", "kb")
        ws.add_score("a", 5.0)
        ws.add_score("b", 3.0)
        scores = ws.get_all_scores()
        assert scores == {"a": 5.0, "b": 3.0}

    def test_cumulative_contribution(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.add_score("agent_0", 10.0)
        ws.add_score("agent_0", 5.0)
        ws.add_score("agent_0", -3.0)  # negative doesn't add to contribution
        assert ws.get_contribution("agent_0") == 15.0


class TestWorldStatePenalty:
    def test_betrayal_warning(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        for i in range(10):
            ws.record_betrayal("agent_0", i + 1)
        assert ws.get_betrayal_count("agent_0") == 10
        assert ws.get_agent_status("agent_0") == AgentStatus.WARNING

    def test_betrayal_demoted(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        for i in range(30):
            ws.record_betrayal("agent_0", i + 1)
        assert ws.get_betrayal_count("agent_0") == 30
        assert ws.get_agent_status("agent_0") == AgentStatus.DEMOTED
        assert ws.get_consensus_weight("agent_0") == 0.3

    def test_betrayal_banned(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        for i in range(50):
            ws.record_betrayal("agent_0", i + 1)
        assert ws.get_betrayal_count("agent_0") == 50
        assert ws.get_agent_status("agent_0") == AgentStatus.BANNED
        assert ws.get_consensus_weight("agent_0") == 0.0

    def test_betrayal_unregistered_noop(self):
        ws = WorldState()
        ws.record_betrayal("ghost", 1)  # Should not raise

    def test_record_cooperation(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.record_cooperation("agent_0")
        ws.record_cooperation("agent_0")
        summary = ws.get_agent_summary("agent_0")
        assert summary["cooperation_rounds"] == 2


class TestWorldStatePublicInterface:
    def test_update_consensus_weight(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.update_consensus_weight("agent_0", 1.5)
        assert ws.get_consensus_weight("agent_0") == 1.5

    def test_set_agent_status(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.set_agent_status("agent_0", AgentStatus.DEMOTED)
        assert ws.get_agent_status("agent_0") == AgentStatus.DEMOTED

    def test_get_all_agent_ids(self):
        ws = WorldState()
        ws.register_agent("a", "ka")
        ws.register_agent("b", "kb")
        assert set(ws.get_all_agent_ids()) == {"a", "b"}

    def test_get_agent_summary(self):
        ws = WorldState()
        ws.register_agent("agent_0", "mykey")
        ws.add_score("agent_0", 25.0)
        for i in range(10):
            ws.record_betrayal("agent_0", i + 1)
        summary = ws.get_agent_summary("agent_0")
        assert summary["agent_id"] == "agent_0"
        assert summary["status"] == AgentStatus.WARNING
        assert summary["score"] == 25.0
        assert summary["betrayal_count"] == 10
        assert summary["consensus_weight"] == 1.0

    def test_get_agent_summary_unknown(self):
        ws = WorldState()
        assert ws.get_agent_summary("ghost") == {}

    def test_get_all_agents_summary(self):
        ws = WorldState()
        ws.register_agent("a", "ka")
        ws.register_agent("b", "kb")
        summaries = ws.get_all_agents_summary()
        assert len(summaries) == 2
        ids = {s["agent_id"] for s in summaries}
        assert ids == {"a", "b"}


class TestWorldStateSystem:
    def test_system_state_update(self):
        ws = WorldState()
        ws.update_system_state(100, 50, 3)
        state = ws.get_system_state()
        assert state["block_height"] == 100
        assert state["total_transactions"] == 50
        assert state["online_agents"] == 3

    def test_system_state_cumulative_tx(self):
        ws = WorldState()
        ws.update_system_state(1, 10, 3)
        ws.update_system_state(2, 15, 3)
        state = ws.get_system_state()
        assert state["total_transactions"] == 25  # cumulative

    def test_record_action(self):
        ws = WorldState()
        ws.register_agent("agent_0", "key0")
        ws.record_action("agent_0", "hash_abc", 5)
        summary = ws.get_agent_summary("agent_0")
        assert summary["last_active_block"] == 5
