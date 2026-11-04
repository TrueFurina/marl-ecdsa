# CHANGELOG
> ⚠️ **历史快照 · 口径已作废（2026-09-28 标注）**
> 本文件写成时的主实验口径为 **n=22 种子/组**（对应 +29.2%、Welch p=0.126 不显著）。该口径**已被后续扩种取代、现已作废**。
> 现行唯一权威口径为 **n=71/组**（`deliverables/number_registry.json` → NR-1 / NR-2）：
> ・末 50 回合 `env_reward`（不含 BC 激励）**+28.17%**，Welch p=0.009524，Cohen d=0.4412，95%CI [0.6476, +4.5761]，检验力≈0.742，**BH-FDR 下显著 / Bonferroni 下不显著**；
> ・全程平均 `env_reward` **+7.92%**，Welch p<1e-10，Cohen d=1.1962，检验力≈1.0。
> **两口径必须同报**，禁单点宣称「激励有效」「强证据」或「证明」。
> **【2026-10-18 更新】上节 n=71 口径亦已被 10 月扩种（+30 对，2001-2030）取代**——现行权威口径为 **n=101/组**（NR-129 末50 / NR-134 全程 / NR-135 合作率，三口径 Bonferroni 全显著），详见下方 2026-10-18 指针修正。
> **本文件的历史数字一律保留、未作修改**（改历史数字等于伪造历史）；引用其数字前请先对齐登记簿。


> MARL-ECDSA 共识链 — 面向多智能体强化学习的区块链 AI 协同共识机制

> **⚠️ 历史存档说明（2026-09-14 追加；2026-10-18 指针修正）**：本 CHANGELOG 按时间顺序记录历次变更，其中的实验数字（如旧版提升率 +13.4% / +29.6% / +42.2% / +40.4% / +46.4%、p 值、测试数、λ 取值）反映**当时**的配置与口径，**均已退役、不代表现行申报口径、不得作为申报数字引用**。下一行括号内「env_reward +29.2%（n=22，Welch p=0.126 不显著，d=0.47）」为 9-14 撰写本说明时点的旧引用，**已作废，仅存档**。**现行权威口径（2026-10-18）以 `deliverables/number_registry.json` 为准**：E31/E34 主证据 **n=101/组** —— 末 50 回合 `env_reward` **+25.7%**（Welch p=0.0034，NR-129）、全程 `env_reward` **+7.70%**（p=1.1×10⁻¹⁴，NR-134）、合作率 **+1.92%**（p=1.5×10⁻¹⁴，NR-135），三口径在 Bonferroni/BH-FDR/Holm 下均显著（**新增 30 对种子单独不显著 p=0.169 须同报**；末 50 口径另有独立种子批次符号翻转的稳健性边界，见 NR-192，⛔ 禁只报末 50 +25.7%）；测试口径为下限式「**1600+ 项自动化测试全部通过（0 失败）**」（NR-19）；Nash 安全裕度 **50%**（λ=0.1）。

---

## 2026-11-04（续二）— 六条覆盖被「顺手 skip」掩盖：连带修掉一处真实口径漂移

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

上一节清掉的是「重复执行」，这一节处理另一类浪费：**假的覆盖**。
`@pytest.mark.skip(reason=...)` 不带条件，等于永久放弃——它不会自己活过来，
也没人会被提醒。全仓当时恰好有 6 处，而且**共用同一个 reason 字符串**。

### 一、6 处无条件 skip 的背后是一处真实漂移

`d9e701c8`「sync 源码对齐 V29 新基线（口径 n=101/2183 + 新版前端）」改了根副本
`analyze_all_experiments.py` 的 `_REGISTRY_FALLBACK`（n=71 → n=101），但漏了
`scripts/legacy/analysis/` 下那份。两份副本于是语义漂移：

| 编号 | 根副本（与登记簿镜像 `declared` 一致） | legacy 副本（旧口径） |
|---|---|---|
| NR-1 | 25.75% / p=0.003348 / d=0.4179 / n_a=101 | 28.17% / p=0.009524 / d=0.4412 / **n_a=71** |
| NR-2 | 7.70% / p=1.142e-14 / d=1.1749 / n_a=101 | 7.92% / p=5.02e-11 / d=1.1962 / **n_a=71** |
| NR-3 | 1.92% / p=1.504e-14 / d=1.1691 / n_a=101 | 1.95% / p=7.28e-11 / d=1.1858 / **n_a=71** |

`test_live_copy_is_semantically_identical_to_its_legacy_sibling` 因此变红。
处置方式不是修数据，而是把 6 条用例一起标了 skip —— 其中 **5 条与漂移毫无关系**。

证据链（用 API 逐版取文件核对，非推断）：

| 时点 | 根副本 | legacy 副本 | 该测试状态 |
|---|---|---|---|
| `0997c829`（10-04 源码入库） | n=71 | n=71 | 两份等价 → 文件内 **0 个 skip** |
| `d9e701c8`（11-03 V29 sync） | n=101 | n=71 | 漂移 → 6 条无条件 skip |

### 二、先实测再改，不靠推断

写了个**运行时摘除 skip marker** 的探针插件（`.agents` 外的一次性脚本，不进仓库），
6 条一起跑：

- **5 条通过**：README 双语存在性、README 无真实仓库链接、门禁自扫源码零泄漏、
  同名 basename 冻结清单、两个消费者解析到同一份；
- **1 条失败**：就是上面那条副本等价性，失败信息把三行漂移原样打出来了。

所以「这 6 条都跑不了」是错的 —— 只有 1 条真跑不了，另外 5 条是连坐的。

### 三、修法与两处刻意不做

1. legacy 副本三行兜底值同步为 n=101，与根副本、与 `number_registry.json` 镜像
   里 NR-1/2/3 的 `declared` **三方一致**。两份现在逐字节相同。
2. 摘掉 6 处 skip 装饰器，每处留一行注释指明原因与出处（`d9e701c8`）。

刻意不做：**不改成薄转发**（`from analyze_all_experiments import *`）。legacy 那份的
`BASE = Path(__file__).parent / 'results'` 依赖自身位置，转发会让它读错目录 —— 那是把一个
「数据不一致」换成「路径不一致」，更隐蔽。

### 四、f11 那条也在跑一个不存在的实现

`tests/test_f11_grandchild_cleanup.py` 原先 `exec_module` 一个本仓库**没有**的
`launcher/supervisor.py`（那边才叫 `_make_job/_assign_job/_close_job`）。模块级加载失败
属**收集期错误**，会让整份套件中断，于是降级为整模块 skip —— **实际覆盖为零**，而且
无条件 skip 永远不会自己恢复。真实实现自 2026-11-02 起就在
`visualization/business_service._win_job_kill_on_close`，由 `business_service.py:248`
对每个训练子进程调用。现改为直接打真实实现。

这条以前从未执行过，所以不敢只看它变绿。做了负对照：

| 场景 | 直接子进程 | 孙进程 |
|---|---|---|
| 有 Job Object（正测：关闭句柄） | 死亡 | **死亡** |
| 仅 terminate 子进程（负对照：无 Job） | 死亡 | **仍存活（孤儿）** |

两个方向都验证到了 —— 断言不是空转，`_alive()` 探测也没有恒真/恒假。
负对照同时证明**病灶真实存在**：这正是 F11 要防的孤儿。

`_close_job()` 是**测试侧**工具，不是生产接口：生产代码刻意不提供「关 Job」的入口，
它把句柄挂在 `_JOB_HANDLES` 上持有到本进程退出 —— 正因如此 Web 崩溃时内核才会连带杀。
测试手动关句柄，就是为了构造「持句柄的进程退出」这一触发条件。

### 五、加守卫：无条件 skip 装饰器归零

`tests/test_no_unconditional_skip.py`：AST 扫 `@pytest.mark.skip(...)` 装饰器，必须为 0。

- **不拦** `skipif` / `importorskip`：条件满足时会自己恢复执行，是正当用法；
- **不拦**函数体内的 `pytest.skip()`：通常前面有 `if <条件>:`（缺 dilithium 后端、
  缺证据 JSON、非 Windows），这类不是放弃覆盖而是「本环境不适用」；
- 确需永久放弃，登记进 `ALLOWED` 并写明**为什么不能写成 skipif** —— 多数情况下
  写到这里理由就不成立了。

带两条自检：植入一个假 skip 必须被命中（防匹配写错退化成空转）；`skipif` /
`importorskip` 必须不被误报（防逼人绕过守卫）。

### 六、实测

本机（Windows / py3.12 / 无 torch），同配置跑全量：

| 项 | 改动前 | 改动后 | 差 |
|---|---|---|---|
| 收集 | 2260 | 2263 | **+3**（新增守卫 3 条） |
| 通过 | 2233 | **2243** | **+10** = +6（F15）+1（f11）+3（守卫） |
| 跳过 | 25 | **18** | **−7** = −6（F15）−1（f11 模块级 skip，Windows 上转为执行） |
| 失败 | 2 | 2 | 0 |

两条失败仍是**既有环境红灯**，与本次无关：`test_deps_importable`（缺 torch）、
`test_next_nr::test_threaded_no_duplicate`（Windows `PermissionError`，文件锁）。

**本次不宣称耗时变化**。300.30s 与上一节 445.92s 不可比 —— 同一天内同一条基线
曾出现 556.20s 与 866.36s（1.56×），这台机器的热状态漂移远大于本节改动的量级。

剩余 18 个 skip 逐条核对，全部为**条件性且理由具体**：缺 torch（qmix 2 + mappo 10 +
torch_import_contract 2）、缺 Dilithium 后端（2）、仓库外脚本缺失（1）、容器环境
派生不出用户名（1）、反向 skip「后端可用时回落路径不适用」（1）、
hybrid 契约另测（1）。

未做：NR-19 仍未重新基线化（需配套 junit 证据，属独立流程）。

---

## 2026-11-04（续）— 套件提速 48.5%：三处重复执行被去掉，断言一条未改

> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

三条线索都指向同一类浪费：**同一段确定性计算被多条用例各算了一遍**。

### 一、同一条用例被收集 3 遍（省 118.98s）

`tests/test_v12_consensus_invariants.py` 原先写的是：

```python
from tests.test_v11_epoch_view import ConsensusV11
class ConsensusV12(ConsensusV11):
```

pytest 的 `python_classes` 里的 `Test*` 前缀过滤**只对普通类生效**，
`unittest.TestCase` 子类**无条件收集**。于是同一条用例跑了 3 遍：
本模块命名空间里的 `ConsensusV11` 一遍、继承它的 `ConsensusV12` 一遍、
`test_v11_epoch_view.py` 自身一遍。`-v` 输出里 pytest 自己就标着
`tests/test_v12_consensus_invariants.py::ConsensusV11::test_... <- tests/test_v11_epoch_view.py`。

实测三条 `test_epoch_reconfiguration_old_certificate` 分别为
27.18s / 27.11s / 27.08s，四条用例的重复部分合计 **118.98s**。而
`visualization.distributed_consensus` 是无状态模块、`setUp` 每次新建临时目录，
重复执行**零新增覆盖**。

修法：把夹具抽成**不继承 TestCase** 的 `_ConsensusHarness`，两个类各自只继承夹具、
只保留定义在自己模块里的用例。两个文件合计收集数 16 → 8。

配套守卫 `tests/test_no_testcase_leaks.py`：AST 静态扫描「import 了别处的 TestCase
子类」与「继承了别处的 TestCase 子类」，并带一条自检用例，确保守卫本身不会退化成
永远通过的空转。

### 二、活代码共演化同一段计算跑 3 遍（省 219.34s）

`TestLiveCoevolution` 三条 live 用例各调一次 `_run_mini`，其中前两条参数**完全相同**
（2 轮 × 2 种子）——第二条纯属重算。

改之前先做了两项实测，不靠推断：

| 检验 | 结论 |
|---|---|
| 同参数（2 轮×2 种子）连跑两遍 | 逐轮指标逐位相同 |
| 3 轮运行的前 2 轮 vs 直接跑 2 轮 | 逐位相同 |

后者成立的理由：`run_round(r, benign, held, attack_cum)` 只依赖 `r` 与累计攻击轨迹，
`r<2` 时 `attack_cum` 只含前两轮；`N_ROUNDS` 只有 `main()` 在用，不参与单轮计算。

据此改为在 `scope="module"` 的 `mini_rounds` 夹具里跑一次 3 轮，2 轮的用例取
`rounds[:2]`。

### 三、代理训练重复 3 次（省 79.29s）

`train_ml_defender()` 与 `train_surrogate()` 都是确定性的，实测：

* 前者连跑两次，`classifier` / `train_accuracy` / `heldout_accuracy` 逐位相同，
  且在 441 个网格点上两份判信的判定 **0 差异**；
* 后者 `SURROGATE_SEED` 是常量、分类器 `random_state=42`，两次调用
  `agreement` 0.9625 / `trusted_cells` 575 / `target` / `target_fidelity` 全等。

改为 `ml_judge` / `surrogate` 两个 module 级夹具。`sweep()` 与 `arm_s2()` 只读
`surrogate["trusted"]`，不改该字典，跨用例共享无副作用。

### 实测（同条件 A/B：两棵树紧邻先后跑完）

| | 基线（pristine main `989785b2`） | 改动后 |
|---|---|---|
| 耗时 | 866.36s（14:26） | **445.92s（7:25）** |
| passed | 2239 | 2233 |
| failed | 2 | 2 |
| skipped | 25 | 25 |
| 收集 | 2266 | 2260 |

* 提速 **420.44s / 48.5%**（1.94×）
* 条数守恒：2266 − 8（去掉 8 次重复执行）+ 2（新增守卫两条）= 2260；passed 同差 −6
* 两条 failed 与基线完全相同，都是既有环境红灯：`test_deps_importable`（本机缺 torch）、
  `test_next_nr::test_threaded_no_duplicate`（Windows 文件锁，`PermissionError 13`）

> **为什么必须 A/B**：上午同一条基线是 556.20s，下午同一棵树跑出 866.36s（机器热状态
> 不同，1.56×）。拿上午那 556s 当基线，会得出「提速约 20%」的错误结论。

> **顺带推翻一次我自己的误判**：中途看到日志停在 `test_next_nr.py .....` 十一分钟不动，
> 一度判为「用例挂死」并据此杀掉了一轮测量。实际原因是 pytest 输出重定向到文件时
> **块缓冲**，日志整体滞后；加 `PYTHONUNBUFFERED=1` 与 `-u` 后可见一直在正常推进，
> 单独跑该文件 0.98s 就结束了。教训：**看进度必须关缓冲**，否则「没输出」会被误读成
> 「没进展」。

---

## 2026-11-04 — 合并后两处收敛：无 torch 也能跑套件 / C4 档案随快照跨重启


> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

### 一、`pytest tests/` 在无 torch 的机器上从「0 条执行」恢复为全量收集

两处**收集期**错误：`tests/test_qmix.py`、`tests/test_algorithm_family_contract.py`
在模块顶层 `from marl.algorithms.qmix import ReplayBuffer, VDNMixer`，而这两个名字
只在 `qmix.py` 的 PyTorch 分支（`if HAS_TORCH:`）里定义 —— NumPy 回退分支按设计
不提供它们（回退实现是纯 Q 表的 IQL，没有回放缓存、也没有混合器）。

缺 torch 时 import 直接抛 ImportError，pytest 记成收集期错误，实测
`Interrupted: 2 errors during collection`，**2259 条一条都不跑**。CI 因为装了 torch
所以一直是绿的——这层盲区一直没人看见。

修法与 F11 同源：**不造假桩**（假桩会让这两个文件在回退路径上绿得毫无意义，
正属本项目禁止的假通过），缺依赖就整模块 skip 并把理由写进报告。修后
`2259 tests collected`，零 error。

> 顺带纠正一处旧记录：`security_audit_2026-11-02.md` §11.7 里写的"已 `--ignore`
> 这两个文件"是当时的手段，需要人工记得加参数；现在是文件自己 skip，不再依赖
> 调用者记忆。

### 二、C4 淘汰档案在快照往返中丢失（真实缺陷，含两重后果）

`to_snapshot()` 只导出 `r_registry`，**没有导出** `_r_evicted_digests` /
`_r_evicted`。而 C4 修复（淘汰即入摘要档案）恰恰依赖后者。实测（探针与本机复现）：

| 时点 | `evicted_digest_count` | `is_degraded` | 重用被淘汰的 `r` |
|---|---|---|---|
| 重启前 | 2 | `True` | 拦下 |
| 快照往返后 | **0** | **`False`** | **放行** |

两层后果：① 上轮 C4 修复只在**进程存活期内**有效，重启后缺口原样回来；
② 重启后系统**自称「未降级」**，把"已滚过内存窗口"这件事瞒掉——比缺口本身更难发现。

修复：快照补入 `r_evicted` / `r_evicted_digests`；`from_snapshot` 对缺失键退化为
空档案（旧状态文件仍能加载，不阻断启动）。修后同一探针：`digests=2`、
`degraded=True`、重用仍被拦。

同时把两条边界写进代码注释，防止后人"优化"掉：
- `_r_evicted_digests` **刻意不设上限**。淘汰是攻击者可廉价触发的，档案一旦有界，
  攻击者继续灌就能把目标 agent 的旧摘要挤出去，等于用极低成本重置 C4 检测。
- `reset_agent()` **刻意不清档案**。`r` 被用第二次无论隔多久都是私钥可能泄露的
  硬事实，不该随"重新准入"一起忘掉。

### 三、测试

- 新增 `test_security_guard_persistence.py` 三条：档案随快照往返存活（正面钉住）、
  旧快照缺字段可加载（向后兼容）、走真实状态文件
  `SigningService.save_state → 新实例 load_state` 的端到端。
- `test_combination_attacks.py::test_c4_residual_archive_is_in_memory_only` 的
  docstring 同步改写：残留边界由「重启即遗忘」收窄为「裸进程之间不共享档案」，
  断言本身不动（仍成立，且现在与正面用例互为对照）。
- `scripts/security/_probe_combination_attacks.py` 的 C4 段补测快照往返，
  并把 `survives_snapshot_roundtrip` 等字段写进证据 JSON —— 证据要能证明新能力，
  不能只在 note 里写一句"已修"。

---

## 2026-11-03（续）— CI 归位后首轮实测：修 8 处、撤回 1 处误判

> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。取证与逐条判据见
> `deliverables/assurance/reports/security_audit_2026-11-02.md` §11。

### 一、第一道门转绿：区块签名

CI 首次运行 `77 passed / 1 failed`，失败项是
`test_signature_payload_binding.py::test_block_with_genuine_tx_accepted` ——
账本自 2026-11-02 起有「出块者签名 + `state_root` 可重算」门，而测试塞的是
`state_root="0"*64` 且不签名的合成区块。`_make_block()` 改走真实出块流程
（`构造 → finalize() → sign_block()`）。顺带修掉 `test_block_with_forged_tx_rejected`
的**假通过**（原先它拦的是「区块没签名」，不是「伪造交易」）。修后 **78 passed**。

### 二、撤回一处误判

`cw_pbft_failover` 的"恢复"实际是把 main 更好的实现（显式 `UNKNOWN`）改回较差的
（预填表、一律 `HEALTHY`），已撤回，与 main 逐字节一致。
连带修掉 main 上一对**自相矛盾**的测试（见上），两份心跳测试并存 **27 passed**。

### 三、真修复：C4 组合攻击缺口关闭

`security_guard` 的淘汰摘要档案让「FIFO 挤出后重用 `r`」被拦下；测试按该文件自述的
约定翻转断言，并新增残留边界测试（档案仅进程内）。探针与证据同步重算：
**4/4 绕过 → 3/4**，C4 转 ✅ 拦截。

### 四、main 上三处既有红灯（CI 归位才看见）

1. `scripts/smoke_test_e2e.py` 的 P0-1 断言 `λ == 0.1`：P2-E 自适应 λ 后取值为
   `(0.05, 0.15)` 带内，实测 `0.10231058578630006`。改为钉「`λ_base=0.1` 的传参通路 +
   运行时在自适应带内」。
2. `tests/test_f04_web_wiring.py` 把通道键写死 `'1'`：全量套件里更早用例注册过用户后
   新用户 id 就不是 1，4 条假红（**单独跑是 5 passed**）。改为从 `session['uid']` 读。
3. `structure_guard.py --all` 报根级历史文件（先 13 个 V18–V27 等说明文档，CI 上又报
   2 个训练结果 json）：登记为**存量冻结豁免**（常量 `LEGACY_ROOT_FILES`，只减不增），
   每次运行打印提醒，不静默腐烂。搬目录会打断 README/thesis 的相对引用，以及
   `visualization/dashboard.py` 等 4 处「按裸文件名从项目根读取」的调用。
   > 那 2 个 json 是第二次才发现的：本地核对用 `git ls-files`，而它们
   > **tracked 却命中 `.gitignore`**，在临时目录 `git add -A` 时被忽略 ——
   > 本地"13 个全过"，CI 报"多 2 个"。核对仓库文件清单要以远端 tree 为准。

### 五、`test_f11_grandchild_cleanup.py` 的收集期错误

依赖 `launcher/supervisor.py`，该模块不在本仓库，模块级 `exec_module` 抛
`FileNotFoundError` → 整个 `pytest tests/` 中断（其余 2000+ 条一条没跑）。
不删用例，缺模块时整模块 skip。

### 六、门禁自身的两个 bug

- `caliber_check.py` 的 `_RE_TESTS` 不支持千分位，`2,183 passed` 被读成 `183`，
  把等于下限的表述判成假红；现接受 `1,234` 与 `1234`。
- `.agents/skills/test-gate/SKILL.md` 里把历史基线数字写成 1632（低于 NR-19 下限 2183），
  改为指向登记簿，不再另抄一份数字。
  顺带一个反讽：本节初稿为了说明这件事，引用了那个数字加 "passed" 的原文写法，
  结果被 `caliber_check --strict` 当成"新声明"判为漂移 —— 门禁是对的，
  说明这类引用只能写数字、不能带 `passed` 后缀。

### 七、全量套件第一次在 CI 上跑完：3 failed / 2275 passed / 11 skipped

3.11 与 3.12 两个 job 结果一致。三条失败都不是"被回退的修复"，而是新暴露的：

1. `test_qmix_state_index_determinism.py` 2 条 —— `_state_index` 是 **NumPy 回退**实现的
   方法，CI 全量 job 装了 torch，`IQLEstimator` 指向 torch 版 `QMIXAgent`，没有该方法。
   这暴露了工作流自身的结构问题：安全不变量门只装 `numpy+cryptography`（跑回退路径），
   全量 job 装了 torch（跑 torch 路径），**同一断言在两道门里落在不同实现上**。
   处理：文件加 `skipif(HAS_TORCH)` 并写明覆盖分工。
2. `test_f04_round_recovery.py::test_transient_failure_resume_same_txid` —— 就绪判据
   写错了：数「在线节点**个数**」而不是等「**指定的**节点」。
   `start(names=('node-3',))` 在 node-1/2 已跑时 `>= 1` 立刻成立，根本没等 node-3。
   本机（无 torch，导入快）恰好赶上；CI 上导入慢几秒就稳定失败。
   处理：按 `node` 字段精确等待，预算 3.6s → 16s。

修后复跑：**2276 passed / 13 skipped / 0 failed**（py3.12，5m59s）。
条数守恒：2275+3+11 = 2276+0+13 = 2289。

随后暴露的是**门禁自身的误判**：本文件为了说明 SKILL.md 里那个过期数字，引用了原写法
（数字 + `passed`），被 `caliber_check --strict` 当成"新声明"判为漂移。门禁是对的 ——
这类引用只能写数字，不能带 `passed` 后缀。

### 实测（本机，非对外口径）

| 项 | 结果 |
|---|---|
| 安全不变量门（10 个文件） | 78 passed |
| 全量 `tests/` | 2227 passed / 2 failed / 22 skipped（合计 2251） |
| 2 条 failed | `test_deps_importable`（本机缺 torch）＋`test_next_nr::test_threaded_no_duplicate`（Windows 文件锁，main 上同样红） |
| 未计入 | `test_qmix.py`、`test_algorithm_family_contract.py`（本机装不上 torch，已 `--ignore`） |

> 这些是**本机实测**，不是对外口径。用例总数已由 NR-19 的 2192 增长到 2251+，
> 登记簿需重新基线化（属独立流程，本次不动）。

---

## 2026-11-03 — 恢复被「源码对齐」提交静默回退的 6 处修复 + CI 归位

> 本节只记录代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

### 事故

`d9e701c`（"sync: 源码对齐 V29 新基线"）改动 258 个文件，其中 10 个源文件被整份
覆盖成更旧的基线，把 2026-11-01/11-02 的修复一并带走：

- `SecurityGuard`：k 重用检测回到 fail-open（缺 `r` 直接放行、淘汰静默遗忘、
  无字段归一）——k 重用可直接推导私钥；
- `mappo`：Critic 回归目标回到 `np.repeat(returns, n_agents)[:T]`（与逐时间步
  `v_pred` 错位）；
- `qmix`：NumPy 回退回到内建 `hash()`（受 `PYTHONHASHSEED` 影响，复跑不一致）；
- `nash_verifier`：`p_me` 回到 `(M[1,0]-M[1,1])/denom`（鹰鸽/猎鹿的混合均衡漏报）；
- `standard_pbft`：女巫门控还在，但自报 `weight` 纠偏被删（真实成员可自带 999）；
- ~~`cw_pbft_failover`：心跳表恒空 → 从未发心跳的主节点永不被判超时（死主不替换）~~
  **此条判断错误，已撤回**：main 现实现是「空表 + 对从未心跳的节点返回 `UNKNOWN`」，
  比 11-02 那版（预填整表、一律 `HEALTHY`）更严 —— 缺信息不等于健康。详见
  `security_audit_2026-11-02.md` §11.2；
- `incentive_contract` / `world_state` / `settlement_coordinator`：三处 NaN 护栏
  全被删 → NaN 被钳成满分、并永久污染账本积分。

仓库里 6 个回归锁文件都还在、断言完好，实测 **19 failed + 1 collection error**。

### 为什么没被拦住

`CI - Test Suite` 一直写在 `marl-ecdsa-consensus-chain/.github/workflows/ci.yml`。
GitHub Actions 只扫描**仓库根**的 `.github/workflows/`，子目录不会被注册 ——
该工作流**一次都没运行过**（`/actions/workflows` 只有 build-binaries 与 pages）。

### 恢复

6 个提交逐条恢复，**以 main 当前版本为底座做定点补丁**，保留 `d9e701c` 的正当增量
（QMIX 的 S9 登记注释、Nash 的 F16 `top_tier_bonus=10.0` 与 λ 边界表述、
`clear_episode_rewards`、`get_consensus_weight`、P1-12 注释）。
逐文件对照与提交清单见 `deliverables/assurance/reports/security_audit_2026-11-02.md` §10。

### 加固（不是回退）

- `verify_action_package`：把"缺字段就跳过绑定校验"改成 **fail-closed** ——
  首版允许把 `agent_id/action/timestamp/nonce` 删掉来整段跳过校验，而
  `cooperation_detector.filter_verified_packages()` 吃的正是外部传入的包；
- `extra` 纳入载荷绑定（原实现没有用例覆盖），并允许 JSON 数值写法差异
  （`1000` vs `1000.0`）以免误杀同值 float 时间戳；
- `test_signature_payload_binding.py` 里"裸字节包仍然通过"的断言是错的
  （把 fail-open 当成了不误杀），更正为断言拒绝，并新增 4 条。

### CI 归位

新增仓库根 `.github/workflows/ci.yml`（`defaults.run.working-directory` 指向子目录），
安全不变量单拆成 fail-fast job（只装 numpy + cryptography），全量套件 `needs` 它。
子目录那份保留不删，加抬头注明"不会被执⾏、可执行版在哪"。

### 审计简报的哈希修正

汇总表原先引用的 8 个哈希（`e7dfa59` 等）在远端**全部 404**，已换成真实存在的
`12212a9` / `44b3962` / `e98d5ca` / `bd56b87` / `7e20a94` / `5d509f9` /
`b07953d` / `2e30262`；P1-11 那轮为 `8bc432b`。

---

## v4.1 (2026-07-10) — 当前版本

### Bug 修复
- **`block.py` logger 未定义修复**：`sign_block()` 方法中 `logger` 未导入导致 `NameError`，已在模块级添加 `import logging` 和 `logger = logging.getLogger(__name__)`
- **`smoke_test_e2e.py` 浮点精度断言修复**：`bridge.lambda_weight == 0.3` 因自适应 λ 计算产生浮点误差而失败，改为 `abs(x - 0.3) < 0.001`
- **`qmix.py` NumPy 回退训练器增强**：原 `train_step()` 返回 `None` 无训练能力，现实现简易 Q 表 Q-learning 训练（含 TD-error 计算、ε 衰减、回放缓存采样）

### 命名修正
- **`QMIXAgent` → `IQLEstimator`**：主类名改为反映实际算法（IQL 独立 Q-learning），`QMIXAgent` 保留为向后兼容别名。PyTorch 路径和 NumPy 回退路径均已统一
- **`main.py` banner 修正**：`QMIX CTDE 多智能体强化学习` → `IQL 独立 Q-learning（CTDE 框架）`
- **`config.json` 算法标注修正**：`algorithm: "QMIX (CTDE)"` → `"IQL (Independent Q-learning, CTDE 框架)"`

### 文档修正
- **README §4 实验数据**：替换为 `fair_comparison_report.json` 实际数据（env_reward 公平口径，BC 提升 +13.4%），删除无法验证的 5 种子 t-test 表，增加消融实验 5 种子数据，增加 Nash 均衡定理证明
- **README §三 核心创新点**：CARS 共识塑形从核心创新点表中移除（实验显示负效果）。CARS 在文件结构中标注为「探索性方向」
- **README §8.5 CARS 整节删除**：因实验验证 CARS 显著降低性能（η=0.10 时 env_reward 降低 -24.2%, p=0.01），不再作为独立特性介绍
- **README §8.4 算法说明**：明确 IQL 为主算法，QMIX/VDN 为可选扩展
- **`delivery/00_集成交付汇总.md`**：数据基线从 V2 Bug 数据（+29.6%）更新为 V3.7 公平口径数据（+13.4%），X9 冲突裁决同步更新
- **`delivery/01_material_digest.md`、`02_research_report.md`、`03_高层架构设计.md`**：添加数据版本说明，标注历史数据来源于 V2 早期版本，竞赛提交以 V3.7 数据为准

### 质检报告
- 新增 `质检报告_MARL-ECDSA共识链_20260710.md`，记录 28 层深度分析结果

### 新增功能
- **真实 Merkle 树**：`block.py` 新增 `compute_merkle_root()` 和 `compute_state_root()`，用交易哈希的 Merkle 根替换 `"s"*64` 占位符。`Block.finalize()` 自动计算真实 state_root
- **私钥安全加固**：`Block.sign_block()` 改为接收 `KeyManager` 句柄和 `agent_id`，不再以 hex 字符串传递私钥。调用方 `bc_integration.py` 已同步更新
- **CARS Potential 函数修复**：将空间势能从"到最近路标的距离"改为"到分配路标的距离"，消除与 `env_reward`（`-dist_to_own`）的系统性冲突。势能权重从 0.7/0.3 调整为 0.5/0.5 减少震荡
- **多智能体规模实验脚本**：新增 `run_scale_experiment.py`，支持 3/5/10/20 agents 自动对比，多种子验证，自动生成报告
- **实验报告自动生成流水线**：新增 `run_experiment_pipeline.py`，一键运行规模实验 + 消融实验 + 生成综合报告 Markdown
- **`delivery/04~07` 数据版本标注**：为系统设计、UserStory、部署设计、安全设计四份文档添加数据版本说明
- **`train.py` 超大函数重构**：将 200 行的 `_run_episode()` 拆分为 6 个独立子方法，单方法不超过 30 行
- **全项目 17 个超大函数重构**：累计消除 2,907 行超大函数，拆分为 97 个小于 40 行的方法。
- **P2P 网络协议测试**：新增 `tests/test_p2p_network.py`，10 个测试覆盖消息协议编解码、所有消息类型、CW-PBFT 共识消息格式
- **PPT 数据更新**：`scripts/generate_ppt.py` 中 V2 旧数据（-63.91/-45.02/+29.6%）更新为 V3.7 公平口径数据（-35.11/-30.41/+13.4%），测试数 188→312

### 实验数据
> ⚠️ **以下为历史 V2 实验数据（1000 回合 / 5 种子 / λ=0.5），已作废，不得引用为结论。**
> 该配置样本量过小，且 λ 取值非竞赛配置（竞赛为 λ=0.1）；其 total_reward 数值
> （如 +42.2% / +40.4%）**含 BC 激励加成**，会系统性放大效应。
> 本项目权威口径【撰写本节时点，2026-09 前后】为 README 所述：n=22 / 3000 回合 / λ=0.1 的 `env_reward`
> （+29.2%，Welch p=0.126，**不显著**）与全程平均合作率（Δ+1.30%，p=0.0022，**显著**）。
> **【2026-10-18 标注】上句为当时时点引用，n=22 口径已作废**——现行权威口径见文件头部（n=101/组，NR-129/134/135）。

- **3 agents 1000回合实验**（5种子，λ=0.5）：total_reward 提升 **+42.2%**（-53.56→-30.96），env_reward 提升 +9.5%（-53.56→-48.46），合作率 50.73%→54.55%
- **5 agents 1000回合实验**（5种子，λ=0.5）：total_reward 提升 **+40.4%**（-76.34→-45.53），env_reward 提升 +4.3%（-76.34→-73.03），合作率 68.44%→69.61%
- **竞赛答辩PPT**：已生成 12 页幻灯片，保存至 `competition_submission/竞赛答辩_MARL-ECDSA共识链.pptx`
- **答辩Q&A文档**：新增 `答辩QA准备_MARL-ECDSA共识链.md`，覆盖 13 个高频问题

---

## v4.0 (2025-06) — 上一版本

### 核心变更
- **奖励 Bug 修复**：bc_score 从"加到每一步（25× 放大）"改为"均匀分配到每一步（÷25）"
- **环境奖励增强**：加入 `coverage_bonus=+2.0`，拉大学会/未学会差距
- **λ 参数基准**：竞赛基准 λ=0.1，env_reward 公平口径下 BC 提升 +13.4%
- **IQL 名实一致**：类名保留 QMIXAgent（历史原因），实际训练为 IQL 独立 TD-error
- **统计检验**：5 种子独立验证，Welch's t-test p < 0.001
- **消融实验**：`--ablate-*` 三开关（security/consensus/incentive），支持模块化验证

### 新增模块
- 合作检测服务 `CooperationDetector`（从 `BlockchainMARLBridge` 拆分）
- 结算协调服务 `SettlementCoordinator`（从 `BlockchainMARLBridge` 拆分）
- 签名服务 `SigningService`（从 `BlockchainMARLBridge` 拆分）
- 行为记录器 `ActionRecorder`（从 `BlockchainMARLBridge` 拆分）
- 共识塑形奖励 `ConsensusRewardShaper`（CARS 近似策略不变性）
- 自适应 λ 控制器 `AdaptiveLambdaController`（BC→MARL 双向反馈）
- Nash 均衡验证器 `NashEquilibriumVerifier`

### 修复
- 奖励分配 Bug：bc_score 放大 25 倍问题
- `SelfishAgentWrapper`：`int(3*0.3)=0` 导致自私智能体数为 0 的 Bug
- 合作检测阈值：从 50% 放宽到 30%，避免中性行为误判为背叛
- 环境奖励归一化：映射区间修正为 `[-1.5, 2.0] → [0.0, 1.0]`
- WorldState 公共接口：`_identities` 直接访问改为 `get_agent_summary()` 等公共方法
- 惩罚阈值：从硬编码改为 `config.json` 集中管理（`penalty_thresholds` 字段）
- SecurityGuard nonce 基线同步：`register_nonce_baseline()` 和 `reset_all_nonces()`
- 矿池条目上限：`MAX_R_ENTRIES=1000` 防止内存泄漏
- 创世区块：使用固定时间戳 0，保证跨运行确定性

### 实验数据
- **三模式对比**（5 种子 × 3 模式 × 1000 回合）：
  - bc_marl: avg_reward **-31.0 ± 1.4** / coop_rate 54.4%
  - pure_marl: avg_reward -52.2 ± 0.9 / coop_rate 51.4%
  - selfish: avg_reward -51.5 ± 1.4 / coop_rate 34.9%
- **统计显著性**：bc vs pure p < 0.001 ✓✓✓

---

## v3.0 (2025-03) — 已弃用

### 核心变更
- λ=0.05 实验，bc_marl 退化至 -86.15，合作率 42.6%
- 激励太弱导致合作崩溃

### 教训
- `lambda_weight` 至少 0.1，不可随意降低
- 纯负奖励环境 gamma 不能太高（>0.9 导致 Q 值发散）

---

## v2.0 (2025-03) — 已弃用（奖励 Bug）

### 核心变更
- 6 个 QMIX 致命 Bug 修复
- Dashboard v3.5（Flask + Chart.js，7 标签页）
- bc_integration v2 完整流水线（ECDSA 签名→SecurityGuard→Transaction→Block→CW-PBFT→链式追加）
- P2P 网络共识模块（3 节点 15 轮 / 4 节点 8 轮 100% 成功率）
- CW-PBFT 共识引擎（fast_consensus / simulated_consensus 两种模式）

### 实验数据
- 1000 回合，λ=0.1：
  - pure_marl avg=-63.91
  - bc_marl avg=-45.02（BC 提升 **+29.6%**）
  - selfish avg=-50.53
- 已知问题：bc_score 被错误地加到每一步（25× 放大），奖励口径非公平

### 修复
- 单向连接拓扑修复
- 副本节点 PREPARE 投票修复
- 主节点先加票再广播修复
- 严格校验 `current_block_hash`
- 每轮 reset 后 `clear_msg_cache()`
- 处理上轮残留 COMMITTED 状态先 reset

---

## v1.0 (2025-03) — 已弃用

### 核心变更
- MVP 完成，34 个源文件，端到端流水线跑通
- ECDSA 签名验证核心（secp256r1 + RFC 6979）
- SimpleSpreadEnv 环境（NumPy 自实现）
- QMIX 算法框架（CTDE 架构）
- 区块链账本核心（Transaction/Block/Blockchain）
- 网络共识模块（P2PConsensusNetwork）
- 基础可视化面板（Flask + Chart.js）
- 智能合约三件套（身份/激励/惩罚）

---

## 版本演进

| 版本 | 时间 | 状态 | 核心特点 |
|------|------|------|---------|
| v1.0 | 2025-03 | 弃用 | MVP 完成，34 源文件，端到端流水线 |
| v2.0 | 2025-03 | 弃用（奖励 Bug） | 6 个 Bug 修复，Dashboard v3.5，P2P 网络 |
| v3.0 | 2025-03 | 弃用（λ 过低） | λ=0.05 实验，合作崩溃 |
| **v4.0** | **2025-06** | **✅ 当前使用** | **奖励修复 + coverage_bonus + λ=0.1 + 5 种子验证** |

---

## 格式说明

本 CHANGELOG 遵循 [Keep a Changelog](https://keepachangelog.com/) 规范，版本号遵循 [Semantic Versioning](https://semver.org/)。