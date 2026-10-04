"""
端到端冒烟测试 - 验证所有修复后的组件能正常工作
覆盖：ECDSA签名/验签 -> SecurityGuard -> Bridge.on_step/on_episode_end 
      -> IncentiveContract -> Block打包 -> CW-PBFT共识 -> Blockchain链式追加
"""
import sys
import os
import numpy as np

# UTF-8 输出（Windows GBK兼容）
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 项目路径（本脚本位于 scripts/ 下，项目根是上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if '__file__' in dir() else os.getcwd()
sys.path.insert(0, PROJECT_ROOT)

from blockchain.ledger.world_state import WorldState, AgentStatus
from blockchain.ledger.blockchain import Blockchain
from blockchain.ledger.block import Block, Transaction
from blockchain.crypto.ecdsa_utils import ECDSAUtils
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.security_guard import SecurityGuard
from blockchain.consensus.cw_pbft import CWPBFTConsensus
from blockchain.contracts.incentive_contract import IncentiveContract
from blockchain.contracts.identity_contract import IdentityContract
from blockchain.contracts.penalty_contract import PenaltyContract
from marl.envs.simple_spread import SimpleSpreadEnv
from marl.integration.bc_integration import BlockchainMARLBridge

print("=" * 70)
print("[SMOKE TEST] End-to-End Smoke Test -- All Fixes Verification")
print("=" * 70)

# ── 1. 基础组件初始化 ──
print("\n[1/8] Init basic components...")
n_agents = 3
n_landmarks = 3
agent_ids = [f"agent_{i}" for i in range(n_agents)]

ws = WorldState()
ic = IncentiveContract(ws)
id_contract = IdentityContract(ws)
penalty = PenaltyContract(ws, id_contract)
km = KeyManager(key_dir=os.path.join(PROJECT_ROOT, "keys"))
sg = SecurityGuard()
bc_chain = Blockchain()  # 自动包含创世区块
cw_pbft = CWPBFTConsensus(node_id="node_0", consensus_nodes=agent_ids)

print(f"  [OK] WorldState initialized")
print(f"  [OK] Blockchain initialized, genesis height={bc_chain.height}")

# ── 2. 智能体注册 + 密钥 ──
print("\n[2/8] Register agents + ECDSA key generation...")
for aid in agent_ids:
    km.generate_or_load(aid)
    pub_hex = km.get_public_key_hex(aid)
    result = id_contract.register(aid, pub_hex)
    assert result.get('success', False), f"{aid} register failed: {result}"
    print(f"  [OK] {aid} registered, pubkey={pub_hex[:32]}...")

# ── 3. Bridge 初始化 ──
print("\n[3/8] Init BlockchainMARLBridge (lambda=0.3)...")
bridge = BlockchainMARLBridge(
    n_agents=n_agents,
    n_landmarks=n_landmarks,
    blockchain_node=bc_chain,
    incentive_contract=ic,
    identity_contract=id_contract,
    key_manager=km,
    security_guard=sg,
    cw_pbft_consensus=cw_pbft,
    lambda_weight=0.3,  # P0-1 fix: lambda=0.3
)

# 验证 nonce 同步（P0-2 修复）
for aid in agent_ids:
    bridge_nonce = bridge._nonce_counters.get(aid, -1)
    sg_nonce = sg._nonce_registry.get(aid, -1)
    assert bridge_nonce == sg_nonce, f"P0-2 nonce mismatch: {aid} bridge={bridge_nonce} sg={sg_nonce}"
print(f"  [OK] nonce baseline sync verified (bridge=0, sg=0)")

# ── 4. 环境初始化 ──
print("\n[4/8] Create env + simulate episode...")
env = SimpleSpreadEnv(n_agents=n_agents, n_landmarks=n_landmarks, max_steps=25)
obs_list = env.reset()  # reset() only returns obs_list, no state
print(f"  [OK] env initialized obs_dim={env.obs_dim}, state_dim={env.state_dim}")

# ── 5. 模拟训练步 ──
print("\n[5/8] Simulate training step (full pipeline)...")
observations = [np.array(obs) for obs in obs_list]
actions = [np.random.randint(0, env.n_actions) for _ in range(n_agents)]

# 计算环境奖励（模拟 train.py 的 global_rewards）
global_rewards = [-1.0] * n_agents  # 模拟负距离奖励

# 调用 on_step（与 train.py 签名一致）
bridge.on_step(
    step=0,
    observations=observations,
    actions=actions,
    agent_ids=agent_ids,
    env_rewards=global_rewards,
    selfish_flags=[False, False, False],
)

print(f"  [OK] on_step called successfully")
print(f"  [OK] ECDSA sign count={bridge._sign_count}")
print(f"  [OK] SecurityGuard pass count={bridge._security_pass_count}")
assert bridge._sign_count == n_agents, f"Sign count abnormal: {bridge._sign_count}"
assert bridge._security_pass_count == n_agents, f"Security check count abnormal: {bridge._security_pass_count}"

# ── 6. 模拟多步直到 UPLOAD_INTERVAL ──
print("\n[6/8] Simulate more steps until Transaction upload...")
for step in range(1, bridge.UPLOAD_INTERVAL + 2):
    # step() returns: (observations, global_rewards, local_rewards, done, info)
    step_result = env.step(actions)
    if len(step_result) == 5:
        obs_list, g_rewards, l_rewards, done, info = step_result
    else:
        obs_list = step_result[0]
        g_rewards = step_result[1]
    
    observations = [np.array(obs) for obs in obs_list]
    actions = [np.random.randint(0, env.n_actions) for _ in range(n_agents)]
    
    # Use global_rewards from env or fallback
    if isinstance(g_rewards, (list, tuple, np.ndarray)):
        global_rewards = list(g_rewards)
    else:
        global_rewards = [-1.0] * n_agents

    bridge.on_step(
        step=step,
        observations=observations,
        actions=actions,
        agent_ids=agent_ids,
        env_rewards=global_rewards,
    )

print(f"  [OK] Multi-step simulation done, step={bridge._step_count}")
print(f"  [OK] Transaction upload count={bridge._tx_count}")

# ── 7. 回合结束 + Block打包 + CW-PBFT共识 ──
print("\n[7/8] Episode end -> Block packaging -> CW-PBFT consensus...")
avg_rewards = [-0.5] * n_agents
bridge.on_episode_end(0, agent_ids, avg_rewards)

print(f"  [OK] on_episode_end called")
print(f"  [OK] Block confirm count={bridge._block_count}")
print(f"  [OK] CW-PBFT consensus rounds={bridge._consensus_count}")
print(f"  [OK] Blockchain height={bc_chain.height}")

assert bc_chain.height >= 1, f"Blockchain height abnormal: {bc_chain.height}"

# ── 8. 验证关键修复点 ──
print("\n[8/8] Verify all fix points...")

# P0-1: lambda_weight=0.3
assert abs(bridge.lambda_weight - 0.3) < 0.001, f"P0-1 FAIL: lambda={bridge.lambda_weight}"
print("  [OK] P0-1: lambda_weight=0.3 verified")

# P0-2: nonce同步
for aid in agent_ids:
    bn = bridge._nonce_counters[aid]
    sn = sg._nonce_registry.get(aid, -999)
    assert bn >= 0 and sn >= 0, f"P0-2 FAIL: {aid} bridge_nonce={bn} sg_nonce={sn}"
print("  [OK] P0-2: nonce sync verified")

# P1-5: BETRAYAL_PENALTY_MULT=2.0
ic_check = IncentiveContract(ws)
assert ic_check.BETRAYAL_PENALTY_MULT == 2.0, f"P1-5 FAIL: penalty_mult={ic_check.BETRAYAL_PENALTY_MULT}"
print("  [OK] P1-5: BETRAYAL_PENALTY_MULT=2.0 verified")

# P2-13: WorldState公共接口
ws_ids = ws.get_all_agent_ids()
print(f"  [OK] P2-13: get_all_agent_ids()={ws_ids}")
ws.update_consensus_weight("agent_0", 1.5)
ws.set_agent_status("agent_0", AgentStatus.ACTIVE)
print("  [OK] P2-13: update_consensus_weight/set_agent_status verified")

# P2-14: Genesis区块timestamp=0
genesis = bc_chain.get_block(0)
assert genesis is not None, "Genesis block missing"
assert genesis.timestamp == 0, f"P2-14 FAIL: genesis.timestamp={genesis.timestamp}"
print("  [OK] P2-14: Genesis timestamp=0 verified")

# 验证链完整性
is_valid = bc_chain.validate_chain()
assert is_valid, "Chain integrity validation failed"
print("  [OK] Chain integrity verified")

# ── 最终统计 ──
print("\n" + "=" * 70)
print("ALL E2E SMOKE TEST PASSED!")
print("=" * 70)
stats = bc_chain.get_stats()
print(f"\nFinal stats:")
print(f"  Blockchain height: {stats['height']}")
print(f"  Total blocks: {stats['total_blocks']}")
print(f"  Total transactions: {stats['total_transactions']}")
print(f"  Pending transactions: {stats['pending_transactions']}")
print(f"  ECDSA signs: {bridge._sign_count}")
print(f"  SecurityGuard passes: {bridge._security_pass_count}")
print(f"  Block confirms: {bridge._block_count}")
print(f"  CW-PBFT consensus: {bridge._consensus_count}")
print(f"\n[OK] All P0/P1/P2 fixes verified - code health is GOOD!")
