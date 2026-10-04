#!/usr/bin/env python3
"""
One-Click Web Dashboard Launcher
================================
Starts the Flask + Chart.js visualization dashboard.

Usage:
    python scripts/one-click/launch_dashboard.py                     # Start dashboard
    python scripts/one-click/launch_dashboard.py --port 9090         # Custom port
    python scripts/one-click/launch_dashboard.py --data results/training_results.json  # Load results
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def main():
    parser = argparse.ArgumentParser(description="One-Click Dashboard Launcher")
    parser.add_argument("--port", type=int, default=9090, help="Dashboard port (default: 9090)")
    parser.add_argument("--data", type=str, default=None, help="Training results JSON to load")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════╗")
    print("║   MARL-ECDSA Web Dashboard Launcher              ║")
    print(f"║   Framework: Flask + Chart.js                     ║")
    print(f"║   URL: http://127.0.0.1:{args.port}                       ║")
    print("║   9 Tabs: Overview | Network | Security | Ledger  ║")
    print("║           MARL | Compare | P2P | ECDSA | System  ║")
    print("╚══════════════════════════════════════════════════╝")

    cmd = ["python", "main.py", "--dashboard"]
    if args.data:
        # Load results file for dashboard
        cmd.extend(["--save", args.data])

    print(f"\n▶ Starting dashboard: {' '.join(cmd)}")
    print(f"\n📊 Open in browser: http://127.0.0.1:{args.port}")
    print("   Press Ctrl+C to stop\n")

    result = subprocess.run(cmd, cwd=str(ROOT_DIR))

    if result.returncode != 0:
        print("\n❌ Dashboard failed to start")
        sys.exit(1)


if __name__ == "__main__":
    main()
