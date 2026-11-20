"""Write raw, unedited run outputs: JSON (full), CSV (flat), Markdown + HTML report."""
from __future__ import annotations
import csv, json, os, statistics, datetime, platform
from .parser import fmt_ts
from .features import overlapping
from .explain import hook_info, cliff_info, why, rank_reason, transcript
from . import __version__
from .profiles import ANGLE_LABEL
from .pipeline import extra_factor


def promo_record(c, rank, eps, pool_med, show):
    h, k = hook_info(c, eps), cliff_info(c, eps)
    segs = []
    for sg in c.segments:
        ep = eps[sg.episode]
        bs = overlapping(ep.blocks, sg.start, sg.end)
        segs.append({"episode": sg.episode, "start": fmt_ts(sg.start), "end": fmt_ts(sg.end),
                     "start_s": round(sg.start, 2), "end_s": round(sg.end, 2), "duration_s": round(sg.dur, 2),
                     "src_file": ep.src_file,
                     "src_lines": [min(b.src_line for b in bs), max(b.src_line for b in bs)] if bs else []})
    return {"rank": rank, "id": f"{show[:12].strip().replace(' ', '_')}-E{c.segments[0].episode:02d}-{int(c.segments[0].start*10):05d}",
            "score": round(c.score, 4), "type": c.kind, "duration_s": round(c.dur, 2), "segments": segs,
            "hook": h, "cliffhanger": k, "why_it_works": why(c, h, k), "rank_reason": rank_reason(c, rank, pool_med),
            "components": dict({kk: round(v, 3) for kk, v in c.comps.items() if not kk.startswith("_")},
                               extra_factor=round(extra_factor(c.comps), 4)), "risk_flags": c.flags,
            "angle": {"primary": c.angle.get("primary", "mixed"), "label": ANGLE_LABEL.get(c.angle.get("primary", ""), "Mixed"),
                      "vector": c.angle.get("vector", {})},
            "spoiler": _spoiler_rec(c),
            "llm_note": getattr(c, "llm_why", None),
            "transcript": transcript(c, eps)}


def _spoiler_rec(c):
    ev = getattr(c, "spoiler", None); pp = getattr(c, "premise_payoff", None)
    return {"risk": c.comps.get("spoiler_risk"),
            "reveal": None if ev is None else {"episode": ev.episode, "at": fmt_ts(ev.t), "kind": ev.kind, "text": ev.text,
                                               "logline_match": round(ev.logline_match, 2)},
            "premise_payoff": None if pp is None else {"episode": pp.episode, "at": fmt_ts(pp.t), "text": pp.text}}


def build_records(result, n=None, key="top"):
    eps = {e.number: e for e in result["episodes"]}
    pool = result[key] if n is None else result[key][:n]
    if result.get("llm_used") and key == "top":
        pool = list(pool)  # already in blended (system x LLM) order
    else:
        pool = sorted(pool, key=lambda c: -c.score)
    med = {k: statistics.median([c.comps[k] for c in pool]) for k in ("hook", "cliff", "standalone", "arc", "premise")} if pool else {}
    return [promo_record(c, i + 1, eps, med, result["show"]) for i, c in enumerate(pool)]


def build_portfolio(result):
    eps = {e.number: e for e in result["episodes"]}
    port = result.get("portfolio") or {}
    allc = [c for lst in port.values() for c in lst]
    if not allc:
        return []
    med = {k: statistics.median([c.comps[k] for c in allc]) for k in ("hook", "cliff", "standalone", "arc", "premise")}
    out = []
    for ang, lst in port.items():
        for c in lst:
            r = promo_record(c, len(out) + 1, eps, med, result["show"])
            r["portfolio_angle"] = ang
            out.append(r)
    return out


def write_outputs(result, out_dir, cfg, timings=None):
    os.makedirs(out_dir, exist_ok=True)
    top = build_records(result, key="top")
    longl = build_records(result, key="longlist")
    port = build_portfolio(result)
    prof = result.get("profile")
    rev = result.get("reveals")
    meta = {"tool": "PromoFinder", "version": __version__, "run_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "python": platform.python_version(), "show": result["show"], "n_episodes": len(result["episodes"]),
            "runtime_minutes": round(sum(e.duration for e in result["episodes"]) / 60, 2),
            "n_hook_moments": len(result["hooks"]), "n_cliff_moments": len(result["cliffs"]),
            "n_candidates": len(result["candidates"]),
            "arousal_mode": result.get("arousal_mode"), "delivery_tag_coverage": result.get("tag_coverage"), "timings_s": timings or {}, "config": cfg,
            "weights_used": (result.get("config_used") or cfg).get("weights"),
            "audience_profile": {"key": prof.key, "label": prof.label} if prof else {"key": "general", "label": "General audience"},
            "spoiler_tolerance": cfg.get("spoilers", {}).get("tolerance", "balanced"),
            "top_reveals": rev.summary(15) if rev is not None else [],
            "learned_weights": result.get("learned_weights"),
            "input_formats": result.get("input_formats", {}),
            "llm_used": result.get("llm_used"),
            "parse_warnings": {e.number: e.warnings for e in result["episodes"] if e.warnings}}
    with open(os.path.join(out_dir, "promos_top.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "promos": top}, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "promos_longlist.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "promos": longl}, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "promos_portfolio.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": {"show": meta["show"], "version": __version__}, "promos": port}, fh, indent=2, ensure_ascii=False)
    write_show_index(result, out_dir)
    for name, recs in (("promos_top.csv", top), ("promos_longlist.csv", longl)):
        with open(os.path.join(out_dir, name), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["rank", "score", "type", "duration_s", "segments", "hook_type", "hook", "cliff_type", "cliffhanger",
                        "why_it_works", "hook_c", "cliff_c", "standalone_c", "arc_c", "premise_c", "flags", "source",
                        "angle", "spoiler_risk"])
            for r in recs:
                w.writerow([r["rank"], r["score"], r["type"], r["duration_s"],
                            " + ".join(f"E{s['episode']} {s['start']}-{s['end']}" for s in r["segments"]),
                            r["hook"]["type"], r["hook"]["text"], r["cliffhanger"]["type"], r["cliffhanger"]["text"],
                            r["why_it_works"], r["components"]["hook"], r["components"]["cliff"], r["components"]["standalone"],
                            r["components"]["arc"], r["components"]["premise"], "; ".join(r["risk_flags"]),
                            " | ".join(f"{s['src_file']} L{s['src_lines'][0]}-{s['src_lines'][1]}" for s in r["segments"] if s["src_lines"]),
                            r["angle"]["label"], r["components"].get("spoiler_risk", "")])
    # raw moment-level scores (every legal cut point), for auditing
    with open(os.path.join(out_dir, "moments_hooks.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(["episode", "t", "timecode", "score", "pct", "text"])
        for m in result["hooks"]:
            w.writerow([m.ep, m.t, fmt_ts(m.t), round(m.score, 4), round(m.pct, 4), m.text[:200]])
    with open(os.path.join(out_dir, "moments_cliffs.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(["episode", "t", "timecode", "score", "pct", "payoff", "text"])
        for m in result["cliffs"]:
            w.writerow([m.ep, m.t, fmt_ts(m.t), round(m.score, 4), round(m.pct, 4), round(m.feats.get("c_payoff", 0), 4), m.text[-200:]])
    with open(os.path.join(out_dir, "promos_top.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown_report(result["show"], meta, top))
    from .report import html_report
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(html_report(result["show"], meta, top, longl))
    from .edl import write_cutlists
    write_cutlists(top, result["show"], out_dir, fps=cfg.get("fps", 30))
    with open(os.path.join(out_dir, "run_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, default=str)
    return top, longl, meta


def write_show_index(result, out_dir):
    """Parsed show (all blocks) + every scored cut point, so search and re-ranking work later without re-scoring."""
    from .formats import episode_to_json
    idx = {"show": result["show"], "version": __version__,
           "episodes": [episode_to_json(e) | {"src_file": e.src_file, "duration": e.duration} for e in result["episodes"]],
           "hooks": [[m.ep, round(m.t, 2), round(m.pct, 4)] for m in result["hooks"]],
           "cliffs": [[m.ep, round(m.t, 2), round(m.pct, 4)] for m in result["cliffs"]]}
    with open(os.path.join(out_dir, "show_index.json"), "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, separators=(",", ":"))


def markdown_report(show, meta, top):
    L = [f"# Promo candidates — {show}", "",
         f"PromoFinder v{meta['version']} · {meta['n_episodes']} episodes ({meta['runtime_minutes']} min) · "
         f"{meta['n_candidates']:,} candidate clips scored · run {meta['run_at']}", ""]
    for r in top:
        segs = " + ".join(f"**E{s['episode']} {s['start']}–{s['end']}**" for s in r["segments"])
        L += [f"## #{r['rank']} · {segs} · {r['duration_s']:.1f}s · score {r['score']:.3f}" + (f" · _{r['type']}_" if r['type'] != 'single' else ""),
              f"- **Hook ({r['hook']['type']}, {r['hook']['at']}):** {r['hook']['text']}",
              f"- **Cliffhanger ({r['cliffhanger']['type']}, {r['cliffhanger']['at']}):** {r['cliffhanger']['text']}",
              f"  - _Withheld next beat:_ {r['cliffhanger']['withheld_next_beat']}",
              f"- **Why it works:** {r['why_it_works']}",
              f"- **Rank:** {r['rank_reason']}",
              "- Components: " + ", ".join(f"{k} {v}" for k, v in r["components"].items()),
              f"- Angle: {r['angle']['label']} · spoiler risk {r['components'].get('spoiler_risk', 0)}",
              f"- Flags: {'; '.join(r['risk_flags']) or 'none'}",
              "- Source: " + "; ".join(f"`{s['src_file']}` lines {s['src_lines'][0]}–{s['src_lines'][1]}" for s in r["segments"] if s["src_lines"]), ""]
    return "\n".join(L)
