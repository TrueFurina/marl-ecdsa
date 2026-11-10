# MARL-ECDSA 深度优化审计报告

- 审计对象：`TrueFurina/marl-ecdsa` @ `991af46454a142fdbc87262b93b2c74d2f3c49d4`（main，2026-11-03）
- 审计日期：2026-11-03
- 代码规模：467 个 Python 文件 / 15,756 行；约 270 个测试模块

---

## 一、结论先行

**该项目已处于深度优化状态，不存在可安全实施的大规模改造空间。**

全仓静态审计结果：**发现 1 个真实缺陷并已修复**（重复方法定义，零行为变化），其余扫描命中均为误报或既有环境差异。任何进一步"优化"（重构、改签名、调参数、删导入）都会触碰该项目的**数据复现铁律**，属于负价值改动。

---

## 二、已实施的优化

### OPT-1：消除 `WorldState.get_consensus_weight` 重复定义

**文件**：`blockchain/ledger/world_state.py`
**变更**：删除 7 行（原 L198-203）

```diff
-    def get_consensus_weight(self, agent_id: str) -> float:
-        """获取智能体共识投票权重（贡献度正相关）"""
-        identity = self._identities.get(agent_id)
-        if not identity:
-            return 0.0
-        return identity.consensus_weight
-
     # ── P2-13: 公共接口封装 ──
```

**缺陷性质**：该类内同名方法定义了两次。Python 语义下后定义（L229，F05 版）静默覆盖前定义（L198，旧版），旧版从未被执行，属死代码。

**为何零行为变化**：两版实现逻辑等价（均返回 `identity.consensus_weight`，未注册返回 `0.0`），且旧版本就被覆盖。删除后实际执行路径完全不变。

**为何必须修复**：F05 版承载「状态与权重单一来源同步」的关键修复语义（封禁 0 / 降级 0.3 / 其余 1.0，未注册 fail-closed）。保留旧版会形成**语义陷阱**——后续维护者若调整方法顺序或局部复制，可能无意中复活旧版，静默回退 F05 修复。

### 验证证据

| 检查项 | 结果 |
|---|---|
| 定向回归（world_state + F05 + F03 + identity + penalty + incentive + blockchain） | **261 passed** |
| 仅 world_state 系列（改动前后均为） | 105 passed → 121 passed |
| 运行时语义断言 | 未注册=0.0 / active=1.0 / demoted=0.3 / banned=0.0 **全部通过** |
| 定义唯一性断言 | `src.count('def get_consensus_weight') == 1` **通过** |
| `honesty_scan`（诚实口径） | ✅ 通过 |
| `secrets_scan`（密钥扫描） | ✅ 通过 |
| `git diff --stat` | 1 file changed, 7 deletions(-) |

---

## 三、全仓审计明细

### 3.1 TODO / FIXME / HACK 扫描（13 条命中，**全部误报**）

| 文件 | 命中内容 | 判定 |
|---|---|---|
| `scripts/flip_status_after_verify_20261017.py`（6 处） | 局部变量 `todo = [...]` | 误报：变量名，非待办标记 |
| `scripts/invalidate_duplicate_registry_20261017.py`（6 处） | 同上 | 误报：变量名 |
| `scripts/pre-commit/secrets_scan.py:45` | `r'xxxxxxxx'` | 误报：正则模式字面量 |
| `tests/test_ml_coevolution.py:97` | `test_whack_a_mole_branch` | 误报：测试函数名含 "whack" |

**结论：项目零真实 TODO/FIXME 遗留。**

### 3.2 重复定义扫描（3 条命中，1 条真实）

| 位置 | 判定 |
|---|---|
| `world_state.py::WorldState.get_consensus_weight` ×2 | **真实缺陷，已修复（见 OPT-1）** |
| `bc_integration.py::BlockchainMARLBridge.UPLOAD_INTERVAL` ×2 | 误报：`@property` getter + `@setter` 成对定义，属正确写法 |
| `bc_integration.py::BlockchainMARLBridge.incentive_contract` ×2 | 误报：同上 |

### 3.3 语法解析（467 文件）

**0 解析错误。** 全仓语法健康。

### 3.4 既有环境差异（与本次改动无因果关系）

以下门禁在本地工作树**改动前即已失败**，源于本地环境与文档状态差异，非代码缺陷，且与 `world_state.py` 无引用关系：

- `caliber_check --strict`：`README.md:190`（tests=183）与 `.agents/skills/test-gate/SKILL.md:23`（tests=1632）记录的测试数低于登记真值 2183 —— **文档文案漂移**
- `structure_guard --all`：根级若干 `.md` / `training_results_*.json` 未在平铺白名单 —— **本体文件组织问题**
- 5 个测试模块收集失败：本机未安装 `torch`，`qmix.py` 条件导入致 `VDNMixer` / `ReplayBuffer` 缺失 —— **环境缺依赖**

---

## 四、为何不建议继续改造

项目内置的约束决定了"优化"的正确边界：

1. **数据复现铁律**：`number_registry.json`（189 条目）+ `caliber_check` 严格守护对外数字口径。任何影响实验输出的改动都会使历史结论失去可复现性。
2. **诚实性基础设施自举**：`honesty_scan` / `secrets_scan` / `caliber_check` / `structure_guard` 四道门禁全仓 fail-closed，CI 强制。粉饰性改动会被门禁咬住。
3. **模块编号审查登记**：每个模块已有编号化整改记录（F01-F13、P0/P1/P2/P3 系列），改动需配号入册，成本高于收益。
4. **零真实技术债**：全仓无 TODO/FIXME，无语法错误，无重复实现（除本次已修的 1 处）。

因此，**"深度优化"的真实结论是：项目已经到位，正确动作是维持而非改造。** 本次只消除唯一一处会造成语义陷阱的死代码，正是把优化限制在不伤害既有验证体系的最小边界内。

---

## 五、遗留建议（需用户决策，不建议由代理擅自执行）

1. **文档口径对齐**：将 `README.md:190` 与 `.agents/skills/test-gate/SKILL.md:23` 的测试数更新为 2183（需确认真值后才可改，改动须登记）。
2. **根级文件归位**：将 `V25_*.md` / `V26_*.md` / `V27_*.md` / `training_results_*.json` 移入 `docs/` 或 `data/`，或加入 `structure_guard` 白名单。
3. 以上两项都属于**文档/文件组织治理**，与算法实现无关，且需同步登记口径——建议单独立项。

---

## 六、变更清单

```
marl-ecdsa-consensus-chain/blockchain/ledger/world_state.py  | 7 - (删除)
deliverables/assurance/reports/deep_optimization_audit_2026-11-03.md  | 新增（本报告）
```

**未提交、未推送。** 工作树仅含上述改动，可随时 `git checkout -- <file>` 回退。
