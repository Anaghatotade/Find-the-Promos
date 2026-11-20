"""Web-app reliability tests: every bad input gets a friendly page, never a 500;
valid uploads produce ranked promos; outputs survive a non-UTF-8 OS default encoding."""
import io, os, subprocess, sys, time, zipfile
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_core import make_episode, LINES

os.environ["PROMOFINDER_PRECOMPUTE_DEMO"] = "0"   # tests trigger the demo explicitly
import app as A


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "RUNS", str(tmp_path / "runs")); os.makedirs(A.RUNS)
    monkeypatch.setattr(A, "FB", str(tmp_path / "fb")); os.makedirs(A.FB)
    monkeypatch.setattr(A, "DEMO_DIR", str(tmp_path / "demo_run"))
    monkeypatch.setattr(A, "PREBUILT_DEMO", str(tmp_path / "no_prebuilt" / "demo_run"))   # tests opt in explicitly
    with A.JOBS_LOCK:
        A.JOBS.clear()
    return A.app.test_client()


def zipof(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files:
            z.writestr(n, d)
    return b.getvalue()


def show_zip(n=6):
    return zipof([(f"My Show/episode-{i:03d}.txt", make_episode(i, LINES)) for i in range(1, n + 1)])


def post(client, files, **form):
    data = {"files": [(io.BytesIO(d), fn) for fn, d in files], "funnel": "on", **form}
    return client.post("/run", data=data, content_type="multipart/form-data")


def wait_job(client, r, timeout=120):
    """Follow the background job started by POST /run; return its final status dict."""
    import time
    assert r.status_code == 302 and "/job/" in r.headers["Location"], r.status_code
    jid = r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    assert client.get(f"/job/{jid}").status_code in (200, 302)
    t = time.time(); seen = set()
    while time.time() - t < timeout:
        st = client.get(f"/job/{jid}/status").get_json()
        seen.add(st["stage"])
        assert 0.0 <= st["frac"] <= 1.0
        if st["status"] in ("done", "error"):
            return jid, st, seen
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_valid_zip_upload_produces_ranked_promos(client):
    r = post(client, [("show.zip", show_zip())], top="5")
    jid, st, stages = wait_job(client, r)
    assert st["status"] == "done" and len(stages) >= 2          # progress stages were reported
    assert client.get(f"/job/{jid}").headers["Location"].endswith(f"/r/{st['rid']}")
    page = client.get(f"/r/{st['rid']}")
    assert page.status_code == 200 and "Promo candidates" in page.get_data(as_text=True)
    rid = st["rid"]
    for f in ("promos_top.json", "promos_top.csv", "cutlist_nle.csv", "promos_top.md", "promos_longlist.csv"):
        assert client.get(f"/r/{rid}/{f}").status_code == 200
    assert client.get(f"/r/{rid}/edl.zip").status_code == 200
    assert client.get("/").status_code == 200 and "My Show" in client.get("/").get_data(as_text=True)


def test_valid_txt_files_upload(client):
    r = post(client, [(f"episode-{i:03d}.txt", make_episode(i, LINES).encode()) for i in (1, 2, 3)])
    assert wait_job(client, r)[1]["status"] == "done"


@pytest.mark.parametrize("files,expect", [
    ([], "No file selected"),
    ([("notes.pdf", b"%PDF-1.4")], "Unsupported file type"),
    ([("bad.zip", b"PK\x03\x04garbage")], "not a valid ZIP"),
    ([("x.zip", zipof([("readme.md", b"hi")]))], "No screenplay found"),
    ([("p.txt", b"Once upon a time there was a duke.")], "No screenplay found"),
    ([("e.txt", b"")], "No screenplay found"),
    ([("episode-001.txt", make_episode(1, LINES[:3]).encode())], "Too short"),
])
def test_bad_inputs_get_friendly_pages_not_500(client, files, expect):
    r = post(client, files)
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and expect in body and "Traceback" not in body and "Back to upload" in body


def test_bad_number_field(client):
    r = post(client, [("show.zip", show_zip())], top="abc")
    assert r.status_code == 400 and "whole number" in r.get_data(as_text=True)


def test_single_episode_works(client):
    r = post(client, [("episode-001.txt", make_episode(1, LINES).encode())])
    assert wait_job(client, r)[1]["status"] == "done"


def test_duplicates_and_notes_banner(client):
    ep = make_episode(1, LINES).encode()
    r = post(client, [("a/episode-001.txt", ep), ("b/episode-001.txt", ep), ("episode-002.txt", make_episode(2, LINES).encode()),
                      ("cover.pdf", b"%PDF")])
    _, st, _ = wait_job(client, r)
    page = client.get(f"/r/{st['rid']}").get_data(as_text=True)
    assert "duplicate file ignored" in page and "ignored (unsupported file type): cover.pdf" in page


def test_unknown_run_and_unexpected_errors_are_friendly(client, monkeypatch):
    assert client.get("/r/does-not-exist").status_code == 404
    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(A.PromoFinder, "run", boom)
    jid, st, _ = wait_job(client, post(client, [("show.zip", show_zip())]))
    assert st["status"] == "error"
    r = client.get(f"/job/{jid}/error"); body = r.get_data(as_text=True)
    assert r.status_code == 500 and "error id" in body and "synthetic failure" not in body
    assert client.get("/job/nope/status").status_code == 404 and client.get("/job/nope").status_code == 404


def test_outputs_survive_non_utf8_default_encoding(tmp_path):
    """Regression for the Windows cp1252 crash: run export with an ASCII default encoding."""
    script = (f"import sys; sys.path.insert(0, {ROOT!r}); sys.path.insert(0, {os.path.join(ROOT, 'tests')!r})\n"
              "import locale; assert locale.getpreferredencoding(False).lower() not in ('utf-8','utf8')\n"
              "from test_core import show_items\nfrom promofinder.ingest import load_bytes\n"
              "from promofinder.config import load_config\nfrom promofinder.pipeline import PromoFinder\n"
              "from promofinder.export import write_outputs\n"
              "show, eps = load_bytes(show_items(4), 'Show — “quotes”')\ncfg = load_config(overrides={'top_n': 3})\n"
              f"write_outputs(PromoFinder(cfg).run(show, eps), {str(tmp_path)!r}, cfg)\nprint('ok')\n")
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0", PYTHONIOENCODING="ascii:replace")
    script_file = tmp_path / "run_export.py"
    script_file.write_text(script, encoding="utf-8")   # source files are always read as UTF-8
    out = subprocess.run([sys.executable, "-X", "utf8=0", str(script_file)], env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    assert out.returncode == 0, out.stderr[-800:]
    assert "“" in open(tmp_path / "promos_top.json", encoding="utf-8").read()


# ------------------------------------------------------------ public deployment features
def test_demo_instant_results_and_live_run(client):
    r = client.get("/demo")                       # first visit: builds the demo, shows progress
    assert r.status_code == 302 and "/job/demo-precompute" in r.headers["Location"]
    import time
    t = time.time()
    while time.time() - t < 60:
        st = client.get("/job/demo-precompute/status").get_json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert st["status"] == "done" and st["rid"] == "demo"
    r = client.get("/demo")                       # afterwards: instant
    assert r.headers["Location"].endswith("/r/demo")
    page = client.get("/r/demo").get_data(as_text=True)
    assert "The Cleaner Was the Heiress" in page and "Notes on this upload" not in page
    assert client.get("/r/demo/edl.zip").status_code == 200
    _, st, _ = wait_job(client, client.post("/demo/run"))      # live run on the sample
    assert st["status"] == "done" and len(st["rid"]) > 30


def test_sample_downloads_and_health(client):
    assert client.get("/samples/sample.zip").status_code == 200
    r = client.get("/samples/episode-001.txt")
    assert r.status_code == 200 and b"EPISODE NUMBER: Episode 1" in r.data
    assert client.get("/samples/../app.py").status_code == 404
    assert client.get("/samples/secret.txt").status_code == 404
    h = client.get("/healthz")
    assert h.status_code == 200 and h.get_json()["ok"] is True
    assert h.headers["X-Content-Type-Options"] == "nosniff" and h.headers["Referrer-Policy"] == "no-referrer"
    home = client.get("/").get_data(as_text=True)
    assert "Try the live demo" in home and "sample .zip" in home


def test_public_mode_hides_runs_and_prunes(client, monkeypatch):
    monkeypatch.setattr(A, "PUBLIC", True); monkeypatch.setattr(A, "KEEP_RUNS", 2)
    for _ in range(3):
        _, st, _ = wait_job(client, post(client, [("show.zip", show_zip(3))]))
        assert st["status"] == "done"
    home = client.get("/").get_data(as_text=True)
    assert "Previous runs" not in home and "deleted automatically" in home
    assert len(os.listdir(A.RUNS)) == 2                         # oldest run pruned


def test_busy_limit(client, monkeypatch):
    monkeypatch.setattr(A, "MAX_QUEUE", 0)
    r = post(client, [("show.zip", show_zip(2))])
    assert r.status_code == 503 and "busy" in r.get_data(as_text=True)


def test_zip_member_and_total_caps(monkeypatch):
    from promofinder import ingest
    ep_len = len(make_episode(2, LINES).encode())
    monkeypatch.setattr(ingest, "MAX_FILE_BYTES", ep_len + 100)
    big = zipof([("show/episode-001.txt", b"x" * (ep_len * 3)), ("show/episode-002.txt", make_episode(2, LINES))])
    _, eps = ingest.load_bytes([("s.zip", big)])
    assert [e.number for e in eps] == [2]                       # oversized member skipped, not read whole
    monkeypatch.setattr(ingest, "MAX_FILE_BYTES", 10_000_000); monkeypatch.setattr(ingest, "MAX_TOTAL_BYTES", 5000)
    with pytest.raises(ingest.InputError):
        ingest.load_bytes([("s.zip", zipof([(f"show/episode-{i:03d}.txt", make_episode(i, LINES)) for i in (1, 2)]))])


def test_identical_upload_served_from_cache_and_changes_recompute(client):
    z = show_zip()
    rid = wait_job(client, post(client, [("show.zip", z)], top="5"))[1]["rid"]
    # same files + same settings -> saved result, no new job
    r = post(client, [("show.zip", z)], top="5")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/r/{rid}?cached=1")
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "already processed" in page and "Promo candidates" in page
    # different settings -> recompute
    r2 = post(client, [("show.zip", z)], top="6")
    assert "/job/" in r2.headers["Location"]; wait_job(client, r2)
    # different content -> recompute
    z2 = zipof([(f"My Show/episode-{i:03d}.txt", make_episode(i, LINES[::-1])) for i in range(1, 7)])
    r3 = post(client, [("show.zip", z2)], top="5")
    assert "/job/" in r3.headers["Location"]; wait_job(client, r3)
    # a pruned run is not served from the cache
    import shutil; shutil.rmtree(os.path.join(A.RUNS, rid))
    r4 = post(client, [("show.zip", z)], top="5")
    assert "/job/" in r4.headers["Location"]; wait_job(client, r4)


def test_public_mode_never_shares_cached_runs(client, monkeypatch):
    monkeypatch.setattr(A, "PUBLIC", True)
    z = show_zip(3)
    wait_job(client, post(client, [("show.zip", z)]))
    assert "/job/" in post(client, [("show.zip", z)]).headers["Location"]   # recomputed, no link reuse


def test_private_samples_local_only(client, monkeypatch, tmp_path):
    pdir = tmp_path / "private"; pdir.mkdir()
    (pdir / "pack.zip").write_bytes(show_zip(3))
    monkeypatch.setattr(A, "PRIVATE_DIR", str(pdir))
    home = client.get("/").get_data(as_text=True)
    assert "Local samples" in home and "pack.zip" in home
    r = client.post("/private-sample/run", data={"name": "pack.zip"})
    _, st, _ = wait_job(client, r); assert st["status"] == "done"
    assert client.post("/private-sample/run", data={"name": "../pack.zip"}).status_code == 404
    assert client.post("/private-sample/run", data={"name": "missing.zip"}).status_code == 404
    monkeypatch.setattr(A, "PUBLIC", True)                      # public deployment: invisible and unreachable
    assert "Local samples" not in client.get("/").get_data(as_text=True)
    assert client.post("/private-sample/run", data={"name": "pack.zip"}).status_code == 404


def test_error_page_names_exception_and_log_location(client, monkeypatch):
    def boom(*a, **k):
        raise MemoryError("secret detail")
    monkeypatch.setattr(A, "load_bytes", boom)
    monkeypatch.setattr(A, "ON_RENDER", True)
    body = post(client, [("show.zip", show_zip())]).get_data(as_text=True)
    assert "MemoryError" in body and "Render dashboard" in body and "secret detail" not in body


# ---- ZIPs whose members can't be read (damaged, Deflate64, password-protected) must get a clear 400
# page, not the generic "Something went wrong" page.
def _deflated_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(1, 4):
            z.writestr(f"My Show/episode-{i:03d}.txt", make_episode(i, LINES) * 3)
    return buf.getvalue()


def _broken_zip(kind):
    import re as _re
    good = _deflated_zip()
    infos = zipfile.ZipFile(io.BytesIO(good)).infolist()
    b = bytearray(good)
    if kind == "corrupt":
        i = infos[0]
        off = i.header_offset + 30 + len(i.filename.encode()) + len(i.extra) + 20
        b[off:off + 30] = b"\x00" * 30
    elif kind == "deflate64":
        for i in infos:
            b[i.header_offset + 8:i.header_offset + 10] = (9).to_bytes(2, "little")
        for m in _re.finditer(rb"PK\x01\x02", good):
            b[m.start() + 10:m.start() + 12] = (9).to_bytes(2, "little")
    elif kind == "encrypted":
        for i in infos:
            b[i.header_offset + 6] |= 1
        for m in _re.finditer(rb"PK\x01\x02", good):
            b[m.start() + 8] |= 1
    return bytes(b)


@pytest.mark.parametrize("kind,expect", [("corrupt", "is damaged"), ("deflate64", "Deflate64 compression"),
                                         ("encrypted", "password-protected")])
def test_zip_member_failures_get_friendly_400(client, kind, expect):
    r = post(client, [("show.zip", _broken_zip(kind))])
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and expect in body and "Something went wrong" not in body, body[:300]


def test_deflated_zip_still_works(client):
    _, st, _ = wait_job(client, post(client, [("show.zip", _deflated_zip())]))
    assert st["status"] == "done"


# ---- deploy-time demo + diagnostics
def test_prebuilt_demo_installs_without_scoring_and_stale_one_is_ignored(tmp_path, monkeypatch):
    import json as _json, shutil as _sh
    pre = tmp_path / "prebuilt" / "demo_run"; demo = tmp_path / "data" / "demo_run"
    monkeypatch.setattr(A, "PREBUILT_DEMO", str(pre)); monkeypatch.setattr(A, "DEMO_DIR", str(demo))
    assert A.prebuild_demo() == 0 and (pre / "BUILD.json").exists()
    calls = []
    monkeypatch.setattr(A, "_run_job", lambda *a, **k: calls.append(1))   # scoring must not happen
    A.precompute_demo()
    assert (demo / "promos_top.json").exists() and not calls
    # stale marker -> ignored -> falls back to scoring
    _sh.rmtree(demo)
    m = _json.loads((pre / "BUILD.json").read_text()); m["version"] = "0.0.0"; (pre / "BUILD.json").write_text(_json.dumps(m))
    A.precompute_demo()
    assert calls == [1]


def test_healthz_reports_version_and_cpu(client):
    j = client.get("/healthz").get_json()
    assert j["ok"] and j["version"] == A.__version__ and "visible_cores" in j["cpu"]
    assert all(n == 1 for n in j["cpu"].get("math_threads", {}).values())    # pinned maths threads


def test_demo_with_prebuilt_goes_straight_to_results(client, tmp_path, monkeypatch):
    pre = tmp_path / "pre" / "demo_run"
    monkeypatch.setattr(A, "PREBUILT_DEMO", str(pre)); monkeypatch.setattr(A, "DEMO_DIR", str(tmp_path / "d" / "demo_run"))
    assert A.prebuild_demo() == 0
    r = client.get("/demo")
    assert r.status_code == 302 and r.headers["Location"].endswith("/r/demo")
    assert "The Cleaner Was the Heiress" in client.get("/r/demo").get_data(as_text=True)


# ---- second sample show
def test_second_sample_has_its_own_demo_files_and_live_run(client):
    home = client.get("/").get_data(as_text=True)
    for needle in ("Sample 1", "Sample 2", "Last Call from the Marigold", 'href="/demo/2"',
                   'name=sample value="2"', 'href="/samples/2/sample.zip"', "30 episodes"):
        assert needle in home, needle
    r = client.get("/demo/2")
    assert r.status_code == 302 and "/job/demo-precompute-2" in r.headers["Location"]
    for _ in range(200):
        if client.get("/job/demo-precompute-2/status").get_json()["status"] == "done":
            break
        time.sleep(0.1)
    r = client.get("/demo/2")
    assert r.headers["Location"].endswith("/r/demo2")
    page = client.get("/r/demo2").get_data(as_text=True)
    assert "Last Call from the Marigold" in page and "The Cleaner Was the Heiress" not in page
    assert client.get("/r/demo2/edl.zip").status_code == 200
    _, st, _ = wait_job(client, client.post("/demo/run", data={"sample": "2"}))
    assert st["status"] == "done"
    z = client.get("/samples/2/sample.zip")
    assert z.status_code == 200 and "last_call_from_the_marigold.zip" in z.headers["Content-Disposition"]
    assert client.get("/samples/2/episode-030.txt").status_code == 200
    for bad in ("/samples/3/sample.zip", "/samples/2/../app.py", "/demo/3"):
        assert client.get(bad).status_code == 404, bad
    assert client.post("/demo/run", data={"sample": "9"}).status_code == 404
