<!-- README.md (English) | 中文版见 README.zh.md -->
# MARL-ECDSA Consensus Chain

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-2%2C183%20passed-brightgreen)](tests/)
[![Consensus](https://img.shields.io/badge/Consensus-CW--PBFT-00d4ff)](blockchain/consensus/cw_pbft.py)

**中文版**: [README.zh.md](README.zh.md)

## 口径声明（Caliber Statement · 以登记簿为准）

> 📌 **现行主口径 = 全程协作增益**（`number_registry.json`，n=101/组，全程 `summary.avg_env_reward`，不含 BC 激励）：
> · **NR-202 +6.54%**（Welch p=6.85×10⁻¹¹，Mann-Whitney p=5.36×10⁻¹⁰，Cohen d=0.971，95%CI [1.626, 2.906] 不含 0）—— **λ 真正进入训练梯度后同种子复现，主效应存活**；
> · NR-2 **+7.70%**（原初批，p=1.1×10⁻¹⁴，d=1.17）；NR-203 **+6.61%**（跨种子 301–400 泛化，p=8.2×10⁻¹²，d=1.03）。
> **三批方向一致、稳健显著**；机制修复后幅度较修复前（NR-134）略降，须并排引用两代读数并标注机制差异。
> ⛔ **末 50 回合 +25.75%（NR-1/NR-129）属「λ 未进梯度」修复前读数，不得作为现行主口径引用。** 修复后同种子重跑（NR-201）末 50 为 **+3.24%，Welch p=0.733，d=0.048，95%CI [-1.34, 1.93] 含 0 —— 不显著**。
> 🗂 **历史基线（仍登记、仅供追溯）**：n=71 口径 **+28.17% / +7.92%**（NR-1 / NR-2 原初批，p=0.0095 —— BH-FDR 显著 / Bonferroni 不显著）。

## 中文摘要（Chinese Summary）

> 本项目面向**多智能体强化学习（MARL）**场景，构建一套**区块链–AI 协同的可信共识与激励机制**：共识层为 **CW-PBFT**（贡献加权拜占庭容错共识），身份层为 **ECDSA(secp256r1) 无 CA 身份锚定 + SecurityGuard 三层防护**（时间戳窗口 / nonce 单调 / k 值重用检测），激励层为**链上激励合约**。
>
> 项目 **2,183 项自动化测试通过（0 失败，9 项跳过；共 2,192 项收集）**；对**6 类签名层攻击**（观测伪造 / 消息篡改 / 重放 / Sybil / k 值重用 / 长程）每类 50 次、共 300 次批量测试**全部拦截**（Wilson 95% 置信区间 [92.9%, 100%]）。
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
- **Rigorous experiments**: ablation matrix, λ-sensitivity and multi-seed statistics, reported under an honest caliber (current headline: **whole-run +6.54% at n=101 (NR-202, p=6.85×10⁻¹¹, d=0.971), robust to the F01 mechanism fix**; the pre-fix last-50 +25.75% is retracted (post-fix +3.24%, p=0.733, not significant); historical n=71 baseline +28.17%, p=0.0095. See [Experiments & Results](#-experiments--results)).

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

# 2. Run full test suite (2,183 项通过 / 0 失败 / 9 跳过，共 2,192 收集)
# ⚠️ Windows 用户请先启用 UTF-8 模式（默认 GBK 下 13 个编码相关用例会失败，
#    均为环境问题非逻辑缺陷；Linux/macOS CI 无此问题）:
# PowerShell: $env:PYTHONUTF8 = "1"
export PYTHONUTF8=1
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

**Headline metric — current authoritative caliber: whole-run cooperation gain (全程协作增益), n=101/group.** After **3000-episode** full convergence, BC-MARL improves the **pure environment reward (`env_reward`, excluding the BC incentive)** over Pure-MARL by **+6.54%** on the whole-run caliber (**NR-202**: −32.4286 ± 2.2913 vs −34.6982 ± 2.3849; Welch **p = 6.85×10⁻¹¹**, Mann-Whitney p = 5.36×10⁻¹⁰, Cohen's **d = 0.971**, bootstrap 95% CI **[1.626, 2.906]** excluding 0). This is the **same-seed re-run after the F01 mechanism fix** (λ actually entering the training gradient) — the main effect **survives the fix**. Two further batches agree in direction: **NR-2 +7.70%** (original batch, p=1.1×10⁻¹⁴, d=1.17) and **NR-203 +6.61%** (cross-seed generalization, seeds 301–400, p=8.2×10⁻¹², d=1.03). The post-fix amplitude is slightly lower than the pre-fix reading (NR-134 +7.70%); the two generations must be quoted side by side with the mechanism difference labelled.

> ⛔ **Retracted as current headline: last-50 `env_reward` +25.75% (NR-1 / NR-129).** That figure is a **pre-F01-fix** reading (λ not in the training gradient). After the fix, the same-seed last-50 result is **+3.24%, Welch p=0.733, d=0.048, 95% CI [−1.34, 1.93] containing 0 — not significant** (NR-201). It must not be quoted as the current last-50 caliber.

**Historical baseline (n=71/group — still registered in `number_registry.json`, kept for traceability only; NOT the current headline).** The table below is the original n=71 baseline: **+28.17%**, Welch p=0.0095 (**BH-FDR significant / Bonferroni non-significant**), d=0.441, 95% CI [0.648, 4.576], post-hoc power = 0.74.

| Mode | env_reward last-50 (mean ± std) | Whole-run coop. rate (mean ± std) | Seeds | Welch p |
|---|---|---|---|---|
| **BC-MARL** | **-6.658 ± 6.045** | 62.46% ± 0.94% | 71 | (baseline) |
| Pure-MARL | -9.270 ± 5.792 | 61.27% ± 1.07% | 71 | 0.0095 (**) |

*Table above = historical n=71 baseline (pre-F01-fix). Current authoritative whole-run `env_reward`: **+6.54%** (NR-202, p=6.85×10⁻¹¹, d=0.971) / **+7.70%** (NR-2, p=1.1×10⁻¹⁴, d=1.17) / **+6.61%** (NR-203, p=8.2×10⁻¹², d=1.03). Current last-50: **+3.24%, p=0.733 — not significant** (NR-201).*

- **BC vs Pure (`env_reward`, current — whole-run, n=101)**: **+6.54%** (NR-202), **p=6.85×10⁻¹¹, d=0.971**, 95% CI [1.626, 2.906] excludes 0 — **robust to the F01 mechanism fix**, and the current headline.
- **BC vs Pure (`env_reward`, current — last-50, n=101)**: **+3.24%, p=0.733, d=0.048 — NOT significant** (NR-201). The earlier **+25.75%** (NR-1 / NR-129) is a **pre-fix** reading and is **retracted** as the current last-50 caliber.
- **BC vs Pure (`env_reward`, historical n=71, pre-fix)**: +28.17% relative, **n=71, p=0.0095, d=0.441 — BH-FDR significant / Bonferroni non-significant** (95% CI [0.648, 4.576] excludes 0). Traceability only; not the headline.
- **Retired historical calibers**: earlier revisions cited two comparison calibers — V3.7 (500 episodes, not converged) and V2 (1000 episodes, BC incentive included). Both are **retired and no longer referenced**: neither is comparable with the competition's unified `env_reward` caliber (a `total_reward` that bundles the BC incentive is not the same quantity). See the caliber registry in `number_registry.json`.
- **Whole-run cooperation rate (pre-fix batch, n=101)**: 0.6250 vs 0.6132, i.e. **+1.92%, Welch p = 1.5×10⁻¹⁴, Cohen d = 1.17** (NR-135; historical n=71 reading 0.6246 ± 0.0094 vs 0.6127 ± 0.0107 = +1.95%, d=1.19). ⚠️ **This reading comes from the pre-fix batch (same batch as NR-134); a post-F01-fix re-measurement of the cooperation-rate caliber is NOT yet registered**, so it must be labelled pre-fix and must not be presented as a post-fix result.
- **Anti-betrayal**: `avg_betrayal_rate` is **exactly 0.000 in all 142 runs** (71 seeds × 2 modes, 3000 episodes each); the `selfish` control mode averages 0.35. The BC incentive/penalty design therefore prevents defection collapse.
- **CW-PBFT vs PBFT — scope of the advantage (honest reporting)**: with **synthetic** weights that already encode the fault prior (spread ratio R≈8), CW-PBFT reaches 97–99% success where standard PBFT collapses to 0% at 40% Byzantine. However, a 5-seed × 2000-round repetition experiment shows that under **uniform weights (R=1)** or weights derived from **real MARL contribution scores (R≈1.007)**, CW-PBFT is **exactly equivalent** to standard PBFT. Weighted voting therefore adds no fault tolerance on its own; the safety bound is `b < n/(2R+1)`, which for R≈1.007 reduces to the classical `n/3`. All CW-PBFT > standard-PBFT success-rate gains come from **controlled weight-broadening configs (R≈15)**; under real MARL contribution weights (R≈1.01) contribution-weighted voting is **identical** to standard PBFT (NR-39~44 verdict=IDENTICAL), and we do **not** claim contribution-weighting improves fault tolerance.
- **Attack defense**: 100% interception for the **6** signature-layer attacks (observation forgery / message tampering / replay / sybil / k-reuse / long-range) recorded in `attack_defense_report.json` and the E6 batch report `results/attack_defense_batch_report.json` (6 classes × 50 trials = 300, 100% blocked (Wilson 95% CI [92.9%, 100%] per class)); 主节点故障（不健康/被标记）触发视图切换的 failover 路径已测试通过（标记驱动模拟，未注入真实矛盾提案/equivocation），由 failover 测试套件覆盖。

> **Positioning**: the value proposition is **trust augmentation** — 容错共识（PBFT 族；实验覆盖省略/崩溃故障，不建模任意拜占庭/矛盾投票）, cryptographic identity anchoring, 100% interception of the signature-layer attacks and verifiable incentive fairness — rather than RL performance optimization. The current headline effect is the **whole-run** `env_reward` gain of **+6.54% at n=101 (NR-202, p=6.85×10⁻¹¹, d=0.971), which survives the F01 mechanism fix**; the pre-fix last-50 +25.75% is **retracted** (post-fix same-seed last-50 is +3.24%, p=0.733, not significant). Cross-algorithm comparison reveals strong algorithm selectivity: QMIX shows significant positive effect (p=0.035, d=0.695, n=20) while MAPPO is non-significant with negative direction (p=0.625, d=-0.222, n=10). Note also the bounded scope of the CW-PBFT advantage documented above.

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
└── tests/ # test modules (2,183 passed / 0 failed / 9 skipped of 2,192 collected)
```

---

## Testing

- **2,183 项自动化测试通过（0 失败，9 项跳过；共 2,192 项收集）**：consensus, crypto security (RFC 6979, k-reuse, replay), blockchain, MARL integration, P2P network, dashboard attack API.
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

