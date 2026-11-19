#!/usr/bin/env bash
# =============================================================================================
#  PromoFinder v1.2.3 upgrade: fixes the "Something went wrong" page after a ZIP upload
# =============================================================================================
#  ROOT CAUSE (reproduced): ZIP errors were only caught when the archive was OPENED. Errors that
#  happen while READING a file inside it escaped as raw Python exceptions -> generic 500 page:
#    * a damaged file inside the ZIP        -> zipfile.BadZipFile ("Bad CRC-32")
#    * Deflate64 compression (some Windows / 7-Zip archives) -> NotImplementedError
#    * a password-protected ZIP             -> RuntimeError
#  v1.2.3 turns each into a clear message telling you what to do, logs the exception type with the
#  error id, and points to Render's Logs. Valid ZIPs are unaffected (same promos, same scores).
#
#  Also included (from v1.2.2): local-only "private samples". Put a confidential ZIP in
#  private_samples/ and your OWN machine shows a one-click Run button. Never shown in public mode
#  (Render), and the folder is git- and docker-ignored.
#
#  USAGE (Windows: open "Git Bash" in your repo folder, e.g. C:\projects\Find-the-Promos)
#    bash fix_promofinder_v123.sh                          apply + verify + test (no git changes)
#    bash fix_promofinder_v123.sh --push                   ...then commit and push (Render redeploys)
#    bash fix_promofinder_v123.sh --private-sample "/c/path/to/show.zip"
#                                                          ...also copy a ZIP into private_samples/
#                                                             (local testing only; never committed)
#  Your README.md is never modified. Every overwritten file is backed up first.
# =============================================================================================
set -euo pipefail

PUSH=0; PRIV=""
while [ $# -gt 0 ]; do
  case "$1" in
    --push) PUSH=1; shift ;;
    --private-sample) PRIV="${2:-}"; [ -n "$PRIV" ] || { echo "ERROR: --private-sample needs a .zip path"; exit 2; }; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (use --help)"; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mOK\033[0m  %s\n' "$*"; }
fail() { printf '\n\033[31mERROR:\033[0m %s\n' "$*"; exit 1; }

# ---------------------------------------------------------------- 1. are we in the project root?
say "1/8 Checking the project folder: $PWD"
for f in app.py render.yaml requirements.txt promofinder/ingest.py promofinder/pipeline.py; do
  [ -f "$f" ] || fail "'$f' not found. Run this script from the folder that contains app.py (e.g. C:\\projects\\Find-the-Promos)."
done
ok "PromoFinder project found"

# ---------------------------------------------------------------- 2. Python + virtualenv
say "2/8 Finding Python"
PY=""
for c in ".venv/Scripts/python.exe" ".venv/bin/python"; do [ -x "$c" ] && { PY="$c"; break; }; done
if [ -z "$PY" ]; then
  SYS=""
  for c in python3 python "py -3"; do
    if $c -c "import sys; assert sys.version_info >= (3, 10)" >/dev/null 2>&1; then SYS="$c"; break; fi
  done
  [ -n "$SYS" ] || fail "Python 3.10+ not found. Install it from python.org (tick 'Add Python to PATH')."
  echo "    no .venv found: creating one with: $SYS"
  $SYS -m venv .venv
  for c in ".venv/Scripts/python.exe" ".venv/bin/python"; do [ -x "$c" ] && { PY="$c"; break; }; done
  [ -n "$PY" ] || fail "could not create .venv"
fi
ok "$($PY -c 'import sys; print(sys.executable, sys.version.split()[0])')"
OLDVER=$($PY -c "import re;print(re.search(r'__version__\s*=\s*[\x22\x27]([^\x22\x27]+)',open('promofinder/__init__.py',encoding='utf-8').read()).group(1))" 2>/dev/null || echo "?")
echo "    current version: $OLDVER"

# ---------------------------------------------------------------- 3. backup
say "3/8 Backing up the files that will be replaced"
TS=$(date +%Y%m%d-%H%M%S)
BACKUP="../promofinder_backup_$TS"
mkdir -p "$BACKUP"
for f in .dockerignore .gitignore app.py promofinder/__init__.py promofinder/ingest.py render.yaml tests/test_app.py; do
  if [ -f "$f" ]; then mkdir -p "$BACKUP/$(dirname "$f")"; cp "$f" "$BACKUP/$f"; fi
done
ok "backup in $(cd "$BACKUP" && pwd)  (outside the repo, so it is never committed)"

# ---------------------------------------------------------------- 4. write v1.2.3 files
say "4/8 Writing PromoFinder v1.2.3 files"
cat > '.dockerignore' <<'PROMOFINDER_V123_EOF'
.venv
__pycache__
*.pyc
.pytest_cache
outputs
feedback
eval
experiments
docs
*.zip
!samples/the_cleaner_was_the_heiress.zip
private_samples
PROMOFINDER_V123_EOF

cat > '.gitignore' <<'PROMOFINDER_V123_EOF'
__pycache__/
*.pyc
.venv/
.pytest_cache/
outputs/
feedback/
# confidential packs for local one-click testing - never commit
private_samples/
*.zip
!samples/the_cleaner_was_the_heiress.zip
PROMOFINDER_V123_EOF

cat > 'app.py' <<'PROMOFINDER_V123_EOF'
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
    priv = _private_samples()
    priv_html = "" if not priv else ('<div class=runs><h3>Local samples <span style="font-weight:400;color:#8a8a90;font-size:13px">'
                                     '(from private_samples/, only on this machine)</span></h3>' + "".join(
        f'<form method=post action="/private-sample/run" style="background:none;border:0;padding:0;margin:6px 0">'
        f'<input type=hidden name=name value="{html.escape(n)}"><button>Run: {html.escape(n)}</button></form>' for n in priv) + "</div>")
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
                    f"The full traceback is in {_where_logs()}."))


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
PROMOFINDER_V123_EOF

mkdir -p "promofinder"
cat > 'promofinder/__init__.py' <<'PROMOFINDER_V123_EOF'
"""PromoFinder: find 20-60s promo moments in timestamped microdrama screenplays."""
__version__ = "1.2.3"
PROMOFINDER_V123_EOF

mkdir -p "promofinder"
cat > 'promofinder/ingest.py' <<'PROMOFINDER_V123_EOF'
"""Load a show from a ZIP, a directory, or individual .txt files (safely)."""
from __future__ import annotations
import hashlib, io, os, zipfile, zlib
from typing import Dict, Iterable, List, Optional, Tuple
from .parser import parse_screenplay, Episode

MAX_FILE_BYTES = 5_000_000      # per screenplay file
MAX_FILES = 2000
MAX_TOTAL_BYTES = 80_000_000    # total decompressed text accepted from one upload


class InputError(ValueError):
    """A problem with what the user supplied (shown to them verbatim, never a stack trace)."""


def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "ignore")


def _read_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, zip_name: str) -> bytes:
    """Return the bytes of one file inside the ZIP. Every way this can fail becomes an InputError the user can act on
    (v1.2.3: these used to escape as BadZipFile / NotImplementedError / RuntimeError -> generic 500 page)."""
    zn, fn = os.path.basename(zip_name), info.filename
    if info.flag_bits & 0x1:
        raise InputError(f"'{zn}' is password-protected ('{fn}'). Upload an unencrypted ZIP, or select the episode .txt files directly.")
    try:
        # read with a hard cap: a member whose header under-states its size (zip bomb) is cut off
        with z.open(info) as fh:
            return fh.read(MAX_FILE_BYTES + 1)
    except NotImplementedError:
        method = {9: "Deflate64", 12: "BZIP2", 14: "LZMA", 95: "XZ", 98: "PPMd", 99: "AES"}.get(info.compress_type, f"#{info.compress_type}")
        raise InputError(f"'{zn}' uses {method} compression, which PromoFinder can't read ('{fn}'). Re-create the ZIP with standard "
                         "(Deflate) compression, or select all the episode .txt files and upload them directly.")
    except RuntimeError as e:   # encrypted members not flagged in the header
        raise InputError(f"'{zn}' could not be read ('{fn}': {e}). Upload an unencrypted ZIP or the .txt files directly.")
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as e:
        raise InputError(f"'{zn}' is damaged: '{fn}' failed its integrity check ({type(e).__name__}). "
                         "Download or create the ZIP again, or upload the episode .txt files directly.")


def _iter_zip(data: bytes, zip_name: str = "upload.zip") -> Iterable[Tuple[str, bytes]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise InputError(f"'{os.path.basename(zip_name)}' is not a valid ZIP archive (it may be corrupted or still downloading).")
    with z:
        if len(z.infolist()) > MAX_FILES:
            raise InputError(f"'{os.path.basename(zip_name)}' contains more than {MAX_FILES} files.")
        total = 0
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or not name.lower().endswith(".txt"):
                continue
            if "__MACOSX" in name or os.path.basename(name).startswith("."):
                continue
            if info.file_size > MAX_FILE_BYTES:
                continue
            data = _read_member(z, info, zip_name)
            if len(data) > MAX_FILE_BYTES:
                continue
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise InputError(f"'{os.path.basename(zip_name)}' expands to more than {MAX_TOTAL_BYTES // 1_000_000} MB of text.")
            yield name, data


def load_inputs(paths: List[str]) -> Tuple[str, List[Episode]]:
    """Accepts any mix of .zip / directories / .txt. Returns (show_name, episodes)."""
    items: List[Tuple[str, bytes]] = []
    show = None
    for p in paths:
        if os.path.isdir(p):
            show = show or os.path.basename(os.path.normpath(p))
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.lower().endswith(".txt"):
                        with open(os.path.join(root, f), "rb") as fh:
                            items.append((os.path.join(root, f), fh.read()))
        elif p.lower().endswith(".zip"):
            with open(p, "rb") as fh:
                zitems = list(_iter_zip(fh.read(), p))
            items.extend(zitems)
            if zitems and show is None:
                d = os.path.dirname(zitems[0][0])
                show = os.path.basename(d) if d else os.path.splitext(os.path.basename(p))[0]
        elif p.lower().endswith(".txt"):
            with open(p, "rb") as fh:
                items.append((p, fh.read()))
    return load_bytes(items, show)


def load_bytes(items: List[Tuple[str, bytes]], show: str | None = None,
               report: Optional[Dict[str, list]] = None) -> Tuple[str, List[Episode]]:
    """Parse uploaded files. If `report` is given it receives lists of skipped files and
    load warnings, so a UI can explain what happened instead of failing silently."""
    report = report if report is not None else {}
    report.setdefault("skipped", []); report.setdefault("warnings", [])
    expanded: List[Tuple[str, bytes]] = []
    for name, data in items:
        if name.lower().endswith(".zip"):
            z = list(_iter_zip(data, name)); expanded.extend(z)
            if z and not show:
                show = os.path.basename(os.path.dirname(z[0][0])) or os.path.splitext(os.path.basename(name))[0]
        else:
            expanded.append((name, data))
    # identical files uploaded twice (e.g. the ZIP and a loose .txt) are dropped, not double-counted
    seen_hash, uniq = set(), []
    for n, d in expanded:
        h = hashlib.sha1(d).hexdigest()
        if h in seen_hash:
            report["warnings"].append(f"duplicate file ignored: {os.path.basename(n)}")
            continue
        seen_hash.add(h); uniq.append((n, d))
    eps = []
    for n, d in uniq:
        e = parse_screenplay(_decode(d), os.path.basename(n))
        if e.blocks:
            eps.append(e)
        else:
            report["skipped"].append(os.path.basename(n))
    eps.sort(key=lambda e: (e.number, e.src_file))
    # unknown or clashing episode numbers go AFTER the highest real number, so real episodes keep their identity
    seen, nxt = set(), max((e.number for e in eps), default=0) + 1
    for e in eps:
        if e.number in seen or e.number <= 0:
            report["warnings"].append(f"{e.src_file}: episode number {e.number} missing or duplicated; treated as episode {nxt}")
            e.warnings.append(f"episode number {e.number} ambiguous; renumbered to {nxt}")
            e.number = nxt; nxt += 1
            for b in e.blocks:
                b.episode = e.number
        seen.add(e.number)
    eps.sort(key=lambda e: e.number)
    return (show or "Untitled show"), eps
PROMOFINDER_V123_EOF

cat > 'render.yaml' <<'PROMOFINDER_V123_EOF'
# Render Blueprint (primary deployment): New > Blueprint > connect this repo.
# Free plan: 512 MB RAM, 0.1 CPU, sleeps after 15 min idle (~1 min to wake). PromoFinder peaks at ~360 MB on a
# 50-episode show, so it fits; scoring is CPU-bound, so expect ~10x the laptop time on 0.1 CPU.
# For a snappy demo switch `plan: free` to `plan: starter` (0.5 CPU, no sleep).
services:
  - type: web
    name: promofinder
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn -c gunicorn.conf.py app:app
    healthCheckPath: /healthz
    autoDeploy: true
    envVars:
      - key: PROMOFINDER_PUBLIC
        value: "1"
      - key: PYTHONUTF8
        value: "1"
      - key: PROMOFINDER_DATA_DIR
        value: /tmp/promofinder
      - key: PROMOFINDER_MAX_UPLOAD_MB
        value: "20"
      - key: PROMOFINDER_KEEP_RUNS
        value: "40"
PROMOFINDER_V123_EOF

mkdir -p "tests"
cat > 'tests/test_app.py' <<'PROMOFINDER_V123_EOF'
"""Web-app reliability tests: every bad input gets a friendly page, never a 500;
valid uploads produce ranked promos; outputs survive a non-UTF-8 OS default encoding."""
import io, os, subprocess, sys, zipfile
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
    assert "duplicate file ignored" in page and "ignored (not .zip/.txt): cover.pdf" in page


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
    assert "The Cleaner Was the Heiress" in page and "original fiction" in page
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


# ---- v1.2.3 regression: ZIPs whose *members* fail to read used to escape as BadZipFile /
# NotImplementedError / RuntimeError and produce the generic "Something went wrong" page on /run.
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
PROMOFINDER_V123_EOF

ok "7 files written: .dockerignore .gitignore app.py promofinder/__init__.py promofinder/ingest.py render.yaml tests/test_app.py"

# ---------------------------------------------------------------- 5. verify every project file
say "5/8 Verifying the whole project against the v1.2.3 fingerprints"
cat > .pf_manifest.json <<'PROMOFINDER_MANIFEST_EOF'
{".dockerignore": "591140226d7559349dcf5c1be9653623c2706c17102f1ef7902e069a83876436", ".gitignore": "d2ec767d3b8e160d866b84fd84f5acaeed5132c0ece6b6b183bc32e1d8127ec1", ".python-version": "02e735b3dfe1c32833eb550b7ff8ffa17f5f2bc3fa1e7bae61a8f5a3883ce398", "Dockerfile": "259b4a2e10bb473c5c8a3f905ea2d537a7142551da66ecb44f41711340ac2cf8", "app.py": "ea140e4f19a14c94529798f834eecd1f2dbc1e398c42c55bdbc9354367976fa7", "benchmarks/bench.py": "1bc7582dcdf3fb922d60a0f94d94ea5d1b82991dd8c16816f66ce4b3ae6be996", "benchmarks/equivalence.py": "08d604f9c50dd1ee1b3628d84d81c0552efe1feb86d926a5a6f1933b586eb667", "config.yaml": "50312986ff9edfb1f116ce815742f18dad958b8b800c998efa257db3679c54ba", "gunicorn.conf.py": "4b559cf8b188b082637be867cb1646147ac3b7d2e9ac178b92680fe9a2726d32", "promofinder/__init__.py": "81da76f11b1195548a6bcc199c0d2b4bc81b44e50d5fddf72f6415fc560631f1", "promofinder/__main__.py": "cf7390a2508a0fcad4777a4a629fc5212ab655cb45845975995f835676a834e3", "promofinder/cli.py": "be72fa446a776ee558875f092b28d078cede222440e4ef4d30be4448ed96d6f7", "promofinder/config.py": "8f19c0e6fa351d649dac5a3d502424cf8955e56f4f6e13bb49de1184746c7672", "promofinder/edl.py": "fb37467f71682fc6c65212ae9a42a95e8c88257ec9f091ded9881e95045f47fa", "promofinder/explain.py": "2fa1ee9193843d93070bc8d7eadf511f645623193d7f609b529a7d3079df0516", "promofinder/export.py": "d860cd881a29a2d40a48cdf5dc5fbc78bed1496462110371b44f22333ff553cd", "promofinder/features.py": "69b209b34dc774399d8d30e920656fd886cf30a32a183fca08bdbc238ec5c07b", "promofinder/ingest.py": "a403f3a2c5c07e900051678ae35a1fbb1b323c1ea909be0cc5ffd90dcc15c7b3", "promofinder/labelmodel.py": "52b6fcd1c324a6b5f78959f213fe90d80f1dbd6e95ea10717c023c7a1c208e57", "promofinder/learn_weights.py": "33be42323ff9f98c7fe9facb7e00761f6da07d761ecfdd81e0dce5c63996036c", "promofinder/lexicons.py": "e5f80e50bf6839512ada1f02bb82e9583c8e74da9fa7a34105424137d2473453", "promofinder/llm.py": "faef1eddacc1ccce66f932cf7473948fd17bb03703963e76ec689a02feb24e19", "promofinder/models.py": "27ad496824896f7307ad1bddc826c87cb88ef7db48b250b40c1dbe6f8db6073e", "promofinder/parser.py": "39d173d583a4fec7b388e84b1fa00f4521ac9d8abb794ee72f6cc13838bbcf0a", "promofinder/pipeline.py": "b70b70df3ee415e765015ba2f1044410cab2efd69b60333a67f7a5603756783a", "promofinder/report.py": "2a605ffaa2d987fad6fe71ec88b9f2169bfa69f56a94aff7e430b52e31e7a7a5", "promofinder/series.py": "2c2ca9e8c811e0a9ecbde70aec07ab77ba1a0574fd9b842a24bfd1a492623b3b", "render.yaml": "ee03d6d5c9673332974e923a7d6f887c7b908de72c19d3262a29b27c6712cf8c", "requirements.txt": "8177ca43ece9540df173afa04eb4a0490c6764616ad083652f338be92e5a6a0f", "run_all.sh": "999c19a59933ae0f192b516c79a8f065cefaceeaa669b5fb0bb28310dafb9879", "samples/build_sample.py": "115618cde64a4febf550fcc43847a81ee60c45869cef920f2e7d0122b5edab66", "samples/the_cleaner_was_the_heiress.zip": "0ce91ec89def20bf5656d02932346912aaa065260ddac2cfc52566f3c214e043", "samples/the_cleaner_was_the_heiress/episode-001.txt": "4250ec56fa5f92f3c4971bcdf267d17e2c6aa20e55114f7ad599c606b980ba66", "samples/the_cleaner_was_the_heiress/episode-002.txt": "bca2687664332f966ed02c1131be7d8173ccb65f65d1f95dde33a5ce72455fe6", "samples/the_cleaner_was_the_heiress/episode-003.txt": "e7ebe54c0dbeb42a4dcd34f3abd00b05b0165243c214a3c4009541821e0a080c", "samples/the_cleaner_was_the_heiress/episode-004.txt": "602c0dea65163fe5633ba81d33eed47afe458968fc172392a9915f382fcedb86", "samples/the_cleaner_was_the_heiress/episode-005.txt": "598ddd84906de0a57325c3a7674071ea29b2a5a66a1f661c01327491dae34688", "samples/the_cleaner_was_the_heiress/episode-006.txt": "09429456eda1a30332653bfff21d43d7d29d5d1fd9421a87fd74d9b67d0be00e", "tests/test_app.py": "fed3d9cecc00cc8c4f89b80ff9f8a65d26c6ed93fbee3ab3b57ac11f783b8e7c", "tests/test_core.py": "66ab89b00d5dac3f81ff23264ea9516d39903e250b15636991262668ba32ce03"}
PROMOFINDER_MANIFEST_EOF
set +e
$PY - <<'PYCHECK'
import hashlib, json, os, sys
m = json.load(open(".pf_manifest.json", encoding="utf-8"))
def h(p):
    b = open(p, "rb").read()
    if not p.endswith((".zip", ".png", ".jpg")):
        b = b.replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n"
    return hashlib.sha256(b).hexdigest()
missing = [p for p in m if not os.path.exists(p)]
diff = [p for p in m if os.path.exists(p) and h(p) != m[p]]
for p in missing: print("    MISSING  ", p)
for p in diff:    print("    DIFFERENT", p)
print(f"    {len(m) - len(missing) - len(diff)}/{len(m)} files identical to v1.2.3 (README.md is yours and not checked)")
sys.exit(1 if (missing or diff) else 0)
PYCHECK
RC=$?
set -e
rm -f .pf_manifest.json
if [ $RC -ne 0 ]; then
  echo "    Some files differ from v1.2.3 (listed above). That is fine if you edited them on purpose;"
  echo "    otherwise download the latest PromoFinder_Render_public.zip and copy the listed files over."
  echo "    Continuing: the test suite below is the real check."
else
  ok "every project file matches v1.2.3"
fi

# ---------------------------------------------------------------- 6. dependencies + tests
say "6/8 Installing dependencies and running the test suite (about 30 s)"
$PY -m pip install -q --disable-pip-version-check -r requirements.txt pytest
if ! $PY -m pytest -q tests; then
  echo
  echo "Tests FAILED. Nothing was committed. To undo, copy the files back from: $BACKUP"
  exit 1
fi
NEWVER=$($PY -c "import promofinder; print(promofinder.__version__)")
ok "all tests passed (version $OLDVER -> $NEWVER)"

# ---------------------------------------------------------------- 7. optional local-only sample
say "7/8 Local private sample"
if [ -n "$PRIV" ]; then
  [ -f "$PRIV" ] || fail "--private-sample: file not found: $PRIV"
  case "$PRIV" in *.zip|*.ZIP) ;; *) fail "--private-sample must be a .zip file" ;; esac
  mkdir -p private_samples
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git check-ignore -q private_samples/probe.zip || fail "private_samples/ is not git-ignored, refusing to copy a confidential ZIP into the repo"
  fi
  cp "$PRIV" "private_samples/$(basename "$PRIV")"
  ok "copied to private_samples/$(basename "$PRIV"): git-ignored, visible only when you run 'python app.py' on this PC"
else
  echo "    skipped (use --private-sample \"/c/path/to/show.zip\" to add one for local testing)"
fi

# ---------------------------------------------------------------- 8. git commit + push (optional)
say "8/8 Git"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "    not a git repository: done (files updated and tested locally)."
  exit 0
fi
# leak guard: confidential material must never be committed to the public repo
LEAKS=$(git status --porcelain --untracked-files=all | grep -iE "broken.?soldier|married|private_samples|kuku.*assignment|/outputs/|^.. outputs/|^.. eval/|^.. experiments/" || true)
if [ -n "$LEAKS" ]; then
  echo "$LEAKS"
  fail "files above look confidential and are NOT git-ignored. Move them out of the repo folder, then re-run. Nothing was committed."
fi
ok "leak guard: no confidential files in the change set"
git status --short
if [ $PUSH -eq 1 ]; then
  git add -A
  # never commit this upgrade script itself if it was saved inside the repo
  SELF="$(basename "$0")"
  [ -f "$SELF" ] && git reset -q -- "$SELF" 2>/dev/null || true
  if git diff --cached --quiet; then
    ok "nothing to commit (already on v1.2.3)"
  else
    git commit -q -m "PromoFinder v1.2.3: friendly errors for damaged / Deflate64 / password-protected ZIPs; clearer error logging; local-only private samples"
    ok "committed: $(git log -1 --oneline)"
  fi
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git push origin "$BRANCH"
  ok "pushed to origin/$BRANCH: Render will redeploy automatically (about 3-5 min)"
  echo
  echo "Next: Render dashboard -> promofinder -> Events/Logs, wait for 'Your service is live',"
  echo "then open <your-url>/healthz and upload a ZIP again."
else
  echo
  echo "    Not committed. To publish:  bash $0 --push"
  echo "    (or: git add -A && git commit -m 'PromoFinder v1.2.3' && git push)"
fi
say "Done"
