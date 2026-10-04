#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""落地证据专测（Deployment Evidence Benchmark）
=================================================
目的：为「应用前景/落地可行性」维度产出**可复现、不注水**的实测数据。

与 scripts/benchmark/run_all.py 的区别（重要）：
  run_all.py 的 TPS 基准**未注册 agent 公钥**且**用假签名**，导致在启用
  identity_contract 的严格模式下**所有交易被安全机制正确拒绝、区块实际上链数=0**，
  而脚本仍按「构造数」统计 → TPS 严重虚高（注水）。本脚本修掉该问题：
    1. 先用 ECDSAUtils 生成真实密钥对并 register 到 IdentityContract；
    2. 每笔交易用真实 ECDSA 签名；
    3. **只统计实际成功上链的交易/区块**（append_block 返回 True 才计数）；
    4. 同时报告「尝试数 vs 成功数」，让拒绝率可见。

测试项（对应官方《测试报告标准章节》3.1–3.4）：
  1. ECDSA 签名/验签吞吐（ops/s）
  2. 区块链真实 TPS（已注册身份 + 真实签名 + 只计上链）
  3. CW-PBFT 共识延迟与吞吐
  4. 端到端开销剖分：BC-MARL 相对 Pure-MARL 的区块链引入开销

输出：results/deployment_evidence.json + results/deployment_evidence.md
用法：
    python scripts/benchmark/run_deployment_evidence.py
    python scripts/benchmark/run_deployment_evidence.py --blocks 100 --txs 20
"""
import argparse
import json
import os
import time
import hashlib
import sys
import platform
import statistics
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

OUT_JSON = ROOT_DIR / "results" / "deployment_evidence.json"
OUT_MD = ROOT_DIR / "results" / "deployment_evidence.md"
# 扁平摘要：verify_numbers.py 的 _recompute_benchmark 只吃顶层标量，
# 故把嵌套报告摊平成 key->scalar，供登记簿机验（NR-89 ~ NR-93）自动复算。
OUT_FLAT = ROOT_DIR / "results" / "deployment_evidence_flat.json"


def _env_metadata():
    """测试环境元数据（可复现性必备：机器换了数字就要重测）"""
    meta = {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "topology": "单机进程内内存测量，无真实网络传输、无分布式节点",
    }
    try:
        import cryptography
        meta["cryptography_version"] = cryptography.__version__
    except Exception:
        meta["cryptography_version"] = None
    return meta


def _repeat_bench(fn, n, label):
    """重复测量 n 次，输出 均值±SD（min/max 一并保留）。

    单次测量无 SD，评委一问"抖动多大"就答不上来，故必须重复。
    """
    runs = []
    for i in range(n):
        runs.append(fn())
    numeric = {}
    for r in runs:
        for k, v in r.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric.setdefault(k, []).append(v)
    stats = {}
    for k, vals in numeric.items():
        if len(vals) != len(runs):
            continue
        stats[k] = {
            "mean": round(statistics.mean(vals), 4),
            "sd": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
        }
    out = {"repeats": n, "runs": runs, "stats": stats}
    for k, s in stats.items():
        out[k] = s["mean"]          # 顶层保留均值，兼容既有消费方
    for k, v in runs[-1].items():   # 非数值字段（note/status 等）取最后一次
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            out[k] = v
    return out


def _ecdsa_bench(iters=5000):
    """1. ECDSA 签名/验签吞吐（真实密钥对、真实签名）"""
    from blockchain.crypto.ecdsa_utils import ECDSAUtils

    priv, pub = ECDSAUtils.generate_key_pair()
    msg = json.dumps({"action": "move", "agent_id": "agent_0",
                      "timestamp": 1234567890, "nonce": 42},
                     sort_keys=True).encode("utf-8")

    for _ in range(50):
        s = ECDSAUtils.sign(priv, msg)
        ECDSAUtils.verify(pub, msg, s)

    t0 = time.perf_counter()
    sigs = [ECDSAUtils.sign(priv, msg) for _ in range(iters)]
    sign_ms = (time.perf_counter() - t0) / iters * 1000

    t0 = time.perf_counter()
    for s in sigs:
        ECDSAUtils.verify(pub, msg, s)
    verify_ms = (time.perf_counter() - t0) / iters * 1000

    return {
        "iterations": iters,
        "sign_ms": round(sign_ms, 4),
        "verify_ms": round(verify_ms, 4),
        "sign_per_sec": round(1000 / sign_ms, 1),
        "verify_per_sec": round(1000 / verify_ms, 1),
        "note": "真实 ECDSA(secp256r1) 密钥对与签名；单机内存环境，非分布式网络",
    }


def _real_tps_bench(num_blocks=200, txs_per_block=20, n_agents=5):
    """2. 真实 TPS：注册身份 + 真实签名 + 只统计实际上链"""
    from blockchain.crypto.ecdsa_utils import ECDSAUtils
    from blockchain.ledger.block import Block, Transaction
    from blockchain.ledger.blockchain import Blockchain
    from blockchain.ledger.world_state import WorldState
    from blockchain.contracts.identity_contract import IdentityContract

    ws = WorldState()
    idc = IdentityContract(ws)
    bc = Blockchain(identity_contract=idc)

    # ── 关键修复：先注册 agent 公钥（否则严格模式下全部拒绝）──
    keys = {}
    for i in range(n_agents):
        priv, pub = ECDSAUtils.generate_key_pair()
        pub_hex = ECDSAUtils.public_key_to_hex(pub)
        idc.register(agent_id=f"agent_{i}", public_key_hex=pub_hex)
        keys[f"agent_{i}"] = priv
    registered = len(idc.list_agents())

    attempted_tx = 0
    committed_tx = 0
    committed_blocks = 0
    rejected_blocks = 0

    t0 = time.perf_counter()
    for h in range(1, num_blocks + 1):
        txs = []
        for i in range(txs_per_block):
            agent_id = f"agent_{i % n_agents}"
            priv = keys[agent_id]
            action = [float(i % 5)]
            nonce = h * txs_per_block + i
            # 关键：账本验签走 verify_action_package(package)，需要
            # message_hex / signature_hex / r / s 四项齐全 → 用 sign_action 生成
            pkg = ECDSAUtils.sign_action(agent_id, priv, action, nonce)
            tx = Transaction(
                tx_id=f"evi_tx_{h}_{i}",
                agent_id=agent_id,
                action=action,
                action_hash=hashlib.sha256(str(action).encode()).hexdigest()[:16],
                timestamp=pkg["timestamp"],
                nonce=nonce,
                signature_hex=pkg["signature_hex"],
                extra={
                    "verified": True,
                    "message_hex": pkg["message_hex"],
                    "r": pkg["r"],
                    "s": pkg["s"],
                },
            )
            txs.append(tx)
        attempted_tx += len(txs)

        blk = Block(
            block_height=h,
            previous_hash=bc.latest_block.block_hash,
            timestamp=int(time.time() * 1000),
            proposer=f"agent_{h % n_agents}",
            transactions=txs,
            state_root="evidence_state_root",
            signature_hex="",
        )
        if bc.append_block(blk):
            committed_blocks += 1
            committed_tx += len(txs)
        else:
            rejected_blocks += 1
    elapsed = time.perf_counter() - t0

    return {
        "num_blocks_attempted": num_blocks,
        "registered_agents": registered,
        "attempted_tx": attempted_tx,
        "committed_tx": committed_tx,
        "committed_blocks": committed_blocks,
        "rejected_blocks": rejected_blocks,
        "commit_rate": round(committed_blocks / num_blocks, 4) if num_blocks else 0.0,
        "elapsed_sec": round(elapsed, 4),
        "tps_committed": round(committed_tx / elapsed, 1) if elapsed > 0 else 0.0,
        "bps_committed": round(committed_blocks / elapsed, 1) if elapsed > 0 else 0.0,
        "note": "仅统计 append_block 返回 True 的实际 committed 交易；单机内存账本，非真实分布式网络",
    }


def _cw_pbft_bench(num_rounds=100, n_nodes=5):
    """3. CW-PBFT 共识延迟与吞吐"""
    try:
        from blockchain.consensus.cw_pbft import CWPBFTConsensus
    except Exception as e:
        return {"error": f"cw_pbft 导入失败: {e}"}

    try:
        # 正确签名：__init__(node_id: str, consensus_nodes: List[str])
        nodes = [f"node_{i}" for i in range(n_nodes)]
        consensus = CWPBFTConsensus(node_id="node_0", consensus_nodes=nodes)
    except Exception as e:
        return {"error": f"CWPBFTConsensus 构造失败: {e}"}

    # 设置差异化权重（与 run_all.py 一致）
    for i, nid in enumerate(nodes):
        try:
            consensus.update_weight(nid, 1.0 + 0.5 * (i / max(1, n_nodes - 1)))
        except Exception:
            pass

    ok = 0
    t0 = time.perf_counter()
    for r in range(num_rounds):
        try:
            # 正确 API：simulated_consensus(block_hash, proposer) -> bool
            if consensus.simulated_consensus(f"bench_hash_{r:08d}",
                                             f"node_{r % n_nodes}"):
                ok += 1
            else:
                consensus.reset()
        except Exception:
            try:
                consensus.reset()
            except Exception:
                pass
    elapsed = time.perf_counter() - t0

    return {
        "num_rounds": num_rounds,
        "n_nodes": n_nodes,
        "successful_rounds": ok,
        "success_rate": round(ok / num_rounds, 4) if num_rounds else 0.0,
        "elapsed_sec": round(elapsed, 4),
        "rounds_per_sec": round(num_rounds / elapsed, 1) if elapsed > 0 else 0.0,
        "ms_per_round": round(elapsed / num_rounds * 1000, 4) if num_rounds else 0.0,
        "note": "单机进程内模拟共识（simulated_consensus，无真实网络传输）；延迟不含广域网往返",
    }


def _e2e_overhead(episodes=30, n_agents=3):
    """4. 端到端开销剖分：BC-MARL vs Pure-MARL 单步耗时

    评审最关心的问题：「加区块链后慢多少」。这里直接对比两种模式的
    训练耗时，给出区块链引入的开销占比。若依赖不可用则优雅降级。
    """
    result = {"episodes": episodes, "n_agents": n_agents}
    try:
        from marl.envs.simple_spread import SimpleSpreadEnv
        from blockchain.crypto.ecdsa_utils import ECDSAUtils
    except Exception as e:
        result["status"] = "skipped"
        result["reason"] = f"环境导入失败: {e}"
        return result

    # ── 诚实声明：本项测的是「环境步进基线」与「叠加区块链签名后的同环境步进」 ──
    # 不是完整 bc_marl/pure_marl 训练循环对比（那需要跑完整 train.py）。
    def _run(with_blockchain: bool):
        try:
            env = SimpleSpreadEnv(n_agents=n_agents)
        except Exception as e:
            return None, f"env 构造失败: {e}"
        priv = None
        if with_blockchain:
            priv, _pub = ECDSAUtils.generate_key_pair()
        t0 = time.perf_counter()
        try:
            for ep in range(episodes):
                env.reset()
                for step in range(25):
                    actions = [step % 5 for _ in range(n_agents)]
                    obs, g_rewards, l_rewards, done, info = env.step(actions)
                    if with_blockchain and priv is not None:
                        # 每步为每个智能体做一次真实 ECDSA 签名（模拟上链前签名开销）
                        for a in range(n_agents):
                            ECDSAUtils.sign_action(
                                f"agent_{a}", priv, [float(actions[a])],
                                ep * 25 + step)
                    if done:
                        break
        except Exception as e:
            return None, f"运行失败: {e}"
        return time.perf_counter() - t0, None

    t_pure, err1 = _run(False)
    t_bc, err2 = _run(True)

    if t_pure is None or t_bc is None:
        result["status"] = "skipped"
        result["reason"] = err1 or err2
        return result

    result["status"] = "ok"
    result["baseline_pure_env_sec"] = round(t_pure, 4)
    result["with_ecdsa_signing_sec"] = round(t_bc, 4)
    result["overhead_ratio"] = round(t_bc / t_pure - 1, 4) if t_pure > 0 else None
    result["steps_measured"] = episodes * 25 * n_agents
    result["note"] = (
        "【口径必读】本项是**同环境步进基线** vs **叠加每步真实 ECDSA 签名后**的耗时对比，"
        "用于量化『区块链侧签名环节』引入的开销；**不是**完整 bc_marl/pure_marl "
        "训练循环端到端对比（后者需运行 train.py 全链路）。差异即签名开销占比。"
    )
    return result


def _write_flat_summary(report):
    """摊平成顶层标量，供 number_registry 机验（见 OUT_FLAT 注释）。

    只输出**可直接对外引用**的汇总量，SD 一并给出——单点无 SD 的时延值
    曾导致 NR-20 前身的『≈40.7ms』类数字被撤回，此处强制带离散度。
    """
    e = report.get("ecdsa", {})
    b = report.get("blockchain_tps", {})
    c = report.get("cw_pbft", {})
    o = report.get("e2e_overhead", {})
    es = e.get("stats", {})
    bs = b.get("stats", {})
    cs = c.get("stats", {})
    os_ = o.get("stats", {})

    def sd(d, k):
        return d.get(k, {}).get("sd")

    flat = {
        "repeats": report.get("repeats"),
        "ecdsa_iterations": e.get("iterations"),
        "ecdsa_sign_ms": e.get("sign_ms"),
        "ecdsa_sign_ms_sd": sd(es, "sign_ms"),
        "ecdsa_verify_ms": e.get("verify_ms"),
        "ecdsa_verify_ms_sd": sd(es, "verify_ms"),
        "ecdsa_sign_ops_per_sec": e.get("sign_per_sec"),
        "ecdsa_verify_ops_per_sec": e.get("verify_per_sec"),
        "chain_tps_committed": b.get("tps_committed"),
        "chain_tps_committed_sd": sd(bs, "tps_committed"),
        "chain_bps_committed": b.get("bps_committed"),
        "chain_committed_tx": b.get("committed_tx"),
        "chain_attempted_tx": b.get("attempted_tx"),
        "chain_commit_rate": b.get("commit_rate"),
        "chain_registered_agents": b.get("registered_agents"),
        "cw_pbft_ms_per_round": c.get("ms_per_round"),
        "cw_pbft_ms_per_round_sd": sd(cs, "ms_per_round"),
        "cw_pbft_rounds_per_sec": c.get("rounds_per_sec"),
        "cw_pbft_success_rate": c.get("success_rate"),
        "e2e_overhead_ratio": o.get("overhead_ratio"),
        "e2e_overhead_ratio_sd": sd(os_, "overhead_ratio"),
    }
    flat = {k: v for k, v in flat.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    OUT_FLAT.write_text(json.dumps(flat, ensure_ascii=False, indent=1), encoding="utf-8")
    return flat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=200)
    ap.add_argument("--txs", type=int, default=20)
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--repeat", type=int, default=7,
                    help="每项基准重复次数（用于报 均值±SD；默认 7）")
    args = ap.parse_args()

    print("=" * 62)
    print("  落地证据专测（Deployment Evidence）")
    print("  真实注册 + 真实签名 + 只统计实际上链")
    print("=" * 62)

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": "单机内存（非分布式网络）",
        "env_metadata": _env_metadata(),
        "repeats": args.repeat,
    }

    print(f"\n[1/4] ECDSA 签名/验签吞吐 …（重复 {args.repeat} 次）")
    report["ecdsa"] = _repeat_bench(lambda: _ecdsa_bench(args.iters),
                                    args.repeat, "ecdsa")
    e = report["ecdsa"]
    print(f"  签名 {e['sign_ms']}±{e['stats']['sign_ms']['sd']} ms "
          f"({e['sign_per_sec']} ops/s) | "
          f"验签 {e['verify_ms']}±{e['stats']['verify_ms']['sd']} ms "
          f"({e['verify_per_sec']} ops/s)")

    print(f"\n[2/4] 真实 TPS（{args.blocks} 块 × {args.txs} 笔，重复 {args.repeat} 次）…")
    report["blockchain_tps"] = _repeat_bench(
        lambda: _real_tps_bench(args.blocks, args.txs), args.repeat, "tps")
    b = report["blockchain_tps"]
    if "error" in b:
        print(f"  ERR: {b['error']}")
    else:
        print(f"  注册 {b['registered_agents']} agent | "
              f"尝试 {b['attempted_tx']} 笔 / 实际上链 {b['committed_tx']} 笔")
        print(f"  区块 {b['committed_blocks']}/{b['num_blocks_attempted']} "
              f"(拒绝 {b['rejected_blocks']}) | 上链率 {b['commit_rate']}")
        print(f"  真实 TPS(committed) = {b['tps_committed']}"
              f"±{b['stats']['tps_committed']['sd']} tx/s")

    print(f"\n[3/4] CW-PBFT 共识延迟 …（重复 {args.repeat} 次）")
    report["cw_pbft"] = _repeat_bench(_cw_pbft_bench, args.repeat, "cw_pbft")
    c = report["cw_pbft"]
    if "error" not in c:
        print(f"  每轮延迟 {c['ms_per_round']}±{c['stats']['ms_per_round']['sd']} ms | "
              f"吞吐 {c['rounds_per_sec']} rounds/s")
    else:
        print(f"  {c}")

    print(f"\n[4/4] 端到端开销剖分 …（重复 {args.repeat} 次）")
    report["e2e_overhead"] = _repeat_bench(
        lambda: _e2e_overhead(args.episodes), args.repeat, "e2e")
    ov = report["e2e_overhead"]
    if "overhead_ratio" in ov:
        print(f"  开销比 {ov['overhead_ratio']}"
              f"±{ov['stats']['overhead_ratio']['sd']} %")
    else:
        print(f"  {ov}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    em = report["env_metadata"]
    lines = ["# 落地证据实测报告\n",
             f"> 生成时间：{report['generated_at']}",
             f"> 测试环境：**{report['environment']}** — 数字不代表真实分布式网络性能",
             f"> 每项基准重复 **{report['repeats']}** 次，报 均值±SD\n",
             "### 测试环境元数据\n",
             "| 项 | 值 |", "|---|---|",
             f"| 操作系统 | {em['os']} |",
             f"| 处理器 | {em['processor']} ({em['machine']}) |",
             f"| 逻辑核数 | {em['cpu_count']} |",
             f"| Python | {em['python']} |",
             f"| cryptography | {em['cryptography_version']} |",
             f"| 拓扑 | {em['topology']} |\n",
             "## 1. ECDSA 签名/验签吞吐\n",
             "| 指标 | 均值±SD | 区间 |", "|---|---|---|",
             f"| 签名延迟 (ms) | {e['sign_ms']} ± {e['stats']['sign_ms']['sd']} | "
             f"{e['stats']['sign_ms']['min']} – {e['stats']['sign_ms']['max']} |",
             f"| 验签延迟 (ms) | {e['verify_ms']} ± {e['stats']['verify_ms']['sd']} | "
             f"{e['stats']['verify_ms']['min']} – {e['stats']['verify_ms']['max']} |",
             f"| 签名吞吐 (ops/s) | {e['sign_per_sec']} ± "
             f"{e['stats']['sign_per_sec']['sd']} | — |",
             f"| 验签吞吐 (ops/s) | {e['verify_per_sec']} ± "
             f"{e['stats']['verify_per_sec']['sd']} | — |\n",
             "## 2. 区块链真实 TPS（只计实际上链）\n",
             "| 指标 | 值 |", "|---|---|"]
    if "error" not in b:
        lines += [
            f"| 注册 agent 数 | {b['registered_agents']} |",
            f"| 尝试交易数 | {b['attempted_tx']} |",
            f"| 实际上链交易数 | {b['committed_tx']} |",
            f"| 成功区块 | {b['committed_blocks']}/{b['num_blocks_attempted']} |",
            f"| 上链率 | {b['commit_rate']} |",
            f"| 耗时 (s) | {b['elapsed_sec']} ± {b['stats']['elapsed_sec']['sd']} |",
            f"| **真实 TPS** | **{b['tps_committed']} ± "
            f"{b['stats']['tps_committed']['sd']} tx/s** |",
        ]
    else:
        lines.append(f"| 错误 | {b['error']} |")
    lines += ["\n## 3. CW-PBFT 共识\n", "| 指标 | 值 |", "|---|---|"]
    if "error" not in c:
        lines += [f"| 轮数 | {c.get('num_rounds')} |",
                  f"| 成功轮 | {c.get('successful_rounds')} |",
                  f"| 每轮延迟 (ms) | {c.get('ms_per_round')} ± "
                  f"{c['stats']['ms_per_round']['sd']} |",
                  f"| 吞吐 (rounds/s) | {c.get('rounds_per_sec')} ± "
                  f"{c['stats']['rounds_per_sec']['sd']} |"]
    else:
        lines.append(f"| 错误 | {c['error']} |")
    lines += ["\n## 4. 端到端开销剖分\n"]
    ov = report["e2e_overhead"]
    lines += ["| 指标 | 值 |", "|---|---|"]
    for k in ("status", "reason", "steps_measured"):
        if k in ov:
            lines.append(f"| {k} | {ov[k]} |")
    for k in ("baseline_pure_env_sec", "with_ecdsa_signing_sec"):
        if k in ov and k in ov.get("stats", {}):
            lines.append(f"| {k} (s) | {ov[k]} ± {ov['stats'][k]['sd']} |")
    if "overhead_ratio" in ov and "overhead_ratio" in ov.get("stats", {}):
        ratio = ov["overhead_ratio"]
        sd = ov["stats"]["overhead_ratio"]["sd"]
        # 口径澄清：ratio=1.527 表示「耗时为基线的 1.527 倍」＝「相对基线 +52.7%」。
        # 写成「+152.7%」会与「+52.7%」相差一倍，属易被质疑的表述，故两种写法同时给出。
        lines.append(f"| **开销比（倍数）** | **{ratio} ± {sd} 倍** |")
        lines.append(f"| **相对基线增幅** | **+{round((ratio - 1) * 100, 1)}% "
                     f"(±{round(sd * 100, 1)} pp)** |")
    if ov.get("note"):
        lines += ["", "### 口径必读（不可省略）", "",
                  ov["note"],
                  "实测为『每一步、每个智能体都签名』的**上界**；项目实际配置为 "
                  "`upload_interval = 10`（每 10 步批量上链一次），"
                  "故真实部署开销约为该上界的 1/10 量级。"]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    _write_flat_summary(report)

    print(f"\n✅ JSON: {OUT_JSON}")
    print(f"✅ MD:   {OUT_MD}")
    print(f"✅ FLAT: {OUT_FLAT}")


if __name__ == "__main__":
    main()
