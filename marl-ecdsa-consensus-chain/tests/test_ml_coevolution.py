"""
ML 共演化环探针守护测试（scripts/security/_probe_ml_coevolution.py）

覆盖：
  1. decide() 预注册决策表（纯函数，全部分支与边界：E0-E6）
  2. 结果 JSON 口径一致性（trajectory / checks / verdict 经 decide() 重导）
  3. 与盲区/定向探针的口径一致（参数逐位 + PRIOR_R0 复读盲区 JSON）
  4. 标签完整性（E3）：build_retrain_set 零冲突 + benign_label 协议语义
  5. 确定性（E6）：5 种子导航确定、exploit_rate 逐位相等
  6. 实时缩样共演化（2 轮×2 种子活代码）：守住 run_exploit 真实反馈预筛
     与 retrain 标签管线（M6 教训：JSON 测试读不到探针代码漂移）

无 sklearn 环境下 1/2/3/4/5(协议语义) 全量运行；5(实时)/6 跳过——
生产路径（规则基）的守护不依赖 ML 可用性。
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "security" / "_probe_ml_coevolution.py"
BLINDSPOT_PATH = REPO_ROOT / "scripts" / "security" / "_probe_ml_blindspot.py"
RESULT_PATH = REPO_ROOT / "scripts" / "security" / "ml_coevolution_result.json"
BLINDSPOT_RESULT_PATH = REPO_ROOT / "scripts" / "security" / "ml_blindspot_result.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return _load_module("probe_ml_coevolution", PROBE_PATH)


@pytest.fixture(scope="module")
def blindspot():
    return _load_module("probe_ml_blindspot_for_coev", BLINDSPOT_PATH)


@pytest.fixture(scope="module")
def result_json():
    if not RESULT_PATH.exists():
        pytest.skip("ml_coevolution_result.json 不存在（未跑探针）")
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))


def _round(r: int, exploit: float, off: int, heldout=0.9879, trusted=560,
           conflicts=0, surr_agr=0.96, real_trusted=True, nav_ok=None,
           target_label="L1", target=(0.0, 0.95)):
    """构造单回合指标（decide() 所需键的最小集）。"""
    return {
        "round": r,
        "model": {"heldout": heldout, "trusted_cells": trusted,
                  "off_cells": off, "off_frac": 0.0,
                  "near": {"L0": 0, "L1": 0, "L2": 0},
                  "train_acc": heldout},
        "attack": {"exploit_rate": exploit, "exploit_rates": [exploit] * 5,
                   "coop_rate": exploit, "coop_rates": [exploit] * 5,
                   "first_hit_step": 2, "target": list(target),
                   "target_label": target_label,
                   "target_real_trusted": real_trusted,
                   "random_exploit_rate": 0.03,
                   "random_coop_rate": 0.03, "new_unique_obs": 200},
        "surrogate": {"agreement": surr_agr, "trusted_cells": 560,
                      "off_cells": off, "target_fidelity": 1.0},
        "train": {"trained": True, "train_rows": 9600 + r * 600,
                  "attack_rows": r * 600, "conflicts": conflicts},
        "nav_consistency_ok": nav_ok,
    }


def _healthy_rounds():
    # 演示用「打地鼠」轨迹：exploit 恒高、off-cells 收窄、目标迁移 L1→L2
    return [
        _round(0, 0.99, 256, trusted=560, nav_ok=True, target_label="L1"),
        _round(1, 0.985, 118, trusted=419, target_label="L2"),
        _round(2, 0.985, 30, trusted=328, target_label="L2"),
        _round(3, 0.98, 8, trusted=300, target_label="L2"),
        _round(4, 0.98, 3, trusted=290, target_label="L2"),
        _round(5, 0.975, 1, trusted=285, target_label="L2"),
    ]


PRIOR = {"trusted_cells": 560, "heldout": 0.9879}


# ---------------------------------------------------------------------------
# 1. decide() 预注册决策表
# ---------------------------------------------------------------------------
class TestDecideDecisionTable:
    def test_whack_a_mole_branch(self, probe):
        d = probe.decide(_healthy_rounds(), PRIOR)
        assert d["checks"]["E0_r0_fingerprint"] is True
        assert d["checks"]["E2_initially_exploitable"] is True
        assert d["checks"]["E3_no_label_conflict"] is True
        assert d["checks"]["E6_determinism"] is True
        assert d["migrated"] is True
        assert "打地鼠" in d["verdict"]

    def test_e0_fingerprint_fail(self, probe):
        # R0 指纹不符：可信格数漂移
        rs = _healthy_rounds()
        rs[0]["model"]["trusted_cells"] = 500
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E0_r0_fingerprint"] is False
        assert "仪表故障" in d["verdict"]

    def test_e0_surrogate_agreement_fail(self, probe):
        rs = _healthy_rounds()
        rs[0]["surrogate"]["agreement"] = 0.90
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E0_r0_fingerprint"] is False

    def test_e0_target_not_real_trusted(self, probe):
        rs = _healthy_rounds()
        rs[0]["attack"]["target_real_trusted"] = False
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E0_r0_fingerprint"] is False

    def test_e0_nav_inconsistency(self, probe):
        rs = _healthy_rounds()
        rs[0]["nav_consistency_ok"] = False
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E0_r0_fingerprint"] is False

    def test_e3_label_conflict_fail(self, probe):
        rs = _healthy_rounds()
        rs[2]["train"]["conflicts"] = 3
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E3_no_label_conflict"] is False
        assert "标签冲突" in d["verdict"]

    def test_e6_determinism_fail(self, probe):
        rs = _healthy_rounds()
        rs[1]["attack"]["exploit_rates"] = [0.985, 0.985, 0.985, 0.985, 0.50]
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E6_determinism"] is False
        assert "确定性" in d["verdict"]

    def test_e2_not_initially_exploitable(self, probe):
        rs = _healthy_rounds()
        rs[0]["attack"]["exploit_rate"] = 0.70
        rs[0]["attack"]["exploit_rates"] = [0.70] * 5
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E2_initially_exploitable"] is False
        assert "初始不可利用" in d["verdict"]

    def test_e1_benign_destroyed_prefix(self, probe):
        rs = _healthy_rounds()
        rs[3]["model"]["heldout"] = 0.85
        d = probe.decide(rs, PRIOR)
        assert d["checks"]["E1_benign_preserved"] is False
        assert d["verdict"].startswith("⚠️")

    def test_closed_branch(self, probe):
        # 末回合 exploit<=0.20 且离流形格==0 ⇒ 关闭（R0 须仍可利用以过 E2）
        rs = _healthy_rounds()
        rs[-1]["attack"]["exploit_rate"] = 0.10
        rs[-1]["attack"]["exploit_rates"] = [0.10] * 5
        rs[-1]["model"]["off_cells"] = 0
        d = probe.decide(rs, PRIOR)
        assert "关闭盲区" in d["verdict"]

    def test_approx_closed_branch(self, probe):
        rs = _healthy_rounds()
        rs[-1]["attack"]["exploit_rate"] = 0.15
        rs[-1]["attack"]["exploit_rates"] = [0.15] * 5
        rs[-1]["model"]["off_cells"] = 5
        d = probe.decide(rs, PRIOR)
        assert "近似关闭" in d["verdict"]

    def test_retrain_invalid_branch(self, probe):
        # exploit>0.80 且目标不迁移 ⇒ 重训无效
        rs = _healthy_rounds()
        for r in rs:
            r["attack"]["target_label"] = "L1"
        d = probe.decide(rs, PRIOR)
        assert d["migrated"] is False
        assert "重训无效" in d["verdict"]

    def test_partial_branch(self, probe):
        rs = _healthy_rounds()
        rs[-1]["attack"]["exploit_rate"] = 0.50
        rs[-1]["attack"]["exploit_rates"] = [0.50] * 5
        rs[-1]["model"]["off_cells"] = 10
        d = probe.decide(rs, PRIOR)
        assert "部分压缩" in d["verdict"]

    def test_boundary_exploit_exactly_020_closes(self, probe):
        # 边界：exploit_final == 0.20 满足 <=0.20 ⇒ 不得判打地鼠/无效
        rs = _healthy_rounds()
        rs[-1]["attack"]["exploit_rate"] = 0.20
        rs[-1]["attack"]["exploit_rates"] = [0.20] * 5
        rs[-1]["model"]["off_cells"] = 0
        d = probe.decide(rs, PRIOR)
        assert "打地鼠" not in d["verdict"]
        assert "重训无效" not in d["verdict"]
        assert "关闭盲区" in d["verdict"]

    def test_boundary_exploit_just_above_080(self, probe):
        rs = _healthy_rounds()
        rs[-1]["attack"]["exploit_rate"] = 0.8001
        rs[-1]["attack"]["exploit_rates"] = [0.8001] * 5
        d = probe.decide(rs, PRIOR)
        assert "打地鼠" in d["verdict"]


# ---------------------------------------------------------------------------
# 2. 结果 JSON 口径一致性
# ---------------------------------------------------------------------------
class TestResultJsonConsistency:
    def test_trajectory_matches_rounds(self, probe, result_json):
        rounds = result_json["rounds"]
        tr = result_json["trajectory"]
        assert tr["exploit_rates"] == [round(r["attack"]["exploit_rate"], 6)
                                       for r in rounds]
        assert tr["off_cells"] == [r["model"]["off_cells"] for r in rounds]
        assert tr["targets"] == [r["attack"]["target"] for r in rounds]
        assert tr["target_labels"] == [r["attack"]["target_label"] for r in rounds]

    def test_checks_recompute(self, probe, result_json):
        d = probe.decide(result_json["rounds"], result_json["prior_r0"])
        assert d["checks"] == result_json["checks"], "checks 未由 decide() 重导"

    def test_verdict_matches_decision_table(self, probe, result_json):
        d = probe.decide(result_json["rounds"], result_json["prior_r0"])
        assert result_json["verdict"] == d["verdict"]

    def test_n_star_migrated_active(self, probe, result_json):
        d = probe.decide(result_json["rounds"], result_json["prior_r0"])
        assert result_json["n_star"] == d["n_star"]
        assert result_json["migrated"] == d["migrated"]
        # JSON 序列化把元组转列表，比较前归一化
        norm = [(r, l) for r, l in result_json["active_targets"]]
        assert norm == d["active_targets"]

    def test_committed_instrument_health(self, probe, result_json):
        """已提交结果必须仪表健康：E0-E6 全真（否则结论不可信）。"""
        c = result_json["checks"]
        assert c["E0_r0_fingerprint"] is True, "R0 未复读盲区实验良性-only 模型"
        assert c["E1_benign_preserved"] is True, "良性检测被重训破坏"
        assert c["E2_initially_exploitable"] is True, "R0 盲区初始不可利用"
        assert c["E3_no_label_conflict"] is True, "own_idx 对齐管线坏"
        assert c["E5_surrogate_instrument"] is True, "代理仪表不良"
        assert c["E6_determinism"] is True, "种子间 exploit 不等（随机源混入）"

    def test_committed_verdict_is_closure(self, probe, result_json):
        """已提交结论方向守卫：共演化重训关闭离流形盲点（换 JSON 须显式）。

        注意：3 轮导引曾显「打地鼠」假象（off-cells 仍 >0），全量 6 轮揭示
        离流形格单调收窄至 0、攻击者末轮无可占格 ⇒ 真实结论是关闭。守卫
        绑定真实方向，不得硬编码为「打地鼠」。"""
        assert "关闭盲区" in result_json["verdict"], \
            "已提交结论应为关闭盲点（非打地鼠/无效）"
        assert result_json["n_star"] is not None
        # 末回合攻击者无可占离流形格
        assert result_json["rounds"][-1]["attack"]["exploit_rate"] <= 0.20
        assert result_json["rounds"][-1]["model"]["off_cells"] == 0
        # 轨迹显示压缩：离流形格单调非增（首>末）
        offs = result_json["trajectory"]["off_cells"]
        assert offs[0] > offs[-1], "盲点应被压缩，离流形格首>末"
        # exploit 轨迹应从高利用率收敛到 0（关闭）
        assert result_json["trajectory"]["exploit_rates"][0] > 0.80
        assert result_json["trajectory"]["exploit_rates"][-1] <= 0.20


# ---------------------------------------------------------------------------
# 3. 与盲区/定向探针的口径一致
# ---------------------------------------------------------------------------
class TestProbeParamsAligned:
    def test_params_identical_to_blindspot(self, probe, blindspot):
        for attr in ("N_AGENTS", "N_LM", "THRESHOLD", "DT", "V_MAX",
                     "N_STEPS", "SEEDS", "LANDMARKS", "START", "GRID_LO",
                     "GRID_HI", "GRID_STEP"):
            assert getattr(probe.BS, attr) == getattr(blindspot, attr), \
                f"{attr} 与盲区探针漂移"

    def test_prior_r0_matches_blindspot_committed(self, probe):
        if not BLINDSPOT_RESULT_PATH.exists():
            pytest.skip("ml_blindspot_result.json 不存在")
        d = json.loads(BLINDSPOT_RESULT_PATH.read_text(encoding="utf-8"))
        assert probe.PRIOR_R0["trusted_cells"] == \
            d["trusted_region"]["trusted_cells"]
        assert abs(probe.PRIOR_R0["heldout"]
                   - d["ml_defender"]["heldout_accuracy"]) < 0.01


# ---------------------------------------------------------------------------
# 4. 标签完整性（E3）与 benign_label 协议语义
# ---------------------------------------------------------------------------
class TestLabelIntegrity:
    def test_benign_label_protocol(self, probe):
        """benign_label 协议：靠近自身 landmark ⇒ 1；远离所有 ⇒ 0。"""
        bs = probe.BS
        # 靠近 L0（own=0）⇒ 1
        l0 = bs.LANDMARKS[0]
        assert bs.benign_label(l0[0], l0[1], 0) == 1
        # 远离所有 landmark（取大坐标，距任一 landmark >> 阈值）⇒ 0（对任意 own）
        for own in range(bs.N_LM):
            assert bs.benign_label(5.0, 5.0, own) == 0
        # 靠近 L1 但 own=0（离流形）⇒ 0（这正是盲点应被标为负）
        l1 = bs.LANDMARKS[1]
        assert bs.benign_label(l1[0], l1[1], 0) == 0

    def test_retrain_set_zero_conflict_live(self, probe):
        """实时：build_retrain_set 不得产生标签冲突（own_idx 对齐管线正确）。"""
        pytest.importorskip("sklearn")
        benign, held, _ = probe.gen_benign_split()
        det, info = probe.retrain_defender(benign, [])
        assert info["trained"] is True
        assert info["conflicts"] == 0, "良性-only 重训不应有标签冲突"


# ---------------------------------------------------------------------------
# 5/6. 实时缩样共演化（活代码，守住探针逻辑不退化）
# ---------------------------------------------------------------------------
class TestLiveCoevolution:
    def _run_mini(self, probe, n_rounds=2, n_seeds=2):
        saved_rounds = probe.N_ROUNDS
        saved_seeds = probe.BS.SEEDS
        probe.N_ROUNDS = n_rounds
        probe.BS.SEEDS = saved_seeds[:n_seeds]
        try:
            benign, held, _ = probe.gen_benign_split()
            attack_cum, rounds = [], []
            for r in range(n_rounds):
                rd, uniq = probe.run_round(r, benign, held, attack_cum)
                rounds.append(rd)
                attack_cum.extend(uniq)
            return probe.decide(rounds, probe.PRIOR_R0), rounds
        finally:
            probe.N_ROUNDS = saved_rounds
            probe.BS.SEEDS = saved_seeds

    def test_live_mini_instrument_healthy(self, probe):
        """2 轮×2 种子活代码：仪表全绿 + R0 初始可利用（run_exploit 真实反馈
        预筛未被移除，否则 exploit=0 → E2 红）。"""
        pytest.importorskip("sklearn")
        d, rounds = self._run_mini(probe, 2, 2)
        assert d["checks"]["E0_r0_fingerprint"] is True
        assert d["checks"]["E2_initially_exploitable"] is True
        assert d["checks"]["E3_no_label_conflict"] is True
        assert d["checks"]["E6_determinism"] is True
        assert d["checks"]["E5_surrogate_instrument"] is True

    def test_live_mini_attacker_still_exploits(self, probe):
        """活代码：攻击者（每轮重窃取）首轮即可占领离流形可信格（exploit>0.8）。
        若 run_exploit 真实反馈预筛被误删，会选到代理误差格 ⇒ exploit≈0。"""
        pytest.importorskip("sklearn")
        d, rounds = self._run_mini(probe, 2, 2)
        assert rounds[0]["attack"]["exploit_rate"] > 0.80, \
            "R0 攻击者未占领离流形盲点——run_exploit 逻辑疑似退化"

    def test_live_mini_off_cells_shrink(self, probe):
        """活代码：重训压缩盲点（离流形格非增），守护 retrain 标签管线方向正确。"""
        pytest.importorskip("sklearn")
        d, rounds = self._run_mini(probe, 3, 2)
        offs = [r["model"]["off_cells"] for r in rounds]
        assert offs[0] >= offs[-1], "离流形格应随重训收窄"
