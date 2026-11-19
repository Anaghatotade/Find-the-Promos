"""Unit tests: parser, cut legality, ingestion, scoring invariants, LLM plumbing, weight learning.
Uses a tiny synthetic screenplay (not the confidential input pack)."""
import io, json, os, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from promofinder.parser import parse_screenplay, fmt_ts
from promofinder.ingest import load_bytes
from promofinder.config import load_config
from promofinder.pipeline import PromoFinder, valid_cut
from promofinder.llm import MockClient, rerank_with_llm, parse_json
from promofinder.learn_weights import fit


def make_episode(n, lines):
    out = [f"EPISODE NUMBER: Episode {n}", f"EPISODE LOGLINE: A bride is betrayed at the altar {n}.", "", "--- SCRIPT START ---", "",
           "SCENE 01", "Scene heading: INT. CHURCH – DAY", "Scene start: 00:00.00", f"Scene end: {fmt_ts(len(lines) * 4.0)}", "",
           "Actions and dialogue:", ""]
    t = 0.0
    for spk, tag, txt in lines:
        out += ["**CAMERA:**", f"Start: ({fmt_ts(t)}) | End: ({fmt_ts(t + 4.0)})", "Close-up on the speaker.", ""]
        if spk == "ACTION":
            out += ["**ACTION:**", f"Start: ({fmt_ts(t + 0.2)}) | End: ({fmt_ts(t + 3.8)})", txt, ""]
        else:
            out += [f"**{spk} ({tag}):**", f"Start: ({fmt_ts(t + 0.5)}) | End: ({fmt_ts(t + 3.5)})", f"\"{txt}\"", ""]
        t += 4.0
    out += ["--- SCRIPT END ---"]
    return "\n".join(out)

LINES = [("NORA", "Shaken", "Theo? Why is your ring on her finger?"), ("VERA", "Smug", "Because he chose me."),
         ("NORA", "Screaming", "You promised me forever!"), ("ACTION", "", "Vera shoves Nora against the table."),
         ("THEO", "Cold", "Plans change."), ("NORA", "Desperate", "Mom, please say something."),
         ("MOTHER", "Quiet", "..."), ("AUNT", "Cruel", "You are a disgrace to this family!"),
         ("NORA", "Trembling", "So what am I to you?"), ("VERA", "Venomous", "The spare nobody wanted."),
         ("DRIVER", "Low, thunderous", "Step away from her."), ("NORA", "Whispering", "Who are you?"),
         ("DRIVER", "Solemn", "Someone who keeps his promises."), ("NORA", "Gentle", "Thank you."),
         ("DRIVER", "Warm", "Let's go.")]


def show_items(n_eps=6):
    return [(f"episode-{i:03d}.txt", make_episode(i, LINES).encode()) for i in range(1, n_eps + 1)]


def test_parser_blocks_and_tags():
    ep = parse_screenplay(make_episode(3, LINES), "episode-003.txt")
    assert ep.number == 3 and not ep.warnings
    d = [b for b in ep.blocks if b.kind == "dialogue"]
    assert len(d) == 14 and d[0].speaker == "NORA" and d[0].tags == ["shaken"]
    assert d[0].text == "Theo? Why is your ring on her finger?" and d[0].src_line > 0
    assert ep.duration == 60.0


def test_header_variants_and_crlf():
    t = make_episode(2, LINES).replace("Start:", "start:").replace("\n", "\r\n")
    ep = parse_screenplay(t, "x.txt")
    assert len([b for b in ep.blocks if b.kind == "dialogue"]) == 14


def test_zip_ingest_and_ordering():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in reversed(show_items(3)):
            z.writestr("My Show/" + n, b)
        z.writestr("__MACOSX/._junk.txt", b"junk")
    show, eps = load_bytes([("pack.zip", buf.getvalue())])
    assert show == "My Show" and [e.number for e in eps] == [1, 2, 3]


def test_pipeline_invariants():
    show, eps = load_bytes(show_items(6), "Test Show")
    cfg = load_config(overrides={"top_n": 5})
    r = PromoFinder(cfg).run(show, eps)
    E = {e.number: e for e in eps}
    assert r["top"], "should find promos"
    for c in r["candidates"]:
        assert 20 - 1e-6 <= c.dur <= 60 + 1e-6
        for sg in c.segments:
            assert valid_cut(E[sg.episode], sg.start) and valid_cut(E[sg.episode], sg.end)
    # no overlapping picks
    for i, a in enumerate(r["top"]):
        for b in r["top"][i + 1:]:
            assert not any(s.episode == t.episode and s.start < t.end - 0.5 and t.start < s.end - 0.5 for s in a.segments for t in b.segments)


def test_llm_rerank_with_mock_never_breaks():
    show, eps = load_bytes(show_items(6), "Test Show")
    cfg = load_config(overrides={"top_n": 3, "llm": {"enabled": True, "provider": "mock", "rerank_top_k": 6}})
    r = PromoFinder(cfg).run(show, eps)
    r = rerank_with_llm(r, cfg, MockClient())
    assert len(r["top"]) == 3 and r["llm_used"]["scored"] > 0
    assert parse_json("noise {\"a\": 1} noise") == {"a": 1} and parse_json("garbage") == {}


def test_learn_weights_recovers_signal():
    import random
    rnd = random.Random(0); rows = []
    for i in range(200):
        c = {k: rnd.uniform(0.05, 1) for k in ("hook", "cliff", "standalone", "arc", "premise")}
        rows.append({"id": i, "vote": "up" if c["hook"] * c["cliff"] > 0.3 else "down", "components": c})
    W, msg = fit(rows)
    assert msg == "ok" and W["hook"] > W["premise"] and W["cliff"] > W["arc"]
    assert fit(rows[:5])[0] is None


def test_stability_and_answer_open_flag():
    show, eps = load_bytes(show_items(6), "Test Show")
    r = PromoFinder(load_config(overrides={"top_n": 4})).run(show, eps)
    for c in r["top"]:
        assert 0.0 <= c.comps["stability"] <= 1.0
    assert r["arousal_mode"] == "tags" and r["tag_coverage"] > 0.9


def test_tagfree_mode_auto_switches():
    import re as _re
    items = [(n, _re.sub(rb" \([^)]*\):\*\*", b":**", b)) for n, b in show_items(6)]
    show, eps = load_bytes(items, "No Tags")
    assert all(not b.tags for e in eps for b in e.blocks)
    r = PromoFinder(load_config(overrides={"top_n": 3})).run(show, eps)
    assert r["arousal_mode"] == "fallback" and r["top"]


def test_edl_roundtrip(tmp_path):
    from promofinder.export import write_outputs
    from promofinder.edl import parse_edl
    show, eps = load_bytes(show_items(6), "Test Show")
    cfg = load_config(overrides={"top_n": 3})
    top, _, _ = write_outputs(PromoFinder(cfg).run(show, eps), str(tmp_path), cfg)
    for p in top:
        ev = parse_edl(open(tmp_path / "edl" / f"promo_{p['rank']:02d}.edl").read())
        assert len(ev) == len(p["segments"])
        for e, s in zip(ev, p["segments"]):
            assert abs(e["src_in"] - s["start_s"]) < 1 / 30 + 1e-6 and abs((e["src_out"] - e["src_in"]) - s["duration_s"]) < 1 / 30 + 1e-6
            assert e["reel"] == f"E{s['episode']:03d}"
        assert abs(sum(e["rec_out"] - e["rec_in"] for e in ev) - p["duration_s"]) < 2 / 30
    assert (tmp_path / "cutlist_nle.csv").exists()


def test_edl_is_ascii():
    from promofinder.edl import promo_edl
    p = {"rank": 1, "segments": [{"episode": 1, "start_s": 1.0, "end_s": 21.5, "src_file": "e.txt", "src_lines": [1, 9]}],
         "hook": {"text": "Nora: “Theo?” → “Why?”"}, "cliffhanger": {"text": "Vera: “Wait…”"}}
    txt = promo_edl(p, "Show — Name")
    txt.encode("ascii")
    assert '"Theo?" -> "Why?"' in txt and "Wait..." in txt


def test_progress_reports_each_hook_fold_and_never_goes_back():
    show, eps = load_bytes(show_items(6), "Test Show")
    seen = []
    PromoFinder(load_config(overrides={"top_n": 3})).run(show, eps, progress=lambda st, fr: seen.append((st, fr)))
    labels = [s for s, _ in seen]
    assert any("model 1 of 5" in s for s in labels) and any("model 5 of 5" in s for s in labels)
    fr = [f for _, f in seen]
    assert fr == sorted(fr) and 0 < fr[0] and fr[-1] <= 1.0


def test_zip_loads_without_cp437_codec():
    # some hosted Pythons cannot load cp437, which zipfile uses for non-UTF-8 names
    import subprocess, sys, textwrap
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = textwrap.dedent("""
        import sys, importlib.abc
        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "encodings.cp437": raise ImportError("blocked")
        sys.meta_path.insert(0, Block())
        from promofinder.ingest import load_bytes
        show, eps = load_bytes([("s.zip", open("samples/the_cleaner_was_the_heiress.zip", "rb").read())])
        assert len(eps) > 0
        print("ok")
    """)
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr
