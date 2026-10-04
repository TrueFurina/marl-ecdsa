#!/usr/bin/env python3
"""
One-Click Full Experiment Pipeline
===================================
Runs all experiments needed for competition submission:
  - 3 modes (pure_marl / bc_marl / selfish)
  - 3 seeds [42, 123, 456]
  - 1000 episodes each
  - Generates comparison charts automatically

Usage:
    python scripts/one-click/run_full_experiment.py              # Full experiment
    python scripts/one-click/run_full_experiment.py --quick       # Quick test (100 ep)
    python scripts/one-click/run_full_experiment.py --agents 5    # 5-agent experiment
"""
import argparse
import json
import os
import sys
import time
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))


def run_command(cmd, description):
    """Run a shell command with progress display."""
    print(f"\n{'='*60}")
    print(f"▶ {description}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{'='*60}")
    start = time.time()
    result = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=False)
    elapsed = time.time() - start
    status = "✅ SUCCESS" if result.returncode == 0 else "❌ FAILED"
    print(f"  {status} ({elapsed:.1f}s)")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="One-Click Full Experiment Pipeline")
    parser.add_argument("--quick", action="store_true", help="Quick test (100 episodes)")
    parser.add_argument("--agents", type=int, default=3, help="Number of agents (3 or 5)")
    parser.add_argument("--seeds", type=str, default="42,123,456", help="Comma-separated seeds")
    parser.add_argument("--skip-dashboard", action="store_true", help="Skip dashboard launch")
    args = parser.parse_args()

    n_episodes = 100 if args.quick else 1000
    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    modes = ["pure_marl", "bc_marl", "selfish"]
    results_dir = ROOT_DIR / "results" / "one_click"
    results_dir.mkdir(parents=True, exist_ok=True)

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   MARL-ECDSA Consensus Chain — Full Experiment Pipeline      ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║   Modes: {', '.join(modes)}                          ║")
    print(f"║   Seeds: {seeds}                                         ║")
    print(f"║   Episodes/mode/seed: {n_episodes}                                  ║")
    print(f"║   Total runs: {len(modes) * len(seeds)}                                            ║")
    print(f"║   Agents: {args.agents}                                                ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    all_results = {}
    total_runs = len(modes) * len(seeds)
    run_idx = 0

    for seed in seeds:
        for mode in modes:
            run_idx += 1
            output_file = results_dir / f"{mode}_seed{seed}_agents{args.agents}.json"
            cmd = [
                "python", "train.py",
                "--mode", mode,
                "--n_agents", str(args.agents),
                "--n_landmarks", str(args.agents),
                "--n_episodes", str(n_episodes),
                "--seed", str(seed),
                "--save", str(output_file),
            ]
            if mode == "selfish":
                cmd.extend(["--selfish_ratio", "0.3"])

            ok = run_command(cmd, f"[{run_idx}/{total_runs}] {mode} seed={seed}")
            if ok and output_file.exists():
                with open(output_file) as f:
                    all_results[f"{mode}_seed{seed}"] = json.load(f)

    # Generate comparison report
    report_path = results_dir / "comparison_report.json"
    summary = {
        "experiment_config": {
            "modes": modes,
            "seeds": seeds,
            "n_episodes": n_episodes,
            "n_agents": args.agents,
        },
        "results": {}
    }

    for key, data in all_results.items():
        s = data.get("summary", {})
        summary["results"][key] = {
            "avg_reward": s.get("avg_reward", 0),
            "avg_env_reward": s.get("avg_env_reward", 0),
            "avg_cooperation_rate": s.get("avg_cooperation_rate", 0),
        }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print("📊 Comparison Report Summary:")
    print(f"{'='*60}")
    for key, r in summary["results"].items():
        print(f"  {key}: avg_reward={r['avg_reward']:.2f}, coop_rate={r['avg_cooperation_rate']:.1%}")
    print(f"\n📁 Full report: {report_path}")
    print(f"📁 Results files: {results_dir}")

    # Auto-generate charts
    try:
        from visualization.plot_results import generate_all_plots
        plot_dir = results_dir / "plots"
        plot_dir.mkdir(exist_ok=True)
        generate_all_plots(str(report_path), str(plot_dir))
        print(f"📊 Charts generated: {plot_dir}")
    except Exception as e:
        print(f"⚠️  Chart generation skipped: {e}")

    print("\n✅ Full experiment pipeline complete!")


if __name__ == "__main__":
    main()
