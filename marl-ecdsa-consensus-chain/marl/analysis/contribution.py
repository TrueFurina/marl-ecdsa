# -*- coding: utf-8 -*-
"""
贡献度评估模块（C1）
在 episode 末记录每个智能体的局部奖励份额与归一化贡献占比。
注意：本模块计算的是「按局部奖励归一化的 leave-one-out 近似贡献份额」，
**不是**博弈论意义上的 Shapley 值，命名与对外表述须据此对齐，避免误导。
不改变训练逻辑，只做记录与事后分析。
"""
import json, os, time
from pathlib import Path
from collections import defaultdict
import numpy as np


class ContributionLogger:
    def __init__(self, n_agents, agent_ids, log_dir, enabled=True):
        self.n = n_agents
        self.ids = list(agent_ids)
        self.enabled = enabled
        self.records = []
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_episode(self, episode, ep_avg_rewards, global_reward=None):
        """记录一个 episode 的贡献度。
        ep_avg_rewards: list[float], 每个 agent 的平均局部奖励
        global_reward: float, 全局合作奖励（默认 sum）
        """
        if not self.enabled:
            return
        r = np.array(ep_avg_rewards, dtype=float)
        total = float(global_reward) if global_reward is not None else float(r.sum())
        if abs(total) < 1e-9:
            shares = np.ones(self.n) / self.n
        else:
            shares = r / total
        # 归一化贡献份额（leave-one-out 近似，非真正 Shapley 值）
        shap = self._contribution_share(r, global_reward)
        rec = {
            "episode": int(episode),
            "local_rewards": [float(x) for x in r],
            "global_reward": total,
            "reward_share": [float(x) for x in shares],
            "contribution_share": [float(x) for x in shap],
        }
        self.records.append(rec)

    def _contribution_share(self, r, global_reward=None):
        """归一化贡献份额（leave-one-out 近似，非真正 Shapley 值）。

        线性奖励下各智能体的 leave-one-out 边际贡献即其局部奖励 m_i=r[i]
        （n>4 与 n<=4 都退化为按局部奖励归一）。F06 修正：对边际向量做「移位归一」
        `share_i ∝ (m_i − min(m) + eps)`，使负奖励区间仍严格按序赋权——离目标越近
        （奖励越大）份额越大，彻底消除旧实现 `m/sum(m)` 在 sum(m)<0 时把最差智能体
        放大成最大治理份额的反转（例如 m=[-3,-2,-1] 旧→[0.5,0.33,0.17]，现→约
        [0,0.33,0.67]）。全等时归一为均匀份额；下游 distributed_consensus 另有
        `0.2/3 + 0.8·share` 权重下限，最差者不会被彻底逐出投票。

        仍是可解释的贡献占比指标，不构成博弈论意义上的 Shapley 值，命名与文档须据此对齐。
        """
        m = np.asarray(r, dtype=float)
        n = m.shape[0]
        if n == 0:
            return m
        shifted = m - m.min() + 1e-9
        total = shifted.sum()
        if total <= 1e-12:
            return np.full(n, 1.0 / n)
        return shifted / total

    def flush(self, tag="", training_result_sha256=None):
        if not self.enabled or not self.records:
            return None
        out = self.log_dir / f"contribution_log_{tag}_{int(time.time())}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "n_agents": self.n,
                "agent_ids": self.ids,
                "run_tag": tag,
                "training_result_sha256": training_result_sha256,
                "records": self.records,
            }, f, ensure_ascii=False, indent=2)
        self.records = []
        return str(out)
