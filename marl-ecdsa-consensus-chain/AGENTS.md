# AGENTS.md — MARL-ECDSA 共识链项目事实源
> 🔴 **口径过期警示（2026-09-28 标注） — 引用前必须对齐登记簿**
> 本文件写成时的主实验口径为 **n=22 种子/组**（对应 +29.2%、Welch p=0.126 不显著）。该口径**已被后续扩种取代、现已作废**。
> 当时的权威口径为 **n=71/组**（`deliverables/number_registry.json` → NR-1 / NR-2）**——已于 2026-10-18 被 n=101 取代，见下行指针**：
> ・末 50 回合 `env_reward`（不含 BC 激励）**+28.17%**，Welch p=0.009524，Cohen d=0.4412，95%CI [0.6476, +4.5761]，检验力≈0.742，**BH-FDR 下显著 / Bonferroni 下不显著**；
> ・全程平均 `env_reward` **+7.92%**，Welch p<1e-10，Cohen d=1.1962，检验力≈1.0。
> **两口径必须同报**，禁单点宣称「激励有效」「强证据」或「证明」。
> **【2026-10-18 口径指针 · 2026-10-24 补记】上节 n=71 口径已被 10 月扩种（+30 对，seeds 2001-2030）取代**——现行主口径为 **n=101/组**（`number_registry.json` → NR-129 末 50 / NR-134 全程 / NR-135 合作率，三口径在 Bonferroni / BH-FDR / Holm 下均显著）：末 50 `env_reward` **+25.7%**（Welch p=0.0034，d=0.42，bootstrap 95%CI [0.83, 4.07]，Mann-Whitney p=0.0021，power≈0.85）；全程 **+7.70%**（p=1.1×10⁻¹⁴）；合作率 **+1.92%**（p=1.5×10⁻¹⁴）。
> **必须同报**：新增 30 对独立种子（2001-2030）**单独不显著**（Welch p=0.169，点估计 +20.5%，n=30 power≈0.42）。⛔ **禁只报末 50 +25.7%**；末 50 口径另有独立批次稳健性边界（NR-192，n=50/组：Δ=+0.53，p=0.691）。
> **本节的 n=71 数字一律保留不改**（改历史数字等于伪造历史），仅供追溯；对外材料引用时须与 n=101 并列。
> ⚠️ 本文件**仅加标注、未修改任何原数字**；正式对外出材料前须按**现行 n=101 口径**改写（本句是 2026-09-28 时点建议，其 n=71 目标已被 2026-10-18 的扩种取代；当时的方案 B 见 `deliverables/gstack/full-check-marl-ecdsa-2026-09-28.md` §7）。


> 外层是竞赛工作区，核心代码在本目录（marl-ecdsa-consensus-chain/）。权威真值详见 README.md / docs/VERIFICATION_INDEX.md 与 .agents/skills/。

## 这是什么
区块链-AI 协同共识：贡献加权 PBFT（CW-PBFT）+ ECDSA 无 CA 身份 + MARL 双向环路。CCF 第五届区块链大赛技术创新赛道 v4.1。

## 命令
- 测试: `python -m pytest tests/ -q`（基线 1600+ 项通过，跌破必须解释）
- 主实验: `python main.py --mode bc_marl --episodes 200`

## 诚实口径（最高红线）
- 实验结论保留完整统计表述（n=22 seeds, p=0.126 方向一致但不显著），禁止夸大显著性
  - 🔴 **2026-09-28 更正：本条口径已作废。** 当时的权威口径为 **n=71/组**（`deliverables/number_registry.json` NR-1 / NR-2；**该口径亦已于 2026-10-18 被 n=101 取代，见文首指针**）：末 50 回合 `env_reward` **+28.17%**（Welch p=0.0095，d=0.4412，**BH-FDR 显著 / Bonferroni 不显著**）＋全程 **+7.92%**（p<1e-10，d=1.1962），**两口径必须同报**；禁单点宣称「激励有效 / 强证据 / 证明」。上句原样保留仅为记录，**不得再据其出数**。
- Nash 均衡 = 参数边界推导+数值验证，非机器检验形式化证明
- 默认签名路径是 ECDSA；Dilithium 是适配器能力，切换需显式配置
- **门禁结果一律三段式：`通过 / 失败 / 未判定`**（2026-10-20，REA #59）。例：`185 条 = 177 通过 / 0 失败 / 8 未判定（1 PENDING + 7 INVALID 已裁定）`。
  - 禁写「185 条全部通过」——**未判定不是通过**，也不等于失败；把它单列出来，读者才知道还差哪一截。
  - 只报通过数（"177 通过"）同样禁止：分母丢失后，「0 失败」与「没跑完」无法区分。

## 禁区
- 提交包只走打包脚本，禁止手工编辑；旧包副本只读
- 私钥/密钥材料永不入库（keys/ 已隔离）
- 文档数字必须能追溯到 analyze_all_experiments.py 输出
  - ⚠️ **2026-09-28 更正**：`analyze_all_experiments.py` **自身仍在打印作废的 n=22 口径**（其报告生成段），在当前状态下**不能充当真值源**。改写完成前，数字一律以 `deliverables/number_registry.json`（NR-* 条目）为准。

## 项目级 skill（触发时读）
- `.agents/skills/project-context/` `.agents/skills/arch-rules/` `.agents/skills/test-gate/` `.agents/skills/debug-playbook/`
- 计划外脑：`plans/current.md` + `plans/decisions.md`

---

## 多会话协作规则（2026-10-16 新增，因一次真实事故）

**事实**：本仓库有多个并行会话同时工作（同日既有安全线提交，也有实验线提交）。
并发写同一文件已造成过一次事故：某会话硬编码 `NR-174` 登记，**静默覆盖**了他人的
条目，随后又与他人的 `NR-176` 撞号产生重复 ID。

### 铁律

1. **登记编号不得硬编码**。一律先用取号器原子分配：
   ```bash
   python scripts/next_nr.py --count 1        # 输出如 NR-180
   ```
   它用文件锁（Windows msvcrt / POSIX fcntl）保证跨进程互斥，并记录
   「已发放但尚未写入 registry」的编号，防止两个会话取到同一号。
2. **登记脚本必须防覆盖**：目标编号已被占用时 **FAIL 退出**并提示占位者，
   绝不静默改写他人条目（见 `scripts/register_e41_longrun.py` 的写法）。
3. **从「当前最大编号 + 1」开始发，不复用历史空号**（NR-46~50/61/88 等是
   已作废/被删条目留下的空号）。
4. **动 registry 前先备份**，且备份要 `ls` 确认真的生成
   （曾因 `backup/` 不存在导致 `cp` 静默失败）。
5. **不要凭记忆判断编号进度**——追加前先查实际最大编号。
6. git 推送前若遇非快进，先 `fetch` + `rebase`，勿 force。

### 相关文件
- `scripts/next_nr.py`：取号器（纯标准库）
- `tests/test_next_nr.py`：契约测试（含线程级并发竞态主判据）
- `deliverables/number_registry_allocations.jsonl`：发放记录（append-only）

### 工程经验（2026-10-16 补充）

7. **推送前先 `git fetch`**：本地 `origin/main` 引用可能因并行会话的操作而陈旧，
   导致 `git log origin/main..HEAD` 显示"8 个未推送"的假象（实际早已推送成功）。
   判断"是否已推送"必须以 **fetch 后的远端引用**为准，不能信本地缓存。
8. **HTTPS 推送不通时走 SSH 直推**（不改 remote 配置，避免影响其他会话）：
   ```bash
   git fetch git@github.com:MARL-ECDSA-Consensus/MARL-ECDSA-Consensus.git \
       refs/heads/main:refs/remotes/origin/main
   GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
     git push git@github.com:MARL-ECDSA-Consensus/MARL-ECDSA-Consensus.git \
       refs/heads/main:refs/heads/main
   ```
9. **材料切换（口径窗）按《材料切换执行手册》施工**：
   `deliverables/材料切换执行手册_预备_20261016.md`——已枚举 120 处旧口径数字的
   分布、旧值→新值对照、7 项新增内容、三步流水线命令与门禁四连。
   窗口期内按表执行（预计 5h），不要从零摸索。
10. **扫描器报告/探针自身是 `--root` 全量扫描的噪声源**（2026-10-17，F6 修复中发现）：
    报告全文收录命中串（含被禁令牌原样），若落在扫描根内（工作区根、`.md` 在
    `include_ext`），下一轮扫描会把它当普通文档**二次计入 → 读数自我放大**
    （实测 2980→17063）。规则：探针/中间报告一律放 `backup/`（整目录已排除）；
    A/B 对比脚本显式剔除探针前缀（`_svt_*`）；最终报告写排除区。
