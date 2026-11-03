"""E32 诊断：对比 bc/pure 的链内指标（合作率/bc_score/全程奖励/λ），判断机制是否工作。"""
import json

for algo in ("iql", "qmix"):
    row = []
    for mode in ("bc_marl", "pure_marl"):
        d = json.load(open(f"results/delivery_main/e32_{algo}_{mode}_seed3001.json", encoding="utf-8"))
        s = d.get("summary", {})
        row.append((mode, s))
    print(f"==== {algo} seed3001 ====")
    for mode, s in row:
        sel = {k: s.get(k) for k in (
            "avg_env_reward", "avg_env_reward_last_50", "avg_cooperation_rate",
            "avg_bc_score", "final_lambda", "n_episodes")}
        print(f"  {mode}: {sel}")
    # 全程 vs 末50 的差（是否欠收敛）
    for mode, s in row:
        full = s.get("avg_env_reward")
        last = s.get("avg_env_reward_last_50")
        if full is not None and last is not None:
            print(f"  [{mode}] full={full:.3f} last50={last:.3f} delta={last-full:+.3f}")
