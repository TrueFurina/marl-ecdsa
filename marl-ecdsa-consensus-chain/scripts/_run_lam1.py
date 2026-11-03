from pathlib import Path
import subprocess, sys, os, json, time
PY = sys.executable
BASE = str(Path(__file__).resolve().parents[1])
OUT = os.path.join(BASE, "results", "delivery_lam1")
os.makedirs(OUT, exist_ok=True)

for seed in [42, 100]:
    for cred in [False, True]:
        tag = "cred" if cred else "base"
        out = os.path.join(OUT, f"{tag}_s{seed}.json")
        if os.path.exists(out):
            j = json.load(open(out, encoding="utf-8"))
            print(f"skip {tag} s{seed}: {j['final_completed']:.3f}")
            continue
        cmd = [PY, "-X", "utf8", "train_delivery_torch.py",
               "--seed", str(seed), "--episodes", "5000",
               "--lam", "1.0", "--out", out]
        if cred:
            cmd.append("--credibility")
        t0 = time.time()
        r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, encoding="utf-8")
        j = json.load(open(out, encoding="utf-8"))
        print(f"{tag} s{seed}: completed={j['final_completed']:.3f}+/-{j['final_std']:.3f} ({time.time()-t0:.0f}s)")
