"""Web endpoints added in v2: upload options, search, active A/B pairs, feedback validation, re-rank."""
import io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PROMOFINDER_PRECOMPUTE_DEMO"] = "0"
import pytest
from test_app import client, show_zip, post, wait_job, zipof   # noqa: F401  (fixture reuse)
from test_formats import to_srt
from test_core import make_episode, LINES
from promofinder.parser import parse_screenplay
import app as A


def _run(client, **form):
    r = post(client, [("show.zip", show_zip())], top="5", **form)
    jid, st, _ = wait_job(client, r)
    assert st["status"] == "done", st
    return st["rid"]


def test_home_has_new_options(client):
    b = client.get("/").get_data(as_text=True)
    for needle in ("name=audience", "name=spoilers", 'value="thriller"', "value=strict", ".srt"):
        assert needle in b, needle


def test_upload_with_profile_and_spoilers_records_them(client):
    rid = _run(client, audience="romance", spoilers="strict")
    meta = json.loads(client.get(f"/r/{rid}/promos_top.json").get_data())["meta"]
    assert meta["audience_profile"]["key"] == "romance" and meta["spoiler_tolerance"] == "strict"
    assert client.get(f"/r/{rid}/promos_portfolio.json").status_code == 200
    page = client.get(f"/r/{rid}").get_data(as_text=True)
    assert "id=b_search" in page and "id=b_cmp" in page and "id=b_port" in page


def test_bad_option_values_fall_back(client):
    rid = _run(client, audience="<script>", spoilers="maybe")
    meta = json.loads(client.get(f"/r/{rid}/promos_top.json").get_data())["meta"]
    assert meta["audience_profile"]["key"] == "general" and meta["spoiler_tolerance"] == "balanced"


def test_search_pair_feedback_rerank_loop(client):
    rid = _run(client)
    j = client.get(f"/r/{rid}/search?q=who are you").get_json()
    assert j["hits"] and "clip" in j["hits"][0]
    assert client.get(f"/r/{rid}/search?q=").get_json() == {"hits": []}
    for _ in range(3):
        pr = client.get(f"/r/{rid}/pair").get_json()
        if pr.get("done"):
            break
        r = client.post("/feedback", json={"type": "pair", "run": rid, "show": "s", "winner": "a",
                                           "a": {"id": pr["a"]["id"], "components": pr["a"]["components"]},
                                           "b": {"id": pr["b"]["id"], "components": pr["b"]["components"]}})
        assert r.get_json()["ok"]
    rr = client.get(f"/r/{rid}/rerank").get_json()
    assert rr["order"] and set(rr["learning"]["fitted"]) == {"hook", "cliff", "standalone", "arc", "premise"}
    # malformed judgments are refused
    assert client.post("/feedback", json={"type": "pair", "winner": "a", "a": {}, "b": {}}).status_code == 400
    assert client.post("/feedback", json={"vote": "up", "components": "x"}).status_code == 400
    assert client.get("/r/nope/pair").status_code == 404


def test_srt_upload_works_and_warns(client):
    files = [(f"episode-{i:03d}.srt", to_srt(parse_screenplay(make_episode(i, LINES), f"episode-{i:03d}.txt")).encode()) for i in range(1, 5)]
    r = post(client, files, top="3")
    jid, st, _ = wait_job(client, r)
    assert st["status"] == "done"
    page = client.get(f"/r/{st['rid']}").get_data(as_text=True)
    assert "subtitles" in page and "no camera/action lines" in page
