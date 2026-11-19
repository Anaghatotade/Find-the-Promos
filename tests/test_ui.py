"""UI regression tests for the redesigned pages: every page renders, and every control and link
the old UI offered is still there (upload fields, demo actions, exports, tabs, votes)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PROMOFINDER_PRECOMPUTE_DEMO"] = "0"
import pytest
import app as A
from promofinder.report import html_report


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "RUNS", str(tmp_path / "runs")); os.makedirs(A.RUNS)
    monkeypatch.setattr(A, "FB", str(tmp_path / "fb")); os.makedirs(A.FB)
    monkeypatch.setattr(A, "DEMO_DIR", str(tmp_path / "demo_run"))
    monkeypatch.setattr(A, "PREBUILT_DEMO", str(tmp_path / "pre" / "demo_run"))
    return A.app.test_client()


def test_home_keeps_every_control(client):
    body = client.get("/").get_data(as_text=True)
    for needle in ('action="/run"', 'name=files', 'accept=".zip,.txt"', 'name=top', 'name=funnel',
                   'href="/demo"', 'action="/demo/run"', 'href="/samples/sample.zip"', 'href="/samples/episode-001.txt"',
                   'id=busy', "Try the live demo", "Find promos in your show"):
        assert needle in body, needle


def test_error_and_progress_pages_render(client):
    r = client.get("/r/missing")
    body = r.get_data(as_text=True)
    assert r.status_code == 404 and "Back to upload" in body and "{" not in body.split("<style>")[0]
    html = A.PROGRESS_PAGE
    for needle in ("id=b", "id=st", "id=el", "id=slow", "/status"):
        assert needle in html, needle


def test_results_page_keeps_exports_tabs_and_votes(client, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PREBUILT_DEMO", str(tmp_path / "pre2" / "demo_run"))
    assert A.prebuild_demo() == 0
    monkeypatch.setattr(A, "DEMO_DIR", str(tmp_path / "pre2" / "demo_run"))
    body = client.get("/r/demo").get_data(as_text=True)
    for f in ("edl.zip", "cutlist_nle.csv", "promos_top.csv", "promos_top.json", "promos_top.md", "promos_longlist.csv"):
        assert f'href="/r/demo/{f}"' in body, f
    for needle in ("id=b_top", "id=b_long", "id=b_method", "id=key", "function vote(", "/feedback", "Promo candidates", 'href="/"'):
        assert needle in body, needle


def test_offline_report_has_no_server_links():
    meta = {"n_episodes": 1, "runtime_minutes": 1.0, "n_candidates": 10, "version": "x", "run_at": "now"}
    page = html_report("Show <b>", meta, [], [], server=False)
    assert "New run" not in page and "Show &lt;b&gt;" in page and "window.PF_SERVER=false" in page
