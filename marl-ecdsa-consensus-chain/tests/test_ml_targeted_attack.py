"""
ML 定向自适应攻击探针守护测试（scripts/security/_probe_ml_targeted_attack.py）

覆盖：
  1. decide() 预注册决策表（纯函数，全部分支与边界：D0-D4）
  2. 结果 JSON 口径一致性（runs 重算 + 判定字符串经 decide() 重导）
  3. 判定不变量（mm≡rm、mr≡rr——v3 搜索判定无关；被植入规则知识必红）
  4. v1 设计缺陷留痕（空区分作废证据不得丢失）
  5. 与盲区探针的口径一致（参数逐位 + PRIOR 复读基准取自查阅 JSON）
  6. 代理仪表未被回退（D2 曾以 2000 查询/深度5 拦下过，防改回弱仪表）
  7. ML 臂实时接线（需 sklearn；结构断言宽松，严格门槛只对已提交 JSON）

无 sklearn 环境下 2/3/4/5/6 全量运行，1/7 跳过——生产路径（规则基）
的守护不依赖 ML 可用性。
"""
import importlib.util
import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "security" / "_probe_ml_targeted_attack.py"
BLINDSPOT_PATH = REPO_ROOT / "scripts" / "security" / "_probe_ml_blindspot.py"
RESULT_PATH = REPO_ROOT / "scripts" / "security" / "ml_targeted_attack_result.json"
BLINDSPOT_RESULT_PATH = REPO_ROOT / "scripts" / "security" / "ml_blindspot_result.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return _load_module("probe_ml_targeted_attack", PROBE_PATH)


@pytest.fixture(scope="module")
def blindspot():
    return _load_module("probe_ml_blindspot_for_targeted", BLINDSPOT_PATH)


@pytest.fixture(scope="module")
def result_json():
    if not RESULT_PATH.exists():
        pytest.skip("ml_targeted_attack_result.json 不存在（未跑探针）")
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ml_judge(probe):
    """训练一次 ML 防御者并对齐判信，模块内共享。

    2026-11-04 实测的确定性依据（不是推断）：连续两次 train_ml_defender()
    返回的 classifier / train_samples / train_accuracy / heldout_accuracy
    逐位相同，且在 441 个网格点上两份判信的判定 0 差异。既然每次训练得到的
    是同一个模型，5 条 live 用例各训一遍就只是重复计算——共享不改变任何
    用例看到的对象。

    原先每条用例各写 4 行训练样板（各 ~1.5s），外加代理训练（~15s/次，
    见 surrogate 夹具）在 3 条用例里重复。
    """
    pytest.importorskip("sklearn")
    ml_det, info = probe.BS.train_ml_defender()
    assert info["trained"] is True
    return probe.BS.make_judge_ml(ml_det)


@pytest.fixture(scope="module")
def surrogate(probe, ml_judge):
    """在共享判信函数上训练一次代理，模块内共享。

    可复现性同样实测过：train_surrogate 内部 rng 由常量 SURROGATE_SEED
    播种、分类器 random_state=42，两次调用返回的 agreement（0.9625）、
    trusted_cells（575）、target、target_fidelity 逐位相同。

    注意 sweep() 与 arm_s2() 只读 surrogate["trusted"]，不改该字典，
    因此跨用例共享无副作用。
    """
    return probe.train_surrogate(ml_judge)


def _healthy_m(**over):
    m = {
        "ada_rr": 0.673, "ada_rm": 0.487, "ada_mm": 0.487, "ada_mr": 0.673,
        "s1": 0.730, "s2": 0.995, "s3": 0.995,
        "rnd_rule": 0.184, "rnd_ml": 0.132,
        "wins_s1": 5, "wins_s2": 5,
        "prior_adaptive_ml": 0.487, "prior_l1_ml": 0.995,
        "model_fp_ok": True,
        "surrogate_agreement": 0.9625,
        "surrogate_target_real_trusted": True,
    }
    m.update(over)
    return m


# ---------------------------------------------------------------------------
# 1. decide() 预注册决策表
# ---------------------------------------------------------------------------
class TestDecideDecisionTable:
    def test_healthy_recovery_branch(self, probe):
        d = probe.decide(_healthy_m())
        assert d["checks"]["D2_capability"] is True
        assert d["best_strong"] == 0.995
        assert "搜索类上限" in d["verdict"]

    def test_d0_fail_is_instrument_failure(self, probe):
        d = probe.decide(_healthy_m(ada_rm=0.60))
        assert d["checks"]["D0_instrument"] is False
        assert "仪表故障" in d["verdict"]

    def test_d0_model_fingerprint_fail(self, probe):
        d = probe.decide(_healthy_m(model_fp_ok=False))
        assert d["checks"]["D0_instrument"] is False
        assert "仪表故障" in d["verdict"]

    def test_d1_fail_is_no_discrimination(self, probe):
        d = probe.decide(_healthy_m(rnd_ml=0.97))
        assert d["checks"]["D1_random_not_full"] is False
        assert "无区分力" in d["verdict"]

    def test_d2_weak_attackers_block_robustness_claim(self, probe):
        """防假阴性核心：攻击者死 ⇒ 低成功率不可解释为 ML 稳健。"""
        d = probe.decide(_healthy_m(s1=0.20, s2=0.30, wins_s1=2, wins_s2=2))
        assert d["checks"]["D2_capability"] is False
        assert "不可解释为 ML 稳健" in d["verdict"]
        assert "死攻击者" in d["verdict"]

    def test_d2_surrogate_agreement_below_gate(self, probe):
        """代理一致率 <0.95 ⇒ 仪表不良，同样阻塞（首版 0.9230 即被此拦下）。"""
        d = probe.decide(_healthy_m(surrogate_agreement=0.923))
        assert d["checks"]["D2_capability"] is False
        assert "不可解释为 ML 稳健" in d["verdict"]

    def test_d2_target_not_real_trusted(self, probe):
        d = probe.decide(_healthy_m(surrogate_target_real_trusted=False))
        assert d["checks"]["D2_capability"] is False

    def test_robust_branch(self, probe):
        """两类更强攻击者均未超出 S0+0.10 ⇒ 稳健分支。"""
        d = probe.decide(_healthy_m(s1=0.52, s2=0.56))
        assert d["checks"]["D2_capability"] is True
        assert d["best_strong"] <= 0.487 + 0.10
        assert "稳健" in d["verdict"]

    def test_anomalous_branch(self, probe):
        """更强攻击者反而更差 ⇒ 异常分支，不得判稳健也不得判恢复。"""
        d = probe.decide(_healthy_m(s1=0.30, s2=0.32, wins_s1=5, wins_s2=5))
        assert d["best_strong"] < 0.487 - 0.10
        assert "异常分支" in d["verdict"]

    def test_boundary_best_strong_exactly_s0_plus_010(self, probe):
        """边界值：best_strong = S0+0.10 不满足 > ⇒ 不得判恢复。"""
        # s1 低；s2=0.587 ⇒ best_strong=0.587=0.487+0.100（浮点安全：0.0999）
        d = probe.decide(_healthy_m(s1=0.30, s2=0.5869))
        assert abs(d["best_strong"] - 0.487 - 0.10) < 1e-3
        assert d["best_strong"] <= 0.487 + 0.10
        assert "搜索类上限" not in d["verdict"]

    def test_boundary_best_strong_just_above(self, probe):
        d = probe.decide(_healthy_m(s1=0.30, s2=0.5871))
        assert d["best_strong"] > 0.487 + 0.10
        assert "搜索类上限" in d["verdict"]

    def test_d4_warn_prefix(self, probe):
        d = probe.decide(_healthy_m(ada_mr=0.75))
        assert d["verdict"].startswith("⚠️")

    def test_advantage_fields_recompute(self, probe):
        d = probe.decide(_healthy_m())
        assert abs(d["advantage_s1"] - (0.730 - 0.132)) < 1e-9
        assert abs(d["advantage_s2"] - (0.995 - 0.132)) < 1e-9
        assert d["best_strong"] == max(0.730, 0.995)


# ---------------------------------------------------------------------------
# 2/3. 结果 JSON 一致性、判定不变量与已提交结果健康
# ---------------------------------------------------------------------------
class TestResultJsonConsistency:
    def test_aggregate_recompute(self, probe, result_json):
        runs = result_json["runs"]

        def mean(arm):
            xs = [r["coop_rate"] for r in runs[arm]]
            return sum(xs) / len(xs)

        agg = result_json["aggregate"]
        for key, arm in (("ada_rr", "rr_adaptive"), ("ada_rm", "rm_adaptive"),
                         ("ada_mm", "mm_adaptive"), ("ada_mr", "mr_adaptive"),
                         ("s1", "s1_restarts"), ("s2", "s2_surrogate"),
                         ("s3", "s3_whitebox"), ("rnd_rule", "random_rule"),
                         ("rnd_ml", "random_ml")):
            assert abs(agg[key] - mean(arm)) < 1e-9, f"{key} 与 runs 重算不符"

    def test_wins_recompute(self, probe, result_json):
        runs = result_json["runs"]
        for arm_a, key in (("s1_restarts", "wins_s1"), ("s2_surrogate", "wins_s2")):
            wins = sum(1 for a, r in zip(runs[arm_a], runs["random_ml"])
                       if a["coop_rate"] - r["coop_rate"] > 0)
            assert result_json["aggregate"][key] == wins

    def test_verdict_matches_decision_table(self, probe, result_json):
        runs = result_json["runs"]

        def mean(arm):
            xs = [r["coop_rate"] for r in runs[arm]]
            return sum(xs) / len(xs)

        m = dict(result_json["aggregate"])
        m["surrogate_agreement"] = result_json["surrogate"]["agreement"]
        m["surrogate_target_real_trusted"] = result_json["surrogate"]["target_real_trusted"]
        d = probe.decide(m)
        assert result_json["verdict"] == d["verdict"]

    def test_sweep_paired_gains_recompute(self, probe, result_json):
        sw = result_json.get("supplementary_sweep")
        if sw is None:
            pytest.skip("无补充扩种段")
        rates = sw["rates"]
        for tag, arm in (("s1", "s1_restarts"), ("s2", "s2_surrogate")):
            paired = [a - b for a, b in zip(rates[arm], rates["rm_adaptive"])]
            assert len(paired) == sw["n_seeds"]
            assert abs(sw[f"paired_{tag}_gain_mean"] - sum(paired) / len(paired)) < 1e-4
            assert sw[f"{tag}_gain_wins"] == sum(1 for x in paired if x > 0)
            # 符号守卫：增益定义为 强攻击臂 − S0 基线（正=更强攻击者更有效）
            assert all(abs(p - (a - b)) < 1e-9 for p, a, b in
                       zip(sw[f"paired_{tag}_gain"], rates[arm], rates["rm_adaptive"]))

    def test_committed_result_instrument_health(self, probe, result_json):
        """已提交结果必须仪表健康：D0/D1/D2 全真 + 判定不变量成立。"""
        assert result_json["checks"]["D0_instrument"] is True
        assert result_json["checks"]["D1_random_not_full"] is True
        assert result_json["checks"]["D2_capability"] is True, \
            "能力闸门未过——结论不可解释（弱攻击者/坏代理）"
        assert result_json["invariants"]["mm_equiv_rm"] is True
        assert result_json["invariants"]["mr_equiv_rr"] is True

    def test_sweep_paired_sign_live(self, probe, ml_judge, surrogate):
        """实时缩样（2 种子）：sweep 记录的配对增益必须与 rates 重算逐位一致。

        已提交 JSON 一致性测试读不到**探针代码漂移**（JSON 是旧代码产的）——
        本测试直接跑活代码，守住配对符号/舍入口径（变异 M6 即杀此）。"""
        pytest.importorskip("sklearn")
        saved = probe.BS.SEEDS_SWEEP
        probe.BS.SEEDS_SWEEP = probe.BS.SEEDS[:2]
        try:
            sw = probe.sweep(ml_judge, surrogate)
        finally:
            probe.BS.SEEDS_SWEEP = saved
        for tag, arm in (("s1", "s1_restarts"), ("s2", "s2_surrogate")):
            paired = [a - b for a, b in zip(sw["rates"][arm],
                                            sw["rates"]["rm_adaptive"])]
            assert sw[f"paired_{tag}_gain"] == [round(x, 4) for x in paired], \
                f"sweep 配对口径漂移（{tag}）——探针代码与 JSON 口径已分叉"
            assert sw[f"paired_{tag}_gain_mean"] == round(sum(paired) / len(paired), 4)

    def test_committed_verdict_is_recovery_finding(self, probe, result_json):
        """已提交结论方向守卫：0.4870 是搜索类上限（换结果 JSON 须显式）。"""
        assert "搜索类上限" in result_json["verdict"]
        assert result_json["best_strong"] > result_json["aggregate"]["ada_rm"] + 0.10

    def test_invariants_hold_in_runs(self, probe, result_json):
        runs = result_json["runs"]
        for a, b in zip(runs["mm_adaptive"], runs["rm_adaptive"]):
            assert a["coop_rate"] == b["coop_rate"]
            assert a["first_hit_step"] == b["first_hit_step"]
        for a, b in zip(runs["mr_adaptive"], runs["rr_adaptive"]):
            assert a["coop_rate"] == b["coop_rate"]
            assert a["first_hit_step"] == b["first_hit_step"]


# ---------------------------------------------------------------------------
# 4. v1 设计缺陷留痕
# ---------------------------------------------------------------------------
class TestDesignFlawRecorded:
    def test_design_flaw_block_present(self, probe, result_json):
        flaw = result_json.get("design_flaw_v1")
        assert flaw is not None, "v1 空区分作废证据丢失——方法论教训不可静默删除"
        for key in ("claim", "reason", "evidence", "caught_by", "correction"):
            assert flaw.get(key), f"design_flaw_v1.{key} 为空"
        assert "判定无关" in flaw["reason"]
        assert "C2" in flaw["caught_by"]

    def test_design_flaw_documented_in_probe(self, probe):
        assert hasattr(probe, "DESIGN_FLAW_V1")
        assert "mm≡rm" in probe.DESIGN_FLAW_V1["evidence"]


# ---------------------------------------------------------------------------
# 5. 与盲区探针的口径一致
# ---------------------------------------------------------------------------
class TestProbeParamsAligned:
    def test_params_identical_to_blindspot(self, probe, blindspot):
        for attr in ("N_AGENTS", "N_LM", "THRESHOLD", "DT", "V_MAX",
                     "N_STEPS", "SEEDS", "LANDMARKS", "START", "GRID_LO",
                     "GRID_HI", "GRID_STEP"):
            assert getattr(probe.BS, attr) == getattr(blindspot, attr), \
                f"{attr} 与盲区探针漂移"

    def test_prior_matches_blindspot_committed(self, probe):
        if not BLINDSPOT_RESULT_PATH.exists():
            pytest.skip("ml_blindspot_result.json 不存在")
        d = json.loads(BLINDSPOT_RESULT_PATH.read_text(encoding="utf-8"))
        agg = d["aggregate"]
        assert abs(probe.PRIOR["adaptive_ml"] - agg["ada_ml"]) < 0.01
        assert abs(probe.PRIOR["l1_ml"] - agg["l1_ml"]) < 0.01
        assert abs(probe.PRIOR["random_ml"] - agg["rnd_ml"]) < 0.01
        assert probe.PRIOR["trusted_cells"] == d["trusted_region"]["trusted_cells"]


# ---------------------------------------------------------------------------
# 6. 代理仪表未被回退
# ---------------------------------------------------------------------------
class TestSurrogateInstrument:
    def test_instrument_not_reverted_to_weak(self, probe):
        """D2 曾以 2000 查询/深度5（一致率 0.9230）拦下首版——防改回弱仪表。"""
        assert probe.SURROGATE_QUERIES >= 8000
        assert probe.SURROGATE_MAX_DEPTH >= 8

    def test_committed_surrogate_passes_gate(self, probe, result_json):
        sur = result_json["surrogate"]
        assert sur["agreement"] >= 0.95
        assert sur["target_real_trusted"] is True
        assert sur["trusted_cells"] > 0
        assert 0 < sur["target_fidelity"] <= 1.0


# ---------------------------------------------------------------------------
# 7. ML 臂实时接线（需 sklearn；结构断言宽松，严格门槛只对已提交 JSON）
# ---------------------------------------------------------------------------
class TestMLArmWiring:
    def test_surrogate_live_structural(self, probe, surrogate):
        # 宽松结构断言（sklearn 版本差异不设严格门槛；严格门槛属 decide() 自身）
        assert surrogate["agreement"] > 0.90
        assert surrogate["trusted_cells"] > 0
        assert surrogate["target"] is not None
        assert surrogate["target_real_trusted"] in (True, False)

    def test_s2_live_recovers_exploitation(self, probe, ml_judge, surrogate):
        """实时端到端：窃取导航必须实际占领（对真实 ML 判信），非 JSON 摆拍。"""
        run = probe.arm_s2(11, ml_judge, surrogate)
        assert run["coop_rate"] >= 0.90, "窃取攻击实时未占领——探针逻辑疑似退化"

    def test_judge_agnostic_invariant_live(self, probe, ml_judge):
        """实时判定不变量：mm≡rm、mr≡rr（同函数同反馈源必同轨迹）。"""
        for seed in (11, 23):
            a, b = probe.arm_mm(seed, ml_judge), probe.arm_rm(seed, ml_judge)
            assert a["coop_rate"] == b["coop_rate"]
            assert a["first_hit_step"] == b["first_hit_step"]
            c, d = probe.arm_mr(seed), probe.arm_rr(seed)
            assert c["coop_rate"] == d["coop_rate"]
            assert c["first_hit_step"] == d["first_hit_step"]

    def test_s1_dominates_s0_live(self, probe):
        """实时：best-of-4 重启对单跑基线应有方向性优势（单种子粗检）。"""
        pytest.importorskip("sklearn")
        ml_det, info = probe.BS.train_ml_defender()
        assert info["trained"] is True
        judge_ml = probe.BS.make_judge_ml(ml_det)
        s0 = probe.arm_rm(37, judge_ml)["coop_rate"]   # 首版中最差种子
        s1 = probe.arm_s1(37, judge_ml)["coop_rate"]
        assert s1 > s0, f"重启未改善最差种子（S0={s0}, S1={s1}）"
