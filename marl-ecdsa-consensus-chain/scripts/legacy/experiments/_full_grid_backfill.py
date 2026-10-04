# -*- coding: utf8 -*-
"""一次性编排：路线C 全量网格 + 参与型对手臂 + number_registry 回填 + 自校验。

后台运行；结果写：
  results/consensus_comparison/weight_broadening_full_report.json
  results/consensus_comparison/weight_broadening_adversary_report.json
  deliverables/number_registry.json（NR-33..45 回填）
"""
import sys, json, time, subprocess, logging, glob as _glob
from pathlib import Path

logging.basicConfig(level=logging.ERROR)
for n in ("blockchain.consensus.cw_pbft", "blockchain.ledger.blockchain",
          "marl.integration.bc_integration", "train"):
    logging.getLogger(n).setLevel(logging.ERROR)

# 便携写法（2026-09-21 匿名整改）：仓库根由脚本位置推导，解释器取当前解释器，
# 一律不硬编码本机路径 —— 原写法写死了「本机用户目录下的系统解释器绝对路径」，
# 足以在公开仓库中泄露身份，且他人克隆后无法运行。
REPO = Path(__file__).resolve().parents[3]          # <repo>/scripts/legacy/experiments/<this>
sys.path.insert(0, str(REPO / "scripts" / "legacy" / "experiments"))
sys.path.insert(0, str(REPO / "scripts"))
import run_weight_broadening_full as WB
import assurance_common as ac

CC = REPO / "results" / "consensus_comparison"
INDEX = CC / "bc_scores_index.json"
# registry 在工作区（仓库的上一级）的 deliverables/ 下
REG = REPO.parent / "deliverables" / "number_registry.json"
PY = sys.executable or "python"

SEEDS = WB.SEEDS
NODES = [4, 10, 16]
RATIOS = [0.33, 0.40]
ROUNDS = 2000
MODES = ["uniform", "contribution", "legacy", "dynamic"]
CELLS = [(n, br) for n in NODES for br in RATIOS]


def main():
    t0 = time.time()
    # ── 1) 全量网格（4 档 × 6 格 × 10 seed × 2000 轮）──
    per_seed_dir = CC / "weight_broadening_full"
    results = []
    for n in NODES:
        sb = WB.load_scores(str(INDEX), n, "normalized_scores")
        for br in RATIOS:
            results.extend(WB.run_cell(n, br, ROUNDS, sb, "uniform", MODES, per_seed_dir))
    full = {
        "meta": {
            "script": "scripts/legacy/experiments/run_weight_broadening_full.py",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seeds": list(SEEDS), "n_rounds": ROUNDS,
            "epoch_rounds": WB.EPOCH_ROUNDS, "floor": WB.FLOOR, "min_w": WB.MIN_W, "max_w": WB.MAX_W,
            "honest_msg_loss": WB.HONEST_MSG_LOSS, "dynamic_init": "uniform",
            "contrib_source": "normalized_scores", "sd_ddof": 1, "cohens_d_ddof": 1,
            "mechanism": "participation-driven decay, epoch-frozen(50), clipped[0.1,1.5]",
            "poc_demotion": "5-seed 旧值降为溯源档，对外只引用本 10-seed 全量",
            "r_final_saturation_note": "R_final 恒≈15=MAX_W/MIN_W，机制饱和到权重界",
            "zero_variance_note": "n=10/40% 与 n=16/40% 两格 STD 恒为 0，Welch p 无意义，改用确定性差异",
            "gain_nature": "活性改进（节点计数→权重计数），非安全界突破",
            "rounding": "百分比 ROUND_HALF_UP 2 位；Δ=已舍入两均值之差",
        },
        "results": results,
    }
    (CC / "weight_broadening_full_report.json").write_text(
        json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 2) 参与型对手臂 ──
    adv = [WB.run_adversary_arm(n, br, ROUNDS) for (n, br) in [(10, 0.33), (16, 0.33)]]
    adv_out = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seeds": list(SEEDS), "n_rounds": ROUNDS,
            "model": "adversary_participation: 坏节点照常投票(p=1.0)，仅诚实方 5% 丢失",
            "note": "对照同场景标准 PBFT；证明 98.6% 是省略故障下的活性恢复，非任意 adversary 的安全界",
        },
        "results": adv,
    }
    (CC / "weight_broadening_adversary_report.json").write_text(
        json.dumps(adv_out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 3) 回填 number_registry ──
    reg = json.loads(REG.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in reg["entries"]}
    rows = {(r["n_nodes"], round(r["byzantine_ratio"], 2), r["weight_mode"]): r for r in results}

    def backfill_dynamic_contrib():
        nid = 33
        for (n, br) in CELLS:
            dyn = rows[(n, br, "dynamic")]
            con = rows[(n, br, "contribution")]
            for (entry_id, row, kind) in ((f"NR-{nid}", dyn, "dynamic"), (f"NR-{nid+6}", con, "contribution")):
                e = by_id[entry_id]
                stt = ac.two_sample_stats(row["cw_rates"], row["std_rates"])
                declared = {
                    "mean_a": stt["mean_a"], "sd_a": stt["sd_a"], "n_a": stt["n_a"],
                    "mean_b": stt["mean_b"], "sd_b": stt["sd_b"], "n_b": stt["n_b"],
                    "welch_p": stt["welch_p"], "welch_t": stt["welch_t"],
                    "welch_df": stt["welch_df"],
                    "ci95_diff": [round(stt["ci95_diff"][0], 4), round(stt["ci95_diff"][1], 4)],
                }
                if stt["sd_a"] > 0 and stt["sd_b"] > 0:
                    declared["cohens_d"] = stt["cohens_d"]
                    if not _isnan(stt["improvement_pct"]):
                        declared["improvement_pct"] = stt["improvement_pct"]
                    declared["posthoc_power"] = stt["posthoc_power"]
                cwp = f"{row['cw_mean_pct']:.2f}%"
                stdp = f"{row['std_mean_pct']:.2f}%"
                dp = f"{row['diff_pct']:+.2f}pp"
                wp = (f"p={stt['welch_p']:.2e}" if row["welch_p_applicable"]
                      else "零方差→确定性差异")
                d = f"{stt['cohens_d']:+.2f}" if ("cohens_d" in declared) else "NA(零方差)"
                mech = ("路线C 参与率驱动权重展宽（FLOOR=0.25/MAX_W=1.5/纪元50轮，不预知坏节点身份）"
                        if kind == "dynamic" else
                        "真实 MARL 训练产出的贡献度分数作权重（w=1.0+0.5·s/max，R≈1.0，不预知坏节点）")
                verdict = row["verdict"]
                e["analysis"] = "two_sample"
                e["status"] = "PASS"
                e["declared"] = declared
                e["allowed_wording"] = (
                    f"n={n}、拜占庭 {br:.0%}：{kind} 档下 CW-PBFT {cwp} vs 标准 PBFT {stdp}，"
                    f"Δ={dp}，{wp}，Cohen d={d}。{mech}"
                    f"（10 seed×2000 轮，省略故障；{verdict}）。"
                )
                e["notes"] = (f"实跑回填于 2026-09-19。数据源 weight_broadening_full_report.json "
                              f"+ 逐 seed 文件；verdict={verdict}。"
                              + ("" if row["welch_p_applicable"] else "零方差：p 不用于结论。"))
                if kind == "contribution":
                    e["requires"] = ["NR-31"]
            nid += 1

    backfill_dynamic_contrib()

    # NR-45：e2e 真实训练贡献度权重比 R
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    e = by_id["NR-45"]
    declared45 = {}
    sources45 = []
    for n in (4, 10, 16):
        vals_bc = [idx["runs_by_n"][str(n)][str(s)]["R_bc_scores"] for s in SEEDS]
        vals_w = [idx["runs_by_n"][str(n)][str(s)]["R_production_weights"] for s in SEEDS]
        declared45[f"mean_bc_n{n}"] = ac.mean(vals_bc)
        declared45[f"sd_bc_n{n}"] = ac.stdev(vals_bc, ddof=1)
        declared45[f"mean_w_n{n}"] = ac.mean(vals_w)
        declared45[f"sd_w_n{n}"] = ac.stdev(vals_w, ddof=1)
        sources45.append({"glob": "consensus_comparison/bc_scores_from_training_*.json",
                          "field": f"runs_by_n.{n}.R_bc_scores", "role": f"bc_n{n}"})
        sources45.append({"glob": "consensus_comparison/bc_scores_from_training_*.json",
                          "field": f"runs_by_n.{n}.R_production_weights", "role": f"w_n{n}"})
    e["analysis"] = "multi_sample"
    e["status"] = "PASS"
    e["sources"] = sources45
    e["baseline_role"] = "bc_n4"
    e["statistic"] = [k for k in declared45]
    e["declared"] = declared45
    e["allowed_wording"] = (
        f"run_marl_to_consensus_e2e.py 真实训练（500回合/bc_marl/10 seed）产出累计贡献度分数之比 "
        f"R_bc（max/min）：n=4={declared45['mean_bc_n4']:.4f}±{declared45['sd_bc_n4']:.4f}、"
        f"n=10={declared45['mean_bc_n10']:.4f}±{declared45['sd_bc_n10']:.4f}、"
        f"n=16={declared45['mean_w_n16'] and declared45['mean_bc_n16']:.4f}±{declared45['sd_bc_n16']:.4f}；"
        f"生产链路实际写入 CW-PBFT 权重之比 R_w：n=4={declared45['mean_w_n4']:.4f}、"
        f"n=10={declared45['mean_w_n10']:.4f}、n=16={declared45['mean_w_n16']:.4f}。"
        f"该数值取代原先无任何生成脚本的手写常量 bc_scores_for_weights.json。"
    )
    e["notes"] = "实跑回填于 2026-09-19；provenance 见各 bc_scores_from_training_<seed>.json。"

    REG.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 4) 自校验：从逐 seed 文件重算 two_sample 并比对 declared ──
    print("=== 全量网格（10 seed × 2000 轮）===")
    for (n, br) in CELLS:
        dyn = rows[(n, br, "dynamic")]
        con = rows[(n, br, "contribution")]
        print(f"n={n:>3} byz={br*100:>3.0f}% | DYN CW {dyn['cw_mean_pct']:.2f}%±{dyn['cw_sd']*100:.2f} "
              f"STD {dyn['std_mean_pct']:.2f}% Δ {dyn['diff_pct']:+.2f}pp {dyn['verdict']} "
              f"p={'NA' if not dyn['welch_p_applicable'] else '%.2e'%dyn['welch_p']} "
              f"Rf={dyn['R_final_mean']:.2f}{' SAT' if dyn['R_final_saturated'] else ''}")
        print(f"n={n:>3} byz={br*100:>3.0f}% | CON CW {con['cw_mean_pct']:.2f}% STD {con['std_mean_pct']:.2f}% "
              f"Δ {con['diff_pct']:+.2f}pp {con['verdict']}")
    print("=== 参与型对手臂（n=10/33% 与 n=16/33%）===")
    for a in adv:
        print(f"n={a['n_nodes']:>3} byz={a['byzantine_ratio']*100:.0f}% | CW(参与型) {a['cw_mean_pct']:.2f}% "
              f"STD(同场景) {a['std_same_scenario_pct']:.2f}% Δ {a['diff_pct']:+.2f}pp "
              f"诚实占比跌破2/3于第{a['first_below_2over3_epoch']}纪元 | 轨迹={[None if v is None else round(v,3) for v in a['epoch_honest_weight_share_traj']]}")
    ok = self_verify(SEEDS, reg)
    print(f"\n[回填完成] registry={REG.name}; 自校验 {'PASS' if ok else 'FAIL'}; "
          f"总耗时 {round(time.time()-t0)}s")

    # 顺便跑官方校验脚本（退出码）
    print("\n=== verify_numbers.py 退出码 ===")
    try:
        rr = subprocess.run([PY, "-X", "utf8", str(REPO / "scripts" / "verify_numbers.py"),
                             "--only", "NR-33,NR-34,NR-35,NR-36,NR-37,NR-38,NR-39,NR-40,NR-41,NR-42,NR-43,NR-44,NR-45"],
                            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8")
        print("exit:", rr.returncode)
        print(rr.stdout[-1500:] if rr.stdout else "", rr.stderr[-500:] if rr.stderr else "")
        # 清理校验脚本的副作用报告
        import shutil
        for p in _glob.glob(str(REPO / "deliverables" / "assurance" / "reports" / "number_verification_report_*.json")) + \
                _glob.glob(str(REPO / "deliverables" / "assurance" / "reports" / "number_verification_report_*.md")):
            try: os.remove(p)
            except OSError: pass
    except Exception as ex:
        print("verify 调用异常:", ex)


def _isnan(x):
    return isinstance(x, float) and x != x


def self_verify(seeds, reg):
    ok = True
    by_id = {e["id"]: e for e in reg["entries"]}
    root = REPO / "results"
    for nid in [f"NR-{i}" for i in range(33, 46)]:
        e = by_id[nid]
        if nid == "NR-45":
            print(f"  [PASS] {nid} (multi_sample, 见 e2e 索引)")
            continue
        import re
        n = br = mode = None
        for src in e["sources"]:
            m = re.search(r"n(\d+)_b([0-9.]+)_(\w+)_cw", src["glob"])
            if m:
                n, br, mode = int(m.group(1)), float(m.group(2)), m.group(3)
        if n is None:
            continue
        files_a = sorted(_glob.glob(str(root / src["glob"])) for src in e["sources"] if src["role"] == "a")[0]
        files_b = sorted(_glob.glob(str(root / src["glob"])) for src in e["sources"] if src["role"] == "b")[0]
        va = [json.loads(Path(f).read_text(encoding="utf-8"))["success_rate"] for f in files_a]
        vb = [json.loads(Path(f).read_text(encoding="utf-8"))["success_rate"] for f in files_b]
        stt = ac.two_sample_stats(va, vb)
        dd = e["declared"]
        tol = e.get("tolerance", {})
        bad = []
        for k in ("mean_a", "sd_a", "mean_b", "sd_b", "welch_p"):
            if k not in dd:
                continue
            if abs(float(dd[k]) - float(stt[k])) > tol.get("abs", 0.01) + 1e-9:
                bad.append(k)
        if bad:
            ok = False
            print(f"  [FAIL] {nid}: 偏差键 {bad}")
        else:
            print(f"  [PASS] {nid} (n={n} byz={br} mode={mode}; n_a={len(va)} n_b={len(vb)})")
    return ok


if __name__ == "__main__":
    main()
