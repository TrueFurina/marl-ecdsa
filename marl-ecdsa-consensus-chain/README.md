<!-- README.md (English) | 中文版见 README.zh.md -->
# MARL-ECDSA Consensus Chain

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-1600%2B%20passed-brightgreen)](tests/)
[![Consensus](https://img.shields.io/badge/Consensus-CW--PBFT-00d4ff)](blockchain/consensus/cw_pbft.py)

**中文版**: [README.zh.md](README.zh.md)

## 中文摘要（Chinese Summary）

> 本项目面向**多智能体强化学习（MARL）**场景，构建一套**区块链–AI 协同的可信共识与激励机制**：共识层为 **CW-PBFT**（贡献加权拜占庭容错共识），身份层为 **ECDSA(secp256r1) 无 CA 身份锚定 + SecurityGuard 三层防护**（时间戳窗口 / nonce 单调 / k 值重用检测），激励层为**链上激励合约**。
>
> 项目 **1600+ 项自动化测试全部通过（0 失败）**；对**6 类签名层攻击**（观测伪造 / 消息篡改 / 重放 / Sybil / k 值重用 / 长程）每类 50 次、共 300 次批量测试**全部拦截**（Wilson 95% 置信区间 [92.9%, 100%]）。
>
> **诚实口径声明**：贡献度加权共识的有效性依赖投票权重的真实异质性。在真实 MARL 行为贡献度分布下（权重带宽比 **R≈1.007**），其表现与标准 PBFT **逐种子相同**；本项目以闭式判据 **f_max = R/(R+2)** 给出该机制的**适用边界**，并如实报告各项不显著结果。详见 `docs/` 与实验登记表。

> A Blockchain–AI synergistic consensus mechanism for Multi-Agent Reinforcement Learning (MARL): contribution-weighted consensus (CW-PBFT) secured by ECDSA identities, with a parameter-boundary Nash equilibrium analysis (numerically verified, not a machine-checked formal proof).
>
> **CCF 5th Blockchain Technology & Innovation Competition · Technical Innovation Track** | Version 4.1

---

## Table of Contents

1. [Highlights](#-highlights)
2. [Architecture](#-architecture)
3. [Key Innovations](#-key-innovations)
4. [Quick Start](#-quick-start)
5. [Experiments & Results](#-experiments--results)
6. [Repository Layout](#-repository-layout)
7. [Testing](#-testing)
8. [CI / Automation](#-ci--automation)
9. [Citation](#-citation)

---

## Highlights

- **Deep Blockchain ↔ MARL loop**: blockchain incentives shape MARL rewards (BC→MARL), while MARL behavior feeds contribution scores that weight consensus (MARL→BC).
- **ECDSA identity without a CA**: on-chain public-key registration + SecurityGuard three-tier defense (k-reuse detection, nonce anti-replay, timestamp validation).
- **Contribution-Weighted PBFT (CW-PBFT)**: Shapley-style weight derivation (three axioms) with dynamic primary failover; configurable modes `cw_pbft` / `standard_pbft` / `fast`.
- **Parameter-boundary derivation & numerical verification of strict-dominant-strategy Nash (NOT machine-checked formal proof)**: strict proof with parameter bounds and 50% safety margin; **post-quantum ML-DSA-44 (CRYSTALS-Dilithium2) adapter IMPLEMENTED** via `dilithium-py` — real keygen/sign/verify (pure-Python backend, no native acceleration); signature 2420 B / public key 1312 B / private key 2560 B; cold-mean sign 44.64 ms (SD 32.40) / verify 10.40 ms, warm-median sign 17.04 ms / verify 4.15 ms — jitter is large, cite only intervals or dual values, never a single point; ~2 orders of magnitude slower than ECDSA; **adapter ready but NOT wired into main chain (P2, independent module) — default signing path still ECDSA**, so the system as a whole is not yet quantum-resistant.
- **Self-built Gossip discovery**: asyncio-based dynamic peer discovery tuned for MARL scenarios.
- **Full-chain cryptographic auditability**: sign → Guard → Tx → Block → consensus.
- **Rigorous experiments**: ablation matrix, λ-sensitivity and multi-seed statistics, reported under an honest caliber (headline: n=71 seeds, p=0.0095 — **BH-FDR significant / Bonferroni non-significant**, Cohen d=0.441; see [Experiments & Results](#-experiments--results)).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Application Layer │
│ MARL training (IQL / QMIX) · Web Dashboard · Attack Demo │
├──────────────────────────────────────────────────────────────┤
│ Smart Contract Layer │
│ IdentityContract · IncentiveContract · PenaltyContract │
├──────────────────────────────────────────────────────────────┤
│ Consensus Layer │
│ CW-PBFT (weighted) · Standard PBFT · Fast · Failover │
├──────────────────────────────────────────────────────────────┤
│ Network & Crypto Layer │
│ P2P (asyncio TCP) · Gossip discovery · ECDSA · SecurityGuard│
└──────────────────────────────────────────────────────────────┘
```

Data flow: `ECDSA sign → SecurityGuard check → Transaction → Block → CW-PBFT consensus → append to chain`

---

## Threat Model & Fault Boundaries (honest disclosure)

| Layer | Coverage | Success criterion |
|---|---|---|
| Signature-layer attacks | ECDSA + SecurityGuard (k-reuse / replay / timestamp / observation-forgery / message-tampering / long-range / sybil) — **6 classes, 100% intercepted** | cryptographic verification |
| Omission / crash faults | covered by consensus experiments (primary marked unhealthy → view change) | weighted-quorum reachability (n ≥ 2f+1) |
| **Equivocation / arbitrary Byzantine** | **out of simulator scope — listed as future work** | not modeled |

> Note: unqualified "Byzantine" in this repo refers to the **controlled omission/crash** setting (a node is silently dropped or stops voting), **not** arbitrary Byzantine behavior (e.g. equivocation / contradictory proposals). The arbitrary-Byzantine bound (n ≥ 3f+1) is **not** claimed.

## Key Innovations

| Dimension | Baseline (known projects) | This project |
|---|---|---|
| Blockchain ↔ MARL two-way loop | none / weak | deep closed loop |
| ECDSA CA-less identity | none or CA-based | on-chain key registration + 3-tier guard |
| Contribution-weighted consensus | equal-weight PBFT / PoS | CW-PBFT (Shapley axioms + failover) |
| Nash equilibrium analysis | none | parameter-boundary derivation + numerical verification (50% margin) |
| Post-quantum (ML-DSA-44 / Dilithium2) | none | adapter IMPLEMENTED (`dilithium-py`, pure-Python backend; signature 2420 B / public key 1312 B / private key 2560 B; cold-mean sign 44.64 ms (SD 32.40) / verify 10.40 ms, warm-median sign 17.04 ms / verify 4.15 ms; ~2 orders of magnitude slower than ECDSA); **NOT wired into main chain (P2, independent module) — default signing path still ECDSA** |
| Gossip dynamic discovery | libp2p only, MARL-unrelated | self-built + asyncio + MARL-tuned |
| Full-chain crypto auditability | none | sign→Guard→Tx→Block→consensus |
| Ablation + λ + multi-seed stats | partial | full matrix, honest reporting |

---

## Quick Start

```bash
# 1. Install dependencies (Python 3.11+)
pip install -r requirements.txt
# 如需精确可复现（锁定本机实测版本），改用:
# pip install -r requirements.lock.txt

# Required before generating or loading private keys (no built-in fallback):
# PowerShell: $env:MARL_ECDSA_KEY_PASSPHRASE = "replace-with-a-strong-secret"
export MARL_ECDSA_KEY_PASSPHRASE="replace-with-a-strong-secret"

# 2. Run full test suite (1600+ 项自动化测试全部通过（0 失败）)
python -m pytest tests/ -q

# 3. Run a training experiment (pure vs bc vs selfish)
python main.py --mode bc_marl --n_episodes 200

# 4. Launch the interactive Web Dashboard
python -c "from visualization.dashboard import start_dashboard; start_dashboard()"
# open http://127.0.0.1:9090

# 5. Run the attack-defense demo (6 attack types)
python scripts/legacy/analysis/attack_defense_demo.py

# 6. One-click reproduction (install → 50-ep smoke train → key tests → verify_numbers)
# Idempotent & resumable; rerun to continue after a failure.
python scripts/one_click_reproduce.py
```

### Multi-consensus mode switching

Set `consensus_mode` in `config.json`: `cw_pbft` (default) / `standard_pbft` / `fast`.

---

## Experiments & Results

**Headline metric.** After **3000-episode** full convergence, BC-MARL improves the **pure environment reward (`env_reward`, excluding the BC incentive)** by **+28.17%** over Pure-MARL. This is based on **n = 71 independent random seeds per group**; Welch **p = 0.0095 (BH-FDR significant / Bonferroni non-significant)**, Cohen's **d = 0.441** (small-to-medium effect), 95% CI [0.648, 4.576] (excludes 0), post-hoc power = 0.74.

| Mode | env_reward last-50 (mean ± std) | Whole-run coop. rate (mean ± std) | Seeds | Welch p |
|---|---|---|---|---|
| **BC-MARL** | **-6.658 ± 6.045** | 62.46% ± 0.94% | 71 | (baseline) |
| Pure-MARL | -9.270 ± 5.792 | 61.27% ± 1.07% | 71 | 0.0095 (**) |

- **BC vs Pure (`env_reward`)**: +28.17% relative, **n=71, p=0.0095, d=0.441 — BH-FDR significant / Bonferroni non-significant** (95% CI [0.648, 4.576] excludes 0).
- **Retired historical calibers**: earlier revisions cited two comparison calibers — V3.7 (500 episodes, not converged) and V2 (1000 episodes, BC incentive included). Both are **retired and no longer referenced**: neither is comparable with the competition's unified `env_reward` caliber (a `total_reward` that bundles the BC incentive is not the same quantity). See the caliber registry in `number_registry.json`.
- **Whole-run cooperation rate**: over the full 3000-episode run, BC-MARL averages **0.6246 ± 0.0094** vs Pure-MARL **0.6127 ± 0.0107** (n=71/group), i.e. **+1.95%, Welch p < 0.0001, Cohen d = 1.19** — a highly significant, large-effect improvement. Note this is a *different caliber* from the `env_reward` headline above (whole-run average vs last-50 average) and the two must not be mixed.
- **Anti-betrayal**: `avg_betrayal_rate` is **exactly 0.000 in all 142 runs** (71 seeds × 2 modes, 3000 episodes each); the `selfish` control mode averages 0.35. The BC incentive/penalty design therefore prevents defection collapse.
- **CW-PBFT vs PBFT — scope of the advantage (honest reporting)**: with **synthetic** weights that already encode the fault prior (spread ratio R≈8), CW-PBFT reaches 97–99% success where standard PBFT collapses to 0% at 40% Byzantine. However, a 5-seed × 2000-round repetition experiment shows that under **uniform weights (R=1)** or weights derived from **real MARL contribution scores (R≈1.007)**, CW-PBFT is **exactly equivalent** to standard PBFT. Weighted voting therefore adds no fault tolerance on its own; the safety bound is `b < n/(2R+1)`, which for R≈1.007 reduces to the classical `n/3`. All CW-PBFT > standard-PBFT success-rate gains come from **controlled weight-broadening configs (R≈15)**; under real MARL contribution weights (R≈1.01) contribution-weighted voting is **identical** to standard PBFT (NR-39~44 verdict=IDENTICAL), and we do **not** claim contribution-weighting improves fault tolerance.
- **Attack defense**: 100% interception for the **6** signature-layer attacks (observation forgery / message tampering / replay / sybil / k-reuse / long-range) recorded in `attack_defense_report.json` and the E6 batch report `results/attack_defense_batch_report.json` (6 classes × 50 trials = 300, 100% blocked (Wilson 95% CI [92.9%, 100%] per class)); 主节点故障（不健康/被标记）触发视图切换的 failover 路径已测试通过（标记驱动模拟，未注入真实矛盾提案/equivocation），由 failover 测试套件覆盖。

> **Positioning**: the value proposition is **trust augmentation** — 容错共识（PBFT 族；实验覆盖省略/崩溃故障，不建模任意拜占庭/矛盾投票）, cryptographic identity anchoring, 100% interception of the signature-layer attacks and verifiable incentive fairness — rather than RL performance optimization. The BC effect on `env_reward` is **BH-FDR significant / Bonferroni non-significant** at n=71 (p=0.0095, d=0.441 small-to-medium effect). The incentive was designed to shape **cooperation**, and there the effect is highly significant (whole-run cooperation rate p<0.0001, d=1.19). Cross-algorithm comparison reveals strong algorithm selectivity: QMIX shows significant positive effect (p=0.035, d=0.695, n=20) while MAPPO is non-significant with negative direction (p=0.625, d=-0.222, n=10). Note also the bounded scope of the CW-PBFT advantage documented above.

---

## Repository Layout

```
marl-ecdsa-consensus-chain/
├── blockchain/
│ ├── consensus/ # CW-PBFT, Standard PBFT, Fast, Failover, factory
│ ├── crypto/ # ECDSA, SecurityGuard, KeyManager, Dilithium adapter
│ ├── contracts/ # Identity / Incentive / Penalty
│ ├── ledger/ # Block, Blockchain, WorldState
│ └── network/ # P2P, Gossip, MessageProtocol
├── marl/
│ ├── algorithms/ # QMIX etc.
│ ├── envs/ # SimpleSpread
│ └── integration/ # Bridge, SelfishAgent, CooperationDetector, AdaptiveLambda
├── visualization/ # Flask Dashboard (attack demo, consensus animation)
├── scripts/ # export_dataset.py, benchmark, ablation, one-click launchers
└── tests/ # 144 test modules (1600+ 项自动化测试全部通过（0 失败）)
```

---

## Testing

- **1600+ 项自动化测试全部通过（0 失败）**：consensus, crypto security (RFC 6979, k-reuse, replay), blockchain, MARL integration, P2P network, dashboard attack API.
- Static checks: `python -m compileall -q blockchain/ marl/ visualization/`.

---

## CI / Automation

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push / PR | Run the full test suite (py3.11/3.12) |

> There are **no scheduled or auto-committing workflows**: the repository contains no activity-farming / self-committing automation.

---

## Citation

```bibtex
@misc{marl-ecdsa-consensus-chain,
 title = {MARL-ECDSA Consensus Chain: Blockchain--AI Synergistic Consensus for Multi-Agent Reinforcement Learning},
 author = {{MARL-ECDSA Team}},
 year = {2026}
}
```

