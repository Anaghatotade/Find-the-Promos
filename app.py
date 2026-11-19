"""PromoFinder web app: upload screenplay .zip / .txt files -> ranked promos.

  python app.py            # http://localhost:7860   (local)
  gunicorn -c gunicorn.conf.py app:app                (production / Render)

Environment (all optional):
  PROMOFINDER_PUBLIC=1      public deployment: hide other visitors' runs, smaller upload cap, run pruning
  PROMOFINDER_DATA_DIR      where runs/feedback are written (default: this folder; /tmp on hosts)
  PROMOFINDER_MAX_UPLOAD_MB upload cap (default 200 locally, 20 when public)
  PROMOFINDER_KEEP_RUNS     how many web runs to keep on disk (default 40 when public)
Editors can ✓/✗ each promo; votes go to feedback/feedback.jsonl and can be used to
re-fit the ranking weights (python -m promofinder.learn_weights).
"""
import gc, hashlib, html, io, json, logging, os, shutil, time, uuid, threading, zipfile
from flask import Flask, request, redirect, Response, abort
from werkzeug.exceptions import HTTPException
from promofinder.ingest import load_bytes, InputError
from promofinder.config import load_config
from promofinder.pipeline import PromoFinder
from promofinder.export import write_outputs
from promofinder.report import html_report
from promofinder import __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.environ.get("PROMOFINDER_PUBLIC", "0").lower() in ("1", "true", "yes")
DATA = os.environ.get("PROMOFINDER_DATA_DIR") or ROOT
RUNS = os.path.join(DATA, "outputs", "web_runs"); FB = os.path.join(DATA, "feedback")
DEMO_DIR = os.path.join(DATA, "outputs", "demo_run")
SAMPLE_DIR = os.path.join(ROOT, "samples", "the_cleaner_was_the_heiress")
SAMPLE_ZIP = os.path.join(ROOT, "samples", "the_cleaner_was_the_heiress.zip")
KEEP_RUNS = int(os.environ.get("PROMOFINDER_KEEP_RUNS", "40" if PUBLIC else "0"))   # 0 = keep everything
MAX_QUEUE = 3            # jobs waiting or running; more than this -> "busy, try again" page
os.makedirs(RUNS, exist_ok=True); os.makedirs(FB, exist_ok=True)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("PROMOFINDER_MAX_UPLOAD_MB", "20" if PUBLIC else "200")) * 1024 * 1024
LOCK = threading.Lock()
log = logging.getLogger("promofinder.app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ERROR_PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder · {title}</title>
<style>body{{margin:0;font:15px/1.55 -apple-system,Segoe UI,Inter,sans-serif;background:#f6f5f2;color:#1d1d1f}}
.w{{max-width:640px;margin:10vh auto;padding:0 24px}}.box{{background:#fff;border:1px solid #e6e4df;border-radius:16px;padding:24px}}
h1{{font-size:22px;margin:0 0 8px}}p{{color:#44444a}}ul{{color:#44444a;padding-left:20px}}code{{background:#f1efe9;padding:1px 5px;border-radius:4px}}
a.btn{{display:inline-block;margin-top:10px;background:#1d1d1f;color:#fff;border-radius:10px;padding:9px 16px;text-decoration:none}}</style></head>
<body><div class=w><div class=box><h1>{title}</h1><p>{message}</p>{details}<a class=btn href="/">Back to upload</a></div></div></body></html>"""


def error_page(title, message, status=400, details=None):
    items = "".join(f"<li>{html.escape(str(d))}</li>" for d in (details or []))
    return ERROR_PAGE.format(title=html.escape(title), message=html.escape(message),
                             details=f"<ul>{items}</ul>" if items else ""), status


@app.errorhandler(HTTPException)
def http_error(e):
    titles = {400: "That upload can't be processed", 404: "Not found", 405: "Not allowed",
              413: "Upload too large"}
    msg = {413: f"The upload is larger than {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB. Upload the screenplay .zip or .txt files only."}
    return error_page(titles.get(e.code, e.name), msg.get(e.code, e.description or e.name), e.code)


@app.errorhandler(Exception)
def unexpected_error(e):
    eid = uuid.uuid4().hex[:8]
    log.exception("unhandled error %s on %s", eid, request.path)
    return error_page("Something went wrong",
                      f"PromoFinder hit an unexpected error (error id {eid}). Nothing was saved. "
                      "The full details are in the terminal running app.py; please include the error id if you report it.", 500)


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)

INDEX = """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder</title>
<style>body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Inter,sans-serif;background:#f6f5f2;color:#1d1d1f}
.w{max-width:640px;margin:9vh auto;padding:0 24px}h1{font-size:30px;letter-spacing:-.02em;margin:0 0 6px}p{color:#6b6b70}
form{background:#fff;border:1px solid #e6e4df;border-radius:16px;padding:24px;margin-top:22px}
input[type=file]{display:block;margin:10px 0 18px}button{background:#1d1d1f;color:#fff;border:0;border-radius:10px;padding:10px 18px;font:inherit;cursor:pointer}
label{font-size:13px;color:#6b6b70}select,input[type=number]{font:inherit;margin-left:6px}.runs a{display:block;color:#1d1d1f;margin:4px 0}
#busy{display:none;margin-top:14px;color:#6b6b70}
.demo{background:#1d1d1f;color:#f6f5f2;border-radius:16px;padding:22px 24px;margin-top:22px}.demo p{color:#c9c6bf;margin:6px 0 14px}
.demo h2{font-size:18px;margin:0}.demo a.b{display:inline-block;background:#f6f5f2;color:#1d1d1f;border-radius:10px;padding:9px 16px;text-decoration:none;margin:0 8px 8px 0;font-weight:600}
.demo button.b2{background:transparent;color:#f6f5f2;border:1px solid #6b6b70;border-radius:10px;padding:8px 14px;font:inherit;cursor:pointer;margin:0 8px 8px 0}
.demo .dl{font-size:13px;color:#c9c6bf}.demo .dl a{color:#f6f5f2}.small{font-size:12px;color:#8a8a90;margin-top:10px}h3{font-size:15px}</style></head><body><div class=w>
<h1>PromoFinder</h1><p>Finds the best 20–60s promo clips in a microdrama's timestamped screenplays: exact timecodes, the hook, the cliffhanger and why each works, ranked. Runs on CPU with no AI API needed.</p>
<div class=demo><h2>Try the live demo</h2><p>Six episodes of <i>The Cleaner Was the Heiress</i>, an original sample show written for this demo in the production screenplay format.</p>
<a class=b href="/demo">See ranked promos →</a>
<form method=post action="/demo/run" style="display:inline;background:none;border:0;padding:0;margin:0"><button class=b2>Run the pipeline live (a few seconds)</button></form>
<div class=dl>Or download the sample and upload it below: <a href="/samples/sample.zip">sample .zip</a> · __EPLINKS__</div></div>
<form method=post action="/run" enctype=multipart/form-data onsubmit="document.getElementById('busy').style.display='block';const b=this.querySelector('button');b.disabled=true;b.textContent='Working…'">
<input type=file name=files multiple accept=".zip,.txt" required>
<label>Promos to return <input type=number name=top value=12 min=3 max=30></label>
<label style="margin-left:14px"><input type=checkbox name=funnel checked> prefer early episodes (fewer spoilers)</label><br><br>
<button>Find promos</button><div id=busy>Uploading…</div>
<div class=small>__PRIVACY__</div></form>
__RUNS__</div></body></html>"""


@app.get("/")
def index():
    links = []
    for r in ([] if PUBLIC else sorted(os.listdir(RUNS), reverse=True)[:15]):
        try:  # one damaged or partial run folder must not break the home page
            show = json.load(open(os.path.join(RUNS, r, "run_meta.json"), encoding="utf-8"))["show"]
            links.append(f'<a href="/r/{html.escape(r)}">{html.escape(show)} · {html.escape(r)}</a>')
        except (OSError, ValueError, KeyError):
            continue
    eplinks = " ".join(f'<a href="/samples/{html.escape(f)}">{html.escape(f.split(".")[0].replace("episode-00", "ep "))}</a>'
                       for f in _sample_files())
    privacy = (f"Uploads up to {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB. Results are only visible to whoever has the link "
               "and are deleted automatically. Don't upload confidential scripts to a public demo." if PUBLIC else
               "Runs are saved in outputs/web_runs on this machine.")
    runs_html = "" if PUBLIC else f'<div class=runs><h3>Previous runs</h3>{"".join(links) or "<p>none yet</p>"}</div>'
    return INDEX.replace("__RUNS__", runs_html).replace("__EPLINKS__", eplinks).replace("__PRIVACY__", privacy)


def _int_field(name, default, lo, hi):
    raw = (request.form.get(name) or "").strip()
    try:
        return max(lo, min(hi, int(float(raw)))) if raw else default
    except ValueError:
        raise InputError(f"'{name}' must be a whole number between {lo} and {hi} (got '{raw[:20]}').")


@app.post("/run")
def run():
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return error_page("No file selected", "Choose the show's screenplay .zip, or one or more episode .txt files, then press Find promos.")
    bad = [f.filename for f in files if not f.filename.lower().endswith((".zip", ".txt"))]
    items = [(f.filename, f.read()) for f in files if f.filename.lower().endswith((".zip", ".txt"))]
    if not items:
        return error_page("Unsupported file type", "PromoFinder reads screenplay .zip archives or .txt files.",
                          details=[f"not supported: {b}" for b in bad])
    try:
        top_n = _int_field("top", 12, 3, 30)
        cfg = load_config(os.path.join(ROOT, "config.yaml") if os.path.exists(os.path.join(ROOT, "config.yaml")) else None)
        cfg["top_n"] = top_n
        cfg["funnel"]["enabled"] = bool(request.form.get("funnel"))
        report = {}
        show, eps = load_bytes(items, report=report)
    except InputError as e:
        return error_page("That upload can't be processed", str(e))
    if not eps:
        return error_page("No screenplay found in the upload",
                          "None of the files contained timestamped screenplay blocks. PromoFinder expects lines like "
                          "**MARA (Desperate):** followed by Start: (00:13.50) | End: (00:14.30).",
                          details=[f"skipped (no timestamped blocks): {n}" for n in report["skipped"][:10]]
                          + [f"not supported: {b}" for b in bad])
    total = sum(e.duration for e in eps)
    if max(e.duration for e in eps) < cfg["min_dur"] and len(eps) < 2:
        return error_page("Too short for a promo",
                          f"The upload holds {total:.1f}s of story; a promo needs at least {cfg['min_dur']:.0f}s of continuous material.")
    # validation passed: score in the background and show live progress (the run takes seconds)
    notes = report["warnings"] + [f"skipped (no timestamped blocks): {n}" for n in report["skipped"]] + [f"ignored (not .zip/.txt): {b}" for b in bad]
    # Off for LLM runs (not deterministic) and in public mode, where an unguessable run link is the only access
    # control and must never be handed to a different visitor.
    key = None if (cfg.get("llm", {}).get("enabled") or PUBLIC) else _cache_key(items, cfg)
    hit = _cache_get(key) if key else None
    if hit:
        log.info("cache hit: identical upload and settings -> run %s", hit)
        return redirect(f"/r/{hit}?cached=1")
    return _start_job(cfg, show, eps, notes, cache_key=key)


# ------------------------------------------------------------------ result cache
# The pipeline is deterministic (fixed seeds), so identical files + identical config + identical code
# version give byte-identical promos. A repeat upload is answered from the saved run instead of rescored.
CACHE_LOCK = threading.Lock()


def _cache_key(items, cfg):
    h = hashlib.sha256()
    h.update(__version__.encode())
    h.update(json.dumps(cfg, sort_keys=True, default=str).encode())
    for name, data in sorted((os.path.basename(n), hashlib.sha256(d).hexdigest()) for n, d in items):
        h.update(name.encode()); h.update(data.encode())
    return h.hexdigest()


def _cache_path():
    return os.path.join(os.path.dirname(RUNS), "_result_cache.json")   # beside, not inside, the runs folder


def _cache_get(key):
    with CACHE_LOCK:
        try:
            rid = json.load(open(_cache_path(), encoding="utf-8")).get(key)
        except (OSError, ValueError):
            return None
    if rid and os.path.exists(os.path.join(RUNS, rid, "promos_top.json")):
        return rid
    return None   # the run was pruned: recompute


def _cache_put(key, rid):
    with CACHE_LOCK:
        try:
            idx = json.load(open(_cache_path(), encoding="utf-8"))
        except (OSError, ValueError):
            idx = {}
        idx = {k: v for k, v in idx.items() if os.path.isdir(os.path.join(RUNS, v))}   # drop pruned runs
        idx[key] = rid
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(idx, fh)
        os.replace(tmp, _cache_path())


def _start_job(cfg, show, eps, notes, out_dir=None, cache_key=None):
    with JOBS_LOCK:
        _prune_jobs()
        active = sum(1 for j in JOBS.values() if j["status"] in ("queued", "running"))
        if active >= MAX_QUEUE:
            return error_page("PromoFinder is busy", f"{active} runs are already in progress. Please try again in a minute.", 503)
        jid = uuid.uuid4().hex   # unguessable: the job / result link is the only access control
        JOBS[jid] = {"status": "queued", "stage": "Waiting for another run to finish", "frac": 0.0,
                     "started": time.time(), "show": show, "n_eps": len(eps), "rid": None, "error": None}
    threading.Thread(target=_run_job, args=(jid, cfg, show, eps, notes, out_dir, cache_key), daemon=True).start()
    return redirect(f"/job/{jid}")


JOBS: dict = {}
JOBS_LOCK = threading.Lock()


def _prune_jobs(max_age=3600):
    now = time.time()
    for k in [k for k, j in JOBS.items() if now - j["started"] > max_age and j["status"] in ("done", "error")]:
        JOBS.pop(k, None)


def _job_update(jid, **kw):
    with JOBS_LOCK:
        if jid in JOBS:
            JOBS[jid].update(kw)


def _prune_runs():
    if KEEP_RUNS <= 0:
        return
    runs = sorted((d for d in os.listdir(RUNS) if os.path.isdir(os.path.join(RUNS, d))), reverse=True)
    for d in runs[KEEP_RUNS:]:
        shutil.rmtree(os.path.join(RUNS, d), ignore_errors=True)


def _run_job(jid, cfg, show, eps, notes, out_dir=None, cache_key=None):
    t0 = time.time()
    try:
        with LOCK:   # one scoring run at a time (the pipeline sets process-wide arousal mode)
            _job_update(jid, status="running", stage="Starting", frac=0.01)
            res = PromoFinder(cfg).run(show, eps, progress=lambda st, fr: _job_update(jid, stage=st, frac=round(fr, 3)))
        if not res["top"]:
            total = sum(e.duration for e in eps)
            _job_update(jid, status="error", error=("No promo-length clips found",
                        f"{len(eps)} episode(s), {total:.1f}s of story were read, but no {cfg['min_dur']:.0f}-{cfg['max_dur']:.0f}s "
                        "window could be cut without splitting a line of dialogue."))
            return
        _job_update(jid, stage="Writing outputs", frac=0.98)
        rid = "demo" if out_dir == DEMO_DIR else time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:16]
        timings = dict(res.get("timings", {}), total_s=round(time.time() - t0, 2))
        target = out_dir or os.path.join(RUNS, rid)
        if out_dir:
            tmp = target + ".tmp"; shutil.rmtree(tmp, ignore_errors=True)
            write_outputs(res, tmp, cfg, timings)
        else:
            write_outputs(res, target, cfg, timings)
        if res.get("arousal_mode") == "fallback":
            notes = notes + [f"Only {res['tag_coverage']:.0%} of lines carry delivery tags, so line intensity was inferred from the camera/action text."]
        with open(os.path.join(tmp if out_dir else target, "load_notes.json"), "w", encoding="utf-8") as fh:
            json.dump(notes, fh, ensure_ascii=False, indent=1)
        if out_dir:   # atomic swap so the demo page never shows a half-written run
            shutil.rmtree(target, ignore_errors=True); os.replace(tmp, target)
        del res; gc.collect()
        _prune_runs()
        if cache_key and not out_dir:
            _cache_put(cache_key, rid)
        log.info("run %s: %s, %d episodes in %.1fs", rid, show, len(eps), time.time() - t0)
        _job_update(jid, status="done", stage="Done", frac=1.0, rid=rid)
    except Exception:
        eid = uuid.uuid4().hex[:8]
        log.exception("job %s failed (error id %s)", jid, eid)
        _job_update(jid, status="error", error=("Something went wrong",
                    f"PromoFinder hit an unexpected error (error id {eid}). Nothing was saved. "
                    "The full details are in the terminal running app.py."))


PROGRESS_PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder · working</title>
<style>body{margin:0;font:15px/1.55 -apple-system,Segoe UI,Inter,sans-serif;background:#f6f5f2;color:#1d1d1f}
.w{max-width:640px;margin:12vh auto;padding:0 24px}.box{background:#fff;border:1px solid #e6e4df;border-radius:16px;padding:26px}
h1{font-size:21px;margin:0 0 4px}.sub{color:#6b6b70;font-size:13px}.bar{height:10px;background:#eeece6;border-radius:6px;overflow:hidden;margin:18px 0 10px}
.bar i{display:block;height:100%;width:0;background:#1d1d1f;transition:width .35s ease}#st{font-size:14px}#el{color:#6b6b70;font-size:12px;margin-top:4px}
a{color:#1d1d1f}</style></head><body><div class=w><div class=box>
<h1>Finding promos · __SHOW__</h1><div class=sub>__N__ episode(s). Every legal cut point is scored; the results open automatically.</div>
<div class=bar><i id=b></i></div><div id=st>Starting…</div><div id=el></div>
<noscript><p>JavaScript is off: <a href="/job/__JID__">refresh this page</a> to check progress.</p></noscript></div></div>
<script>
const t0=Date.now();
async function poll(){
  try{
    const r=await fetch('/job/__JID__/status',{cache:'no-store'});
    if(r.status===404){document.getElementById('st').textContent='This job is no longer available.';return}
    const j=await r.json();
    document.getElementById('b').style.width=Math.round(j.frac*100)+'%';
    document.getElementById('st').textContent=j.stage+' · '+Math.round(j.frac*100)+'%';
    document.getElementById('el').textContent='Elapsed '+Math.round((Date.now()-t0)/1000)+' s';
    if(j.status==='done'){location.replace('/r/'+j.rid);return}
    if(j.status==='error'){location.replace('/job/__JID__/error');return}
  }catch(e){document.getElementById('el').textContent='Reconnecting…'}
  setTimeout(poll,500);
}
poll();
</script></body></html>"""


@app.get("/job/<jid>")
def job_page(jid):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        j = dict(j) if j else None
    if not j:
        abort(404)
    if j["status"] == "done":
        return redirect(f"/r/{j['rid']}")
    return (PROGRESS_PAGE.replace("__JID__", html.escape(jid)).replace("__SHOW__", html.escape(j["show"]))
            .replace("__N__", str(j["n_eps"])))


@app.get("/job/<jid>/status")
def job_status(jid):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        j = dict(j) if j else None
    if not j:
        return {"status": "missing"}, 404
    return {k: j[k] for k in ("status", "stage", "frac", "rid")} | {"elapsed_s": round(time.time() - j["started"], 1)}


@app.get("/job/<jid>/error")
def job_error(jid):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        j = dict(j) if j else None
    if not j or j["status"] != "error":
        abort(404)
    title, msg = j["error"]
    return error_page(title, msg, 500 if title == "Something went wrong" else 400)


def _run_dir(rid):
    return DEMO_DIR if rid == "demo" else os.path.join(RUNS, os.path.basename(rid))


@app.get("/r/<rid>")
def view(rid):
    d = _run_dir(rid)
    if not os.path.exists(os.path.join(d, "promos_top.json")):
        abort(404)
    top = json.load(open(os.path.join(d, "promos_top.json"), encoding="utf-8")); lng = json.load(open(os.path.join(d, "promos_longlist.json"), encoding="utf-8"))
    page = html_report(top["meta"]["show"], top["meta"], top["promos"], lng["promos"], server=True, run_id=rid)
    notes_path = os.path.join(d, "load_notes.json")
    notes = json.load(open(notes_path, encoding="utf-8")) if os.path.exists(notes_path) else []
    if request.args.get("cached"):
        meta_t = top["meta"].get("timings_s", {}).get("total_s")
        notes = [f"Identical files and settings were already processed, so this is the saved result (computed earlier"
                 + (f" in {meta_t:.1f}s" if isinstance(meta_t, (int, float)) else "") + "). PromoFinder is deterministic: rescoring gives the same promos."] + notes
    if notes:
        banner = ('<div style="max-width:1080px;margin:12px auto 0;padding:10px 16px;background:#fef3c7;border:1px solid #fcd34d;'
                  'border-radius:10px;font-size:13px;color:#78350f"><b>Notes on this upload</b><ul style="margin:4px 0 0;padding-left:18px">'
                  + "".join(f"<li>{html.escape(n)}</li>" for n in notes[:12]) + "</ul></div>")
        page = page.replace("<main>", banner + "<main>", 1)
    dl = f'<div style="max-width:1080px;margin:10px auto 0;padding:0 24px;font-size:13px">Download: <a href="/r/{rid}/promos_top.json">JSON</a> · <a href="/r/{rid}/promos_top.csv">CSV</a> · <a href="/r/{rid}/promos_longlist.csv">longlist CSV</a> · <a href="/r/{rid}/promos_top.md">Markdown</a> · <a href="/r/{rid}/edl.zip">EDLs (Premiere/Resolve)</a> · <a href="/r/{rid}/cutlist_nle.csv">NLE cut list</a></div>'
    return page.replace("<main>", dl + "<main>", 1)


@app.get("/r/<rid>/edl.zip")
def edl_zip(rid):
    d = os.path.join(_run_dir(rid), "edl")
    if not os.path.isdir(d):
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(os.listdir(d)):
            if f.endswith(".edl"):
                z.write(os.path.join(d, f), f)
    return Response(buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": "attachment; filename=promo_edls.zip"})


@app.get("/r/<rid>/<name>")
def download(rid, name):
    allowed = {"promos_top.json", "promos_top.csv", "promos_longlist.csv", "promos_longlist.json", "promos_top.md", "run_meta.json", "cutlist_nle.csv"}
    if name not in allowed:
        abort(404)
    p = os.path.join(_run_dir(rid), name)
    if not os.path.exists(p):
        abort(404)
    mt = {"json": "application/json", "csv": "text/csv", "md": "text/markdown"}[name.rsplit(".", 1)[1]]
    return Response(open(p, "rb").read(), mimetype=mt, headers={"Content-Disposition": f"attachment; filename={name}"})


@app.post("/feedback")
def feedback():
    j = request.get_json(force=True, silent=True) or {}
    if j.get("vote") not in ("up", "down") or "components" not in j:
        abort(400)
    j["ts"] = time.time()
    path = os.path.join(FB, "feedback.jsonl")
    if os.path.exists(path) and os.path.getsize(path) > 5_000_000:
        return {"ok": False, "reason": "feedback store full"}, 507
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: j[k] for k in ("run", "show", "id", "vote", "components", "ts") if k in j}) + "\n")
    return {"ok": True}


# ------------------------------------------------------------------ live demo
def _sample_files():
    try:
        return sorted(f for f in os.listdir(SAMPLE_DIR) if f.endswith(".txt"))
    except OSError:
        return []


def _demo_cfg():
    cfg = load_config(os.path.join(ROOT, "config.yaml") if os.path.exists(os.path.join(ROOT, "config.yaml")) else None)
    cfg["top_n"] = 8
    return cfg


def _load_sample():
    with open(SAMPLE_ZIP, "rb") as fh:
        return load_bytes([(os.path.basename(SAMPLE_ZIP), fh.read())])


def precompute_demo():
    """Build the instant demo results once (at startup); safe to call repeatedly."""
    if os.path.exists(os.path.join(DEMO_DIR, "promos_top.json")) or not os.path.exists(SAMPLE_ZIP):
        return
    show, eps = _load_sample()
    jid = "demo-precompute"
    with JOBS_LOCK:
        JOBS[jid] = {"status": "queued", "stage": "Preparing demo", "frac": 0.0, "started": time.time(),
                     "show": show, "n_eps": len(eps), "rid": None, "error": None}
    _run_job(jid, _demo_cfg(), show, eps, ["Sample show: original fiction written for this demo (not production content)."], DEMO_DIR)


@app.get("/demo")
def demo():
    if os.path.exists(os.path.join(DEMO_DIR, "promos_top.json")):
        return redirect("/r/demo")
    with JOBS_LOCK:
        j = JOBS.get("demo-precompute")
    if j and j["status"] in ("queued", "running"):
        return redirect("/job/demo-precompute")
    threading.Thread(target=precompute_demo, daemon=True).start()
    time.sleep(0.2)
    return redirect("/job/demo-precompute")


@app.post("/demo/run")
def demo_run():
    """Run the full pipeline live on the sample (shows the progress page and a fresh result)."""
    if not os.path.exists(SAMPLE_ZIP):
        return error_page("Demo unavailable", "The sample show is missing from this deployment.", 404)
    show, eps = _load_sample()
    return _start_job(_demo_cfg(), show, eps, ["Live run on the sample show (original fiction written for this demo)."])


@app.get("/samples/<name>")
def sample_file(name):
    if name == "sample.zip":
        p, mt = SAMPLE_ZIP, "application/zip"
        fn = "the_cleaner_was_the_heiress.zip"
    elif name in _sample_files():
        p, mt, fn = os.path.join(SAMPLE_DIR, name), "text/plain; charset=utf-8", name
    else:
        abort(404)
    with open(p, "rb") as fh:
        return Response(fh.read(), mimetype=mt, headers={"Content-Disposition": f"attachment; filename={fn}"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "public": PUBLIC, "demo_ready": os.path.exists(os.path.join(DEMO_DIR, "promos_top.json"))}


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")       # result links are capability URLs
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return resp


if os.environ.get("PROMOFINDER_PRECOMPUTE_DEMO", "1") == "1":
    threading.Thread(target=precompute_demo, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)), debug=False)
