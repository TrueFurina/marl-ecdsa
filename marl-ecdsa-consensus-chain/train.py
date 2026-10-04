"""
端到端训练入口（优化版）
集成 MARL QMIX 算法 + 区块链激励双向协同

核心修复（vs 原版）：
1. on_episode_end 新 API：传入 agent_ids 和 episode_rewards，在回合结束时统一结算
2. 奖励计算：使用 _bc_rewards（本回合 delta）而非 _bc_scores（累计积分）
3. 经验回放：episode_rewards 正确存储含区块链激励的 total_rewards
4. 合作率统计：基于回合内累积判断，而非单步快照
"""
import argparse
import json
import logging
import os
import sys
import time
import numpy as np
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any

sys.path.insert(0, str(Path(__file__).parent))

from marl.envs.simple_spread import SimpleSpreadEnv
from marl.integration.bc_integration import BlockchainMARLBridge
from marl.integration.selfish_agent import SelfishAgentWrapper, create_agents
from marl.algorithms.qmix import QMIXTrainer, HAS_TORCH
from marl.algorithms.mappo import MAPPOTrainer
from marl.integration.consensus_shaper import ConsensusRewardShaper

from blockchain.ledger.world_state import WorldState
from blockchain.ledger.blockchain import Blockchain
from blockchain.contracts.incentive_contract import IncentiveContract
from blockchain.contracts.penalty_contract import PenaltyContract
from blockchain.contracts.identity_contract import IdentityContract
from blockchain.crypto.key_manager import KeyManager
from blockchain.crypto.security_guard import SecurityGuard
from blockchain.consensus.cw_pbft import CWPBFTConsensus
from marl.analysis.nash_verifier import NashEquilibriumVerifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('train')


class TrainingConfig:
    def __init__(self, **kwargs):
        self.n_agents: int = kwargs.get('n_agents', 3)
        self.n_landmarks: int = kwargs.get('n_landmarks', 3)
        self.hidden_dim: int = kwargs.get('hidden_dim', 128)
        self.lr: float = kwargs.get('lr', 1e-3)
        self.gamma: float = kwargs.get('gamma', 0.8)
        self.epsilon_start: float = kwargs.get('epsilon_start', 1.0)
        self.epsilon_end: float = kwargs.get('epsilon_end', 0.05)
        self.epsilon_decay: int = kwargs.get('epsilon_decay', 5000)
        self.batch_size: int = kwargs.get('batch_size', 64)
        self.n_episodes: int = kwargs.get('n_episodes', 500)
        self.max_steps: int = kwargs.get('max_steps', 25)
        self.lambda_weight: float = kwargs.get('lambda_weight', 0.1)
        self.upload_interval: int = kwargs.get('upload_interval', 10)
        self.selfish_ratio: float = kwargs.get('selfish_ratio', 0.0)
        self.betrayal_mode: str = kwargs.get('betrayal_mode', 'random')  # 'greedy'=理性自私 | 'random'=随机背叛（旧行为）
        # greedy 一步贪心假设的每步位移。默认 0.5 = 沿用历史行为（实为"力的量级"，
        # 而环境真实稳态位移约 0.05，见 SimpleSpreadEnv: dt=0.1/damping=0.25/max_speed=0.5）。
        # 0.05 为校准值；改此值会改变 greedy 智能体行为，仅影响 selfish_ratio>0 的实验。
        self.greedy_step: float = kwargs.get('greedy_step', 0.5)
        self.mode: str = kwargs.get('mode', 'bc_marl')
        self.seed: int = kwargs.get('seed', 42)
        self.log_interval: int = kwargs.get('log_interval', 10)
        self.save_interval: int = kwargs.get('save_interval', 100)
        self.use_p2p: bool = kwargs.get('use_p2p', False)  # 是否使用P2P网络共识
        # ── 消融实验开关（P0-3）──
        self.ablate_security: bool = kwargs.get('ablate_security', False)
        self.ablate_consensus: bool = kwargs.get('ablate_consensus', False)
        # 路线C：参与率驱动权重展宽（默认关闭，保持旧实验可复现）
        self.weight_broadening: bool = kwargs.get('weight_broadening', False)
        # 训练内省略故障注入（默认0=关闭；与NR-82省略故障模型一致）
        self.omission_ratio: float = kwargs.get('omission_ratio', 0.0)
        self.omission_seed: int = kwargs.get('omission_seed', 0)
        self.ablate_incentive: bool = kwargs.get('ablate_incentive', False)
        # ── P2-E 新增：自适应λ / Nash验证开关 ──
        self.adaptive_lambda: bool = kwargs.get('adaptive_lambda', True)  # 默认启用
        self.verify_nash: bool = kwargs.get('verify_nash', True)  # 默认启用
        # ── Tier1 新增：算法选择 iql/vdn/qmix ──
        self.algorithm: str = kwargs.get('algorithm', 'iql')
        # ── Tier1 新增：共识感知奖励塑形 (CARS) ──
        self.consensus_shaping: bool = kwargs.get('consensus_shaping', False)  # 默认关闭，需显式启用
        self.shaping_eta: float = kwargs.get('shaping_eta', 0.05)


class TrainingStats:
    def __init__(self):
        self.episode_rewards: List[float] = []      # 总训练奖励（含BC激励）
        self.env_rewards: List[float] = []           # [v3.7] 纯环境奖励（不含BC激励，用于公平对比）
        self.episode_lengths: List[int] = []
        self.bc_scores_history: List[Dict[str, float]] = []
        self.cooperation_rates: List[float] = []
        self.betrayal_rates: List[float] = []
        self.losses: List[float] = []
        self.elapsed_time: float = 0.0
        self.lambda_history: List[float] = []       # [P2-E] 自适应λ变化历史

    def record_episode(self, total_reward, length, bc_scores, coop_rate, betrayal_rate=0.0, env_reward=None, lambda_value=None):
        self.episode_rewards.append(total_reward)
        self.episode_lengths.append(length)
        self.bc_scores_history.append(dict(bc_scores))
        self.cooperation_rates.append(coop_rate)
        self.betrayal_rates.append(betrayal_rate)
        # env_reward: 纯环境奖励（用于纯MARL vs BC-MARL 公平对比）
        self.env_rewards.append(env_reward if env_reward is not None else total_reward)
        # [P2-E] 自适应λ历史
        self.lambda_history.append(lambda_value if lambda_value is not None else 0.1)

    def record_loss(self, loss):
        if loss is not None:
            self.losses.append(loss)

    def summary(self, window=50):
        recent_r = self.episode_rewards[-window:] if len(self.episode_rewards) >= window else self.episode_rewards
        recent_c = self.cooperation_rates[-window:] if len(self.cooperation_rates) >= window else self.cooperation_rates
        recent_env = self.env_rewards[-window:] if len(self.env_rewards) >= window else self.env_rewards
        return {
            'total_episodes': len(self.episode_rewards),
            'avg_reward': float(np.mean(self.episode_rewards)) if self.episode_rewards else 0.0,
            'avg_reward_last_{}'.format(window): float(np.mean(recent_r)) if recent_r else 0.0,
            'avg_env_reward': float(np.mean(self.env_rewards)) if self.env_rewards else 0.0,  # [v3.7]
            'avg_env_reward_last_{}'.format(window): float(np.mean(recent_env)) if recent_env else 0.0,  # [v3.7]
            'avg_cooperation_rate': float(np.mean(self.cooperation_rates)) if self.cooperation_rates else 0.0,
            'avg_betrayal_rate': float(np.mean(self.betrayal_rates)) if self.betrayal_rates else 0.0,
            'total_losses': len(self.losses),
            'elapsed_time': self.elapsed_time,
        }


class MARLBlockchainTrainer:
    def __init__(self, config: TrainingConfig):
        self.config = config
        self.stats = TrainingStats()
        np.random.seed(config.seed)

        self.env = SimpleSpreadEnv(n_agents=config.n_agents, n_landmarks=config.n_landmarks, max_steps=config.max_steps)
        self.agent_ids = [f"agent_{i}" for i in range(config.n_agents)]

        self._init_blockchain_components()
        self._init_trainer()
        self._init_network()
        self._init_bridge()
        self._init_selfish_agents()
        self._init_consensus_shaper()

        logger.info(f"[Trainer] 初始化完成，模式={config.mode}, 智能体={config.n_agents}")
        logger.info(f"[Trainer] 环境: obs_dim={self.env.obs_dim}, actions={self.env.n_actions}")

    def _init_blockchain_components(self):
        """初始化区块链基础组件（合约/账本/共识）"""
        c = self.config
        self.world_state = WorldState()
        self.incentive_contract = IncentiveContract(self.world_state)
        self.identity_contract = IdentityContract(self.world_state)
        self.penalty_contract = PenaltyContract(self.world_state, self.identity_contract)
        self.key_manager = KeyManager(key_dir="./keys")
        self.security_guard = SecurityGuard() if not c.ablate_security else None
        # 09-28 接线修复：注入 identity_contract，使交易级 ECDSA 验签在主链路真实生效。
        # 此前未注入 → blockchain.py:_validate_new_block 中整段 ECDSA 验签被
        # `if self._identity_contract is not None` 跳过（空签名/verified=False 仅打 debug 日志、不拦截）。
        # 消融模式（ablate_security）下不注入：消融即移除安全层，同时保证既有消融实验
        # （results/ablation/、NR e4/e9 条目）行为与结论保持可复现。
        self.blockchain = Blockchain(
            identity_contract=None if c.ablate_security else self.identity_contract
        )
        self.cw_pbft = CWPBFTConsensus(node_id="consensus_node_0", consensus_nodes=self.agent_ids)
        if c.ablate_security:
            logger.info("[Trainer] 消融模式：SecurityGuard 已禁用")
        if c.ablate_incentive:
            self.incentive_contract = None
            logger.info("[Trainer] 消融模式：IncentiveContract 已禁用")

    def _init_trainer(self):
        """初始化 MARL 训练器"""
        c = self.config
        if c.algorithm == 'mappo':
            # MAPPO：on-policy 策略梯度（第四算法，接口与 QMIXTrainer 对齐）
            self.trainer = MAPPOTrainer(
                n_agents=c.n_agents, obs_dim=self.env.obs_dim, state_dim=self.env.state_dim,
                n_actions=self.env.n_actions, hidden_dim=c.hidden_dim, lr=c.lr, gamma=c.gamma,
            )
        else:
            self.trainer = QMIXTrainer(
                n_agents=c.n_agents, obs_dim=self.env.obs_dim, state_dim=self.env.state_dim,
                n_actions=self.env.n_actions, hidden_dim=c.hidden_dim, lr=c.lr, gamma=c.gamma,
                epsilon_start=c.epsilon_start, epsilon_end=c.epsilon_end, epsilon_decay=c.epsilon_decay,
                algorithm=c.algorithm,
            )
        self._register_agents()

    def _init_network(self):
        """初始化 P2P 网络（可选）"""
        self.p2p_network = None
        if self.config.use_p2p and self.config.mode != 'pure_marl':
            try:
                from blockchain.network.network_consensus import P2PConsensusNetwork
                self.p2p_network = P2PConsensusNetwork(n_nodes=self.config.n_agents, base_port=7001)
                self.p2p_network.start()
                logger.info(f"[Trainer] P2P网络共识已启用 - {self.config.n_agents} 节点")
            except Exception as e:
                logger.warning(f"[Trainer] P2P网络启动失败: {e}")
                self.p2p_network = None

    def _init_bridge(self):
        """初始化区块链-MARL 桥接层"""
        c = self.config
        if c.mode == 'pure_marl':
            self.bridge = None
            return
        self.bridge = BlockchainMARLBridge(
            n_agents=c.n_agents, n_landmarks=c.n_landmarks,
            blockchain_node=self.blockchain, incentive_contract=self.incentive_contract,
            identity_contract=self.identity_contract, key_manager=self.key_manager,
            security_guard=self.security_guard, cw_pbft_consensus=self.cw_pbft,
            lambda_weight=c.lambda_weight, ablate_consensus=c.ablate_consensus,
            weight_broadening=c.weight_broadening,
            omission_ratio=c.omission_ratio, omission_seed=c.omission_seed,
        )
        if c.weight_broadening:
            logger.info("[Trainer] 参与率权重展宽已启用（路线C，纪元=%d轮）",
                        self.cw_pbft.EPOCH_ROUNDS if self.cw_pbft else 50)
        self.bridge.UPLOAD_INTERVAL = c.upload_interval
        if not c.adaptive_lambda:
            self.bridge._adaptive_lambda = None
            logger.info("[Trainer] 自适应λ已禁用")
        if self.p2p_network is not None:
            self.bridge.enable_p2p_consensus(self.p2p_network)

    def _init_selfish_agents(self):
        """初始化自私智能体封装"""
        c = self.config
        self.selfish_wrappers = self._init_selfish_wrappers() if (c.mode == 'selfish' and c.selfish_ratio > 0) else None

    def _init_consensus_shaper(self):
        """初始化共识感知奖励塑形器 (CARS)"""
        c = self.config
        self.consensus_shaper = None
        if c.consensus_shaping and c.mode != 'pure_marl':
            self.consensus_shaper = ConsensusRewardShaper(
                n_agents=c.n_agents, eta=c.shaping_eta, gamma=c.gamma, n_landmarks=c.n_landmarks,
            )
            logger.info(f"[Trainer] 共识感知奖励塑形已启用 (eta={c.shaping_eta})")

    def _register_agents(self):
        for agent_id in self.agent_ids:
            self.key_manager.generate_or_load(agent_id)
            pub_key_hex = self.key_manager.get_public_key_hex(agent_id)
            result = self.identity_contract.register(agent_id, pub_key_hex)
            if not result.get('success', False):
                logger.warning(f"[Trainer] {agent_id} 注册失败: {result.get('error', '')}")

    def _init_selfish_wrappers(self):
        # 修正：确保至少1个自私智能体（int(3*0.3)=0 的 bug）
        n_selfish = max(1, round(self.config.n_agents * self.config.selfish_ratio))
        wrappers = []
        for i in range(self.config.n_agents):
            aid = self.agent_ids[i]
            is_selfish = i < n_selfish
            wrapper = SelfishAgentWrapper(
                agent_id=aid,
                base_agent=self.trainer.agents[i] if HAS_TORCH else None,
                is_selfish=is_selfish,
                betrayal_prob=0.3 if is_selfish else 0.0,
                n_landmarks=self.config.n_landmarks,
                betrayal_mode=self.config.betrayal_mode if is_selfish else 'random',
                greedy_step=getattr(self.config, 'greedy_step', 0.5),
            )
            wrappers.append(wrapper)
        logger.info(f"[Trainer] 创建 {n_selfish}/{self.config.n_agents} 个自私智能体")
        return wrappers

    # -------------------------------------------------------------------------
    # 主训练循环
    # -------------------------------------------------------------------------

    def train(self):
        config = self.config
        start_time = time.time()

        logger.info("=" * 60)
        logger.info(f"训练开始 | 模式={config.mode} | 回合数={config.n_episodes}")
        logger.info("=" * 60)

        for episode in range(1, config.n_episodes + 1):
            ep_stats = self._run_episode(episode)

            self.stats.record_episode(
                total_reward=ep_stats['total_reward'],
                length=ep_stats['length'],
                bc_scores=ep_stats.get('bc_scores', {}),
                coop_rate=ep_stats['cooperation_rate'],
                betrayal_rate=ep_stats.get('betrayal_rate', 0.0),
                env_reward=ep_stats.get('env_reward_sum'),  # [v3.7] 纯环境奖励
                lambda_value=ep_stats.get('lambda_value'),  # [P2-E] 自适应λ值
            )

            loss = self.trainer.train_step(batch_size=config.batch_size)
            self.stats.record_loss(loss)

            if episode % config.log_interval == 0:
                self._log_progress(episode)

        self.stats.elapsed_time = time.time() - start_time
        logger.info("=" * 60)
        logger.info(f"训练完成 | 耗时={self.stats.elapsed_time:.1f}s")
        logger.info(f"最终统计: {json.dumps(self.stats.summary(), indent=2, default=str)}")
        logger.info("=" * 60)
        return self.stats

    def _step_agent_decisions(self, observations, hidden_states):
        """智能体决策：获取动作（含自私智能体替换逻辑）"""
        config = self.config
        if self.selfish_wrappers is not None:
            base_actions, base_hiddens = self.trainer.get_actions(observations, hidden_states)
            actions = list(base_actions)
            new_hiddens = list(base_hiddens)
            for i, wrapper in enumerate(self.selfish_wrappers):
                if not wrapper.is_selfish:
                    continue
                if wrapper.betrayal_mode == 'greedy':
                    # 理性自私：贪心策略直接决定动作（不掷骰子）
                    actions[i], new_hiddens[i] = wrapper.step(observations[i], new_hiddens[i])
                    logger.debug(f"[Selfish] {wrapper.agent_id} 贪心决策: action={actions[i]}")
                elif wrapper.should_betray():
                    # 随机背叛（旧行为）
                    actions[i] = np.random.randint(0, self.env.n_actions)
                    logger.debug(f"[Selfish] {wrapper.agent_id} 背叛: 原动作={base_actions[i]} → {actions[i]}")
        else:
            actions, new_hiddens = self.trainer.get_actions(observations, hidden_states)
        return actions, new_hiddens

    def _step_bc_bridge(self, step, episode, observations, actions, local_rewards):
        """区块链桥接：记录行为、检测合作、叠加塑形奖励"""
        config = self.config
        betrayal_flags = [False] * config.n_agents
        if self.selfish_wrappers is not None:
            for i, w in enumerate(self.selfish_wrappers):
                if w.is_selfish:
                    betrayal_flags[i] = w.should_betray()

        self.bridge.on_step(
            step=step + episode * config.max_steps,
            observations=observations,
            actions=actions,
            agent_ids=self.agent_ids,
            env_rewards=[0.0] * config.n_agents,  # bridge 此时只关心签名和检测
            selfish_flags=betrayal_flags,
            # 2026-09-22：合作率必须是**行为学**口径。
            # legacy 口径下 greedy 智能体每步都被标记背叛 → 合作率退化为
            # "未被标记的步数占比"，用它比较背叛模式 = 循环论证。
            behavioral_only=True,
        )

        coop_status = self.bridge.get_cooperation_status()
        total_rewards = list(local_rewards)

        # 共识感知奖励塑形
        if self.consensus_shaper is not None:
            shaping_rewards = self.consensus_shaper.shape_reward(
                observations=observations,
                next_observations=observations,  # 当前步用当前观测近似
                actions=actions,
                agent_ids=self.agent_ids,
                verification_status=[True] * config.n_agents,
                cooperation_status=coop_status,
                contribution_scores=self.bridge.get_bc_scores(),
                consensus_weights=self._get_consensus_weights(),
            )
            for i in range(config.n_agents):
                total_rewards[i] += shaping_rewards[i]

        return total_rewards, coop_status, betrayal_flags

    def _get_consensus_weights(self):
        """获取CW-PBFT共识权重"""
        try:
            if hasattr(self.cw_pbft, 'get_weights'):
                return self.cw_pbft.get_weights()
        except Exception:
            pass
        return {}

    def _step_pure_marl(self, observations, local_rewards):
        """纯MARL：无区块链激励，仅环境奖励"""
        config = self.config
        total_rewards = list(local_rewards)
        coop_count = 0
        for i, aid in enumerate(self.agent_ids):
            try:
                obs = np.array(observations[i], dtype=float)
                n_lm = config.n_landmarks
                lm_rel = obs[4:4 + 2 * n_lm].reshape(-1, 2)
                if min(float(np.linalg.norm(lm_rel[j])) for j in range(n_lm)) < 0.5:
                    coop_count += 1
            except (ValueError, IndexError, TypeError):
                pass
        return total_rewards, coop_count

    def _episode_end_settlement(self, episode, episode_rewards, episode_local_rewards, total_steps):
        """回合结束：激励结算 + BC均匀分配"""
        config = self.config
        if self.bridge is None:
            return

        # 计算各智能体平均局部奖励
        ep_avg_rewards = [0.0] * config.n_agents
        if episode_local_rewards:
            for lr_list in episode_local_rewards:
                for i in range(config.n_agents):
                    ep_avg_rewards[i] += lr_list[i]
            ep_avg_rewards = [r / len(episode_local_rewards) for r in ep_avg_rewards]

        self.bridge.on_episode_end(episode, self.agent_ids, ep_avg_rewards)

        # BC激励均匀分配到每一步
        if total_steps > 0 and not config.ablate_incentive:
            bc_deltas = self.bridge.get_bc_rewards()
            for t in range(total_steps):
                step_rewards = list(episode_rewards[t])
                for i, aid in enumerate(self.agent_ids):
                    is_selfish = (
                        self.selfish_wrappers is not None
                        and self.selfish_wrappers[i].is_selfish
                    )
                    if not is_selfish:
                        delta = bc_deltas.get(aid, 0.0)
                        step_rewards[i] += config.lambda_weight * delta / float(total_steps)
                episode_rewards[t] = step_rewards

    def _run_episode(self, episode: int):
        """执行一个训练回合"""
        config = self.config
        observations = self.env.reset()
        hidden_states = self.trainer.init_hidden()

        # 每回合重置塑形器势能
        if self.consensus_shaper is not None:
            self.consensus_shaper.reset()

        # 回合内数据收集
        episode_obs, episode_actions, episode_rewards = [], [], []
        episode_next_obs, episode_states = [], []
        episode_global_rewards, episode_local_rewards = [], []
        episode_states.append(self.env.get_state())

        coop_count = betrayal_count = total_steps = 0
        episode_env_reward_sum = 0.0

        for step in range(config.max_steps):
            total_steps += 1

            # 1. 智能体决策
            actions, new_hiddens = self._step_agent_decisions(observations, hidden_states)

            # 2. 执行环境
            next_observations, global_rewards, local_rewards, done, info = self.env.step(actions)
            episode_states.append(self.env.get_state())

            # 3. 区块链桥接 / 纯MARL
            if self.bridge is not None:
                total_rewards, coop_status, step_betray_flags = self._step_bc_bridge(
                    step, episode, observations, actions, local_rewards)
                # 合作 = 行为学判定（距任意路标 < 阈值），与"是否被标记背叛"无关
                coop_count += sum(1 for v in coop_status.values() if v is True)
                # 背叛 = 本步实际被标记背叛的智能体数（独立记账，不再混入合作率）
                betrayal_count += sum(1 for v in step_betray_flags if v)
            else:
                total_rewards, step_coop = self._step_pure_marl(observations, local_rewards)
                coop_count += step_coop

            # 4. 存储经验
            episode_obs.append(observations)
            episode_actions.append(actions)
            episode_rewards.append(total_rewards)
            episode_next_obs.append(next_observations)
            episode_global_rewards.append(list(global_rewards))
            episode_local_rewards.append(list(local_rewards))
            episode_env_reward_sum += sum(local_rewards)

            observations = next_observations
            hidden_states = new_hiddens
            if done:
                break

        # 5. 回合结束：结算激励
        self._episode_end_settlement(episode, episode_rewards, episode_local_rewards, total_steps)

        # 6. 存入经验回放
        episode_total_reward = sum(sum(r) for r in episode_rewards)
        self.trainer.store_episode({
            'observations': episode_obs,
            'actions': episode_actions,
            'rewards': episode_rewards,
            'next_observations': episode_next_obs,
            'state_list': episode_states,
            'done': done,
        })

        # 7. 统计
        bc_scores = self.bridge.get_bc_scores() if self.bridge else {}
        n_total = max(1, config.n_agents * total_steps)

        return {
            'total_reward': episode_total_reward,
            'env_reward_sum': episode_env_reward_sum,
            'length': total_steps,
            'bc_scores': bc_scores,
            'cooperation_rate': coop_count / n_total,
            'betrayal_rate': betrayal_count / n_total,
            'lambda_value': self.bridge.lambda_weight if self.bridge else None,
            'shaping_stats': self.consensus_shaper.get_stats() if self.consensus_shaper else None,
        }

    def _log_progress(self, episode: int):
        window = min(50, episode)
        summary = self.stats.summary(window=window)
        eps = self.trainer.epsilon

        bc_info = ""
        if self.bridge is not None:
            rewards = self.bridge.get_bc_rewards()
            avg_reward = float(np.mean(list(rewards.values()))) if rewards else 0.0
            bc_info = f"  BC奖励={avg_reward:.1f}"

        logger.info(
            f"[E{episode:4d}/{self.config.n_episodes}] "
            f"ε={eps:.3f} "
            f"AvgR({window})={summary.get(f'avg_reward_last_{window}', summary.get('avg_reward', 0.0)):.2f} "
            f"合作={summary['avg_cooperation_rate']:.1%}"
            + bc_info
        )

    # -------------------------------------------------------------------------
    # 导出
    # -------------------------------------------------------------------------

    def export_results(self, filepath='training_results.json'):
        summary = self.stats.summary()
        result = {
            'comparison_note': '竞赛对比统一使用 env_reward 口径（不含 BC 激励）；权威提升幅度以 number_registry 登记值为准',
            'config': vars(self.config),
            'summary': summary,
            'episode_rewards': self.stats.episode_rewards,           # 总奖励（含BC激励）
            'env_rewards': self.stats.env_rewards,                  # [v3.7] 纯环境奖励（公平对比）
            'cooperation_rates': self.stats.cooperation_rates,
            'betrayal_rates': self.stats.betrayal_rates,
            'bc_scores_history': self.stats.bc_scores_history,
            'losses': [l for l in self.stats.losses if l is not None],
            'bc_scores_final': self.bridge.get_bc_scores() if self.bridge else {},
            'lambda_history': self.stats.lambda_history,  # [P2-E] 自适应λ变化曲线
            'consensus_shaping_stats': self.consensus_shaper.get_stats() if self.consensus_shaper else None,  # [Tier1] CARS
        }
        if self.bridge is not None:
            try:
                result['leaderboard'] = [
                    {'agent_id': a, 'score': s}
                    for a, s in self.incentive_contract.get_leaderboard()
                ]
            except Exception as e:
                logger.warning(f"导出排行榜失败: {e}")
                result['leaderboard'] = []

            # ── v2集成版：导出区块链流水线数据 ──
            try:
                bridge_stats = self.bridge.get_stats()
                result['ecdsa_stats'] = {
                    'sign_count': bridge_stats.get('ecdsa_sign_count', 0),
                    'verify_count': bridge_stats.get('ecdsa_verify_count', 0),
                }
                result['security_stats'] = self.bridge.get_security_stats()
                result['consensus_stats'] = self.bridge.get_consensus_stats()
                result['blockchain_stats'] = self.bridge.get_blockchain_stats()
            except Exception as e:
                logger.debug(f"[Trainer] 集成统计导出异常: {e}")
                result['ecdsa_stats'] = {'sign_count': 0, 'verify_count': 0}
                result['security_stats'] = {'total_alerts': 0, 'danger_agents': []}
                result['consensus_stats'] = {'state': 'N/A', 'n_nodes': 0}
                result['blockchain_stats'] = {'height': 0, 'total_transactions': 0}

            # ── P2-E：自适应λ统计 ──
            if self.bridge and self.bridge._adaptive_lambda is not None:
                try:
                    result['adaptive_lambda_stats'] = self.bridge._adaptive_lambda.get_stats()
                    result['adaptive_lambda_history'] = self.bridge._adaptive_lambda.get_adaptation_history()
                except Exception as e:
                    logger.debug(f"[Trainer] 自适应λ统计导出异常: {e}")

            # ── 路线C：参与率权重展宽统计（实验聚合的落盘依据）──
            if self.cw_pbft is not None:
                try:
                    eng = self.cw_pbft
                    weights = eng.get_weights()
                    vals = list(weights.values())
                    total_w = sum(vals) or 1.0
                    omissions = self.bridge.get_omission_nodes() if self.bridge else set()
                    n_succ = eng.consensus_success_count
                    n_fail = eng.consensus_fail_count
                    result['weight_broadening_stats'] = {
                        'enabled': self.bridge.weight_broadening if self.bridge else False,
                        'omission_ratio': self.bridge.omission_ratio if self.bridge else 0.0,
                        'omission_nodes': sorted(omissions),
                        'consensus_success_rate': n_succ / max(1, n_succ + n_fail),
                        'consensus_success_count': n_succ,
                        'consensus_fail_count': n_fail,
                        'epochs_triggered': eng._epoch_index,
                        'honest_weight_share': sum(
                            w for nid, w in weights.items() if nid not in omissions
                        ) / total_w,
                        'weight_max': max(vals) if vals else 0.0,
                        'weight_min': min(vals) if vals else 0.0,
                        'weights': weights,
                    }
                except Exception as e:
                    logger.debug(f"[Trainer] 展宽统计导出异常: {e}")
        else:
            result['leaderboard'] = []

        # ── P2-E：Nash均衡验证报告（在JSON写入之前执行，确保路径写入JSON）──
        nash_report_path = None
        if self.config.verify_nash and self.config.mode != 'pure_marl':
            try:
                verifier = NashEquilibriumVerifier(
                    lambda_weight=self.config.lambda_weight,
                )
                report = verifier.generate_report(n_agents=self.config.n_agents)
                nash_report_path = os.path.join(
                    os.path.dirname(filepath) or '.', 
                    'nash_equilibrium_report.md'
                )
                with open(nash_report_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                logger.info(f"[Trainer] Nash均衡验证报告已生成: {nash_report_path}")
                result['nash_report_path'] = nash_report_path
            except Exception as e:
                logger.warning(f"[Trainer] Nash验证报告生成失败: {e}")

        # 防御：导出前确保父目录存在（避免相对路径/CWD 错位导致落盘失败）
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"[Trainer] 结果已导出: {filepath}")

        # 自动生成图表
        try:
            from visualization.plot_results import generate_all_plots
            plot_dir = os.path.join(os.path.dirname(filepath) or '.', 'plots')
            generate_all_plots(filepath, plot_dir)
        except Exception as e:
            logger.warning(f"图表生成失败: {e}")

        return result

    def cleanup(self):
        """清理资源（P2P网络等）"""
        if self.p2p_network is not None:
            try:
                self.p2p_network.stop()
                logger.info("[Trainer] P2P网络已停止")
            except Exception as e:
                logger.warning(f"[Trainer] P2P网络停止异常: {e}")
            self.p2p_network = None


# =============================================================================
# 命令行入口
# =============================================================================

def load_config_defaults(mode: str = 'bc_marl') -> dict:
    """从 config.json 加载指定模式的默认参数（P2-A：统一配置源）"""
    config_path = Path(__file__).parent / 'config.json'
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = json.load(f)
        mode_cfg = raw_config.get('modes', {}).get(mode, {})
        defaults = {
            'n_agents': mode_cfg.get('n_agents', 3),
            'n_landmarks': mode_cfg.get('n_landmarks', 3),
            'n_episodes': mode_cfg.get('n_episodes', 1000),
            'max_steps': mode_cfg.get('max_steps', 25),
            'hidden_dim': mode_cfg.get('hidden_dim', 128),
            'lr': mode_cfg.get('lr', 1e-3),
            'gamma': mode_cfg.get('gamma', 0.8),
            'batch_size': mode_cfg.get('batch_size', 64),
            'epsilon_decay': mode_cfg.get('epsilon_decay', 5000),
            'lambda_weight': mode_cfg.get('lambda_weight', 0.1),
            'upload_interval': mode_cfg.get('upload_interval', 10),
            'selfish_ratio': mode_cfg.get('selfish_ratio', 0.0),
            'seed': mode_cfg.get('seed', 42),
            'log_interval': mode_cfg.get('log_interval', 10),
        }
        logger.info(f"[Config] 从 config.json 加载 {mode} 模式默认值: lambda={defaults['lambda_weight']}")
        return defaults
    except Exception as e:
        logger.warning(f"[Config] 加载 config.json 失败 ({e})，使用硬编码默认值")
        return {
            'n_agents': 3, 'n_landmarks': 3, 'n_episodes': 1000, 'max_steps': 25,
            'hidden_dim': 128, 'lr': 1e-3, 'gamma': 0.8, 'batch_size': 64,
            'epsilon_decay': 5000, 'lambda_weight': 0.1, 'upload_interval': 10,
            'selfish_ratio': 0.0, 'seed': 42, 'log_interval': 10,
        }


def parse_args():
    # P2-A: 从 config.json 读取默认值，CLI 参数仍可 override
    defaults = load_config_defaults('bc_marl')

    parser = argparse.ArgumentParser(description='MARL-ECDSA 共识链')
    parser.add_argument('--mode', type=str, default='bc_marl',
                        choices=['pure_marl', 'bc_marl', 'selfish'],
                        help='训练模式 (默认从config.json读取对应参数)')
    parser.add_argument('--n_agents', type=int, default=defaults['n_agents'])
    parser.add_argument('--n_landmarks', type=int, default=defaults['n_landmarks'])
    parser.add_argument('--n_episodes', type=int, default=defaults['n_episodes'])
    parser.add_argument('--max_steps', type=int, default=defaults['max_steps'])
    parser.add_argument('--hidden_dim', type=int, default=defaults['hidden_dim'])
    parser.add_argument('--lr', type=float, default=defaults['lr'])
    parser.add_argument('--gamma', type=float, default=defaults['gamma'])
    parser.add_argument('--batch_size', type=int, default=defaults['batch_size'])
    parser.add_argument('--lambda_weight', type=float, default=defaults['lambda_weight'],
                        help='区块链激励权重λ (从config.json读取，竞赛基准λ=0.1，X5裁决)')
    parser.add_argument('--upload_interval', type=int, default=defaults['upload_interval'])
    parser.add_argument('--selfish_ratio', type=float, default=defaults['selfish_ratio'])
    parser.add_argument('--seed', type=int, default=defaults['seed'])
    parser.add_argument('--log_interval', type=int, default=defaults['log_interval'])
    parser.add_argument('--save', type=str, default='training_results.json')
    parser.add_argument('--dashboard', action='store_true')
    # ── 消融实验开关（P0-3）──
    parser.add_argument('--ablate-security', action='store_true',
                        help='消融：禁用 SecurityGuard（跳过 k 值/nonce 校验）')
    parser.add_argument('--ablate-consensus', action='store_true',
                        help='消融：CW-PBFT 等权（不按贡献度加权投票）')
    parser.add_argument('--weight-broadening', action='store_true',
                        help='启用参与率驱动权重展宽（路线C，纪元50轮冻结+MAX_WEIGHT=1.5钳制）')
    parser.add_argument('--omission-ratio', type=float, default=0.0,
                        help='训练内省略故障比例（默认0=关闭；仅 --weight-broadening 对照实验用）')
    parser.add_argument('--omission-seed', type=int, default=0,
                        help='省略故障节点采样种子（默认0）')
    parser.add_argument('--ablate-incentive', action='store_true',
                        help='消融：禁用激励合约（无链上激励，纯行为记录）')
    # ── P2-E 新增：自适应λ / Nash验证开关 ──
    parser.add_argument('--adaptive-lambda', action='store_true', default=True,
                        help='启用自适应λ控制器（BC→MARL双向反馈，默认启用）')
    parser.add_argument('--no-adaptive-lambda', action='store_true',
                        help='禁用自适应λ（λ保持静态，用于对比实验）')
    parser.add_argument('--verify-nash', action='store_true', default=True,
                        help='训练结束后生成Nash均衡验证报告（默认启用）')
    parser.add_argument('--no-verify-nash', action='store_true',
                        help='跳过Nash均衡验证')
    # ── Tier1: 算法选择 ──
    parser.add_argument('--algorithm', type=str, default='iql',
                        choices=['iql', 'vdn', 'qmix', 'mappo'],
                        help='值分解算法: iql(独立Q学习) / vdn(值分解网络) / qmix(单调值分解)')
    # ── Tier1: 共识感知奖励塑形 ──
    parser.add_argument('--consensus-shaping', action='store_true', default=False,
                        help='启用共识感知奖励塑形CARS（每步注入共识反馈信号）')
    parser.add_argument('--shaping-eta', type=float, default=0.05,
                        help='CARS塑形强度系数eta (默认0.05)')
    args = parser.parse_args()

    # P2-A: 当指定了不同于默认的模式时，重新从config.json加载该模式参数
    # 仅覆盖用户未显式指定的参数（保持CLI override能力）
    if args.mode != 'bc_marl':
        mode_defaults = load_config_defaults(args.mode)
        # 检测哪些参数是用户显式指定的（而非从argparse default继承）
        explicit_args = {k for k, v in vars(args).items()
                        if v != parser.get_default(k)}
        # 对于非显式指定的参数，用目标模式的config.json值覆盖
        for key, value in mode_defaults.items():
            if key not in explicit_args and hasattr(args, key):
                setattr(args, key, value)

    return args


def main():
    args = parse_args()
    config = TrainingConfig(
        n_agents=args.n_agents,
        n_landmarks=args.n_landmarks,
        n_episodes=args.n_episodes,
        max_steps=args.max_steps,
        hidden_dim=args.hidden_dim,
        lr=args.lr,
        gamma=args.gamma,
        batch_size=args.batch_size,
        lambda_weight=args.lambda_weight,
        upload_interval=args.upload_interval,
        selfish_ratio=args.selfish_ratio,
        mode=args.mode,
        seed=args.seed,
        log_interval=args.log_interval,
        # ── 消融实验开关 ──
        ablate_security=args.ablate_security,
        ablate_consensus=args.ablate_consensus,
        ablate_incentive=args.ablate_incentive,
        weight_broadening=args.weight_broadening,       # 路线C：参与率驱动权重展宽
        omission_ratio=args.omission_ratio,
        omission_seed=args.omission_seed,
        # ── P2-E：自适应λ / Nash验证 ──
        adaptive_lambda=not args.no_adaptive_lambda,  # 默认启用，--no-adaptive-lambda 禁用
        verify_nash=not args.no_verify_nash,           # 默认启用，--no-verify-nash 禁用
        algorithm=args.algorithm,                       # Tier1: iql/vdn/qmix
        consensus_shaping=args.consensus_shaping,       # Tier1: CARS共识感知塑形
        shaping_eta=args.shaping_eta,                   # Tier1: CARS塑形强度
    )

    # ── 优雅停机：SIGINT → 保存状态 → 导出 JSON → 退出 ──
    trainer = None
    stats = None

    def _graceful_shutdown(signum, frame):
        logger.info(f"\n[SIGINT] 收到中断信号，正在保存状态...")
        if trainer and stats:
            try:
                trainer.export_results(args.save)
                logger.info(f"[SIGINT] 训练结果已导出到 {args.save}")
            except Exception as e:
                logger.warning(f"[SIGINT] 导出失败: {e}")
        logger.info("[SIGINT] 安全退出")
        sys.exit(0)

    import signal
    signal.signal(signal.SIGINT, _graceful_shutdown)

    logger.info(f"启动训练: mode={config.mode}")
    trainer = MARLBlockchainTrainer(config)
    stats = trainer.train()
    trainer.export_results(args.save)

    if args.dashboard:
        try:
            from visualization.dashboard import start_dashboard
            start_dashboard(stats, trainer)
        except Exception as e:
            logger.warning(f"Dashboard 启动失败: {e}")


if __name__ == '__main__':
    main()
