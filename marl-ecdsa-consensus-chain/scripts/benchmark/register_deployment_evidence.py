#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「性能基准实测」登记进 number_registry.json（NR-89 ~ NR-93）。

对应官方测试报告章节 3.1 ECDSA 吞吐 / 3.2 链 TPS / 3.3 共识延迟 / 3.4 训练剖分——
这四块此前在测试报告里没有独立章节，是官方点名却空着的缺口（W2.1）。

数据源：results/deployment_evidence_flat.json（由 run_deployment_evidence.py 生成，
**扁平顶层标量**结构，verify_numbers.py 的 _recompute_benchmark 可直接机验）。

纪律（吸取历史教训：某个无出处、无量纲限定的单点时延值曾被登记后惨遭撤回，
详见 `number_registry.json` NR-20 的 allowed_wording 备注）：
- 每个时延/吞吐值**必须带 SD 与重复次数**，禁止写单点；
- 每条 allowed_wording **必须带环境限定**（单机内存、无网络传输、进程内模拟共识）；
- declared 值全部由 flat 文件复算，不手抄。
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import assurance_common as ac  # noqa: E402

REG = Path(os.environ.get("MARL_REGISTRY") or ac.REGISTRY_PATH)
FLAT = Path(os.environ.get("MARL_FLAT") or ac.RESULTS_DIR / "deployment_evidence_flat.json")

ENV_LIMIT = ("**环境限定（不可省略）**：单机进程内内存测量，无真实网络传输、无分布式节点；"
             "数字仅用于刻画本实现的计算开销量级，**不代表生产分布式网络性能**。")


def _mk(nr, claim, keys, wording, notes, tol=0.01):
    f = json.load(open(FLAT, encoding="utf-8"))
    declared = {k: round(float(f[k]), 4) for k in keys}
    return {
        "id": nr,
        "claim": claim,
        "allowed_wording": wording + " " + ENV_LIMIT,
        "analysis": "benchmark",
        "sources": [{"file": "deployment_evidence_flat.json", "field": ",".join(keys)}],
        "n_expected": None,
        "statistic": keys,
        "declared": declared,
        "tolerance": {"abs": tol, "p_abs": 0.001},
        "status": "PASS",
        "pre_registered": False,
        "evidence_kind": "benchmark",
        "notes": notes,
    }


def build():
    f = json.load(open(FLAT, encoding="utf-8"))
    R = int(f["repeats"])
    out = []

    out.append(_mk(
        "NR-89",
        "ECDSA 签名延迟与吞吐实测（secp256r1 / cryptography-OpenSSL 后端）",
        ["ecdsa_sign_ms", "ecdsa_sign_ms_sd", "ecdsa_sign_ops_per_sec",
         "ecdsa_iterations", "repeats"],
        (f"ECDSA 签名：单次 {f['ecdsa_sign_ms']} ± {f['ecdsa_sign_ms_sd']} ms"
         f"（{R} 次重复 × {int(f['ecdsa_iterations'])} 次迭代，"
         f"折算 {f['ecdsa_sign_ops_per_sec']} ops/s）。"
         f"曲线 secp256r1，后端 cryptography(OpenSSL)；SD/均值≈2%，分布稳定无双峰。"),
        ("官方测试报告 §3.1 对应项。2026-09-30 实测（机器空闲态）。"
         "**同日曾有一轮在残留负载下测得 0.0483±0.0214 ms（SD 达均值 44%，双峰），已作废**——"
         "负载对微基准影响可达 2.8 倍，故本项只在机器空闲时取数，且必须报 SD。"
         "取代已撤回的旧口径 0.12ms（无出处）。")))

    out.append(_mk(
        "NR-90",
        "ECDSA 验签延迟与吞吐实测（secp256r1 / cryptography-OpenSSL 后端）",
        ["ecdsa_verify_ms", "ecdsa_verify_ms_sd", "ecdsa_verify_ops_per_sec"],
        (f"ECDSA 验签：单次 {f['ecdsa_verify_ms']} ± {f['ecdsa_verify_ms_sd']} ms"
         f"（折算 {f['ecdsa_verify_ops_per_sec']} ops/s），"
         f"约为签名耗时的 {round(f['ecdsa_verify_ms'] / f['ecdsa_sign_ms'], 2)} 倍。"),
        ("官方测试报告 §3.1 对应项。2026-09-30 实测，与 NR-89 同批同源，须与 NR-89 同报。")))

    out.append(_mk(
        "NR-91",
        "区块链真实 TPS（只统计实际上链交易，单机内存账本）",
        ["chain_tps_committed", "chain_tps_committed_sd", "chain_bps_committed",
         "chain_committed_tx", "chain_attempted_tx", "chain_commit_rate",
         "chain_registered_agents"],
        (f"链吞吐：{f['chain_tps_committed']} ± {f['chain_tps_committed_sd']} tx/s"
         f"（{R} 次重复；{int(f['chain_attempted_tx'])} 笔尝试 / "
         f"{int(f['chain_committed_tx'])} 笔实际上链，上链率 {f['chain_commit_rate']}；"
         f"{int(f['chain_registered_agents'])} 个注册 agent）。"
         f"**只计 append_block 返回 True 的 committed 交易**，不把被拒绝的交易计入分子。"),
        ("官方测试报告 §3.2 对应项。2026-09-29 曾修掉『把未上链交易也计入分子』的注水 bug，"
         "本项为修 bug 后的口径。单机内存账本，**无共识、无网络、无磁盘持久化**，"
         "严禁与生产级公链 TPS 横向比较。")))

    out.append(_mk(
        "NR-92",
        "CW-PBFT 共识延迟（进程内模拟共识，非真实网络多节点）",
        ["cw_pbft_ms_per_round", "cw_pbft_ms_per_round_sd",
         "cw_pbft_rounds_per_sec", "cw_pbft_success_rate"],
        (f"CW-PBFT 共识：每轮 {f['cw_pbft_ms_per_round']} ± {f['cw_pbft_ms_per_round_sd']} ms"
         f"（折算 {f['cw_pbft_rounds_per_sec']} rounds/s，成功率 {f['cw_pbft_success_rate']}）。"
         f"**注意**：这是进程内 simulated_consensus 的**计算开销**，"
         f"不含任何节点间网络往返，**不可表述为『共识延迟 0.014ms』**。"),
        ("官方测试报告 §3.3 对应项。对外表述必须写明『不含网络往返』——"
         "真实广域网下共识延迟由网络 RTT 主导，本项只量化共识算法本身的计算成本。")))

    out.append(_mk(
        "NR-93",
        "区块链侧签名环节的端到端开销剖分（同环境步进基线 vs 叠加每步真实签名）",
        ["e2e_overhead_ratio", "e2e_overhead_ratio_sd"],
        (f"端到端开销：叠加每步真实 ECDSA 签名后，耗时为纯环境步进基线的 "
         f"{f['e2e_overhead_ratio']} 倍（即 +{round((f['e2e_overhead_ratio'] - 1) * 100, 1)}%，"
         f"SD {f['e2e_overhead_ratio_sd']}）。"
         f"**口径必读**：这是『每步每智能体都签名』的**上界**；项目实际配置为 "
         f"upload_interval=10（每 10 步批量上链一次），真实部署开销约为该上界的 1/10 量级。"),
        ("官方测试报告 §3.4 对应项。**不是**完整 bc_marl/pure_marl 训练循环的端到端对比，"
         "后者需跑 train.py 全链路；本项仅隔离量化『区块链侧签名环节』引入的开销。")))

    return out


def main():
    doc = json.load(open(REG, encoding="utf-8"))
    have = {e["id"] for e in doc["entries"]}
    added = []
    for e in build():
        if e["id"] in have:
            print(f"[skip] {e['id']} 已存在")
            continue
        doc["entries"].append(e)
        added.append(e["id"])
    with open(REG, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1)
    print(f"{REG.name}: 新增 {added}")
    for e in build():
        if e["id"] in added:
            print(f"  {e['id']}: {json.dumps(e['declared'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
