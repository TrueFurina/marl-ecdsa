"""
配送 MARL 训练脚本：A/B 对比
- A 组：纯环境奖励（无链上可信层）
- B 组：环境奖励 + λ·贡献度激励（链上可信层）
"""
import sys, os, json, random, time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from marl.envs.delivery_env import DeliveryMARLEnv
from marl.algorithms.qmix import QMIXTrainer


def run_episode(env, trainer, use_credibility=False, lam=0.1, max_steps=50):
    obs = env.reset()
    hidden = trainer.init_hidden()
    episode_data = {"observations": [], "actions": [], "rewards": [], "next_observations": []}
    agent_contributions = np.zeros(env.n_agents)  # 记录贡献

    for step in range(max_steps):
        actions, hidden = trainer.get_actions(obs, hidden)
        next_obs, rewards, done, info = env.step(actions)

        # 记录贡献（完成订单+1，交接+0.5）
        for i in range(env.n_agents):
            if rewards[i] >= 4.0:  # DELIVERY_BONUS
                agent_contributions[i] += 1.0
            elif rewards[i] >= 1.5:  # HANDOFF_BONUS
                agent_contributions[i] += 0.5

        episode_data["observations"].append(obs)
        episode_data["actions"].append(actions)
        episode_data["rewards"].append(rewards.tolist())
        episode_data["next_observations"].append(next_obs)

        obs = next_obs
        if done:
            break

    # B 组：episode 末加贡献度激励
    if use_credibility:
        total_contrib = agent_contributions.sum()
        if total_contrib > 0:
            # 按贡献比例分配额外奖励（Shapley 简化：按局部贡献比例）
            contrib_bonus = (agent_contributions / total_contrib) * lam * 10.0
            # 加到最后一步 rewards
            last_rew = episode_data["rewards"][-1]
            for i in range(env.n_agents):
                last_rew[i] += contrib_bonus[i]

    trainer.store_episode(episode_data)
    return info, agent_contributions


def run_experiment(seed, use_credibility=False, n_episodes=500, lam=0.1):
    random.seed(seed)
    np.random.seed(seed)

    env = DeliveryMARLEnv(max_steps=50)
    trainer = QMIXTrainer(
        n_agents=env.n_agents,
        obs_dim=env.obs_dim,
        state_dim=env.state_dim,
        n_actions=env.n_actions,
    )

    results = []
    for ep in range(n_episodes):
        trainer.epsilon = max(0.05, 0.5 - ep / (n_episodes * 0.8))
        info, contrib = run_episode(env, trainer, use_credibility, lam)
        trainer.train_step(batch_size=32)

        if ep % 50 == 0:
            results.append({
                "episode": ep,
                "completed": info["completed"],
                "contrib": contrib.tolist(),
            })

    # 最后 100 episodes 评估
    eval_completed = []
    for _ in range(20):
        trainer.epsilon = 0.05
        info, _ = run_episode(env, trainer, use_credibility, lam)
        eval_completed.append(info["completed"])

    return {
        "seed": seed,
        "use_credibility": use_credibility,
        "final_eval_completed": float(np.mean(eval_completed)),
        "final_eval_std": float(np.std(eval_completed)),
        "history": results,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--credibility", action="store_true")
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--lam", type=float, default=0.1)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    result = run_experiment(args.seed, args.credibility, args.episodes, args.lam)
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, ensure_ascii=False, indent=2))

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
