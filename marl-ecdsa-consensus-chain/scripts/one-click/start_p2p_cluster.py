#!/usr/bin/env python3
"""
One-Click P2P Network Cluster Demo
==================================
Launches N asyncio P2P nodes and runs CW-PBFT consensus rounds.

Usage:
    python scripts/one-click/start_p2p_cluster.py                    # Default: 3 nodes, 15 rounds
    python scripts/one-click/start_p2p_cluster.py --nodes 5          # 5 nodes
    python scripts/one-click/start_p2p_cluster.py --nodes 4 --rounds 20 --verbose
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def main():
    parser = argparse.ArgumentParser(description="One-Click P2P Network Cluster Launcher")
    parser.add_argument("--nodes", type=int, default=3, help="Number of P2P nodes")
    parser.add_argument("--rounds", type=int, default=15, help="Number of consensus rounds")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════╗")
    print("║   MARL-ECDSA P2P Network Cluster Launcher        ║")
    print(f"║   Nodes: {args.nodes}  |  Rounds: {args.rounds}                         ║")
    print("║   Protocol: TCP + JSON + asyncio                 ║")
    print("║   Consensus: CW-PBFT (Contribution-Weighted)      ║")
    print("╚══════════════════════════════════════════════════╝")

    cmd = [
        sys.executable, str(ROOT_DIR / "scripts" / "network_demo.py"),
        "--nodes", str(args.nodes),
        "--rounds", str(args.rounds),
    ]
    if args.verbose:
        cmd.append("--verbose")

    print(f"\n▶ Starting P2P cluster: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))

    if result.returncode == 0:
        print("\n✅ P2P network consensus demo complete!")
        print(f"   All {args.nodes} nodes successfully completed {args.rounds} consensus rounds")
    else:
        print("\n❌ P2P network demo failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
