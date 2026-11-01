# 数字复算报告（number_verification_report）

- 生成时间：2026-11-01T11:33:59
- 注册表：`marl-ecdsa-consensus-chain/number_registry.json`
- 数据源：`marl-ecdsa-consensus-chain/results`（镜像：`backup/pkg_old_src_20260917/results`，commit `e06109a`）
- 汇总：total=2 PASS=1 FAIL=0 PENDING=0 INVALID=0 DATA_MISSING=1
- 双源一致：**否**

| ID | 状态 | 复算值（摘要） | 差异 | 备注 |
|---|---|---|---|---|
| NR-15 | DATA_MISSING |  |  | 数据源缺失（FileNotFoundError）：本数据包不含该条目所需文件 |
| NR-18 | PASS | dilithium_available=True |  | 2026-09-18 由空壳改为真实现（commit 0aa6036）。适配器层已实现、默认链路仍为 ECDSA；详见 NR-20 实测。取代原『未实现』表述。2026-10-15：真实后端 dilithium-py 已 vendored 入仓库与提交包（离线自包含），确认 DILITHIUM_AVAILABLE 运行时为 True（此前仅靠常量/测试，本次确认真实可加载，非静默回落）；SigningService 新增 opt-in hybrid 后端（signature_backend='hybrid'，默认 ecdsa，AND 双签、Dilithium 公钥随包携带、后端缺失 fail-closed），默认主链路仍为 ECDSA、不接主链路。 |
