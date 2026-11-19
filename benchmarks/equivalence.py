"""Snapshot / compare the complete pipeline result (every candidate's score and components,
the top-N and longlist picks, hook & cliff moment scores) to prove optimizations change nothing.

  python benchmarks/equivalence.py snapshot <pack.zip> ref.pkl
  python benchmarks/equivalence.py compare  <pack.zip> ref.pkl
"""
import os, pickle, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from promofinder.ingest import load_inputs
from promofinder.config import load_config
from promofinder.pipeline import PromoFinder

KEYS = ("hook", "cliff", "standalone", "arc", "premise", "duration_fit", "funnel", "stability")


def key(c):
    return (c.kind,) + tuple((s.episode, round(s.start, 3), round(s.end, 3)) for s in c.segments)


def snapshot(pack):
    show, eps = load_inputs([pack])
    t = time.time(); r = PromoFinder(load_config()).run(show, eps); dt = time.time() - t
    return dt, {
        "cands": {key(c): (c.score, tuple(c.comps.get(k) for k in KEYS), tuple(c.flags)) for c in r["candidates"]},
        "top": [key(c) for c in r["top"]], "longlist": [key(c) for c in r["longlist"]],
        "hooks": [(m.ep, m.t, m.score) for m in r["hooks"]], "cliffs": [(m.ep, m.t, m.score) for m in r["cliffs"]],
        "timings": r.get("timings", {})}


def compare(ref, new, tol=1e-9):
    out = {"same_top": ref["top"] == new["top"], "same_longlist": ref["longlist"] == new["longlist"],
           "same_candidate_set": set(ref["cands"]) == set(new["cands"]), "n_candidates": len(new["cands"])}
    worst, diff_flags, worst_comp = 0.0, 0, 0.0
    for k, (s, comps, flags) in ref["cands"].items():
        if k not in new["cands"]:
            continue
        s2, comps2, flags2 = new["cands"][k]
        worst = max(worst, abs(s - s2))
        worst_comp = max([worst_comp] + [abs(a - b) for a, b in zip(comps, comps2) if a is not None and b is not None])
        diff_flags += flags != flags2
    out.update(max_abs_score_diff=worst, max_abs_component_diff=worst_comp, candidates_with_different_flags=diff_flags,
               max_hook_moment_diff=max(abs(a[2] - b[2]) for a, b in zip(ref["hooks"], new["hooks"])),
               max_cliff_moment_diff=max(abs(a[2] - b[2]) for a, b in zip(ref["cliffs"], new["cliffs"])))
    out["EQUIVALENT"] = (out["same_top"] and out["same_longlist"] and out["same_candidate_set"]
                         and worst <= tol and worst_comp <= tol and diff_flags == 0)
    return out


if __name__ == "__main__":
    mode, pack, path = sys.argv[1:4]
    dt, snap = snapshot(pack)
    if mode == "snapshot":
        pickle.dump(snap, open(path, "wb")); print(f"snapshot saved ({dt:.1f}s, {len(snap['cands'])} candidates)")
    else:
        res = compare(pickle.load(open(path, "rb")), snap)
        print(f"run {dt:.2f}s"); [print(f"  {k}: {v}") for k, v in res.items()]
        print("  stage timings:", snap["timings"])
