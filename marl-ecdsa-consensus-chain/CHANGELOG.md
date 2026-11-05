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

## 2026-11-06 — 诚实扫描器的四种「扫了等于没扫」：空格文件名被切碎 / UTF-16 文档读成空白 / CI 文件自己从不被扫 / 零扫描报 ✅

> 本节只记工具与测试变更，不含任何实验数字。

`scripts/pre-commit/honesty_scan.py` 是 pre-commit 第 2 步、也在 CI 的
`Pre-commit gates — repo-wide` 里跑，职责是拦「假水位」表述（「解出数 5→13」、
「冲第一」、「真实水位 92%」之类）。它此前**零测试覆盖的失败路径**里，有四种情况
会让「含假水位的文档」判成「✅ 通过」。

| # | 形态 | 旧行为（实测） | 应有 |
|---|---|---|---|
| 1 | 文件名含空格 | `git diff --name-only` 输出按 `split()` 切 ⇒ `报告 记录.md` 变成 `报告` + `记录.md` 两个不存在的路径，读失败被 `except: return []` 吞掉 | 按 `-z` 的 NUL 切分 |
| 2 | UTF-16 / GBK 文档 | `read_text(errors="ignore")` 把中文整段丢弃，剩下 ASCII 里没有短语 ⇒ 通过 | 多编码探测，读得出就扫 |
| 3 | 路径含 `.git` / `build` / `dist` 子串 | `.github/workflows/ci.yml`（含 `".git"`）**从未被扫过**，连带 `scripts/build_*.py`、`static/v9-distributed.*` 共 8 个文件 | 只按**路径段**精确跳过 |
| 4 | 读不出 / 什么都没扫到 | 目录、悬空链接、git 不可用、零文件——四种都打印「✅ 诚实口径扫描通过」 | 分别是 1 / 1 / 2 / （`--strict` 下）1 |

### 实测证据（都在临时目录里现造，不依赖仓库状态）

1. 暂存 3 个各含「解出数 5→13」的文件（`control.md` / `报告 记录.md` /
   `.github/workflows/ci.yml`）：旧版只报 `control.md` 一处，另两个静默通过；
   新版三个文件各命中 2 处（短语 + 正则），共 6 处。
2. 同一句话存成 UTF-16（记事本「Unicode」，带 BOM）与 GBK：旧版对两者均
   `✅ 通过`；新版分别命中 2 处。
3. 真·非 git 目录下跑 `--cached`：旧版 `✅ 通过`、`rc=0`；新版
   `❌ 无法取得待扫文件列表（git 退出码 129：fatal: not a git repository…）`、`rc=2`。
4. 传一个目录当参数：旧版 `✅ 通过`；新版 `❌ adir: 读不出（是目录不是文件）`、`rc=1`。
5. 覆盖面差异（同一份 611 文件的工作树）：旧版自报「扫过」603 个，其中 14 个是 PNG
   （按 `errors="ignore"` 当文本读），实际含文本 589 个，且**不含**那 8 个被误伤的文件；
   新版 `597 个文本 + 14 个二进制`，文本数正好 = 589 + 8，二进制不再冒充文本。

### 改法

1. `split_z()`：只按 `\0` 切 `git diff -z` 的输出；`get_staged_files()` 显式返回
   `(文件列表, 错误说明)`，git 失败时错误说明非空，`main()` 据此 `exit 2`。
2. `classify_bytes()`：UTF-16 BOM → 解码；含 NUL 无 BOM → `binary`（无法与 PNG/PDF
   安全区分，显式跳过并计数，不假装扫过）；否则依次 `utf-8` → `utf-8-sig` → `gbk`，
   并过一道「控制字符占比 ≤ 2%」的可读性闸门（GBK 几乎能解出任何字节，这道闸门
   负责把「解出来了但明显不是文本」挡回去）。全部失败 → `decode_failed`，
   是**状态**而不是空字符串。
3. `read_document()`：目录 / 权限 / 悬空链接 → `unreadable`，与「读到了、没命中」
   彻底分开；`PROBLEM_STATUSES` 两种状态在默认模式下即判失败
   （读不懂不等于没有假水位）。
4. `is_skipped()` 成为**唯一**跳过规则（路径段精确匹配）；`main()` 里那层
   `any(ign in str(f) for ign in [...])` 子串过滤删除，并加测试防止回潮。
5. 新增 `--strict`（零个文件被扫描 ⇒ 失败，防 CI 里 cwd 跑偏）与 `--self-test`
   （16 条夹具）。收尾打印`扫过 N 个文本文件，跳过 M 个二进制、K 个忽略路径`，
   「通过」不再与「什么都没扫」同形。
6. `scan_file()` 保留旧签名（只返回命中列表）以免破坏外部调用；新增
   `scan_document()` 返回完整状态。

### 验证

| 项 | 结果 |
|---|---|
| 新增测试 | `tests/test_honesty_scan_blind_spots.py` **38 项**（含一条"子串过滤不得回潮"的源码断言）；既有 `test_gate_scripts.py` 13 项不回归 |
| 自证 | `--self-test` **16/16** |
| 变异目标 | 48 → **54**；新增 6 条逐条承重（分别 6 / 3 / 3 / 3 / 4 / 1 个用例变红） |
| 本仓实跑 | `--strict` 全仓 0 命中；`caliber_check --strict`、`structure_guard --all`、`check_evidence_closure --strict`、`check_registry_mirror` 均通过 |
| 本机全量 pytest | 2552 收集 / **2532 passed** / 20 skipped / 2 failed：`test_deps_importable`（本机 python 3.13 未装 torch，与本次无关）、`test_gate_source_is_machine_independent`（工作副本无 `.git`，`git ls-files` 越界扫到外层仓库；在带 `.git` 的副本里单跑通过） |
| CI | 两个 workflow 的 `Pre-commit gates` 步骤改为先 `--self-test` 再 `--strict` |

## 2026-11-06 — 数字复算器的三处「报告说了假话」：一条坏数据让 191 条失去校验 / 登记缺陷报成缺数据 / `--check-mirror` 从未跑通

> 本节只记工具与测试变更，不含任何实验数字。

`scripts/verify_numbers.py` 是「所有数字必须实测」的落地件：读注册表、按
glob+field 从 `results/` 复算、逐条比对 `declared`。三道自检（`--strict`、
`doctor.py --full`、`plot` 前置）都依赖它的报告。这一轮查出它自己在三种情况下
**说了不真实的话**，或干脆不说话。

| # | 形态 | 旧行为（实测） | 应有 |
|---|---|---|---|
| 1 | 某份结果文件的指标写成 `null`（跑挂了常见形态） | 整跑 `TypeError` 退出，`--report` 指定的文件**根本没生成** | 该条 FAIL，其余 190 条照查 |
| 2 | 登记缺 `role=b`（登记缺陷，数据都在盘上） | `DATA_MISSING` + 退出码 3（不阻断），理由写「本数据包不含该结果文件」 | FAIL + 退出码 1 |
| 3 | `--check-mirror`（repo↔backup 双源一致） | 对真实注册表第一条 NR-1 就 `KeyError: 'glob'`；报告一份都没写出 | 三态结论：一致 / 有差异 / **未判定** |

### 根因

1. 主循环只接
   `except (FileNotFoundError, NotADirectoryError, PermissionError, OSError)`。
   可复算家族还会抛 `extract_field` 的 `KeyError`、`float(None)` 的 `TypeError`、
   `load_json` 的 `JSONDecodeError`、`_recompute_attack` 的 `doc["summary"][...]`。
   异常穿透 `main()`，而报告是在**循环之后**才写的 ⇒ 一条坏数据把「191 条体检表」
   变成一段 traceback。门禁从「有一条红」退化成「没有门禁」。
2. `_sources_present()` 只读 `src.get("glob")`。注册表 537 个数据源里 `globs`
   有 135 处、`file` 有 31 处；用它们登记的条目在复算提前返回（`files == 0`）时
   **永远被判成「没有数据」**。于是「登记写漏了一个 role」被伪装成「数据缺失」
   ——正是本模块一直警告的那种误诊，只不过这次伪装的是**登记错误**。
3. `check_mirror()` 里 `g = src["glob"]` 直接取键：
   `globs` / `file` 条目 → `KeyError: 'glob'`；NR-19 的字符串 sources
   （junit `path#attr` 引用）→ `TypeError: string indices must be integers`。
   它只认单个 `glob`，多批次并集（如 NR-1 的 60 种子跨两批落盘）只比了前半截；
   而零比较（镜像根不存在）时 `diffs == 0` ⇒ `consistent = True`，抬头写
   「双源一致：是（比较 0 个文件）」——与 `declared` 为空的 fail-open 同一个病。

### 改法

1. 新增 `SourceReadError`：`_collect_source` 的每次取值失败都包上**文件名 + 字段名**
   （`<file>: 字段 'x.y' 取不到（KeyError）` / `值不是数值（NoneType: None）`）。
   主循环拆三段：`FileNotFoundError / NotADirectoryError` → 缺失通道（与旧行为一致，
   本机 174/191 条属于此列）；其余 `OSError`（权限 / 被占用 / 目录当文件）→ FAIL
   （「文件在，但读不出」不是缺数据）；`except Exception` → 单条 FAIL。
   FAIL 理由带异常类型与**根因帧**位置
   （沿 `__cause__` 链走到最初的出错行，而不是那行 `raise`）。
   新增 `crashed` 标记 + `CRASHED=` 汇总计数，读者能区分「算错」与「没算出来」。
   崩溃**优先于**「declared 待补登」判定：复算出不来是硬失败，不许因为登记还没
   补完就降级成 PENDING（PENDING 不阻断）。
2. `_sources_present()` 与 `_collect_source()` 用同一套模式解析（`_source_patterns`
   + `file`）；「有没有数据」和「怎么取数」不再各说各话。
3. `check_mirror()` 重写：
   * 逐 source 形态处理（`globs` / `glob` / `file` / 字符串静态引用），字符串引用
     与不可机读的字段进 `skipped` 并写明原因，**不崩、也不静默消失**；
   * 先把「两边各是哪份文件」配好再比数值：`file` 源按 data-root 范围判定
     （`deliverables/` 类派生物不在镜像范围 → `outside_data_root`，既不报差异
     也不当一致），镜像侧路径用两种基准解析（`mirror/rel` 与 `mirror/rel[1:]`），
     解析不到就记 `file_not_found`，**绝不回落到 repo 路径**（同一份文件比两次
     永远「一致」）；
   * 结论三态：`True` 真比过且全同 / `False` 有差异 / `None` 未判定，人读报告
     四种状态（未检查 / 未判定 / 是 / 否）一眼可分；
   * `--only` 同时作用于双源校验（否则「只校验 NR-1」仍会比 191 条）。
4. 新增 `--self-test`（8 条夹具，全部在临时目录里现造注册表/数据/镜像，不读仓库
   数据）：崩溃隔离、登记缺陷不误诊、双源三种 source 形态、数值漂移、零比较未判定、
   错值必 FAIL、真缺数据仍 DATA_MISSING、`--check-mirror` 端到端。
   **CI 加一步**跑它——`--check-mirror` 崩了这么久没人知道，正因为这套流程
   从来不在 CI 里。

### 验证

| 项 | 结果 |
|---|---|
| 新增测试 | `tests/test_verify_numbers_failure_isolation.py` **27 项**；原有 `test_verify_numbers_unverified_contract.py` 19 项不回归 |
| 自证 | `--self-test` 8/8 |
| 变异目标 | 43 → **48**；新增 5 条逐条承重（分别 7 / 4 / 5 / 6 / 1 个用例变红） |
| 缺陷 1 复现 | 修前：`TypeError: float() argument must be a string or a real number, not 'NoneType'`，报告文件不存在；修后：`NR-1 FAIL [复算抛异常：SourceReadError: bc_marl_seed0.json: 字段 'summary.avg_env_reward_last_50' 的值不是数值（NoneType: None）；位置 verify_numbers.py:112 vals.append(float(v)) —— 只判该条 FAIL，其余条目继续校验]`，报告照写，退出码 1 |
| 缺陷 2 复现 | 修前：`NR-1 DATA_MISSING [数据源缺失：本数据包不含该条目所需的任何结果文件]`、退出码 3；修后：`NR-1 FAIL [sources 缺 role=b（现有 role: ['a']），条目登记不完整，无法复算]`、退出码 1 |
| 缺陷 3 复现 | 修前：`KeyError: 'glob'`（第一条 NR-1 就崩）；修后：191 条 / 537 个 source 全过一遍，`consistent=未判定`（镜像根不存在）或按差异数判否，报告与 `.md` 俱在 |
| 仓库自身（总结论不变） | 本机 191 条：修前 `PASS=5 FAIL=1 PENDING=4 INVALID=7 DATA_MISSING=174`，修后**逐项相同**——修的是失败形态的归类，不是把红改绿 |
| 本机全量 pytest | 2514 收集 / **2492 passed** / 20 skipped / 2 failed：`test_deps_importable`（本机 python 3.13 未装 torch，`ModuleNotFoundError: No module named 'torch'`，与本次改动无关）、`test_next_nr.py` 线程并发瞬时（单独复跑 8/8 通过，未触碰相关代码） |
| CI 位置 | 新增一步 `Number-verification self-test`（`--self-test`，只吃临时目录数据）；全量复算仍不进 CI——权威登记表在仓库外、`results/` 3.2 GB 不入库，干净 checkout 上只能得到 DATA_MISSING |

边界（不粉饰）：

* 双源校验只比**纯点路径**形态的 `field`；注册表里大量描述性 `field`
  （如 `"DILITHIUM_AVAILABLE / 签名长度常量"`）仍是人读口径说明，进 `skipped`
  而不是被猜成路径——所以「一致」只覆盖可机读的那部分，`files_compared` 一并写出。
* `CRASHED` 是 `FAIL` 的子集（同时计入 FAIL 数），不是新状态：崩溃条目依然阻断。
* `--check-mirror` 修好之后，本机跑出来的结论是「未判定 / 否」——镜像目录本来
  就只存在于维护机上；这不是新问题，只是以前它连报告都不给。

---

## 2026-11-06 — 证据闭合门禁的「读不懂 = 没有」：截断、坏列、非对象 JSON 五处静默放行

> 本节只记工具与测试变更，不含任何实验数字。

`scripts/check_evidence_closure.py` 的口径写得很硬：**fail / unknown / unsupported /
truncated 永不被聚合成 pass**。但它的**读取层**先做了五件事，把「读不懂」折叠成
「没有」——聚合层再严格也没用。同一份 10 个 JSON 的目录实测：

| # | 形态 | 旧判定 | 应为 |
|---|---|---|---|
| 1 | `config.n_episodes: 500.0`，`episode_rewards` 只有 100 条 | `pass: undeclared` | truncated |
| 2 | `config.n_episodes: "500"`，同上 | `pass: undeclared` | truncated |
| 3 | `cooperation_rates` 是 500 个字符串 `"0.5"` | `pass: closed` | unknown |
| 4 | `cooperation_rates` 是 500 个 `null` | `pass: closed` | unknown |
| 5 | `cooperation_rates: []`（声明 500 回合） | `pass: closed` | truncated |
| 6 | 顶层是数组 / 标量的 JSON | **不出现**（输出「扫描 5 个 JSON」，目录里 7 个） | unknown |
| 7 | `--compare` 的 glob 零匹配 | 打印空表 + exit 0 | exit 3 |

三处根因，各自把「不懂」折叠成「没有」：

1. `_declared_episodes()` 只认 `isinstance(value, int)`。`500.0`（numpy `/` 的产物）
   与 `"500"`（配置被序列化成字符串）当场退化成「没声明」，再走
   `undeclared` 那条「仅记录不判罚」的分支——**写了的声明被读成没写**。
2. `usable = {name: arr for name, arr in present.items() if arr}`。函数注释写着
   「数组里若混入非数值就整列不认（宁可 unknown，不猜）」，实现却是把非数值列
   与空数组**一起丢出**可核对集合；剩下任一列正常，就判 `pass: closed`。
3. `scan_root()` 对 `not isinstance(doc, dict)` 直接 `continue`：文件既不进分母
   也不留记录，输出里的「扫描 N 个 JSON」从此不再等于目录里的文件数。

第四处同族问题在比较侧：`build_partial_order()` 有四处 `continue` 静默丢样本，
`main()` 又只把 glob 结果交给它，于是「一条都没比到」与「比完了」都是 exit 0。

### 改法

1. 新增 `_as_episode_count()`：认 `int`、整值 `float`、纯数字字符串；`null` 仍按
   「没写」处理（JSON 的 null 就是没有值），其余（`0` / `"abc"` / 对象）记
   `invalid_declaration`——读不懂与没写是两件事，不许互相顶替。
2. 列分三态：`arrays`（键在、值可解析，**含空数组**）/ `nonempty`（零填充与退化
   判定只用它）/ `malformed`（键在但读不成数值数组）。空数组参与长度核对，
   非数值列记 `malformed_column`；两者都不许聚合成 pass。
3. `scan_root()` 对非对象 JSON 记 `not_an_object`（unknown），不再静默跳过。
4. `build_partial_order()` 返回 `skipped`（`unreadable / not_object / no_seed /
   no_metric`）；`--compare` 零匹配、或匹配到文件但无一条同时具备种子与口径，
   一律 exit 3 并写明丢弃计数。
5. 自证夹具 7 → 10（补 `float_declared_truncated` / `malformed_column` /
   `list_root`），**每一类静默都必须在 `--self-test` 里被抓住**。
6. 这道门禁此前**只由 `doctor.py` 手动调用**，所以上面五处静默一直没人发现。
   CI 加一步：先 `--self-test` 证明门禁不空，再 `--strict` 判仓库。

### 验证

| 项 | 结果 |
|---|---|
| 新增测试 | `tests/test_evidence_closure_silent_skip.py` **16 项**；原有 23 项不回归 |
| 自证 | 10/10 夹具命中，聚合规则 fail-closed |
| 变异目标 | 38 → **43**；新增 5 条逐条承重（分别 1 / 1 / 3 / 2 / 2 个用例变红） |
| 仓库自身 | 3 个 JSON → 1 pass + 2 not_applicable，`--strict` rc=0 |
| 本机全量 pytest | 2489 收集 / 2466 passed / 20 skipped / 3 failed（1 条缺 torch；2 条 `next_nr` 锁竞争为本机瞬时，单独复跑 3/3 通过，未改动相关代码） |
| 全量探针 | 25/43，其余 18 条**全部**带本机批量删除守卫指纹（首个失败 #24，与既有环境局限同源；同一现象在未改动的 main 快照上可复现） |

边界（不粉饰）：`malformed_column` 只判「这列读不出数」，不判断「读出来的数对不对」；
`not_an_object` 目前一律 unknown——若将来真有「逐回合记录写成数组」的格式，需要专门
实现而不是放宽这一条。

---

## 2026-11-06 — 口径门禁的「零真值通过」：读不到真值时它一直判 ✅

> 本节只记工具与测试变更，不含任何实验数字。

`scripts/pre-commit/caliber_check.py --strict` 是 CI 里的一道口径门禁。它的退出码
此前只看**扫到了几条漂移**，于是「读不到真值」与「没有问题」在退出码上是同一件事。
四条路径实测（同一份含旧口径 `n=22 种子/组` 的文档，全部 rc=0、末行写着
「✅ 口径体检通过（无未豁免漂移）」）：

| 路径 | 触发方式 | 旧行为 |
|---|---|---|
| 真值源缺失 | 登记簿被删 / 改名 | `load_registry` 返回 `{}`，样本量族与测试数族**整族跳过** |
| 真值源损坏 | JSON 非法（合并冲突、半截写入） | `except: continue` 静默吞掉，退化成「未找到」 |
| 样本量真值为空 | 条目里没有 `n_expected` / `declared.n*` | `if not uni: continue` —— 整族跳过，输出仍写「真值源：登记簿」 |
| 测试数下限为空 | NR-19 缺失或无 `NNN+` | `tests_floor is None` → 整族跳过 |

输出里确实有一行 `⚠️`，但**末行仍是 ✅、退出码仍是 0**。这正是本仓库反复清理的
「零断言通过」：告警不是阻断，读的人只看末行与退出码。

同一性质还有一处「宣称覆盖」：`DOC_EXT` 一直含 `.docx / .pdf / .pptx`，而读取是
`read_text(encoding="utf-8", errors="ignore")` —— 这三种是二进制容器，读出来是
压缩流乱码，**一个数字都匹配不到**。实测：同一份正文写着已作废的 `n=999 种子/组` 的 docx，
旧实现在 `--strict` 下判 ✅（`sample_size=999` 根本没被读出来）。

### 改法

1. `load_registry()` 改为返回 `(内容, 来源信息)`，来源信息带 `source` 与 `error`——
   「没找到」与「找到了但坏了」不再合并成同一个空 dict。
2. 新增 `truth_blockers()` → `no_registry / registry_unreadable / no_sample_truth /
   no_tests_truth` 四个显式状态码；`--strict` 下有阻塞项**直接 exit 1**，并写明
   「无真值 ≠ 无漂移」。不加 `--strict`（pre-commit 交互场景）仍只告警。
3. 新增 `read_doc_text()`：`.docx` / `.pptx` 用标准库 `zipfile` 抽
   `word/document.xml` 与 `ppt/slides/*.xml` 正文（去标签、段尾转换行、标签间不插
   分隔符，被拆成多个 run 的数字能接回）；`.pdf` 走 `pypdf`（缺失即「未解析」）；
   纯文本按 UTF-8 解码并检查替换符占比，超千分之一判 `decode_failed`。
4. 任何读不出文字的文件进 `unparsed`，`--strict` 下 fail-closed——**没读过的文件
   不得计入「已通过」**；同时汇总行明写「扫描 N 篇文档 / 未解析 M 篇」。
5. `--strict` 全仓模式下一篇都没扫到也判失败（扩展名选择器坏了 ≠ 没问题）。

### 验证

| 项 | 结果 |
|---|---|
| 新增测试 `tests/test_caliber_check_truth_source.py` | 25 passed（原有 `test_caliber_check.py` 11 项不回归） |
| 变异目标 | 35 → **38**（三条自举：真值阻断、office 取文、未解析 fail-closed） |
| 新目标逐条 | 4 / 4 / 2 个用例变红，逐字节还原 |
| 全量探针 | **38/38** 承重 |
| 仓库自身 `--strict` | 扫描 41 篇、未豁免漂移 0、已豁免 13（与改前一致）、未解析 0 → 绿 |
| 四扇门复验 | 缺失 / 损坏 / 空样本量 / 缺下限 → 全部 rc=1，还原登记簿后 sha256 逐字节一致 |

**已知边界**：`.docx` 只取正文（页眉/脚注不取）；`.pdf` 依赖 `pypdf`，未安装的环境
会把 PDF 判成「未解析」并拦住 `--strict`（这是刻意 fail-closed，不是 bug——提示里
写了补救命令）。仓库内当前 `.docx/.pdf/.pptx` 数量为 0，故 CI 不受影响。

---

## 2026-11-06 — 变异探针的「退出码即证据」：假红根因查明，顺带堵掉一处**假承重**

> 本节只记工具与测试变更，不含任何实验数字。上一版 CHANGELOG 里「探针假红根因未定」
> 一条在此**收回**：根因已查明，且不在仓库里。

`scripts/mutation_probe.py` 判定承重只看退出码：基线要求 `rc == 0`，注入后要求
`rc == 1`。这套口径在 2026-11-06 全量跑时崩了——33 个目标只报 24/33，**从第 25 个
目标起**每个基线子进程都是「用例进度全是点、没有 pytest 汇总行、退出码 1」。
当时只能在 CHANGELOG 里写「根因未定位」。

### 一、定位：三段实测，逐段收窄

1. **同快照、同命令，前台 35/35、后台 24/33。** 说明与提交内容无关，与「这一轮
   进程怎么被启动」有关（运行环境不同）。
2. **给 `check_pytest` 临时加落盘**，拿到首个假红子进程的完整输出。stdout 停在
   `[100%]`，没有 `63 passed in 0.40s`；stderr 里多出一条**不属于 pytest** 的记录：

   ```
   [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
   {"count":60,"threshold":50,"scope":"turn",
    "targets":["...\\Temp\\pytest-of-<user>\\garbage-e0bc4f67-..."]}
   ```

3. **单文件连跑 8 次**（同一命令、同一目录）：

   | run | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
   |---|---|---|---|---|---|---|---|---|
   | rc | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
   | 有汇总行 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
   | 命中删除守卫 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**结论**：pytest 会话收尾要删自己的临时目录（60 个文件 > 阈值 50），删除被**运行
环境的批量删除守卫**拒绝，进程在打印汇总行之前退出，退出码 1。**一个用例都没失败。**
这是「环境守卫 × pytest 临时目录回收」的冲突，不是仓库缺陷，也无法在仓库里修好
——GitHub Actions 与普通终端没有这个守卫。附带影响不止探针：任何在本机沙盒内
跑且用到 `tmp_path` 的 pytest 都会在会话收尾时被打断。

### 二、真正属于仓库的缺陷：同一个 `rc=1` 在两侧被读成相反的两件事

| 子进程实际发生的事 | rc | 旧基线判定 | 旧变异判定 |
|---|---|---|---|
| 真的有用例失败 | 1 | FAIL「先修关联测试」✔ | 承重 ✔ |
| **全过，但会话收尾被打断** | 1 | FAIL「**先修关联测试**」✘ 误导 | **承重** ✘ **假证据** |

同一份输出，基线侧把人引去改根本没坏的测试，变异侧却给守卫背书。**这不是假红，
是双向失真**：24/33 那次里 `kappa-scoring-ignores-config`（#24）就是这样被记成
承重的——它的变异子进程同样只有全点、没有汇总行。也就是说旧口径的 24/33 里
**至少 1 条是假承重**，真实可证的只有 23 条。

### 三、改法（判定必须取证）

* `parse_pytest_summary()`：从 stdout 解析 pytest 计数行（`1 failed, 62 passed in 0.8s`，
  兼容 `=` 装饰、`errors/warnings` 复数、`no tests ran`）。**解析不到就返回 `None`**，
  这本身是情报，不是「0 失败」。
* `judge_baseline()`：`rc == 0` 才绿；非零但没有汇总行 → 明说「这不是关联测试红，
  先查运行环境」；有汇总行且失败/错误 ≥ 1 → 才说「先修关联测试」；有汇总行但零
  失败 → 判「退出码与用例结果自相矛盾」，fail-closed。
* `judge_mutated()`：**必须 `failed ≥ 1` 才认承重**。`rc=1` 而零失败、`rc=1` 而无
  汇总行、`rc=2/3/4/5`，一律 FAIL。
* `guard_hint()`：从子进程 stderr 里认环境拦截指纹（`SAFE_DELETE` / `PermissionError`
  等），直接写在 FAIL 行里。
* `_save_artifact()`：**解释不了的非零**（无汇总行，或汇总行说零失败）才落盘
  `reports/mutation/artifacts/<stamp>/<id>-<phase>.stdout.txt|.stderr.txt`（`reports/`
  已 gitignore）。正常被抓住的变异不落盘，避免每次多 33 份垃圾。
* 新测试 `tests/test_mutation_probe_pytest_evidence.py` **54 项**，样本直接照抄现场
  （含那份「全点无汇总行」的截断输出）。
* 变异目标 33 → **35**，方向是**自举**：把判定放宽一个字（`mut_failed < 1` →
  `< 0`）或允许无汇总行继续判定（`is None` → `is not None`），回归网必须变红。

### 四、验证

| 项 | 结果 |
|---|---|
| 新增测试 | 54 passed（0.09s） |
| 登记表守卫 | `test_mutation_targets_registry.py` 13 passed（35 条） |
| 新目标逐条 | 分别 **3 / 5** 个用例变红，`rc=1`，原文逐字节恢复 |
| 全量探针（前台） | **35/35**，工作树干净 |
| 全量探针（本机沙盒，守卫生效） | 25/35，且 10 条 FAIL **全部**写明「没有 pytest 汇总行 + 命中 SAFE_DELETE + 落盘路径」，不再误报「先修关联测试」 |

### 五、诚实边界

* 仓库侧只能做到「不再误判 + 留证」，**消除不了**触发条件（守卫在环境里）。
  在带批量删除守卫的环境里跑全量探针仍会 FAIL，那是环境事实，**不代表守卫不承重**；
  要看承重结论请在没有该守卫的终端或 CI 里跑。
* 「24/33」这个旧数字已作废，不得再引用为承重证据（其中至少 1 条是假承重）。
* 判定只解析 final summary 行；若将来有人给探针加上 `--junitxml` 之外的输出格式，
  解析器要同步，否则会 fail-closed 报「无汇总行」——宁可红，不可默默放过。

---

## 2026-11-06 — 数字门禁的「零断言 PASS」：7 条已核验条目其实一条数值都没比对

> 本节只记代码与基础设施变更；文中出现的 0.9882 / 0.9879 / 0.995 / 0.825 / 0.175 等
> 数值均来自登记表 **NR-180~183 原有 claim**，属已在册口径，不是本轮新增实验结论。

`scripts/verify_numbers.py` 是「所有数字必须实测」的落地件：按 glob+field 从
`results/` 复算，再与 `number_registry.json` 的 `declared` 逐值比对。但它的比对器
`compare()` 是这样写的：

```python
ok, deltas = True, {}
for key, dec in entry.get("declared", {}).items():   # declared 为空 → 一次都不进
    ...
```

`declared` 为空时循环体不执行，`ok` 保持初值 `True` ⇒ **判 PASS**，`deltas={}`，
退出码 0。「PASS」在这一刻等价于「没检查」，而报告抬头把它计入 `PASS=184`。

### 一、两次独立实测（不是推断）

**1）完全没有数据时，这 4 条照样 PASS。** 在只含 `results/legacy_json/` 的快照里
跑全量 191 条：

```
汇总：total=191 PASS=5 FAIL=1 PENDING=1 INVALID=7 DATA_MISSING=177
```

5 条 PASS 里除 NR-18（代码常量核对，本就不依赖数据）之外，**NR-180/181/182/183
是 `analysis=none` + `sources=[]` + `declared={}`** —— 数据缺失 177 条、FAIL 1 条、
PENDING 1 条、INVALID 7 条，只有这 4 条「不需要数据就能过」。

**2）数据与主张完全相反，照样 PASS。** 把 NR-121（主张「三类非法洪泛 20,000/20,000
= 100% 拦截、吞吐 344,279 pkg/s」）的 source 指向一份
`{"throughput_pkg_s": 1, "blocked": 0, "total_trials": 999999}`：

```
NR-121 PASS   computed={'throughput_pkg_s': 1, 'blocked': 0, ...}  deltas={}
汇总：total=1 PASS=1 FAIL=0 ...   通过（退出码 0）
```

`deltas={}` 就是证据：**零次比对**。受影响的 7 条是 NR-120/121/122（`benchmark`
+ 空 `declared`）与 NR-180~183（`analysis=none` + 空 `declared`）。

### 二、修法：空 `declared` 一律 fail-closed，并新增 UNVERIFIED 状态

- `compare()` 对空/缺失的 `declared` 直接返回失败并给出 `__declared__` 原因键 ——
  不再依赖「循环体碰巧不进」这种隐式行为；
- `main()` 新增状态 **UNVERIFIED**：登记 `status=PASS` 但无可复算值 → UNVERIFIED，
  **阻断（退出码 1）且不计入 PASS**；登记 `status=PENDING`（待补登）保持 PENDING，
  不阻断常规运行，`--strict` 下阻断；
- 报告抬头与汇总行输出 `UNVERIFIED=N`，`release_data_bundle.py` 生成的 README
  退出码说明同步（`1` = 数字不符 **或** 零断言条目）。

### 三、把 NR-180~183 接上真数据（从「零断言」变成「逐值比对」）

`benchmark` 类此前只能取**顶层**数值字段，而这 4 条的数值藏在 `ml_defender.*` 与
`runs.*[].coop_rate` 里，取不到 → 于是以空 `declared` 登记。新增 `_json_path_value()`
支持点路径取数：

```
ml_defender.train_accuracy            # 嵌套字段
runs.L1_omniscient[].coop_rate        # 列表逐项取字段，默认取均值
runs.L1_omniscient[].coop_rate#min    # 指定聚合 mean/min/max/n/sum
runs.L2_adaptive[seed=11].coop_rate   # 按字段等值定位唯一项
```

路径不存在、选择器命中数 ≠ 1、聚合对象为空都记 error（→ FAIL），**不静默当 0**。
随后 4 条改成 `analysis=benchmark` + 显式 `paths`，`declared` 填**从源文件实测的
值**（`scripts/security/ml_blindspot_result.json` / `adaptive_attacker_result.json`）：

| 条目 | 复算键 | declared |
|---|---|---|
| NR-180 | `ml_defender.train_accuracy` / `train_samples` / `heldout_samples` | 0.9882 / 9600 / 2400 |
| NR-181 | `ml_defender.heldout_accuracy` / `benign_diag.off_manifold_samples` / `total_samples` | 0.9879 / 0 / 12000 |
| NR-182 | `runs.L1_omniscient[].coop_rate` 的 mean/min/max/n | 0.995 / 0.995 / 0.995 / 5 |
| NR-183 | `runs.L2_adaptive[seed=11].coop_rate` | 0.825 |

漂移实测：把 seed 11 的 `coop_rate` 改成 0.5 → `FAIL`，`deltas={'L2_seed11_coop':
0.325}`（迁移前同一条是 PASS 且 `deltas={}`）。

### 四、NR-120/121/122 降级为 PENDING（不猜数）

E22/E23/E24 的结果文件（`results/security_replay_20261014/` 等）不在版本库内，本机
测不出 `declared`。**不猜、也不把 claim 里的文字数字抄成 `declared`**（那是自证），
改登记为 PENDING 并在 `notes` 写明审计结论：`declared` 补齐前不得标回 PASS。
`--strict` 下这 3 条阻断，常规运行不阻断（与「未核实 ≠ 错误」的既有语义一致）。

### 五、验证

| 项 | 结果 |
|---|---|
| 新增测试 | `tests/test_verify_numbers_unverified_contract.py` **19 项**（比对器 fail-closed / UNVERIFIED 状态机 / 嵌套取数语法 / 漂移抓取 / 源缺失降级 / 登记表不变式 / 迁移幂等） |
| 变异目标 | 28 → **33**，新增 5 条逐条承重（注入后 2/1/1/1/1 项变红，`rc=1`，原文逐字节恢复） |
| 迁移后全量 | `PASS=5 FAIL=1 PENDING=4 INVALID=7 DATA_MISSING=174`（FAIL 为 NR-20 缺工作区基准文件，迁移前一致） |
| `--code-check-only`（CI 原子） | 与基线一致（2 条：NR-15 PASS / NR-18 DATA_MISSING，退出码 3） |
| 登记表改动 | 仅 7 条条目 + `_mirror_sha256`（`8e9b61c8…` → `00db05e0…`，镜像与自身内容指纹保持自洽）；191 条 id 集合未变 |

**探针的一处既有局限（本轮实测，非本次改动引入）**：这 5 条目标是**逐条单跑**
验证的（`--id <目标>`，基线绿 → 注入后 rc=1 → 原文逐字节恢复；另有一批 5 条连跑
5/5 承重）。**单进程一次跑完全部目标时，第 25 个目标起会报「基线（未注入）退出码
1」**，但该次子进程的 junit 明确写着 `failures=0 errors=0`、进度行全为点，工作树
也是干净的 —— 即 pytest 判了「全过」却返回 1，属探针/环境层面的假红。在**未改动
的 main 快照**（`_base4`，28 个目标）上复跑同样得到 **24/28**、同样从第 25 个目标
开始假红，可确认与本次改动无关。故本轮不宣称「33/33 全量通过」，只宣称逐条承重
5/5；这条假红已作为待查缺陷记录，未在本 PR 内修复（避免把未定位原因的问题一并
改坏）。

### 六、需要人工执行的一步（否则镜像与权威源不一致）

`number_registry.json` 是只读镜像，权威在 `<工作区>/deliverables/number_registry.json`。
本次迁移必须**两边都跑**，否则 `check_registry_mirror.py --check` 会（正确地）报不一致：

```bash
python -X utf8 scripts/wire_unverified_entries_20261106.py --apply \
    --registry ../deliverables/number_registry.json
python -X utf8 scripts/check_registry_mirror.py --check      # 应为 PASS
```

`tests/test_verify_numbers_unverified_contract.py::test_registry_has_no_pass_entry_without_declared`
是这条迁移的持久守卫：若有人用**旧**权威源执行 `check_registry_mirror.py --sync`，
镜像会被整份覆盖回旧内容，该测试立刻变红。

### 诚实边界

本轮修的是「PASS 的门槛」与「4 条条目的可复算性」，**没有**新增任何实验数据：
NR-120/121/122 的数值仍未复算（故降级为 PENDING，不是「已修复」）；
`paths` 语法只覆盖 `mean/min/max/n/sum`，中位数/分位数未支持；
`_json_path_value` 不支持跨列表的嵌套（`a[].b[].c`），遇到会明确报错而非猜。
`verify_numbers.py` 也仍然只管「声明值算得对不对」，不管「实验跑没跑完」
（后者在 `check_evidence_closure.py`）。

---

## 2026-11-05（续三）— κ 三元组的「单一真源」只喂了统计回显，算分处仍硬编码

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

`cw_pbft.py` 顶上有一段注释，说 κ（任务 0.40 / 协作 0.35 / 合规 0.25）已经
「收敛到单一真源」，理由是此前在 3 处各自内联、改一处忘两处即口径漂移。
读代码时发现收敛的只有第 3 处 —— `_KAPPA_TASK / _KAPPA_COOP / _KAPPA_COMPLIANCE`
**只出现在 `get_consensus_stats()` 的 `weight_derivation` 回显里**，全文件再无引用。
真正参与链上结算的 `ContributionScore.weighted_score` 仍然是三个字面常量。

### 一、实测口径差 0.05，且没有任何告警

把 `config.json` 的 `blockchain.contribution_weights` 改成 0.6 / 0.3 / 0.1，
在同一个进程里同时读两条路径（任务分 1.0、协作 0.0、合规 1.0）：

| 口径 | 算式 | 结果 |
|---|---|---|
| 声明（config） | 0.60·1 + 0.30·0 + 0.10·1 | 0.70 |
| 实际（结算） | 0.40·1 + 0.35·0 + 0.25·1 | **0.65** |
| 差值 | — | **−0.05** |

也就是说：报告里写的权重、`get_consensus_stats()` 返回的权重，与实际分钱的权重
可以是两套值。改配置的人会看到统计变了、结算没变，而中间没有任何一条日志。

### 二、顺带发现值域校验缺失：和为 1 就放行

旧实现在 `cw_pbft` 里只校验 `|Σκ − 1| < 1e-6`。`{1.5, −0.5, 0.0}` 和为 1，
因此被**原样采纳**：高任务分智能体的 `weighted_score` 冲到 1.5（超出 `[0,1]`
不变式），高协作分智能体被压到 −0.5，结算时 `clamp_finite` 把两端都压成极端
档位 —— 一份错误配置不会报错，只会安静地扭曲激励方向。

### 三、修法

新增 `blockchain/contribution_weights.py`，把读取与校验收敛到一处，两个消费方
（`incentive_contract` 算分、`cw_pbft` 统计）都调 `get_contribution_weights()`
（进程内缓存，首次读盘）。校验三层，任一层不通过即**整体**回退默认值：

1. 可解析：文件存在、合法 JSON、`contribution_weights` 是 dict
2. 可量化且有限：每个 κ 能转 float 且非 NaN / ±inf
3. 值域与归一：每个 κ ∈ [0, 1]，且 Σκ = 1（±1e-6）

不做部分回退是刻意的：缺一个维度就会让 Σκ ≠ 1，直接破坏
`weighted_score ∈ [0,1]` —— 那正是第 3 层要拦的东西。

`cw_pbft` 侧同时删掉了 import 期展开的三个模块常量。快照与缓存一旦读取顺序
分叉，又会长出「统计口径 ≠ 算分口径」两套值，也就是本轮修的缺陷本身。

### 四、测试与承重证据

新增 `tests/test_contribution_weight_single_source.py`（63 项）：默认口径不变、
算分确实跟随配置（0.65 → 0.70，含结算 delta 16.5 → 17.0 的端到端验证）、
非法配置四类回退（非归一 / 负权重 / NaN / inf / 非数值 / 非 dict / JSON 坏 /
缺文件 / 缺项）、容差边界（+3e-7 接受、+5e-6 拒绝）、三维 27 组输入下
`weighted_score ∈ [0,1]`、缓存命中与重置语义。

变异目标 23 → 28（`kappa-scoring-ignores-config`、`kappa-normalization-check`、
`kappa-unit-interval-guard`、`kappa-invalid-value-partial-adoption`、
`kappa-stats-read-same-cache`），逐条实测承重：注入后分别为 4 / 5 / 2 / 6 / 1 项
变红、退出码均为 1，原文逐字节恢复。`scripts/mutation_probe.py` 的
`UNCOVERED_NOTE` 里「κ 三元组仍无变异目标」一句已过期，同步删除并留更正说明。

**诚实边界**：默认配置下 κ 仍是 0.40 / 0.35 / 0.25，行为零变化 —— 这次修的是
「配置改了不生效」和「非法配置静默通过」，不是权重标定本身。σ=0.1 / φ=0.05
仍只是声明值回显，没有参与任何计算；按 σ/φ 反算 κ 的问题见 `cw_pbft.py` 注释，
本轮未动。

---

## 2026-11-05（续二）— BC→MARL 反馈层：五条 NaN 通道，外加一个高报 20 倍的统计字段

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

上一节收尾时 `UNCOVERED_NOTE` 还剩「`marl/integration` 的自适应 λ 与结算系数」。
去补这块时先做的不是写用例，而是**灌数据**：把三个模块的入口逐个喂 NaN / ±inf，
看会发生什么。结果是五条独立的通道全部 fail-open —— 而且每一条的方向都恰好是
"坏数据反而让系统更激进"。

### 一、`adaptive_lambda`：NaN 指标把 λ 顶到上限（真实 fail-open）

收尾裁剪写的是 `max(lambda_min, min(lambda_max, x))`。对 `x=NaN` 来说，
`min(hi, nan)` 返回 `hi`（比较恒 False，`min` 保留首个参数），于是 `max` 再把它
传到上限 —— **NaN 被裁剪"洗"成了上界**。实测三项指标任一为 NaN：

| 输入 | 修复前 λ | 修复后 λ |
|---|---|---|
| 全 0.8（基线） | 0.1015 | 0.1015 |
| 共识率 NaN | **0.1500**（= 1.5·λ_base 上限） | 0.1009 |
| 合作率 NaN | **0.1500** | 0.1010 |
| 安全计数 NaN | 0.1011（静默变"无数据"） | 0.1011 |

更糟的是这一次跳变**绕过了 EMA**：`0.9*0.1 + 0.1*nan = nan`，NaN 顺着 EMA 走，
裁剪再把它洗成上限 —— 平滑机制在最需要它的时候完全失效。也就是说，链上指标
算崩的那一回合，区块链激励权重会瞬间拉满。这与审计简报 §9「NaN 被钳成满分」
是同一类错误，只是发生在参数侧而不是分数侧。

修法：新增 `_finite_float` / `_clamp_unit`，非有限值一律按"该指标缺失"处理
（回退文档既有的中性 0.5），比率越界按文档声明的 `[0,1]` 值域裁剪并告警；
收尾裁剪前加有限性判断，非有限 λ 保持上一回合值，**不再交给 `max/min`**。
顺带修掉 `_extract_security_rate` 里 `"8" + 2` 这类字符串计数直接 `TypeError` 崩掉
的路径（原来先做加法再判断 `> 0`）。

### 二、`rl_lambda`：F01 的键契约只修了一半 —— 这项指标恒为默认值

`adaptive_lambda` 在 2026-11-02 修过 F01（读 `consensus_success_rate`），
同族的 `rl_lambda._composite_metric` 漏了：它优先读 `success_rate`，回退读
`success_count` / `total_rounds`，而 `cw_pbft.get_consensus_stats()` **只提供**
`consensus_success_rate`。合作率同样读 `detector_stats`，但 `bridge.get_stats()`
从不产出这个键（真实合作率由 `on_episode_end` 以顶层 `cooperation_rate` 注入）。
两项同时落空，`composite` 里 60% 的权重被钉死在 0.5。

实测（真实 `CWPBFTConsensus`，10 轮全失败 vs 全成功）：

| 共识状态 | 修复前 composite | 修复后 composite |
|---|---|---|
| 0 成功 / 10 轮 | 0.5000 | 0.3000 |
| 10 成功 / 10 轮 | 0.5000 | 0.7000 |

也就是说，`select_lambda_by_metric` 这条"可解释性子调度器"此前输出的是**常数**，
与链上状态无关 —— 而它的 docstring 写着"与 AdaptiveLambdaController 口径一致"。
现在一致了。

**诚实边界**：`RLLambdaScheduler` 在生产路径上**没有消费者**（`grep` 全仓只有它
自己的用法示例与测试）。所以这一条是**潜伏缺陷**，不影响任何已归档结果；
修它是为了让"口径一致"这句话成立，而不是因为它正在造成危害。

### 三、一次 NaN 回报永久劫持元学习器

`episode_reward=NaN` 经 EMA 写进 `_bucket_rewards` 之后，`np.argmax` 在含 NaN 的
数组上返回 **NaN 的那个下标**，而该桶的估值永远是 NaN，于是永远被选中。实测
（ε=0，先喂 1.0 再喂 NaN）：此后 20 个回合 100% 选中同一桶，其余桶估值停在 0，
**单次 NaN 让元学习器永久失去探索能力**。

修法：非有限回报不参与元学习（不更新桶估值、不刷新回报基线），历史记录里存
净化后的值。后者不只是洁癖 —— `json.dumps(nan)` 会写成非标准 JSON 的 `NaN`
字面量，Dashboard 侧 `JSON.parse` 直接抛错，而 `get_adaptation_history()` 正是
要导出给 Dashboard 的。

### 四、NaN 共识权重直接进奖励向量（`consensus_shaper`）

`consensus_weights` 与 `contribution_scores` 此前不做任何值域检查：

| 输入 | 修复前 | 修复后 |
|---|---|---|
| 权重 NaN | 塑形奖励 = `[nan, 0.0044, 0.0037]` → 进训练 | 全部有限（按中性权重，bonus=0） |
| 权重 inf | `total_consensus_bonus` 永久 = `inf`，`get_stats()` 之后永远报 inf | 有限 |
| 贡献分 NaN | 势能 NaN → 塑形 NaN | 按无信号处理 |
| 观测含 NaN | 空间势能 NaN → 塑形 NaN | 出口兜底置 0 并告警 |

塑形奖励是**直接加在 env_reward 上**进训练的，单步 NaN 足以让整批策略梯度变 NaN
且不回滚。前三条在入境处挡（权重/贡献分），第四条挡不住 —— NaN 藏在观测里，
`np.linalg.norm` 把它带进空间势能，只能在出口兜底。

### 五、`avg_shaping_per_step` 高报 20 倍（统计口径）

三个 `_total_*_bonus` 累加的都是 **η 之前**的原始分量，而字段名写的是"每步塑形"；
势能项（potential-based）则**完全没被累计**。实测 η=0.05、10 步、3 智能体、
每步全部验证通过：

| 项 | 修复前 | 实测真值 | 修复后 |
|---|---|---|---|
| `avg_shaping_per_step` | **0.180000** | 0.009000 | 0.009000 |
| `total_verification_bonus` | **3.0000** | 0.1500 | 0.1500 |

高报倍数恰为 `1/η = 20`。这不是内部字段：`train.py` 把它以 `shaping_stats` /
`consensus_shaping_stats` 导出到训练结果，属对外口径。

**口径变更声明**：`total_verification_bonus` / `total_cooperation_bonus` /
`total_consensus_bonus` 改为累计 η 之后实际加进奖励的量，新增
`total_potential_shaping`，`avg_shaping_per_step` 改为四项之和的均值。
字段名与键名不变，只改数值口径。已 grep 全仓：**没有任何交付物或归档 JSON 引用
这三个字段**（`deliverables/` 与仓库内 `.json` 均零命中），故不影响任何 NR。

### 六、承重证据：变异目标 16 → 23

新增 7 条目标（λ 有限性 / λ 值域 / 共识键契约 / NaN 回报 / 塑形权重 / η 口径 /
塑形出口），全部登记进 `tests/mutation_targets.json` 与 `AUDIT_INVARIANT_IDS`。
新增用例 `tests/test_feedback_layer_nonfinite_contract.py`（23 条）。

**承重验证（双向）**：把这 23 条用例拿去跑**修复前**的三份源码，实测
**16 条红 / 7 条绿**；换回修复版后 23/23 绿。那 7 条本来就不该红 —— 它们是
"净化后仍要满足"的契约（值域、可 JSON 序列化、势能不变量），不是缺陷探测器。
全量探针 23/23 承重，恢复逐字节一致。

`UNCOVERED_NOTE` 相应划掉「自适应 λ 与结算系数」一条，但**没有**顺手宣称全覆盖：
激励合约的 κ 三元组权重推导仍无变异目标，这条显式写进了盲区声明。

---

## 2026-11-05（续）— 匿名门禁的两处 fail-open：占位豁免整行短路、同名即豁免

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

上一节把变异目标铺到 14 个之后，`UNCOVERED_NOTE` 里还剩几条「知道自己没测什么」。
其中一条写着「`check_submission_anonymity.py` 的逐模式承重（只测过整链）」。
去补这条时先撞到的是门禁自身的两个漏洞 —— 都是**声明说 fail-closed、实现却放行**。

### 一、占位豁免被做成了「整行短路」（真实 fail-open）

`scan_file()` 原本每行每类只取 `re.search` 的**首处**匹配，命中后拿这一处的文本
去比占位表；只要首处是占位（`SomeUser`、`/home/user`、`example.com`…），就
`continue` 掉**整行**，同一行后面的真泄漏再也不会被看。

实测（同一检查函数、同一规则表；**示例里的真名一律用占位表示**——第一版本文
写了测试用的假用户名 `devuser01`，CI 的 `--tracked` 模式立刻把本文件扫红，
本节所述的毛病正好落在了本节自己身上）：

| 构造的文本 | 修复前 | 修复后 |
|---|---|---|
| `把 C:/Users/SomeUser/x 换成 C:/Users/<开发者A>/y` | **0 命中**（exit 0） | 1 命中 |
| `C:/Users/<开发者A>/x C:/Users/<开发者B>/y` | 1 命中（只报首处） | 2 命中 |
| `C:/Users/SomeUser/bin`（纯占位） | 0 命中 ✓ | 0 命中 ✓ |

第一行不是编出来的刁钻用例——文档里写「样例路径 … 换成你的真实路径 …」正是这个
形态。修复是把 `re.search` 换成 `rx.finditer`：占位豁免本来就是**逐处**语义，
旧写法把它降级成了**逐行**语义。

### 二、`SELF_EXEMPT_FILES` 只看文件名，与自己的准入判据矛盾

该表的注释写着「准入判据：只有当文件里出现的东西是**规则定义本身**才可豁免」，
但实现是 `if p.name in SELF_EXEMPT_FILES: continue` —— 比的是**名字**。
于是任何叫 `secrets_scan.py` 的文件（比如把自己写的同名脚本一起打进提交包）都连座
隐身，里面的 `C:/Users/<真名>/...` 永远不会被扫。

修复：文件名改为**必要条件**，另要求文件头 4KB 内带显式标记
`anon-gate-exemption: rule-definition`。三个真正豁免的文件（门禁本体、它的测试、
`scripts/pre-commit/secrets_scan.py`）各加一行注释；复制进提交包时逐字节带走，
仍然豁免。同名缺标记的文件按普通文件扫，并在输出里明说「缺豁免标记」——
否则「老副本被扫出规则定义字样」会显得莫名其妙。

### 三、证据

新增 4 条用例（39 → 43）：`test_placeholder_before_real_leak_still_flagged`、
`test_two_leaks_on_one_line_both_reported`、
`test_self_exempt_name_without_marker_is_scanned`、
`test_repo_exempt_files_carry_marker_in_head`。

新增 2 个变异目标（14 → 16），均实测承重：

| 目标 | 复原的缺陷 | 未注入 | 注入后 |
|---|---|---|---|
| `anon-placeholder-per-match` | 退回 `re.search` 首处判定 → 占位在前时真泄漏 exit 0 | 43 绿 | 2 红 / 41 绿 |
| `anon-self-exempt-name-only` | 退回「同名即豁免」→ 同名无标记文件不再被扫 | 43 绿 | 1 红 / 42 绿 |

### 四、顺手推翻一条自己写的过期情报

`UNCOVERED_NOTE` 里列过「`scripts/pack_submission_zips.py` 打包链路」。
这个文件**在仓库里不存在**：`git ls-files | grep -i pack` 只有
`scripts/pack_slim_testdata.py`，全仓 `grep -rn pack_submission` 只命中那条注释
自己。一条不存在的文件不能算盲区——那是把「没查过」写成「查过但没测」。
已从声明里删除并留下更正说明；同时把「匿名门禁逐模式承重」从盲区里划掉。

### 五、不宣称的部分

本节的结论只覆盖**规则匹配与自豁免**这两条路径。门禁的容器通道（docx/xlsx/pptx/pdf）
与二进制通道仍然只靠既有用例兜底，没有逐规则登记变异目标；`visualization/` 与
`static/` 前端路由、`train.py` 等训练脚本同样不在覆盖范围内。这两处修复也**不**
证明门禁对「非身份类泄漏」（密钥、凭据、业务机密）有任何新增能力——那仍归
`secrets_scan.py`。

---

## 2026-11-05 — 承重证据制度化：变异目标 2 → 14，并堵掉探针自身的两条「假绿」通道


> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

`scripts/mutation_probe.py` 早就在仓库里，纪律也写得很足（locator 必须唯一定位、
恢复必须校验、报告落盘、未覆盖类别显式声明）。但它只登记了 **2 个**目标
（signing backend 值域、doctor 的 git head 格式）。审计简报 §1–§9 那 9 处安全与
正确性修复、加上 11-04 的 `flush_pending` 缺陷，**一处都没登记**。

工具在、纪律在、**证据不在** —— 那 9 条「已修复」仍然只是一句自述。本节把
它们变成可复跑的证据，并顺手修掉探针自身的两条假绿通道。

### 一、登记 12 个新目标（2 → 14），全部实测承重

每个目标必须同时满足四条：locator 在目标文件里**恰好**命中 1 次；未注入时关联
测试**绿**；注入后**红**；恢复后**逐字节**一致。14/14 实测：

| 目标 | 复原的缺陷 | 未注入 | 注入后 |
|---|---|---|---|
| `security-guard-r-type-normalization` | `r` 不归一 → `123` 与 `"123"` 两个键，k 重用检测被绕过（§1） | 7 绿 | 3 红 / 4 绿 |
| `security-guard-timestamp-normalization` | `timestamp` 非整数 → `abs(now_ms-ts)` 抛 TypeError，畸形包打崩守卫（§2） | 7 绿 | 2 红 / 5 绿 |
| `security-guard-nonce-normalization` | `nonce` 非整数 → `nonce <= last_nonce` 抛 TypeError（§2 第二处） | 7 绿 | 2 红 / 5 绿 |
| `ecdsa-payload-field-binding` | 不重建被签消息 → 复用公开历史签名可伪造任意交易（§6） | 24 绿 | 12 红 / 12 绿 |
| `mappo-critic-target-shape` | `np.repeat(returns,n)[:T]` 与 `v_pred` 错位（§5） | 3 绿 | 1 红 / 2 绿 |
| `qmix-state-index-hash-seed` | 走内建 `hash()` → 受 `PYTHONHASHSEED` 影响（§4） | 2 绿 | 1 红 / 1 绿 |
| `nash-mixed-p-me-formula` | `p_me` 与 `p_opp` 不同公式 → 混合均衡漏报（§3） | 3 绿 | 2 红 / 1 绿 |
| `pbft-self-reported-weight` | 吃成员自报权重（`weight=999` 撬阈值）（§7） | 8 绿 | 1 红 / 7 绿 |
| `failover-unknown-heartbeat` | 缺省 0 判超时 → 每轮虚假视图切换（§8） | 27 绿 | 5 红 / 22 绿 |
| `incentive-nan-clamp` | NaN 被钳成满分 → 算崩的拿最高激励（§9） | 13 绿 | 7 红 / 6 绿 |
| `world-state-nonfinite-reject` | NaN 写进积分 → 永久污染（§9 第二层） | 13 绿 | 2 红 / 11 绿 |
| `action-recorder-flush-clear` | `clear()` 嵌在 `bc_node` 判断内 → stub 模式不排空（11-04） | 34 绿 | 2 红 / 32 绿 |

原有两条也一并重跑：`signing-backend-value-domain` 22 绿 → 13 红；
`doctor-git-head-format` 3 绿 → 2 红。汇总 **14/14 目标探测且承重**。

### 二、探针自身有两条「假绿」通道（都已堵）

1. **pytest 类完全没有基线检查**。原实现对 `kind=pytest` 只跑一次「注入后」，
   退出码非 0 即判承重。于是一个**本来就红**的关联测试文件，能让任何变异体
   都"通过" —— 变异在红基线上不携带任何信息。现改为：基线必须绿，注入后必须红。

2. **`rc != 0` 不等于「有用例失败」**。pytest 的 2=被中断、3=内部错误、4=用法错、
   5=一条都没收集，全都是非零。原实现会把「args 路径写错 / 一条没收集」读成
   「守卫承重」—— **把门禁噪音当成证据**。现只认 rc=1，其余一律 fail-closed 记
   FAIL 并把退出码含义打进报告。

顺带把「目标文件 git 干净」的判定与 `tests/mutation_targets.json` 的静态校验
合并成一套规则 `validate_targets()`：探针拒跑的登记，测试也必须判红，不再有
「探针说不行、测试说没事」的两套真值。

### 三、恢复的是文本，不是字节（行尾）

原实现用 `Path.read_text()` / `write_text()`，默认做 universal newline 转换：
Windows 上把 LF 文件**整份**写成 CRLF。注入确实被"恢复"了，但恢复的是文本，
工作树留下整文件行尾翻转的假改动（`git status` 报 M，`git diff` 却是空的）。

现改为 `read_bytes` / `write_bytes`，显式记录原文行尾并在写回时还原，恢复校验
也改成**字节比对**（`path.read_bytes() == raw_before`）。报告里因此多两个字段：
`line_ending`（CRLF/LF）与 `original_sha256`（字节级）。实测：目标文件里既有 CRLF
（`security_guard.py`）也有 LF，14 个目标恢复后 `git status` 均无输出。

### 四、登记表本身进 CI：`tests/test_mutation_targets_registry.py`

探针是**手动**工具（刻意不进必需链），所以登记表漂移只会安静地烂掉 —— locator
指向的行被改掉之后，要等到下次有人手动跑才喊。新增 13 条静态守卫，把「探针拒跑
的条件」提前成 CI 里的红/绿：

* 必填字段齐全、id 唯一、`check.kind` 合法、关联测试文件真实存在；
* locator **恰好**命中 1 次（0 次 = 漂移，多次 = 歧义）；
* locator 与 mutation 不得相同（相同 = 空变异）；
* `AUDIT_INVARIANT_IDS`：12 个审计目标不得从登记表里消失（防止静默删证据）；
* 行尾往返自检（LF / CRLF 各一条，注入+还原的完整往返也要字节一致）。

七条负向自检防退化：目标文件不存在 / locator 命中 2 次 / 命中 0 次 / 空变异 /
关联测试不存在 / 未知 kind / 空登记表 —— 每一种都必须被判红。实测两种真实退化：
把 locator 改成漂移写法 → 3 条红；删掉 `action-recorder-flush-clear` → 1 条红
（命中 `AUDIT_INVARIANT_IDS`）。

### 五、CI 加第三道门：无 torch 回退档全量套件

审计简报 §12.1 记过一个结构问题：`qmix.py` 是**一个模块两套实现**，由模块级
`HAS_TORCH` 选择。全量 job 装了 torch ⇒ 2200+ 条用例全部落在 torch 实现上；
回退实现只有「安全不变量」那 10 个文件覆盖。于是「第一道门绿」推不出
「回退路径绿」，而回退路径**恰恰是 torch 装不上时真实会跑的那条**。

新增 `test-fallback` job：只从 `requirements.txt` 摘掉 torch 一行，其余依赖与全量
job 完全一致 —— 两个 job 的差异变量只有「torch 在不在」。两道保险：

* 一步 `find_spec('torch') is None` 断言：若依赖解析把 torch 作为传递依赖拖进来，
  本 job 会退化成全量 job 的复制品（假绿），断言直接拦下；
* 唯一豁免 `test_deps_importable` 用 `--deselect` 显式点名（它的契约就是
  "requirements 里每个依赖都能 import"，本 job 刻意不装 torch，此环境不适用）。
  不改软断言 —— 改软等于让它在全量 job 里也失去意义。

本机（Windows / py3.12 / 无 torch / 干净 tarball）实测该档：**2249 通过 / 3 失败 /
20 跳过**，三条失败全部是可解释的环境差异（tarball 无 `.git` 导致
`test_gate_source_is_machine_independent` 红、缺 torch 导致 `test_deps_importable`
红、Windows 文件锁导致 `test_next_nr` 并发用例红）；前两条在 CI 里分别由 `.git`
与 `--deselect` 消失，第三条只在 Windows 出现。

### 实测小结

* 探针：14/14 承重，基线全绿，恢复全字节一致；单次全跑约 10 秒。
* 新增守卫：13 条全绿；两种真实退化分别打红 3 条 / 1 条。
* 全量套件（干净 tarball，本机无 torch）：2249 通过 / 3 失败 / 20 跳过，
  失败集合与上一轮完全一致（未引入新红）。
* **没有**宣称「测试有覆盖率保证」：变异只证明**这 12 个点**上有用例真的盯着，
  未登记的地方仍然是未知。未覆盖类别已在 `UNCOVERED_NOTE` 里更新并随报告输出。

---

## 2026-11-04（续五）— 16 条「零断言」用例：其中两条各自掩盖了一个真实问题

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

用 AST 扫全仓 `tests/test_*.py`（2211 条 `test_*` 函数），找出**函数体内没有任何
断言**的用例：**16 条**。它们永远 PASS —— 被测行为完全错了也不会红。

这类用例比「被 skip」更危险：skip 至少会在报告里留下痕迹，零断言用例
**看起来是通过的**。而其中两条各自精确地描述了一个真实问题却从未失败过。

### 一、`flush_pending()` 在 stub 模式下从不回收缓冲（真实缺陷，已修）

`marl/integration/action_recorder.py`：

```python
if self.bc_node is not None and self._pending_actions:   # 修复前
    ...
    self._pending_actions.clear()                        # clear 嵌在 if 之内
```

`record_action()` 无条件 `append`，而 `flush_pending()` 只在有 `bc_node` 时才清 ——
stub 模式（`bc_node=None`）下 flush 是**空操作**，缓冲随回合数单调增长。实测：

| 场景 | flush 前 | flush 后 |
|---|---|---|
| 有 `bc_node` | 24 | **0** |
| stub（`bc_node=None`） | 24 | **24** |
| stub 跑 20 回合 ×100 步 | — | **2000（从不回收）** |

同一个类里的 `batch_upload()` 是把 `clear()` 放在 `bc_node` 判断**之外**的 ——
两个「排空缓冲」的方法处置不一致，这本身就是缺陷的旁证。

调用方 `Bridge.on_episode_end()` 的编排第 7 步还留着一句
`self._recorder._pending_actions.clear()` 兜底 —— 那正是这条缺陷的痕迹。
而仓库里正有 P1-4「替代直接操作 `_` 前缀属性」的整改号召，一旦有人把第 7 步
当冗余删掉，泄漏就会露出来。

修复：把 `clear()` 移出 `bc_node` 判断，与 `batch_upload()` 对齐；stub 模式下
记一条 debug 说明「无可上链节点，仅排空缓冲」。

### 二、`test_corrupted_priv_key_regenerates`：写错的是 docstring，不是实现

该用例名为「…regenerates」、docstring 写「新实例应能检测损坏并重新生成」，
但**既没有调用被测方法，也没有任何断言** —— 只留了准备代码（造一个损坏的
私钥文件），然后就结束了。

实测真实行为（探针，非推断）：抛 `ValueError`，且

* 损坏的私钥文件**不被改写**（不留半成品）
* 公钥文件**不被改写**（链上身份仍可读）
* 重复调用仍以同样方式失败（不会第二次「自愈」）

这是正确的 **fail-closed**：静默重新生成会换掉密钥对，而公钥可能已上链，
历史签名将全部失配，且用户不会知道自己被换了钥。所以改的是用例名与断言，
不改实现 —— 现更名为 `test_corrupted_priv_key_fails_closed`，把上面四条钉住。

### 三、其余 14 条补上可失败的断言

把 `*_noop` / `*_no_crash` 从「不抛异常」升级为「可判定无副作用」：

| 文件 | 用例 | 补的断言 |
|---|---|---|
| `test_world_state.py` | `add_score_unregistered_noop` | 不得凭空建条目；`get_all_scores()=={}`；读分仍 `KeyError` |
| `test_world_state.py` | `betrayal_unregistered_noop` | 不建积分/行为档案；权重 0.0；摘要 `{}` |
| `test_world_state_behavior.py` | `record_action_unregistered_noop` | 不建行为档案；`_behaviors` 仍恰好 2 项 |
| `test_world_state_behavior.py` | `record_betrayal_unregistered_noop` | 背叛计数 0；无档案 |
| `test_world_state_behavior.py` | `record_cooperation_unregistered_noop` | 不建积分条目；他人计数不受影响 |
| `test_action_recorder_boundary.py` | `flush_without_bc_noop` → `_drains_buffer` | 原断言 `len(...) >= 0` 对 list **恒真**；改为排空 + 不计数 |
| `test_dashboard_startup.py` | `run_server_flask_unavailable` | 断言记录了 error 日志（静默 return 会让「未装 Flask」表现为无响应） |
| `test_f11_process_and_lock.py` | `file_lock_acquire_release_ok` | 锁文件被建出；两次都真的走完上下文管理器 |
| `test_p2p_consensus_network.py` | `update_weights_unstarted_noop` | `nodes` 为空；`get_weights()=={}` |
| `test_p2p_node_msgs.py` | `broadcast_no_peers_no_crash` | 广播后 `_connections` 仍为空 |
| `test_plot_helpers.py` | `empty_no_crash` | 空数据仍产出非空图（契约是"能出图"） |
| `test_plot_results.py` | `empty_leaderboard_no_crash` | 无数据时**不**写空图 |
| `test_signing_service_boundary.py` | `verify_episode_none_bc_no_crash` | 验签/失败计数均不增长 |
| `test_signing_service_more.py` | `verify_no_bc_returns` | 同上 |

顺带修掉一处**假断言**：`assert len(ar._pending_actions) >= 0  # 不崩溃即可`
—— 对 list 恒真，任何实现都能过。

### 四、新增守卫 `tests/test_no_assertion_free_tests.py`

AST 扫描全仓 `test_*`（含 `async def`），要求函数体内至少有一种断言形态：
`assert` / `raise` / 名字以 `assert` 开头的调用（`self.assertEqual` 等）/
`pytest.raises|fail|warns|approx|deprecated_call`。

刻意**不拦弱断言**（如对 `len()` 恒真的 `assert x >= 0`）—— 那需要按表达式推断
恒真性，误报率高，属另一个族。

三条自检防退化：

1. 植入一条只有赋值的用例 → 必须被命中
2. 6 种合法断言形态 → 不得误报
3. `async def` 用例 → 必须纳入扫描

外加两项结构性检查：

* **分母自检**：扫到的用例数必须 ≥ 2000（当前 2211）；低于即说明 `rglob` 或
  判据退化，守卫在空转而不是在保护
* **双向对账**：`ALLOWED` 里每条都必须仍是一条真实存在的无断言用例；
  过期条目（用例已补断言/改名/删除）会报错 —— 否则将来同名的空用例被静默放过

例外仅 1 条：`test_deps_scripts.py::test_deps_importable`，理由写进 `ALLOWED`
—— 它的契约就是「import 不抛 ImportError」，写 `assert True` 只是把空转伪装成断言。

### 五、实测

* `marl/integration/action_recorder.py`：stub 模式 flush 后缓冲 24 → **0**；
  2000 步累积从 2000 → **0**；有 `bc_node` 路径行为不变（`_tx_count` 仍 24）
* 受影响的 9 个测试文件：**81 passed**
* 守卫自身：**4 passed**
* 全仓零断言用例：**16 → 1**（剩余 1 条为显式例外）
* 变异验证：
  - `flush_pending`：还原缺陷 → 2 条断言红；删掉 `clear()` → 3 条红
  - 守卫：清空 `ALLOWED` / 登记幽灵例外 / 判据恒 False / 扫描根为空 /
    真实用例摘掉断言 —— **5/5 命中**，且各自打到对应分支；
    分母自检单独验证（空根 + 空 `ALLOWED` → 「只扫到 0 条」）

---

## 2026-11-04（续四）— 一个模块两套实现：回退分支在 CI 上从未被执行

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

`marl/algorithms/qmix.py` 是**一个模块、两套实现**，由模块级 `HAS_TORCH` 选择：
有 torch 走 `QMIXAgent` / `VDNMixer` / 混合网络，无 torch 走纯 Q 表的 IQL 回退。

覆盖被环境劈成两半，而且**两半互不相交**：

| 环境 | 执行哪半 | 另半 |
|---|---|---|
| CI（`ubuntu-latest`，装了 torch） | PyTorch 分支 | 回退分支**一行不跑** |
| 开发机（常无 torch） | 回退分支 | PyTorch 分支**一行不跑** |

于是回退实现里的任何回归，**CI 全绿也发现不了**，只会在某台无 torch 的机器上炸。

`tests/test_torch_import_contract.py` 已经用假 `torch` 包验证过「回退分支能被
`import`」，但**import 成功 ≠ 能干活**。本节补的是"能干活"这一层。

### 一、新增 `tests/test_qmix_dual_path_contract.py`

用同一个会抛 `ModuleNotFoundError(name='torch')` 的假包遮蔽真 torch，
在**任何环境**（包括 CI）强制走回退分支，然后跑一遍真实训练动作：
构造 trainer → `init_hidden` → `get_actions` → `store_episode` ×2 → `train_step`。

同一段调用代码也用于驱动 PyTorch 分支。四条用例：

1. **回退分支可被驱动**（任何环境都跑）——并断言 `has_torch is False`，
   证明假包确实生效；否则它在重复测 PyTorch 路径，回退分支仍然零覆盖。
2. **PyTorch 分支可被驱动**（`importorskip("torch")`）。
3. **两条路径逐项对齐**：先断言本次真的拿到 `{False, True}` 两个取值
   （否则字段比对退化成"同一份实现自己比自己"），再比契约字段。
4. **对断言本身的自检**：注入 7 种违规（`train_step` 恒返回 None / 动作个数不符 /
   越界 / 非整数 / 三个公开名字被删），每一种都必须被拦下；外加合规基线必须通过。

### 二、只比契约，不比数值

模块自己在缺 torch 时就会警告「结果口径与 PyTorch 版不同，禁止跨实现混比」。
因此对齐的是**调用契约**：动作个数 = `n_agents`、动作是整数、取值在
`[0, n_actions)`、数据足够时 `train_step` 必须产出损失（而不是 `None`）、
`QMIXAgent` / `QMIXMixer` / `QMIXTrainer` 三个名字都在。

### 三、mappo 不需要同样的处理

`marl/algorithms/mappo.py` 的回退分支是**显式占位**：

```python
class MAPPOTrainer:  # pragma: no cover
    def __init__(self, *a, **k):
        raise ImportError("MAPPO 需要 PyTorch")
```

它在构造时就 fail-closed，不存在"悄悄换成另一套实现"的路径，因此没有两半覆盖问题。

### 四、一处自我更正

初次用 AST 比对 `QMIXTrainer.__init__`，得出「PyTorch 版 13 个参数 / 回退版 5 个，
接口不兼容」——**这个判断是错的**。两边的 `__init__` 与 `train_step` 都带 `**kwargs`
（回退版写作 `train_step(self, **kwargs)`），多出来的参数会被吸收，不会 `TypeError`。

真实差异只有两处，且都不影响位置调用：
- `store_episode` 的形参名不同（`episode_data` / `data`）—— 只有**关键字调用**会破；
- `train_step` 回退版是 `**kwargs`，**位置传参**（`train_step(64)`）会 `TypeError`，
  必须写 `train_step(batch_size=64)`。

新用例统一用关键字形式调用，正是为了同时兼容两侧。

### 五、实测

- 本机（Windows / py3.12 / 无 torch）：`2 passed, 2 skipped`。
- 干净 tarball 全量：`3 failed, 2245 passed, 20 skipped`。
  与上一轮基线（`2243 passed / 18 skipped`）相比 **+2 passed / +2 skipped**，
  精确对应新增的 4 条用例；失败集合不变，仍是三条环境差异
  （tarball 无 `.git` 的 tracked 门禁 / 本机缺 torch / Windows 文件锁）。
- PyTorch 分支的两条用例只在 CI 上执行 —— 这正是本次要修的那个缺口本身。

---

## 2026-11-04（续三）— 同名副本「为什么不构成缺陷」落成代码

> 本节只记代码与基础设施变更，**不含任何实验口径数字**（口径见
> `deliverables/number_registry.json`）。

前两节拆掉了「重复执行」与「假覆盖」。这一节处理第三种浪费：**看起来有守卫，
其实没人判**。`tests/test_module_resolution_contract.py` 把 5 对同名 basename 冻结
在 `FROZEN_DUPLICATES` 里，但检视后发现，**只有 `analyze_all_experiments` 那一对
被真正校验等价**；另外 4 对「为什么不需要等价」只写在 commit message 与讨论里。

后果是具体的：新增第 6 对副本时，最省力的过测方式是往白名单加一行（T1 立刻变绿），
而「这一对要不要等价」这个判断可以完全不做 —— 守卫在，判定不在。

### 一、处置登记表：三种 kind，每种都有既有断言背书

`DUPLICATE_DISPOSITION` 为 5 对逐一登记处置方式与实测依据，kind 只有三种：

| kind | 含义 | 背书断言 |
|---|---|---|
| `equivalent` | 两份必须语义等价 | T2 按本表**参数化**逐条校验（不再硬编码唯一一对） |
| `explicit_path` | 两份有意不同，消费者必须显式注入目录 | T4 |
| `orphan_unused` | 无任何消费者，歧义面为零 | T5 断言其保持无人引用 |

5 对的实际登记：`analyze_all_experiments` → equivalent；`run_all` → explicit_path；
`analyze_deep_tests` / `deep_test_driver` / `deep_test_orchestrator` → orphan_unused。

### 二、T7 交叉校验：四张表不得互相矛盾

新增 `test_every_duplicate_basename_declares_a_consistent_disposition`，六项检查：

1. 与 `FROZEN_DUPLICATES` 双向对账（新增副本不能只加白名单、也不能登记幽灵名）；
2. kind 必须在允许集合内；
3. `reason` 必须写实测依据，不接受占位符（短于 20 字符即失败）；
4. kind 蕴含的「有无消费者」必须与 `FROZEN_TEST_IMPORTERS` 一致
   （`orphan_unused` 不得有消费者；`equivalent`/`explicit_path` 必须有）；
5. `equivalent` 必须与 `SEMANTIC_EQUIVALENT_PAIR` 一一对应（T3 只读后者，
   多余的 `equivalent` 会被静默跳过）；
6. `orphan_unused` 必须与 T5 实际扫描的 `ORPHAN_BASENAMES` 一致
   （否则「声明为孤儿」只是个标签，没人断言它保持无人引用）。

外加一条防退化自检：T2 的参数表不得为空 —— 表一空，参数化用例整体消失，
核心断言静默失效。

### 三、变异验证：10/10 命中，且各自打到对应分支

不是"改一处然后看红"，而是逐条注错，确认每条变异触发的是**它自己**那条问题
条目（避免所有变异都被同一句兜底吞掉）：

| 变异 | 触发 |
|---|---|
| 删掉 `run_all` 登记 | 报 missing |
| 孤儿副本被登记为有消费者 | 报 kind 与消费者矛盾 |
| 孤儿改成 `equivalent` | 三重冲突：无消费者 + 等价表不一致 + 孤儿表脱节 |
| `run_all` 改成 `orphan_unused` | 消费者矛盾 + 孤儿表不一致 |
| `reason` 写 `TODO` | 报过短 |
| kind 写非法值 | 报不在允许集合 |
| 清空 T2 参数表 | 报核心断言静默失效 |
| 多登记一个不存在的名字 | 报 extra |
| `ORPHAN_BASENAMES` 被截断 | 报与登记不一致 |
| 两份等价副本出现真实漂移 | T2 用 unified diff 定位到具体行 |

### 四、顺手推翻两处旧记录（自我更正）

- 早前记的「`run_all` 两份相差 **531 行**」是 **diff 输出行数**，不是文件行数。
  实际两份分别是 ablation **263 行** / benchmark **359 行**。
- 5 对副本字节数已逐个复核：`analyze_all_experiments` 两份 **25183 B 逐字节相同**、
  `analyze_deep_tests` 两份 **12277 B 逐字节相同**；`deep_test_driver` 128 / 119 行、
  `deep_test_orchestrator` 126 / 118 行（漂移存在但无消费者，见上表 orphan_unused）。

回归：`tests/test_module_resolution_contract.py` **11 passed**（原 10 条，+1 条 T7；
T2 由 1 条硬编码改为按表参数化）。

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