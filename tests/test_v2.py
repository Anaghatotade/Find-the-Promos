"""v2 features: spoiler model, angles/profiles/portfolio, search, preference learning, LLM layer, evaluation.
Synthetic screenplays only (the confidential pack is never needed)."""
import json, math, os, sys, tempfile, threading, http.server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pytest
from test_core import make_episode, LINES, show_items
from promofinder.ingest import load_bytes
from promofinder.config import load_config
from promofinder.pipeline import PromoFinder, valid_cut
from promofinder.parser import parse_screenplay, canon_speaker
from promofinder.spoilers import RevealIndex, spoiler_penalty
from promofinder.profiles import angle_vector, PROFILES, portfolio
from promofinder.export import write_outputs
from promofinder import preferences as P

REVEAL_LINES = LINES[:6] + [("THUG", "Terrified", "Voss paid us! Victor Voss paid us to burn it!"),
                            ("NORA", "Stunned", "You are my real father?"), ("DRIVER", "Low", "I am the rightful duke.")] + LINES[9:]


def reveal_show(n=6, title="The Bride Who Married a Duke"):
    items = [(f"episode-{i:03d}.txt", make_episode(i, LINES if i <= 4 else REVEAL_LINES).encode()) for i in range(1, n + 1)]
    return load_bytes(items, title)


@pytest.fixture(scope="module")
def run_dir():
    show, eps = reveal_show(8)
    cfg = load_config(overrides={"top_n": 5, "longlist_n": 20})
    r = PromoFinder(cfg).run(show, eps)
    d = tempfile.mkdtemp()
    write_outputs(r, d, cfg)
    return d, r, eps


# ---------------------------------------------------------------- spoilers
def test_reveal_index_finds_culprit_and_respects_free_episodes_and_premise():
    show, eps = reveal_show(6)
    R = RevealIndex(show, eps, free_episodes=3)
    kinds = {(e.episode, e.kind) for e in R.events if not e.premise and e.severity > 0.3}
    assert (5, "culprit") in kinds and not any(ep <= 3 for ep, _ in kinds)          # nothing flagged in free episodes
    duke = [e for e in R.events if "duke" in e.text.lower()]
    assert duke and all(e.premise and e.severity == 0 for e in duke)               # the title promises a duke: premise payoff


def test_known_relationship_is_not_a_reveal():
    lines = [("NORA", "Warm", "You are my father, and I love you.")] * 15
    items = [(f"episode-{i:03d}.txt", make_episode(i, lines).encode()) for i in range(1, 6)]
    show, eps = load_bytes(items, "Show")
    R = RevealIndex(show, eps)
    assert all(e.severity < 0.4 for e in R.events)


def test_spoiler_penalty_tolerance():
    assert spoiler_penalty(0.2, "strict") == 1.0                                    # weak cues never bite
    assert spoiler_penalty(1.0, "off") == 1.0
    assert spoiler_penalty(1.0, "strict") < spoiler_penalty(1.0, "balanced") < 1.0


def test_spoiler_tolerance_changes_ranking_monotonically():
    show, eps = reveal_show(8)
    def mean_risk(tol):
        r = PromoFinder(load_config(overrides={"top_n": 6, "spoilers": {"tolerance": tol}})).run(show, eps)
        return np.mean([c.comps.get("spoiler_risk", 0) for c in r["top"]]) if tol != "off" else None
    assert mean_risk("strict") <= mean_risk("balanced") + 1e-9


# ---------------------------------------------------------------- angles / profiles
def test_angle_vector_and_profile_bounds(run_dir):
    _, r, _ = run_dir
    ep = parse_screenplay(make_episode(1, [("A", "Tender", "I love you, my darling."), ("B", "Loving", "Kiss me.")] * 3), "e1.txt")
    v = angle_vector([b for b in ep.blocks if b.kind == "dialogue"])
    assert next(iter(v)) == "romance" and abs(sum(v.values()) - 1) < 0.01
    for p in PROFILES.values():
        for c in r["candidates"][:200]:
            f = p.factor(c)
            assert 0.85 - 1e-9 <= f <= 1.15 + 1e-9


def test_portfolio_has_no_overlaps(run_dir):
    _, r, _ = run_dir
    port = [c for lst in r["portfolio"].values() for c in lst]
    for i, a in enumerate(port):
        for b in port[i + 1:]:
            assert not any(x.episode == y.episode and x.start < y.end - 0.5 and y.start < x.end - 0.5 for x in a.segments for y in b.segments)


def test_profile_run_changes_weights_not_constraints():
    show, eps = reveal_show(6)
    r = PromoFinder(load_config(overrides={"top_n": 5, "audience": "thriller"})).run(show, eps)
    assert r["config_used"]["weights"]["cliff"] > 1.0 and r["top"]
    assert all(20 - 1e-6 <= c.dur <= 60 + 1e-6 for c in r["top"])


def test_canon_speaker():
    assert canon_speaker("LADY MARA") == canon_speaker("Mara") == "MARA"
    assert canon_speaker("THE") == "THE"


# ---------------------------------------------------------------- exports + search
def test_new_exports_exist_and_validate(run_dir):
    d, r, eps = run_dir
    for f in ("promos_portfolio.json", "show_index.json"):
        assert os.path.exists(os.path.join(d, f))
    top = json.load(open(os.path.join(d, "promos_top.json"), encoding="utf-8"))
    p0 = top["promos"][0]
    assert {"angle", "spoiler"} <= set(p0) and "extra_factor" in p0["components"]
    from promofinder.evaluate import hard_constraints
    hc = hard_constraints(top["promos"], eps, run_dir=d)
    assert hc["all_ok"], hc


def test_search_returns_legal_clips(run_dir):
    d, _, eps = run_dir
    from promofinder.search import search_run, expand
    E = {e.number: e for e in eps}
    hits = search_run(d, "who paid the attackers", k=5)
    assert hits and hits[0]["episode"] >= 5 and "paid" in hits[0]["text"].lower()
    for h in hits:
        c = h["clip"]
        if c:
            assert 20 - 1e-6 <= c["end_s"] - c["start_s"] <= 60 + 1e-6
            assert c["start_s"] <= h["t"] + 1e-6 and valid_cut(E[c["episode"]], c["start_s"]) and valid_cut(E[c["episode"]], c["end_s"])
    terms, concepts, tags, inten = expand("strong emotional betrayal")
    assert "betrayal" in concepts and "emotional" in concepts and inten == 1 and "strong" not in terms


def test_search_paraphrase_via_synonyms():
    from promofinder.search import expand, stem
    terms, *_ = expand("she is locked in jail")
    assert {stem("dungeon"), stem("cell"), stem("chained")} <= set(terms)       # paraphrase reaches the script's words
    assert terms[stem("jail")] == 1.0 and terms[stem("dungeon")] < 1.0           # exact words outrank expansions


# ---------------------------------------------------------------- preference learning
def _rand_comps(rng):
    return {k: float(rng.uniform(0.2, 1.0)) for k in P.KEYS} | {"extra_factor": 1.0}


def test_bradley_terry_recovers_preferred_component():
    rng = np.random.RandomState(0)
    true = {"hook": 0.2, "cliff": 3.0, "standalone": 0.2, "arc": 0.2, "premise": 0.2}
    pairs = []
    for _ in range(300):
        a, b = _rand_comps(rng), _rand_comps(rng)
        ua = sum(true[k] * math.log(a[k]) for k in P.KEYS); ub = sum(true[k] * math.log(b[k]) for k in P.KEYS)
        win = rng.rand() < 1 / (1 + math.exp(-(ua - ub)))
        pairs.append((P.feat(a), P.feat(b), 1.0, 1.0) if win else (P.feat(b), P.feat(a), 1.0, 1.0))
    w, info = P.fit_weights(pairs, prior_strength=1.0)
    assert max(w, key=w.get) == "cliff" and all(v >= 0 for v in w.values())


def test_votes_become_pairs_and_last_vote_wins(tmp_path):
    f = str(tmp_path / "fb.jsonl")
    c1, c2 = {"hook": .9, "cliff": .9, "standalone": .5, "arc": .5, "premise": .5}, {"hook": .3, "cliff": .3, "standalone": .5, "arc": .5, "premise": .5}
    P.append_feedback(f, {"type": "vote", "run": "r", "show": "s", "id": "a", "vote": "down", "components": c1})
    P.append_feedback(f, {"type": "vote", "run": "r", "show": "s", "id": "a", "vote": "up", "components": c1})
    P.append_feedback(f, {"vote": "down", "run": "r", "show": "s", "id": "b", "components": c2})          # legacy line format
    pairs = P.to_pairs(P.read_feedback(f))
    assert len(pairs) == 1 and np.allclose(pairs[0][0], P.feat(c1))


def test_learning_gate_and_rescore(run_dir, tmp_path):
    d, _, _ = run_dir
    recs = json.load(open(os.path.join(d, "promos_longlist.json"), encoding="utf-8"))["promos"]
    cfg = load_config()
    f = str(tmp_path / "fb.jsonl")
    assert not P.learned_weights_for(f, cfg)["applied"]
    R = P.rescore(recs, cfg["weights"])
    assert max(abs(r["score"] - next(x for x in recs if x["id"] == r["id"])["score"]) for r in R) < 0.002
    seen = set()
    for i in range(cfg["learning"]["min_judgments"]):
        a, b, p = P.next_pair(sorted(recs, key=lambda r: -r["score"]), f, cfg, run="r")
        key = frozenset((a["id"], b["id"])); assert key not in seen; seen.add(key)
        P.append_feedback(f, {"type": "pair", "run": "r", "a": {"id": a["id"], "components": a["components"]},
                              "b": {"id": b["id"], "components": b["components"]}, "winner": "a"})
    st = P.learned_weights_for(f, cfg)
    assert st["applied"] and abs(sum(st["weights"].values()) - P.TOTAL) < 0.01


def test_measured_performance_is_separate_and_learnable(run_dir, tmp_path):
    d, _, _ = run_dir
    recs = json.load(open(os.path.join(d, "promos_longlist.json"), encoding="utf-8"))["promos"][:3]
    csvp = tmp_path / "perf.csv"
    csvp.write_text("id,impressions,clicks\n" + "\n".join(f"{r['id']},{5000},{50 * (i + 1)}" for i, r in enumerate(recs)) + "\nunknown,10,1\n")
    f = str(tmp_path / "fb.jsonl")
    assert P.import_performance(str(csvp), f, recs)["imported"] == 3
    rows = P.read_feedback(f)
    assert all(r["type"] == "performance" for r in rows) and len(P.performance_pairs(rows)) == 3


# ---------------------------------------------------------------- LLM layer
class _Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        sysm = body.get("system") or body["messages"][0]["content"]
        ans = json.dumps({"winner": "A", "confidence": 3, "reason": "x"}) if "winner" in sysm else \
            json.dumps({"hook": 4, "cliffhanger": 4, "standalone": 3, "spoiler_safe": 5, "overall": 4, "why": "w", "risk": ""})
        out = {"content": [{"type": "text", "text": ans}]} if self.path.endswith("/messages") else {"choices": [{"message": {"content": ans}}]}
        b = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


def test_http_llm_client_both_styles_cache_and_position_bias(tmp_path, monkeypatch):
    from promofinder.llm import HTTPClient, judge_pair
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test"); monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    try:
        for prov in ("openai_compatible", "anthropic"):
            c = HTTPClient(prov, "m", f"http://127.0.0.1:{srv.server_port}", cache_dir=str(tmp_path / prov))
            assert "hook" in c.complete("score it", "u") and c.complete("score it", "u") and c.calls == 1 and c.cache_hits == 1
            v = judge_pair(c, "one", "two")       # the fake always answers "A": a pure position bias
            assert v["winner"] == "tie" and not v["consistent"]
    finally:
        srv.shutdown()


def test_llm_needs_key_and_never_leaks_it(monkeypatch, tmp_path):
    from promofinder.llm import HTTPClient, llm_status, load_dotenv
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError):
        HTTPClient("groq", cache_dir=str(tmp_path))
    envf = tmp_path / ".env"; envf.write_text("# comment\nexport GROQ_API_KEY='gsk-secret'\n")
    assert load_dotenv(str(envf)) == ["GROQ_API_KEY"]
    st = llm_status({"llm": {"provider": "groq"}})
    assert st["ready"] and "gsk-secret" not in json.dumps(st)


def test_mock_llm_rerank_end_to_end(run_dir):
    _, r, _ = run_dir
    from promofinder.llm import rerank_with_llm, MockClient
    cfg = load_config(overrides={"top_n": 5, "llm": {"enabled": True, "provider": "mock", "rerank_top_k": 10}})
    out = rerank_with_llm(dict(r), cfg, MockClient())
    u = out["llm_used"]
    assert u["scored"] == 10 and u["errors"] == 0 and len(out["top"]) == 5
    assert u["pairwise_swaps"] + u["pairwise_inconsistent"] <= 4


# ---------------------------------------------------------------- evaluation harness
def test_evaluate_agreement_and_spoiler_labels(run_dir):
    d, r, _ = run_dir
    from promofinder.evaluate import agreement, spoiler_exposure, _load
    top = _load(d)["promos"]
    a = agreement(top, top)
    assert a["exact_overlap_frac"] == 1.0 and a["same_top1"]
    labels = {"reveals": [{"episode": 5, "class": "twist", "what": "x", "keys": [["paid"]]}]}
    sx = spoiler_exposure(top, labels)
    assert sx["twist_or_resolution_shown"] == sum(1 for p in top if {5, 6} & {s["episode"] for s in p["segments"]}
                                                   and "paid" in " ".join(l["text"] for l in p["transcript"]).lower())
