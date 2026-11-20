"""Evaluation harness: checks a finished run against its source screenplays.

Nothing here needs ground-truth editor labels. It measures what can be measured honestly:

* hard constraints  - every pick is 20-60 s, every cut lands outside a line of dialogue, timestamps lie
                      inside the episode, picks don't overlap, EDL events match the JSON timecodes;
* spoiler exposure  - (optional) given a reveal-label file, how many picks show a labelled twist/resolution;
* agreement         - how similar two runs are (overlap@k and rank correlation), used for format-robustness
                      and before/after comparisons.

    python -m promofinder eval outputs/run --source show.zip [--labels reveals.json] [--compare other_run]
"""
from __future__ import annotations
import json, os
from typing import Dict, List, Optional


def _load(run_dir: str, name="promos_top.json"):
    with open(os.path.join(run_dir, name), encoding="utf-8") as fh:
        return json.load(fh)


def clip_key(p: Dict) -> tuple:
    return tuple((s["episode"], round(s["start_s"], 1), round(s["end_s"], 1)) for s in p["segments"])


def _overlaps(a: Dict, b: Dict, tol=0.5) -> bool:
    return any(x["episode"] == y["episode"] and x["start_s"] < y["end_s"] - tol and y["start_s"] < x["end_s"] - tol
               for x in a["segments"] for y in b["segments"])


def hard_constraints(promos: List[Dict], episodes, min_dur=20.0, max_dur=60.0, run_dir: Optional[str] = None) -> Dict:
    """Returns counts of violations (all should be 0) and the number of checks made."""
    eps = {e.number: e for e in episodes}
    v = {"duration_out_of_range": 0, "cut_inside_dialogue": 0, "timestamp_outside_episode": 0,
         "unknown_episode": 0, "overlapping_picks": 0, "edl_mismatch": 0}
    checks = 0
    for p in promos:
        checks += 1
        if not (min_dur - 0.05 <= p["duration_s"] <= max_dur + 0.05):
            v["duration_out_of_range"] += 1
        tot = 0.0
        for s in p["segments"]:
            ep = eps.get(s["episode"])
            if ep is None:
                v["unknown_episode"] += 1
                continue
            tot += s["end_s"] - s["start_s"]
            if s["start_s"] < -1e-6 or s["end_s"] > ep.duration + 0.05 or s["end_s"] <= s["start_s"]:
                v["timestamp_outside_episode"] += 1
            for t in (s["start_s"], s["end_s"]):
                if any(b.kind == "dialogue" and b.start + 0.05 < t < b.end - 0.05 for b in ep.blocks):
                    v["cut_inside_dialogue"] += 1
        if abs(tot - p["duration_s"]) > 0.05:
            v["duration_out_of_range"] += 1
    for i, a in enumerate(promos):
        for b in promos[i + 1:]:
            if _overlaps(a, b):
                v["overlapping_picks"] += 1
    if run_dir and os.path.isdir(os.path.join(run_dir, "edl")):
        from .edl import parse_edl
        for p in promos:
            path = os.path.join(run_dir, "edl", f"promo_{p['rank']:02d}.edl")
            if not os.path.exists(path):
                continue
            ev = parse_edl(open(path, encoding="utf-8").read())
            for e, s in zip(ev, p["segments"]):
                if abs(e["src_in"] - s["start_s"]) > 1 / 30 + 1e-6 or e["reel"] != f"E{s['episode']:03d}":
                    v["edl_mismatch"] += 1
    v["n_promos_checked"] = checks
    v["all_ok"] = all(val == 0 for k, val in v.items() if k not in ("n_promos_checked",))
    return v


def _clip_text(p: Dict) -> str:
    return " ".join(l.get("text", "") for l in p.get("transcript", [])).lower()


def spoiler_exposure(promos: List[Dict], labels: Dict) -> Dict:
    """A pick 'shows' a labelled reveal if it comes from that episode (or the next one, whose cold open
    often replays it) and its transcript matches every key group."""
    shown = {"twist": [], "resolution": [], "premise": []}
    for p in promos:
        eps_in = {s["episode"] for s in p["segments"]}
        txt = _clip_text(p)
        for r in labels.get("reveals", []):
            if not ({r["episode"], r["episode"] + 1} & eps_in):
                continue
            if all(any(k in txt for k in grp) for grp in r["keys"]):
                shown.setdefault(r["class"], []).append({"rank": p["rank"], "episode": r["episode"], "what": r["what"]})
    return {"twist_or_resolution_shown": len(shown["twist"]) + len(shown["resolution"]),
            "premise_reveals_shown": len(shown["premise"]), "details": shown}


def agreement(a: List[Dict], b: List[Dict], k: Optional[int] = None) -> Dict:
    """overlap@k by exact clip identity and by 'same moment' (overlapping time ranges)."""
    k = k or min(len(a), len(b))
    A, B = a[:k], b[:k]
    exact = len({clip_key(p) for p in A} & {clip_key(p) for p in B})
    loose = sum(1 for p in A if any(_overlaps(p, q, tol=5.0) for q in B))
    return {"k": k, "exact_overlap": exact, "moment_overlap": loose,
            "exact_overlap_frac": round(exact / max(k, 1), 3), "moment_overlap_frac": round(loose / max(k, 1), 3),
            "same_top1": bool(A and B and _overlaps(A[0], B[0], tol=5.0))}


def summary(promos: List[Dict]) -> Dict:
    eps = [s["episode"] for p in promos for s in p["segments"][:1]]
    out = {"n": len(promos), "distinct_episodes": len(set(eps)),
           "median_first_episode": sorted(eps)[len(eps) // 2] if eps else None,
           "mean_duration_s": round(sum(p["duration_s"] for p in promos) / max(len(promos), 1), 1),
           "hook_types": {}, "cut_types": {}}
    for p in promos:
        out["hook_types"][p["hook"]["type"]] = out["hook_types"].get(p["hook"]["type"], 0) + 1
        out["cut_types"][p["cliffhanger"]["type"]] = out["cut_types"].get(p["cliffhanger"]["type"], 0) + 1
        if "angle" in p:
            out.setdefault("angles", {})
            out["angles"][p["angle"]["primary"]] = out["angles"].get(p["angle"]["primary"], 0) + 1
    st = [p["components"].get("stability") for p in promos if p["components"].get("stability") is not None]
    if st:
        out["mean_stability"] = round(sum(st) / len(st), 3)
    return out


def evaluate_run(run_dir: str, source_paths: List[str], labels_path: Optional[str] = None,
                 compare_dir: Optional[str] = None) -> Dict:
    from .ingest import load_inputs
    top = _load(run_dir)
    meta, promos = top["meta"], top["promos"]
    _, eps = load_inputs(source_paths)
    cfg = meta.get("config", {})
    rep = {"run": run_dir, "version": meta.get("version"), "summary": summary(promos),
           "hard_constraints_top": hard_constraints(promos, eps, cfg.get("min_dur", 20), cfg.get("max_dur", 60), run_dir)}
    try:
        lng = _load(run_dir, "promos_longlist.json")["promos"]
        hc = hard_constraints(lng, eps, cfg.get("min_dur", 20), cfg.get("max_dur", 60))
        rep["hard_constraints_longlist"] = hc
    except OSError:
        pass
    if labels_path:
        with open(labels_path, encoding="utf-8") as fh:
            labels = json.load(fh)
        rep["spoilers_top"] = spoiler_exposure(promos, labels)
    if compare_dir:
        rep["agreement_with"] = {"run": compare_dir, **agreement(promos, _load(compare_dir)["promos"])}
    return rep
