"""Command line: python -m promofinder.cli run <zip|dir|txt...> --out outputs/run"""
import argparse, os, sys, time, json
from .ingest import load_inputs
from .config import load_config
from .pipeline import PromoFinder
from .export import write_outputs


def _safe_console():
    """Windows consoles / redirected output may use cp1252: never crash on “quotes” or →."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _safe_console()
    ap = argparse.ArgumentParser(prog="promofinder", description="Find 20-60s promo moments in timestamped screenplays.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="process a show")
    r.add_argument("inputs", nargs="+", help=".zip, directory, or .txt files")
    r.add_argument("--out", default="outputs/run")
    r.add_argument("--config", default=None)
    r.add_argument("--top", type=int, default=None)
    r.add_argument("--llm", default=None, help="provider for optional re-ranking: anthropic | openai | none")
    r.add_argument("--llm-model", default=None)
    r.add_argument("--audience", default=None, help="general | romance | revenge | thriller | mystery | power | family | humor")
    r.add_argument("--spoilers", default=None, choices=["strict", "balanced", "off"], help="spoiler tolerance (default balanced)")
    r.add_argument("--no-learning", action="store_true", help="ignore weights learned from editor feedback")
    r.add_argument("--feedback", default="feedback/feedback.jsonl", help="editor feedback file used for learned weights")
    s = sub.add_parser("search", help="semantic search over a finished run: promofinder search outputs/run \"betrayal at the altar\"")
    s.add_argument("run_dir"); s.add_argument("query", nargs="+"); s.add_argument("-k", type=int, default=8)
    e = sub.add_parser("eval", help="check a run against its source screenplays")
    e.add_argument("run_dir"); e.add_argument("--source", nargs="+", required=True)
    e.add_argument("--labels", default=None); e.add_argument("--compare", default=None)
    lw = sub.add_parser("learn", help="fit ranking weights from editor feedback (votes + A/B comparisons)")
    lw.add_argument("feedback", nargs="?", default="feedback/feedback.jsonl")
    a = ap.parse_args(argv)
    if a.cmd == "search":
        from .search import search_run
        for h in search_run(a.run_dir, " ".join(a.query), k=a.k):
            clip = h.get("clip") or {}
            print(f"{h['score']:.3f} E{h['episode']} {h['at']}  {h['speaker'] or '-'}: {h['text'][:80]}")
            if clip:
                print(f"       promo-ready clip: E{clip['episode']} {clip['start']}-{clip['end']} ({clip['duration_s']}s)  why: {', '.join(h['matched'])}")
        return
    if a.cmd == "eval":
        from .evaluate import evaluate_run
        print(json.dumps(evaluate_run(a.run_dir, a.source, a.labels, a.compare), indent=2))
        return
    if a.cmd == "learn":
        from .preferences import learn_from_file
        print(json.dumps(learn_from_file(a.feedback), indent=2))
        return
    cfg = load_config(a.config)
    if a.audience:
        cfg["audience"] = a.audience
    if a.spoilers:
        cfg["spoilers"]["tolerance"] = a.spoilers
    if a.no_learning:
        cfg["learning"]["auto_apply"] = False
    if a.top:
        cfg["top_n"] = a.top
    if a.llm and a.llm != "none":
        cfg["llm"].update(enabled=True, provider=a.llm, model=a.llm_model or cfg["llm"].get("model", ""))
    t0 = time.time()
    show, eps = load_inputs(a.inputs)
    fmts = {}
    for e in eps:
        fmts[getattr(e, "format", "kuku")] = fmts.get(getattr(e, "format", "kuku"), 0) + 1
    if not eps:
        sys.exit("No timestamped screenplay files found in the inputs.")
    t1 = time.time()
    learned = None
    if cfg["learning"].get("auto_apply") and os.path.exists(a.feedback):
        from .preferences import learned_weights_for
        learned = learned_weights_for(a.feedback, cfg)
        if learned and learned.get("applied"):
            cfg["weights"] = learned["weights"]
    res = PromoFinder(cfg).run(show, eps)
    res["learned_weights"] = learned
    res["input_formats"] = fmts
    t2 = time.time()
    timings = {"load_parse": round(t1 - t0, 2), "score_rank": round(t2 - t1, 2), "stages": res.get("timings", {})}
    if cfg["llm"]["enabled"]:
        from .llm import rerank_with_llm
        res = rerank_with_llm(res, cfg)
        timings["llm_rerank"] = round(time.time() - t2, 2)
    top, longl, meta = write_outputs(res, a.out, cfg, timings)
    print(f"{show}: {len(eps)} episodes, {meta['n_candidates']:,} candidates in {t2 - t0:.1f}s -> {a.out}")
    for p in top:
        segs = " + ".join(f"E{s['episode']} {s['start']}-{s['end']}" for s in p["segments"])
        print(f"#{p['rank']:>2} {p['score']:.3f} {segs:32s} {p['duration_s']:5.1f}s | {p['hook']['text'][:60]} ... {p['cliffhanger']['text'][:50]}")


if __name__ == "__main__":
    main()
