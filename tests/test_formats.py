"""Format adapters: every supported format must parse to the same blocks as the production format
(for the information it carries) and produce valid promos end to end."""
import io, json, os, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_core import make_episode, LINES
from promofinder.parser import parse_screenplay, fmt_ts
from promofinder.formats import parse_any, episode_to_json, parse_inline, parse_subtitles
from promofinder.ingest import load_bytes
from promofinder.config import load_config
from promofinder.pipeline import PromoFinder, valid_cut

REF = parse_screenplay(make_episode(2, LINES), "episode-002.txt")


def key(b, tags=True):
    return (round(b.start, 2), round(b.end, 2), b.kind, b.speaker, tuple(b.tags) if tags else (), b.text)


def to_inline(ep, tags=True):
    L = [f"EPISODE NUMBER: Episode {ep.number}", f"EPISODE LOGLINE: {ep.logline}", "", "SCENE 01"]
    for b in ep.blocks:
        who = {"camera": "CAMERA", "action": "ACTION", "sfx": "SOUND FX"}.get(b.kind, b.speaker)
        if b.kind == "dialogue" and b.tags and tags:
            who += f" ({', '.join(b.tags)})"
        L.append(f"[{fmt_ts(b.start)} - {fmt_ts(b.end)}] {who}: {b.text}")
    return "\n".join(L)


def to_srt(ep, vtt=False):
    def t(x):
        h, r = divmod(x, 3600); m, s = divmod(r, 60)
        v = f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
        return v if vtt else v.replace(".", ",")
    L = ["WEBVTT", ""] if vtt else []
    k = 1
    for b in ep.blocks:
        if b.kind != "dialogue":
            continue
        L += [str(k), f"{t(b.start)} --> {t(b.end)}", f"{b.speaker}: {b.text}", ""]; k += 1
    return "\n".join(L)


def test_production_format_is_detected_and_unchanged():
    e = parse_any(make_episode(2, LINES), "episode-002.txt")
    assert e.format == "kuku" and [key(b) for b in e.blocks] == [key(b) for b in REF.blocks]


def test_json_roundtrip_is_lossless():
    e = parse_any(json.dumps(episode_to_json(REF)), "episode-002.json")
    assert e.format == "json" and [key(b) for b in e.blocks] == [key(b) for b in REF.blocks]
    assert e.number == 2 and e.logline == REF.logline


def test_inline_format_matches():
    e = parse_any(to_inline(REF), "episode-002.txt")
    assert e.format == "inline" and [key(b) for b in e.blocks] == [key(b) for b in REF.blocks]
    assert {b.scene for b in e.blocks} == {1}


def test_inline_start_only_timestamps():
    txt = "[00:01.0] MARA (Cold): Who are you?\n[00:03.5] THEO: Nobody.\n[00:05.0] ACTION: She slaps him."
    e = parse_inline(txt, "episode-004.txt")
    assert [(b.kind, b.start, b.end) for b in e.blocks] == [("dialogue", 1.0, 3.5), ("dialogue", 3.5, 5.0), ("action", 5.0, 7.5)]
    assert e.blocks[0].tags == ["cold"] and e.number == 4


def test_loose_production_variants():
    t = make_episode(2, LINES).replace("**", "")              # no bold
    e = parse_any(t, "episode-002.txt")
    assert [key(b) for b in e.blocks] == [key(b) for b in REF.blocks]
    t2 = "\n".join(f"{('CAMERA' if b.kind == 'camera' else 'ACTION' if b.kind == 'action' else b.speaker + ' (' + ', '.join(b.tags) + ')')}: "
                   f"[{fmt_ts(b.start)} --> {fmt_ts(b.end)}]\n{b.text}\n" for b in REF.blocks)
    e2 = parse_any(t2, "episode-002.txt")
    assert [key(b) for b in e2.blocks] == [key(b) for b in REF.blocks]


def test_srt_and_vtt():
    want = [key(b, tags=False) for b in REF.blocks if b.kind == "dialogue"]
    for vtt in (False, True):
        e = parse_any(to_srt(REF, vtt), "episode-002." + ("vtt" if vtt else "srt"))
        assert e.format == "subtitles"
        assert [key(b, tags=False) for b in e.blocks] == want


def test_subtitle_sound_cues_and_unlabelled_speakers():
    s = "1\n00:00:01,000 --> 00:00:02,000\n[door slams]\n\n2\n00:00:02,500 --> 00:00:04,000\n- Where were you?\n\n3\n00:00:04,000 --> 00:00:05,000\n[MARA] Out.\n"
    e = parse_subtitles(s, "ep-7.srt")
    assert [b.kind for b in e.blocks] == ["sfx", "dialogue", "dialogue"]
    assert e.blocks[0].text == "door slams" and e.blocks[2].speaker == "MARA" and e.number == 7


def test_mixed_format_zip_runs_end_to_end():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(1, 7):
            ep = parse_screenplay(make_episode(i, LINES), f"episode-{i:03d}.txt")
            if i % 3 == 0:
                z.writestr(f"Show/episode-{i:03d}.json", json.dumps(episode_to_json(ep)))
            elif i % 3 == 1:
                z.writestr(f"Show/episode-{i:03d}.txt", to_inline(ep))
            else:
                z.writestr(f"Show/episode-{i:03d}.txt", make_episode(i, LINES))
    rep = {}
    show, eps = load_bytes([("pack.zip", buf.getvalue())], report=rep)
    assert [e.number for e in eps] == [1, 2, 3, 4, 5, 6] and set(rep["formats"]) == {"inline", "kuku", "json"}
    r = PromoFinder(load_config(overrides={"top_n": 4})).run(show, eps)
    E = {e.number: e for e in eps}
    assert r["top"]
    for c in r["top"]:
        assert 20 - 1e-6 <= c.dur <= 60 + 1e-6
        assert all(valid_cut(E[s.episode], s.start) and valid_cut(E[s.episode], s.end) for s in c.segments)


def test_garbage_is_skipped_not_crashing():
    rep = {}
    show, eps = load_bytes([("notes.txt", b"just some notes\nno timings here"), ("bad.json", b"{not json"),
                            ("episode-001.txt", make_episode(1, LINES).encode())], report=rep)
    assert [e.number for e in eps] == [1] and set(rep["skipped"]) == {"notes.txt", "bad.json"}
