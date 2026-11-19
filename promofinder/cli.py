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
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if a.top:
        cfg["top_n"] = a.top
    if a.llm and a.llm != "none":
        cfg["llm"].update(enabled=True, provider=a.llm, model=a.llm_model or cfg["llm"].get("model", ""))
    t0 = time.time()
    show, eps = load_inputs(a.inputs)
    if not eps:
        sys.exit("No timestamped screenplay files found in the inputs.")
    t1 = time.time()
    res = PromoFinder(cfg).run(show, eps)
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
