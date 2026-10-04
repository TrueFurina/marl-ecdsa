"""Probe E13 inner results keys + aggregate E13/E14 across seeds (env_reward 口径)."""
from __future__ import annotations

import glob
import io
import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "results", "dispatch_20260921")
OUT = os.path.join(HERE, "_probe_out.txt")

lines: list[str] = []


def load(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- E13 probe
e13 = sorted(glob.glob(os.path.join(D, "e13_expb_seed*.json")))
obj = load(e13[0])
res = obj["experiments"][0]["results"]
lines.append(f"E13 experiments[0]: name={obj['experiments'][0].get('name')}")
lines.append(f"E13 results keys ({len(res)}): {list(res)}")
sample_key = next(k for k in res if k != "comparison")
lines.append(f"\nsample label '{sample_key}' full dict:")
for k, v in res[sample_key].items():
    lines.append(f"    {k}: {str(v)[:90]}")

# ------------------------------------------------------ E13 aggregate by mode
labels = [k for k in res if k != "comparison"]
modes = sorted({lbl.rsplit("_", 1)[1] for lbl in labels})
ratios = sorted({int(lbl.split("_")[1].replace("pct", "")) for lbl in labels})

METRICS = [m for m in res[sample_key] if isinstance(res[sample_key][m], (int, float))]

data: dict[tuple[int, str], dict[str, list[float]]] = {}
for p in e13:
    r = load(p)["experiments"][0]["results"]
    for lbl in labels:
        ratio = int(lbl.split("_")[1].replace("pct", ""))
        mode = lbl.rsplit("_", 1)[1]
        for m in METRICS:
            data.setdefault((ratio, mode), {}).setdefault(m, []).append(float(r[lbl][m]))

lines.append(f"\n=== E13 聚合（{len(e13)} 种子, 500 回合）===")
lines.append(f"可用数值指标: {METRICS}")
for ratio in ratios:
    for m in METRICS:
        row = []
        for mode in modes:
            v = data.get((ratio, mode), {}).get(m, [])
            row.append(f"{mode}={st.mean(v):.3f}±{st.stdev(v):.3f}(n={len(v)})" if v else f"{mode}=NA")
        lines.append(f"  {ratio:>3}%  {m:<26} " + "  ".join(row))

# paired greedy - random
lines.append("\n=== E13 配对差（greedy − random，同种子配对）===")
try:
    from scipy import stats  # type: ignore
    have_scipy = True
except Exception:  # noqa: BLE001
    have_scipy = False
lines.append(f"scipy available: {have_scipy}")
for ratio in ratios:
    for m in METRICS:
        a = data.get((ratio, "greedy"), {}).get(m)
        b = data.get((ratio, "random"), {}).get(m)
        if not a or not b or len(a) != len(b):
            continue
        d = [x - y for x, y in zip(a, b)]
        mu, sd = st.mean(d), st.stdev(d)
        tail = ""
        if have_scipy:
            t, pt = stats.ttest_rel(a, b)
            w, pw = stats.wilcoxon(a, b) if any(x != 0 for x in d) else (float("nan"), float("nan"))
            tail = f" | t-test p={pt:.4g} | wilcoxon p={pw:.4g}"
        lines.append(f"  {ratio:>3}%  {m:<26} Δ={mu:+.3f} (sd {sd:.3f}){tail}")

# ----------------------------------------------------------- E14 aggregate
e14 = sorted(glob.glob(os.path.join(D, "e14_*.json")))
algos = sorted({os.path.basename(p).split("_")[1] for p in e14})
agg: dict[str, dict[str, list[float]]] = {}
for p in e14:
    algo = os.path.basename(p).split("_")[1]
    s = load(p)["summary"]
    for m in ["avg_reward", "avg_env_reward", "avg_env_reward_last_50", "avg_cooperation_rate", "avg_betrayal_rate"]:
        agg.setdefault(algo, {}).setdefault(m, []).append(float(s[m]))

lines.append(f"\n=== E14 聚合（每算法 n={len(e14) // max(1, len(algos))} 种子, 3000 回合）===")
lines.append(f"{'metric':<26}" + "".join(f"{a:>16}" for a in algos))
for m in ["avg_env_reward", "avg_env_reward_last_50", "avg_reward", "avg_cooperation_rate", "avg_betrayal_rate"]:
    row = f"{m:<26}"
    for a in algos:
        v = agg.get(a, {}).get(m, [])
        row += f"{st.mean(v):>10.3f}±{st.stdev(v):<5.2f}" if v else f"{'NA':>16}"
    lines.append(row)

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
