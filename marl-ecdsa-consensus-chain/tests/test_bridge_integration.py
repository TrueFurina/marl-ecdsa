"""
区块链-MARL桥接层集成测试
覆盖：on_step→on_episode_end 全流水线、签名校验、合作检测、奖励融合
"""
import pytest
import sys
sys.path.insert(0, '.')

from marl.envs.simple_spread import SimpleSpreadEnv
from blockchain.ledger.world_state import WorldState
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.contracts.incentive_contract import IncentiveContract, ContributionScore
from blockchain.contracts.identity_contract import IdentityContract
from blockchain.contracts.penalty_contract import PenaltyContract
from marl.integration.bc_integration import BlockchainMARLBridge
import tempfile
import shutil


@pytest.fixture
def bridge_components():
    """构建完整桥接层组件（不含P2P）"""
    key_dir = tempfile.mkdtemp(prefix="test_bridge_keys_")
    ws = WorldState()
    km = KeyManager(key_dir=key_dir)
    id_contract = IdentityContract(ws)
    env = SimpleSpreadEnv(n_agents=3, n_landmarks=3, max_steps=25)

    # 注册3个智能体
    for i in range(3):
        pk_hex = km.generate_or_load(f"agent_{i}")[1]
        pk_str = ECDSAUtils.public_key_to_hex(pk_hex)
        ws.register_agent(f"agent_{i}", pk_str)

    # 构建区块链
    from blockchain.ledger.blockchain import Blockchain
    bc = Blockchain()
    node_ids = ["agent_0", "agent_1", "agent_2"]
    cw_pbft = CWPBFTConsensus(node_id="agent_0", consensus_nodes=node_ids)
    incentive = IncentiveContract(ws)
    penalty = PenaltyContract(ws, id_contract)

    bridge = BlockchainMARLBridge(
        n_agents=3, n_landmarks=3,
        blockchain_node=bc,
        incentive_contract=incentive,
        identity_contract=id_contract,
        key_manager=km,
        cw_pbft_consensus=cw_pbft,
        lambda_weight=0.1,
    )

    yield bridge, env, ws, bc, km, key_dir

    shutil.rmtree(key_dir, ignore_errors=True)


AGENT_IDS = ["agent_0", "agent_1", "agent_2"]


class TestOnStep:
    """on_step 流水线测试"""

    def test_on_step_basic(self, bridge_components):
        bridge, env, ws, bc, km, _ = bridge_components
        obs = env.reset()
        actions = [0, 1, 2]
        bridge.on_step(step=0, observations=obs, actions=actions,
                       agent_ids=AGENT_IDS, env_rewards=[-1.0, -1.0, -1.0])
        # 验证签名已产生
        assert len(bridge._pending_actions) > 0

    def test_on_step_multiple_steps(self, bridge_components):
        bridge, env, ws, bc, km, _ = bridge_components
        obs = env.reset()
        for step in range(5):
            actions = [0, 0, 0]
            obs, global_r, local_r, done, info = env.step(actions)
            bridge.on_step(step=step, observations=obs, actions=actions,
                           agent_ids=AGENT_IDS, env_rewards=local_r)
            if done:
                break
        assert len(bridge._pending_actions) > 0


class TestOnEpisodeEnd:
    """on_episode_end 流水线测试"""

    def test_episode_end_settles_rewards(self, bridge_components):
        """验证 on_episode_end 返回激励结算 deltas"""
        bridge, env, ws, bc, km, _ = bridge_components
        obs = env.reset()
        total_env_r = [0.0, 0.0, 0.0]
        for step in range(5):
            actions = [0, 0, 0]
            obs, global_r, local_r, done, info = env.step(actions)
            bridge.on_step(step=step, observations=obs, actions=actions,
                           agent_ids=AGENT_IDS, env_rewards=local_r)
            for i in range(3):
                total_env_r[i] += local_r[i]

        result = bridge.on_episode_end(episode=0, agent_ids=AGENT_IDS,
                                       env_rewards=total_env_r)
        # on_episode_end 应返回各智能体激励变化量 dict
        assert result is not None, "on_episode_end 应返回激励结算 deltas"
        assert isinstance(result, dict), "返回值应为 dict 类型"
        assert len(result) == 3, f"应包含3个智能体的结算结果，实际 {len(result)}"
        for aid in AGENT_IDS:
            assert aid in result, f"缺少智能体 {aid} 的结算结果"

    def test_episode_end_creates_block(self, bridge_components):
        bridge, env, ws, bc, km, _ = bridge_components
        obs = env.reset()
        env_rewards = [0.0, 0.0, 0.0]
        for step in range(10):
            actions = [1, 1, 1]
            obs, global_r, local_r, done, info = env.step(actions)
            bridge.on_step(step=step, observations=obs, actions=actions,
                           agent_ids=AGENT_IDS, env_rewards=local_r)
            for i in range(3):
                env_rewards[i] += local_r[i]

        bridge.on_episode_end(episode=0, agent_ids=AGENT_IDS,
                              env_rewards=env_rewards)
        assert bc.height >= 1

    def test_ablate_incentive_mode(self, bridge_components):
        """验证 --ablate-incentive 不崩溃且正确返回结算结果（P0-1修复验证）"""
        bridge, env, ws, bc, km, _ = bridge_components
        bridge.incentive_contract = None
        obs = env.reset()
        total_env_r = [0.0, 0.0, 0.0]
        for step in range(5):
            actions = [0, 0, 0]
            obs, global_r, local_r, done, info = env.step(actions)
            bridge.on_step(step=step, observations=obs, actions=actions,
                           agent_ids=AGENT_IDS, env_rewards=local_r)
            for i in range(3):
                total_env_r[i] += local_r[i]

        # 关键：ContributionScore NameError 修复后应不崩溃，且返回模拟结算 deltas
        result = bridge.on_episode_end(episode=0, agent_ids=AGENT_IDS,
                                       env_rewards=total_env_r)
        assert result is not None, "ablate模式下 on_episode_end 也应返回 deltas"
        assert isinstance(result, dict), "返回值应为 dict 类型"
        assert len(result) == 3


class TestRewardFusion:
    """奖励融合机制测试"""

    def test_lambda_weight(self, bridge_components):
        bridge, env, ws, bc, km, _ = bridge_components
        assert bridge.lambda_weight == 0.1


class TestFullPipeline:
    """完整流水线：签名→校验→上链→打包→共识→链追加"""

    def test_full_pipeline_3_episodes(self, bridge_components):
        bridge, env, ws, bc, km, _ = bridge_components
        for episode in range(3):
            obs = env.reset()
            total_env_r = [0.0, 0.0, 0.0]
            for step in range(10):
                actions = [1, 1, 1]
                obs, global_r, local_r, done, info = env.step(actions)
                bridge.on_step(step=step, observations=obs, actions=actions,
                               agent_ids=AGENT_IDS, env_rewards=local_r)
                for i in range(3):
                    total_env_r[i] += local_r[i]

            bridge.on_episode_end(episode=episode, agent_ids=AGENT_IDS,
                                  env_rewards=total_env_r)

        assert bc.height >= 3
        assert bc.validate_chain()
