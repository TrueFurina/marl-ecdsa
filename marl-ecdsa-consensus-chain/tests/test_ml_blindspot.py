"""
ML 路径盲区探针守护测试（scripts/security/_probe_ml_blindspot.py）

覆盖：
  1. decide() 预注册决策表（纯函数，含全部分支与边界）
  2. 结果 JSON 口径一致性（从 runs 重算均值/优势/Δ/胜率/配对落差，
     与记录字段逐项核对；判定字符串必须与决策表重导一致）
  3. 已提交结果的仪表健康（C3 ML 仪表 + 规则臂复现必须为真——
     防导航步长振荡类仪表退化重新潜入）
  4. 良性数据生成确定性 + 标签完整性（标签不得编码 min_dist_any 旁路）
  5. 两探针参数口径一致（防 _probe_ml_blindspot 与 _probe_adaptive_attacker 漂移）
  6. ML 臂接线与非同一性（需 sklearn；无 sklearn 环境自动跳过）

无 sklearn 环境下 2/3/4/5 全量运行，1/6 跳过——与生产实际路径
（规则基）的守护不依赖 ML 可用性。
"""
import importlib.util
import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "security" / "_probe_ml_blindspot.py"
ADAPTIVE_PROBE_PATH = REPO_ROOT / "scripts" / "security" / "_probe_adaptive_attacker.py"
RESULT_PATH = REPO_ROOT / "scripts" / "security" / "ml_blindspot_result.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return _load_module("probe_ml_blindspot", PROBE_PATH)


@pytest.fixture(scope="module")
def result_json():
    if not RESULT_PATH.exists():
        pytest.skip("ml_blindspot_result.json 不存在（未跑探针）")
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))


def _healthy_m(**over):
    m = {
        "l1_rule": 0.995, "ada_rule": 0.673, "rnd_rule": 0.184,
        "l1_ml": 0.995, "ada_ml": 0.487, "rnd_ml": 0.132,
        "wins_rule": 4, "wins_ml": 3, "ml_heldout": 0.99,
    }
    m.update(over)
    return m


# ---------------------------------------------------------------------------
# 1. decide() 预注册决策表
# ---------------------------------------------------------------------------
class TestDecideDecisionTable:
    def test_healthy_robustness_branch(self, probe):
        d = probe.decide(_healthy_m())
        assert d["checks"]["C3_ml_instrument"] is True
        assert "显著压低" in d["verdict"]
        assert d["delta"] > 0.10

    def test_c0_fail_is_instrument_failure(self, probe):
        d = probe.decide(_healthy_m(l1_rule=0.5))
        assert d["checks"]["C0_rule_l1_high"] is False
        assert "仪表故障" in d["verdict"]

    def test_c1_fail_is_no_discrimination(self, probe):
        d = probe.decide(_healthy_m(rnd_rule=0.97))
        assert d["checks"]["C1_random_not_full"] is False
        assert "无区分力" in d["verdict"]

    def test_c3_fail_blocks_robustness_claim(self, probe):
        """ML 臂退化（白盒 L1 低）⇒ 低自适应率不可解释为稳健。"""
        d = probe.decide(_healthy_m(l1_ml=0.5))
        assert d["checks"]["C3_ml_instrument"] is False
        assert "仪表故障" in d["verdict"]
        assert "不可解释为稳健" in d["verdict"]

    def test_c3_heldout_fail_blocks_claim(self, probe):
        d = probe.decide(_healthy_m(ml_heldout=0.5))
        assert d["checks"]["C3_ml_instrument"] is False
        assert "仪表故障" in d["verdict"]

    def test_ml_worse_branch(self, probe):
        d = probe.decide(_healthy_m(ada_ml=0.85, rnd_ml=0.132))
        assert d["delta"] < -0.10
        assert "反而扩大盲区" in d["verdict"]

    def test_no_increment_branch(self, probe):
        """两臂优势相同（Δ≈0）⇒ 无显著稳健增量。"""
        d = probe.decide(_healthy_m(ada_ml=0.673, rnd_ml=0.184))
        assert abs(d["delta"]) < 1e-9
        assert "无显著稳健增量" in d["verdict"]

    def test_c2_fail_warns_prefix(self, probe):
        d = probe.decide(_healthy_m(wins_rule=2))
        assert d["checks"]["C2_rule_replicates"] is False
        assert d["verdict"].startswith("⚠️")

    def test_replication_mismatch_warns(self, probe):
        d = probe.decide(_healthy_m(ada_rule=0.50))
        assert d["replication_ok"] is False
        assert "偏差" in d["verdict"]

    def test_boundary_delta_just_below_010(self, probe):
        """边界值：Δ 略小于 0.10 ⇒ 不得判显著压低（浮点安全偏移 1e-4）。"""
        # adv_rule=0.489；adv_ml=0.3891 ⇒ delta=0.0999
        d = probe.decide(_healthy_m(ada_ml=0.5211, rnd_ml=0.132))
        assert 0.0998 < d["delta"] < 0.10
        assert "显著压低" not in d["verdict"]
        assert "无显著稳健增量" in d["verdict"]

    def test_boundary_delta_just_above_010(self, probe):
        """边界值：Δ 略大于 0.10 且绝对成功率也降 ⇒ 判显著压低。"""
        # adv_ml=0.3889 ⇒ delta=0.1001；ada_ml=0.5209 < ada_rule-0.10=0.573
        d = probe.decide(_healthy_m(ada_ml=0.5209, rnd_ml=0.132))
        assert 0.10 < d["delta"] < 0.1002
        assert "显著压低" in d["verdict"]


# ---------------------------------------------------------------------------
# 2/3. 结果 JSON 一致性与仪表健康
# ---------------------------------------------------------------------------
class TestResultJsonConsistency:
    def test_aggregate_recompute(self, probe, result_json):
        runs = result_json["runs"]

        def mean(arm):
            xs = [r["coop_rate"] for r in runs[arm]]
            return sum(xs) / len(xs)

        agg = result_json["aggregate"]
        for key, arm in (("l1_rule", "rule_L1"), ("ada_rule", "rule_L2_adaptive"),
                         ("rnd_rule", "rule_L2_random"), ("l1_ml", "ml_L1"),
                         ("ada_ml", "ml_L2_adaptive"), ("rnd_ml", "ml_L2_random")):
            assert abs(agg[key] - mean(arm)) < 1e-9, f"{key} 与 runs 重算不符"

    def test_advantage_and_delta_recompute(self, probe, result_json):
        agg = result_json["aggregate"]
        adv_rule = agg["ada_rule"] - agg["rnd_rule"]
        adv_ml = agg["ada_ml"] - agg["rnd_ml"]
        assert abs(result_json["advantage_rule"] - adv_rule) < 1e-9
        assert abs(result_json["advantage_ml"] - adv_ml) < 1e-9
        assert abs(result_json["delta"] - (adv_rule - adv_ml)) < 1e-9

    def test_wins_recompute(self, probe, result_json):
        runs = result_json["runs"]
        for arm_a, arm_r, key in (("rule_L2_adaptive", "rule_L2_random", "rule"),
                                  ("ml_L2_adaptive", "ml_L2_random", "ml")):
            wins = sum(1 for a, r in zip(runs[arm_a], runs[arm_r])
                       if a["coop_rate"] - r["coop_rate"] > 0)
            assert result_json["wins"][key] == wins, f"wins[{key}] 与 runs 重算不符"

    def test_verdict_matches_decision_table(self, probe, result_json):
        """判定字符串必须能从 runs 重算的聚合指标经 decide() 重导——防 main() 口径漂移。"""
        runs = result_json["runs"]

        def mean(arm):
            xs = [r["coop_rate"] for r in runs[arm]]
            return sum(xs) / len(xs)

        m = {
            "l1_rule": mean("rule_L1"), "ada_rule": mean("rule_L2_adaptive"),
            "rnd_rule": mean("rule_L2_random"), "l1_ml": mean("ml_L1"),
            "ada_ml": mean("ml_L2_adaptive"), "rnd_ml": mean("ml_L2_random"),
            "wins_rule": result_json["wins"]["rule"],
            "wins_ml": result_json["wins"]["ml"],
            "ml_heldout": result_json["ml_defender"]["heldout_accuracy"] or 0.0,
        }
        d = probe.decide(m)
        assert result_json["verdict"] == d["verdict"]

    def test_sweep_paired_drop_recompute(self, probe, result_json):
        sw = result_json.get("supplementary_sweep")
        if sw is None:
            pytest.skip("无补充扩种段")
        rates = sw["rates"]
        paired = [a - b for a, b in zip(rates["rule_L2_adaptive"], rates["ml_L2_adaptive"])]
        assert len(paired) == sw["n_seeds"]
        assert abs(sw["paired_adaptive_drop_mean"] - sum(paired) / len(paired)) < 1e-4
        assert sw["adaptive_drop_wins"] == sum(1 for x in paired if x > 0)
        # 符号守卫：paired drop 定义为 rule − ml（正=规则臂更易被攻破）
        assert all(abs(p - (a - b)) < 1e-9 for p, a, b in
                   zip(sw["paired_adaptive_drop"], rates["rule_L2_adaptive"],
                       rates["ml_L2_adaptive"]))

    def test_committed_result_instrument_health(self, probe, result_json):
        """已提交结果必须仪表健康：C3（ML 白盒可达 + 留出准确率）与规则臂复现。"""
        assert result_json["checks"]["C3_ml_instrument"] is True, \
            "ML 臂仪表退化（导航振荡/训练失败类回归）——结论不可解释"
        assert result_json["checks"]["C0_rule_l1_high"] is True
        assert result_json["replication_ok"] is True, \
            "规则臂未复现既有探针读数——两探针口径疑似漂移"

    def test_committed_result_rule_arm_matches_prior(self, probe, result_json):
        prior = result_json["prior_readings"]
        runs = result_json["runs"]

        def mean(arm):
            xs = [r["coop_rate"] for r in runs[arm]]
            return sum(xs) / len(xs)

        assert abs(mean("rule_L1") - prior["L1_omniscient"]) < 0.01
        assert abs(mean("rule_L2_adaptive") - prior["L2_adaptive"]) < 0.01
        assert abs(mean("rule_L2_random") - prior["L2_random"]) < 0.01


# ---------------------------------------------------------------------------
# 4. 良性数据完整性与确定性
# ---------------------------------------------------------------------------
class TestBenignData:
    def test_generation_deterministic(self, probe):
        ep1, diag1 = probe.gen_benign_episodes()
        ep2, diag2 = probe.gen_benign_episodes()
        assert diag1 == diag2
        for (o1, l1, i1), (o2, l2, i2) in zip(ep1, ep2):
            assert o1 == o2 and l1 == l2 and i1 == i2

    def test_label_definition_integrity(self, probe):
        """标签=1 必须且只能来自「到达自身 landmark」——不得编码 min_dist_any 旁路。"""
        episodes, _diag = probe.gen_benign_episodes()
        n_pos = 0
        for obs, labs, ids in episodes:
            for o, lab, aid in zip(obs, labs, ids):
                i = int(aid[1:])
                lm_rel = o[4:4 + 2 * probe.N_LM]
                d_own = math.hypot(lm_rel[2 * i], lm_rel[2 * i + 1])
                if lab == 1:
                    assert d_own < probe.THRESHOLD, \
                        f"标签1但 dist_to_own={d_own:.3f}≥阈值 ⇒ 标签被旁路污染"
                    n_pos += 1
                else:
                    assert d_own >= probe.THRESHOLD
        assert n_pos > 0

    def test_attack_pattern_absent_from_benign(self, probe):
        """良性数据中攻击模式（近任意 landmark 但远离自身）须近乎绝迹 ⇒ ML 必须离线外推，
        实验度量的是外推鲁棒性而非记忆。"""
        _episodes, diag = probe.gen_benign_episodes()
        assert diag["off_manifold_frac"] < 0.05
        assert diag["total_samples"] > 10000

    def test_benign_label_function_semantics(self, probe):
        """标签函数单元语义：自身 landmark→1；**别人** landmark（远离自身）→0；远处→0。

        良性诚实轨迹中「到达自身」与「靠近任意」两定义数值巧合一致
        （off_manifold=0），数据性质测试守不住「标签改走 min_dist_any 旁路」
        这一退化变异——只有直接测函数体才能守住「ML 不重放规则」。"""
        assert probe.benign_label(1.0, 0.0, 0) == 1    # 自身 landmark 上
        assert probe.benign_label(0.9, 0.1, 0) == 1    # 自身 landmark 邻域内
        assert probe.benign_label(0.0, 1.0, 0) == 0    # 别人 landmark 上、远离自身
        assert probe.benign_label(1.0, 1.0, 0) == 0    # 同上
        assert probe.benign_label(2.0, 2.0, 0) == 0    # 远处


# ---------------------------------------------------------------------------
# 5. 两探针参数口径一致
# ---------------------------------------------------------------------------
class TestProbeParamsAligned:
    def test_params_identical_to_adaptive_probe(self, probe):
        spec = importlib.util.spec_from_file_location(
            "probe_adaptive", ADAPTIVE_PROBE_PATH)
        adp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adp)
        for attr in ("N_AGENTS", "N_LM", "THRESHOLD", "DT", "V_MAX",
                     "N_STEPS", "SEEDS", "LANDMARKS", "START"):
            assert getattr(probe, attr) == getattr(adp, attr), \
                f"{attr} 与 _probe_adaptive_attacker 漂移"

    def test_prior_readings_match_adaptive_probe(self, probe):
        """PRIOR 常量必须与既有探针已提交读数一致（复现核对的基准）。"""
        spec = importlib.util.spec_from_file_location(
            "probe_adaptive", ADAPTIVE_PROBE_PATH)
        adp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adp)
        prior_file = (ADAPTIVE_PROBE_PATH.parent / "adaptive_attacker_result.json")
        if not prior_file.exists():
            pytest.skip("adaptive_attacker_result.json 不存在")
        prior = json.loads(prior_file.read_text(encoding="utf-8"))
        # 逐位核对：取既有探针的均值与 PRIOR 常量比
        def mean(arm):
            xs = [r["coop_rate"] for r in prior["runs"][arm]]
            return sum(xs) / len(xs)
        assert abs(probe.PRIOR["L1_omniscient"] - mean("L1_omniscient")) < 0.01
        assert abs(probe.PRIOR["L2_adaptive"] - mean("L2_adaptive")) < 0.01
        assert abs(probe.PRIOR["L2_random"] - mean("L2_random")) < 0.01


# ---------------------------------------------------------------------------
# 6. ML 臂接线与非同一性（需 sklearn）
# ---------------------------------------------------------------------------
class TestMLArmWiring:
    def test_train_and_judge_geography(self, probe):
        pytest.importorskip("sklearn")
        ml_det, info = probe.train_ml_defender()
        assert info["trained"] is True
        assert info["classifier"] == "ExtraTreesClassifier"
        assert info["heldout_accuracy"] is not None
        assert info["heldout_accuracy"] >= 0.90
        judge_ml = probe.make_judge_ml(ml_det)
        # 可信域必须存在（白盒 L1 的前提）、不覆盖过半工作区、且必在 landmark 邻域
        trusted = probe.map_trusted_region(judge_ml)
        n_cells = (int(round((probe.GRID_HI - probe.GRID_LO) / probe.GRID_STEP)) + 1) ** 2
        assert 0 < len(trusted) < 0.5 * n_cells
        assert all(probe._min_dist_any(x, y) < probe.THRESHOLD for x, y in trusted)
        assert judge_ml(probe.build_obs(0, 0, 2.0, 2.0)) is False

    def test_arms_not_identical(self, probe):
        """两防御臂必须存在判定分歧——否则实验同义反复。"""
        pytest.importorskip("sklearn")
        ml_det, _info = probe.train_ml_defender()
        judge_ml = probe.make_judge_ml(ml_det)
        diff = 0
        n = int(round((probe.GRID_HI - probe.GRID_LO) / probe.GRID_STEP)) + 1
        for ix in range(n):
            for iy in range(n):
                x = probe.GRID_LO + ix * probe.GRID_STEP
                y = probe.GRID_LO + iy * probe.GRID_STEP
                obs = probe.build_obs(0, 0, x, y)
                if (judge_ml(obs) is True) != (probe.judge_rule(obs) is True):
                    diff += 1
        assert diff > 0, "ML 臂与规则臂判定完全一致——实验退化为同义反复"
