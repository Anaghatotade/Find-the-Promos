"""End-to-end wall-clock benchmark: N runs of `python -m promofinder run` (fresh process each,
so imports, parsing, scoring, ranking and writing outputs are all included).
  python benchmarks/bench.py <repo_dir> <pack.zip> [runs]"""
import json, os, statistics, subprocess, sys, tempfile, time
repo, pack = sys.argv[1], sys.argv[2]; runs = int(sys.argv[3]) if len(sys.argv) > 3 else 3
walls = []
for i in range(runs):
    out = tempfile.mkdtemp()
    t = time.perf_counter()
    subprocess.run([sys.executable, "-m", "promofinder", "run", pack, "--out", out], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL)
    walls.append(time.perf_counter() - t)
meta = json.load(open(os.path.join(out, "run_meta.json"), encoding="utf-8"))
print(json.dumps({"repo": repo, "runs": [round(w, 2) for w in walls], "median_wall_s": round(statistics.median(walls), 2),
                  "last_run_timings": meta.get("timings_s")}, indent=1))
