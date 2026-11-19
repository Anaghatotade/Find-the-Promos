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
import gc, hashlib, html, io, json, logging, os, shutil, sys, time, uuid, threading, zipfile
from flask import Flask, request, redirect, Response, abort
from werkzeug.exceptions import HTTPException
from promofinder.ingest import load_bytes, InputError
from promofinder.config import load_config
from promofinder.pipeline import PromoFinder
from promofinder.export import write_outputs
from promofinder.report import html_report
from promofinder.theme import BASE_CSS
from promofinder import __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.environ.get("PROMOFINDER_PUBLIC", "0").lower() in ("1", "true", "yes")
DATA = os.environ.get("PROMOFINDER_DATA_DIR") or ROOT
RUNS = os.path.join(DATA, "outputs", "web_runs"); FB = os.path.join(DATA, "feedback")
DEMO_DIR = os.path.join(DATA, "outputs", "demo_run")
SAMPLE_DIR = os.path.join(ROOT, "samples", "the_cleaner_was_the_heiress")
SAMPLE_ZIP = os.path.join(ROOT, "samples", "the_cleaner_was_the_heiress.zip")
PREBUILT_DEMO = os.path.join(ROOT, "prebuilt", "demo_run")   # built at deploy time (render.yaml buildCommand)
KEEP_RUNS = int(os.environ.get("PROMOFINDER_KEEP_RUNS", "40" if PUBLIC else "0"))   # 0 = keep everything
MAX_QUEUE = 3            # jobs waiting or running; more than this -> "busy, try again" page
os.makedirs(RUNS, exist_ok=True); os.makedirs(FB, exist_ok=True)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("PROMOFINDER_MAX_UPLOAD_MB", "20" if PUBLIC else "200")) * 1024 * 1024
LOCK = threading.Lock()
log = logging.getLogger("promofinder.app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ERROR_PAGE = ("""<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder: {title}</title>
<style>@@CSS@@</style></head>
<body><div class=shell><div class=sheet><h1>{title}</h1><p>{message}</p>{details}<a class=btn href="/">Back to upload</a></div></div></body></html>"""
              .replace("@@CSS@@", BASE_CSS.replace("{", "{{").replace("}", "}}")))


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


ON_RENDER = bool(os.environ.get("RENDER"))   # Render sets RENDER=true in every service


def _where_logs():
    return ("Render dashboard → this service → Logs (search for the error id)" if ON_RENDER else
            "the server logs" if PUBLIC else "the terminal running app.py")


def _upload_summary():
    """File names and sizes only (never contents), so a log line explains what was being processed."""
    try:
        return [(f.filename, f.content_length or getattr(f.stream, "tell", lambda: None)()) for f in request.files.getlist("files")]
    except Exception:
        return []


@app.errorhandler(Exception)
def unexpected_error(e):
    eid = uuid.uuid4().hex[:8]
    log.exception("unhandled error %s on %s %s (%s) uploads=%s", eid, request.method, request.path, type(e).__name__, _upload_summary())
    return error_page("Something went wrong",
                      f"PromoFinder hit an unexpected error ({type(e).__name__}, error id {eid}). Nothing was saved. "
                      f"The full traceback is in {_where_logs()}; please include the error id if you report it.", 500)


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)

INDEX = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder</title>
<style>@@CSS@@
.top{background:var(--sheet);border-bottom:1px solid var(--rule)}
.top .in{max-width:1040px;margin:0 auto;padding:40px 28px 30px}
.top h1{font-size:56px;line-height:.95}
.top .in{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:40px;align-items:end}
.anat{font-size:13px;color:var(--mute)}
.anat .strip{position:relative;height:18px;background:var(--soft);border-radius:3px;overflow:hidden;margin:8px 0 6px}
.anat .strip span{position:absolute;top:0;bottom:0}
.anat .row{display:flex;justify-content:space-between;font-variant-numeric:tabular-nums}
.anat b{color:var(--ink)}
.lede{font-size:18px;max-width:58ch;margin:14px 0 0}
.grid{max-width:1040px;margin:0 auto;padding:28px;display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:24px;align-items:start}
.up h2,.demo h2{margin-bottom:4px}
.drop{display:block;border:2px dashed var(--rule);border-radius:8px;padding:22px;margin:16px 0;background:var(--paper);cursor:pointer}
.drop b{display:block;margin-bottom:8px}
.drop input{font:inherit;max-width:100%}
.opts{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:center;color:var(--mute);font-size:14px;margin-bottom:18px}
.opts input[type=number]{font:inherit;width:64px;margin-left:6px;padding:4px 6px;border:1px solid var(--rule);border-radius:4px;background:var(--sheet)}
#busy{display:none;margin-top:12px;color:var(--mute)}
.small{font-size:13px;color:var(--mute);margin-top:14px}
.demo{background:var(--slate);color:var(--slate-ink);border-radius:8px;padding:26px 28px}
.demo h2{color:#fff}.demo p{color:#b9c2bb}
.demo .btn{background:var(--slate-ink);color:var(--slate);border-color:var(--slate-ink);margin:6px 8px 8px 0}
.demo .btn-quiet{background:transparent;color:var(--slate-ink);border-color:#5c6a62}
.demo .dl{font-size:13px;color:#b9c2bb;margin-top:10px}.demo .dl a{color:var(--slate-ink);white-space:nowrap}
.lists{max-width:1040px;margin:0 auto;padding:0 28px 48px}
.runs{background:var(--sheet);border:1px solid var(--rule);border-radius:8px;padding:18px 22px;margin-top:18px}
.runs a{display:block;padding:5px 0;font-weight:600}.runs .hint{font-weight:400;color:var(--mute);font-size:13px}
.runs form{margin:8px 0}
@media(max-width:860px){.grid{grid-template-columns:1fr;padding:18px}.top .in{grid-template-columns:1fr;gap:22px;padding:30px 18px 24px}.top h1{font-size:42px}.lists{padding:0 18px 40px}}
</style></head><body>
<div class=top><div class=in><div><h1>PromoFinder</h1>
<p class=lede>Upload a show's timestamped screenplays and get back ranked 20&ndash;60 second promos: exact timecodes, the hook, the moment to cut, and why each one works. Runs on an ordinary CPU, no AI API needed.</p></div>
<div class=anat aria-label="What every promo is checked for"><b>What every clip is checked for</b>
<div class=strip><span style="left:0;width:10%;background:var(--safelight)"></span><span style="right:0;width:18%;background:var(--tape)"></span><span style="left:0;width:3px;background:var(--pencil)"></span><span style="right:0;width:3px;background:var(--pencil)"></span></div>
<div class=row><span>Hook in the first 3 s</span><span>Cut on an open question</span></div>
<p style="margin:8px 0 0">Every cut lands between lines of dialogue, never inside one.</p></div></div></div>
<div class=grid>
<form class="up sheet" method=post action="/run" enctype=multipart/form-data onsubmit="document.getElementById('busy').style.display='block';const b=this.querySelector('button');b.disabled=true;b.textContent='Uploading';">
<h2>Find promos in your show</h2><p class=mute>A .zip of episode screenplays, or several .txt files.</p>
<label class=drop><b>Choose screenplay files</b><input type=file name=files multiple accept=".zip,.txt" required></label>
<div class=opts><label>Promos to return <input type=number name=top value=12 min=3 max=30></label>
<label><input type=checkbox name=funnel checked> Prefer early episodes (fewer spoilers)</label></div>
<button>Find promos</button><div id=busy>Uploading. Scoring starts as soon as the files arrive.</div>
<div class=small>__PRIVACY__</div></form>
<div class=demo><h2>Try the live demo</h2><p>Six episodes of <i>The Cleaner Was the Heiress</i>, an original sample show written for this demo in the production screenplay format.</p>
<a class=btn href="/demo">See ranked promos</a>
<form method=post action="/demo/run" style="display:inline"><button class="btn btn-quiet">Run the pipeline live</button></form>
<div class=dl>Or download the sample and upload it yourself: <a href="/samples/sample.zip">sample .zip</a>, __EPLINKS__</div></div>
</div>
<div class=lists>__RUNS__</div></body></html>""".replace("@@CSS@@", BASE_CSS)


@app.get("/")
def index():
    links = []
    for r in ([] if PUBLIC else sorted(os.listdir(RUNS), reverse=True)[:15]):
        try:  # one damaged or partial run folder must not break the home page
            show = json.load(open(os.path.join(RUNS, r, "run_meta.json"), encoding="utf-8"))["show"]
            links.append(f'<a href="/r/{html.escape(r)}">{html.escape(show)} <span class=hint>{html.escape(r)}</span></a>')
        except (OSError, ValueError, KeyError):
            continue
    eplinks = ", ".join(f'<a href="/samples/{html.escape(f)}">{html.escape(f.split(".")[0].replace("episode-00", "ep "))}</a>'
                       for f in _sample_files())
    privacy = (f"Uploads up to {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB. Results are only visible to whoever has the link "
               "and are deleted automatically. Don't upload confidential scripts to a public demo." if PUBLIC else
               "Runs are saved in outputs/web_runs on this machine.")
    runs_html = "" if PUBLIC else f'<div class=runs><h3>Previous runs</h3>{"".join(links) or "<p class=mute>None yet. Your runs on this machine will be listed here.</p>"}</div>'
    priv = _private_samples()
    priv_html = "" if not priv else ('<div class=runs><h3>Local samples <span class=hint>(from private_samples/, only on this machine)</span></h3>' + "".join(
        f'<form method=post action="/private-sample/run"><input type=hidden name=name value="{html.escape(n)}">'
        f'<button class="btn btn-quiet">Run: {html.escape(n)}</button></form>' for n in priv) + "</div>")
    return INDEX.replace("__RUNS__", priv_html + runs_html).replace("__EPLINKS__", eplinks).replace("__PRIVACY__", privacy)


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
    # validation passed: score in the background and show live progress
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
                    f"The full traceback is in {_where_logs()}."))


PROGRESS_PAGE = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder: working</title>
<style>@@CSS@@
.bar{height:12px;background:var(--soft);border-radius:3px;overflow:hidden;margin:20px 0 10px}
.bar i{display:block;height:100%;width:0;background:var(--tape)}
#st{font-weight:600}#el{color:var(--mute);font-size:13px;margin-top:4px;font-variant-numeric:tabular-nums}
#slow{display:none;margin-top:16px;font-size:14px;color:#4d3800;background:var(--warn-bg);border-left:4px solid var(--pencil);border-radius:4px;padding:10px 14px}
</style></head><body><div class=shell><div class=sheet>
<h1>Finding promos in __SHOW__</h1><p class=mute>__N__ episode(s). Every legal cut point is being scored, and the results open by themselves when it's done.</p>
<div class=bar><i id=b></i></div><div id=st>Starting</div><div id=el></div>
<div id=slow>Still working. This server has far less CPU than a laptop, so a full 50-episode show can take a minute or more here (about 7 s on a laptop). The progress above is live; you can leave this tab open.</div>
<noscript><p>JavaScript is off: <a href="/job/__JID__">refresh this page</a> to check progress.</p></noscript></div></div>
<script>
const t0=Date.now();
async function poll(){
  try{
    const r=await fetch('/job/__JID__/status',{cache:'no-store'});
    if(r.status===404){document.getElementById('st').textContent='This job is no longer available.';return}
    const j=await r.json();
    document.getElementById('b').style.width=Math.round(j.frac*100)+'%';
    document.getElementById('st').textContent=j.stage+' ('+Math.round(j.frac*100)+'%)';
    document.getElementById('el').textContent=Math.round((Date.now()-t0)/1000)+' s elapsed';
    if(Date.now()-t0>30000)document.getElementById('slow').style.display='block';
    if(j.status==='done'){location.replace('/r/'+j.rid);return}
    if(j.status==='error'){location.replace('/job/__JID__/error');return}
  }catch(e){document.getElementById('el').textContent='Reconnecting'}
  setTimeout(poll,500);
}
poll();
</script></body></html>""".replace("@@CSS@@", BASE_CSS)


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
        banner = ('<div class=notes><div><b>Notes on this upload</b><ul>'
                  + "".join(f"<li>{html.escape(n)}</li>" for n in notes[:12]) + "</ul></div></div>")
        page = page.replace("<main>", banner + "<main>", 1)
    dl = (f'<div class=dl><span class=mute>Download </span><a href="/r/{rid}/edl.zip">EDLs for Premiere or Resolve</a>'
          f' <a href="/r/{rid}/cutlist_nle.csv">Cut list (CSV)</a> <a href="/r/{rid}/promos_top.csv">Promos (CSV)</a>'
          f' <a href="/r/{rid}/promos_top.json">JSON</a> <a href="/r/{rid}/promos_top.md">Markdown</a>'
          f' <a href="/r/{rid}/promos_longlist.csv">Longlist (CSV)</a></div>')
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


# ------------------------------------------------------------------ local-only private samples
# Put confidential packs (e.g. the Kuku development screenplays) in private_samples/ to test them in one click
# on YOUR machine. Never served in public mode; the folder is git- and docker-ignored and not in the public bundle.
PRIVATE_DIR = os.environ.get("PROMOFINDER_PRIVATE_SAMPLES", os.path.join(ROOT, "private_samples"))


def _private_samples():
    if PUBLIC:
        return []
    try:
        return sorted(f for f in os.listdir(PRIVATE_DIR) if f.lower().endswith(".zip") and os.path.isfile(os.path.join(PRIVATE_DIR, f)))
    except OSError:
        return []


@app.post("/private-sample/run")
def private_sample_run():
    name = request.form.get("name", "")
    if name not in _private_samples():   # exact match against the listing: no paths, nothing in public mode
        abort(404)
    with open(os.path.join(PRIVATE_DIR, name), "rb") as fh:
        items = [(name, fh.read())]
    cfg = load_config(os.path.join(ROOT, "config.yaml") if os.path.exists(os.path.join(ROOT, "config.yaml")) else None)
    try:
        report = {}
        show, eps = load_bytes(items, report=report)
    except InputError as e:
        return error_page("That sample can't be processed", str(e))
    if not eps:
        return error_page("No screenplay found in the sample", f"{name} contains no timestamped screenplay files.")
    key = _cache_key(items, cfg)
    hit = _cache_get(key)
    if hit:
        return redirect(f"/r/{hit}?cached=1")
    return _start_job(cfg, show, eps, report["warnings"] + [f"Local private sample: {name} (never served in public mode)."], cache_key=key)


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


def _sample_sha():
    with open(SAMPLE_ZIP, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _install_prebuilt_demo():
    """Copy the demo built at deploy time into place. Costs no CPU at runtime, so a free instance
    waking from sleep never queues a visitor's upload behind a demo run. Used only if it was built by this
    exact code version from this exact sample; otherwise the demo is computed as before."""
    try:
        with open(os.path.join(PREBUILT_DEMO, "BUILD.json"), encoding="utf-8") as fh:
            marker = json.load(fh)
        if (marker.get("version") != __version__ or marker.get("sample_sha256") != _sample_sha()
                or not os.path.exists(os.path.join(PREBUILT_DEMO, "promos_top.json"))):
            log.info("prebuilt demo ignored (built by %s, this is %s)", marker.get("version"), __version__)
            return False
        tmp = DEMO_DIR + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(PREBUILT_DEMO, tmp)
        shutil.rmtree(DEMO_DIR, ignore_errors=True)
        os.replace(tmp, DEMO_DIR)
        log.info("demo installed from the deploy-time build (no runtime scoring)")
        return True
    except (OSError, ValueError):
        return False


def prebuild_demo():
    """`python app.py --prebuild-demo`: score the sample once at build time (Render buildCommand / Dockerfile)."""
    shutil.rmtree(PREBUILT_DEMO, ignore_errors=True)
    show, eps = _load_sample()
    jid = "prebuild-demo"
    JOBS[jid] = {"status": "queued", "stage": "", "frac": 0.0, "started": time.time(), "show": show,
                 "n_eps": len(eps), "rid": None, "error": None}
    _run_job(jid, _demo_cfg(), show, eps, ["Sample show: original fiction written for this demo (not production content)."], PREBUILT_DEMO)
    if JOBS[jid]["status"] != "done" or not os.path.exists(os.path.join(PREBUILT_DEMO, "promos_top.json")):
        print("prebuild-demo FAILED:", JOBS[jid].get("error")); return 1
    with open(os.path.join(PREBUILT_DEMO, "BUILD.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": __version__, "sample_sha256": _sample_sha(), "built_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    print(f"prebuild-demo OK: {show}, {len(eps)} episodes -> {PREBUILT_DEMO}")
    return 0


def precompute_demo():
    """Build the instant demo results once (at startup); safe to call repeatedly."""
    if os.path.exists(os.path.join(DEMO_DIR, "promos_top.json")) or not os.path.exists(SAMPLE_ZIP):
        return
    if _install_prebuilt_demo():
        with JOBS_LOCK:   # anyone already waiting on the demo progress page is sent to the results
            JOBS["demo-precompute"] = {"status": "done", "stage": "Done", "frac": 1.0, "started": time.time(),
                                       "show": "demo", "n_eps": 0, "rid": "demo", "error": None}
        return
    show, eps = _load_sample()
    jid = "demo-precompute"
    with JOBS_LOCK:
        JOBS[jid] = {"status": "queued", "stage": "Preparing demo", "frac": 0.0, "started": time.time(),
                     "show": show, "n_eps": len(eps), "rid": None, "error": None}
    _run_job(jid, _demo_cfg(), show, eps, ["Sample show: original fiction written for this demo (not production content)."], DEMO_DIR)


@app.get("/demo")
def demo():
    if os.path.exists(os.path.join(DEMO_DIR, "promos_top.json")) or _install_prebuilt_demo():
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


def _cpu_info():
    """What this host really gives us: visible cores vs usable CPU quota vs maths threads."""
    info = {"visible_cores": os.cpu_count()}
    try:
        info["usable_cores"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    for path in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"):
        try:
            with open(path) as fh:
                info["cgroup_cpu_limit"] = fh.read().strip()
            break
        except OSError:
            continue
    try:
        from threadpoolctl import threadpool_info
        info["math_threads"] = {i.get("internal_api", "?"): i.get("num_threads") for i in threadpool_info()}
    except Exception:
        pass
    return info


@app.get("/healthz")
def healthz():
    return {"ok": True, "public": PUBLIC, "version": __version__,
            "demo_ready": os.path.exists(os.path.join(DEMO_DIR, "promos_top.json")),
            "demo_source": "prebuilt" if os.path.exists(os.path.join(PREBUILT_DEMO, "BUILD.json")) else "runtime",
            "cpu": _cpu_info()}


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")       # result links are capability URLs
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return resp


if os.environ.get("PROMOFINDER_PRECOMPUTE_DEMO", "1") == "1" and "--prebuild-demo" not in sys.argv:
    threading.Thread(target=precompute_demo, daemon=True).start()


if __name__ == "__main__":
    if "--prebuild-demo" in sys.argv:
        sys.exit(prebuild_demo())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7860)), debug=False)
