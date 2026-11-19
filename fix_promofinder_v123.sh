#!/usr/bin/env bash
# =============================================================================================
#  PromoFinder v1.2.5 upgrade: faster on hosted CPUs (Render free = 0.1 CPU), identical results
# =============================================================================================
#  WHY UPLOADS TOOK MINUTES ON RENDER: wall time there is ~CPU-seconds x 10, and the pipeline wasted CPU:
#    * numpy/OpenBLAS ran one thread per *visible* core of the big host; on a tiny CPU slice those
#      threads compete. Pinned to 1 thread: 12.9 -> 7.4 CPU-seconds for the 50-episode pack.
#    * exact memoisation (tokens across hook-model folds, VADER, opens-on-answer, names): -> 6.8 CPU-s.
#    * after every sleep/restart the demo was re-scored at startup and a visitor's upload queued
#      behind it; the demo is now scored at DEPLOY time (render.yaml buildCommand).
#  Every score, component, flag and moment score is bit-identical (benchmarks/equivalence.py).
#  Includes all earlier fixes (v1.2.3: friendly errors for damaged/Deflate64/password ZIPs; live
#  progress; local-only private samples). /healthz now reports cores, CPU quota and maths threads.
#
#  USAGE (Windows: open "Git Bash" in your repo folder, e.g. C:\projects\Find-the-Promos)
#    bash fix_promofinder_v125.sh                          apply + verify + test (no git changes)
#    bash fix_promofinder_v125.sh --push                   ...then commit and push (Render redeploys)
#    bash fix_promofinder_v125.sh --private-sample "/c/path/to/show.zip"
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
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
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
for f in .dockerignore .gitignore Dockerfile app.py promofinder/__init__.py promofinder/features.py promofinder/ingest.py promofinder/models.py promofinder/pipeline.py promofinder/series.py render.yaml tests/test_app.py tests/test_core.py; do
  if [ -f "$f" ]; then mkdir -p "$BACKUP/$(dirname "$f")"; cp "$f" "$BACKUP/$f"; fi
done
ok "backup in $(cd "$BACKUP" && pwd)  (outside the repo, so it is never committed)"

# ---------------------------------------------------------------- 4. write v1.2.5 files
say "4/8 Writing PromoFinder v1.2.5 files"
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
# generated at deploy time by `python app.py --prebuild-demo`
prebuilt/
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

cat > 'Dockerfile' <<'PROMOFINDER_V123_EOF'
# Container image for any Docker host (Render's Docker runtime, Railway, Koyeb, Google Cloud Run, a VPS).
# Render's simplest path is render.yaml (native Python runtime, no Docker needed).
# Runs as a non-root user; listens on $PORT (hosts set it; default 7860).
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    PORT=7860 PROMOFINDER_PUBLIC=1 PROMOFINDER_DATA_DIR=/tmp/promofinder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python app.py --prebuild-demo
RUN useradd -m -u 1000 app && mkdir -p /tmp/promofinder && chown -R app /tmp/promofinder
USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/healthz')"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
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
import gc, hashlib, html, io, json, logging, os, shutil, sys, time, uuid, threading, zipfile
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
PREBUILT_DEMO = os.path.join(ROOT, "prebuilt", "demo_run")   # built at deploy time (render.yaml buildCommand)
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
<div id=slow style="display:none;margin-top:12px;font-size:13px;color:#6b6b70;background:#f6f5f2;border-radius:10px;padding:10px 12px">
Still working: this server has much less CPU than a laptop, so a full 50-episode show can take several minutes here
(about 8 s on a laptop). The progress above is live, and the results open automatically. You can leave this tab open.</div>
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
    if(Date.now()-t0>30000)document.getElementById('slow').style.display='block';
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


def _sample_sha():
    with open(SAMPLE_ZIP, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _install_prebuilt_demo():
    """Copy the demo built at deploy time into place (v1.2.5). Costs no CPU at runtime, so a free instance
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
    """What this host really gives us: visible cores vs usable CPU quota vs maths threads (v1.2.5)."""
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
PROMOFINDER_V123_EOF

mkdir -p "promofinder"
cat > 'promofinder/__init__.py' <<'PROMOFINDER_V123_EOF'
"""PromoFinder: find 20-60s promo moments in timestamped microdrama screenplays."""
__version__ = "1.2.5"

import os as _os

# One maths thread by default (v1.2.5). Hosted CPUs are often a small slice of a large machine
# (Render free: 0.1 CPU); BLAS/OpenMP size their thread pools from the *visible* cores and then
# compete for that slice. Measured: 16 threads on 2 cores cost +78% CPU-seconds for identical results.
# Must run before numpy/scipy/sklearn are imported; an explicit environment setting still wins.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ.setdefault(_v, "1")
PROMOFINDER_V123_EOF

mkdir -p "promofinder"
cat > 'promofinder/features.py' <<'PROMOFINDER_V123_EOF'
"""Moment- and window-level features computed directly from timestamped blocks."""
from __future__ import annotations
import functools
import re
from bisect import bisect_left
import numpy as np
from typing import List, Dict
from .parser import Block, Episode
from . import lexicons as L

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = SentimentIntensityAnalyzer()
except Exception:  # optional dependency
    _VADER = None

# arousal source: "tags" (v1.0 behaviour) | "fallback" (tags, else inferred) | "max" (max of both)
AROUSAL_MODE = "tags"


def set_arousal_mode(mode: str):
    global AROUSAL_MODE
    assert mode in ("tags", "fallback", "max"), mode
    AROUSAL_MODE = mode


def inferred_arousal(ep: Episode, b: Block) -> float:
    ctx = " ".join(x.text for x in overlapping(ep.blocks, b.start - 0.5, b.end + 0.3, {"camera", "action"}))
    return max(L.visual_arousal(ctx), L.text_arousal(b.text))


def line_arousal(ep: Episode, b: Block):
    """Per-line value, cached on the block (it is requested once per window containing the line)."""
    cache = b.__dict__.setdefault("_arousal_cache", {})
    if AROUSAL_MODE not in cache:
        cache[AROUSAL_MODE] = _line_arousal(ep, b)
    return cache[AROUSAL_MODE]


def _line_arousal(ep: Episode, b: Block):
    tag = L.tag_arousal(b.tags)
    if AROUSAL_MODE == "tags":
        return tag
    inf = inferred_arousal(ep, b)
    if AROUSAL_MODE == "fallback":
        return tag if tag is not None else inf
    return max(tag or 0.0, inf)


HOOK_SPAN = 3.5     # brief: "something in the first 3 seconds"
CLIFF_SPAN = 6.0    # last beat(s) before the cut


def vader(text: str) -> float:
    if not _VADER or not text:
        return 0.0
    return _vader_cached(text)


@functools.lru_cache(maxsize=65536)
def _vader_cached(text: str) -> float:
    """VADER is a pure function of the text; overlapping moments repeat the same text ~3x (v1.2.5)."""
    return _VADER.polarity_scores(text)["compound"]


_OV_INDEX: dict = {}


def _ov_index(blocks: List[Block]):
    """(starts, max_duration, sorted?) for a block list; lists are cached by identity."""
    ent = _OV_INDEX.get(id(blocks))
    if ent is not None and ent[0] is blocks and ent[1] == len(blocks):
        return ent[2]
    starts = [b.start for b in blocks]
    ok = all(a <= c for a, c in zip(starts, starts[1:]))
    idx = (starts, max((b.end - b.start for b in blocks), default=0.0), ok)
    if len(_OV_INDEX) > 4096:
        _OV_INDEX.clear()
    _OV_INDEX[id(blocks)] = (blocks, len(blocks), idx)
    return idx


def overlapping(blocks: List[Block], t0: float, t1: float, kinds=None) -> List[Block]:
    """Blocks intersecting (t0, t1), in original order. Uses binary search on start times
    (blocks are sorted by start); exactly the same result as a full linear scan."""
    starts, maxdur, ok = _ov_index(blocks)
    if not ok:
        return [b for b in blocks if b.end > t0 + 1e-6 and b.start < t1 - 1e-6 and (kinds is None or b.kind in kinds)]
    lo = bisect_left(starts, t0 - maxdur - 1.0)        # safe lower bound: nothing earlier can reach t0
    hi = bisect_left(starts, t1 - 1e-6)                 # start < t1 - 1e-6
    return [b for b in blocks[lo:hi] if b.end > t0 + 1e-6 and (kinds is None or b.kind in kinds)]


def masked(text: str) -> str:
    return L.META_LEAK.sub(" ", text)


def moment_text(bs: List[Block], mask=True) -> str:
    parts = []
    for b in bs:
        if b.kind == "dialogue":
            tag = masked(" ".join(b.tags[:2])) if mask else " ".join(b.tags[:2])
            parts.append(f"{b.text} __tag_{'_'.join(tag.split())}")
        elif b.kind in ("action",):
            parts.append(masked(b.text) if mask else b.text)
    return " ".join(parts)


def hook_features(ep: Episode, s: float) -> Dict[str, float]:
    bs = overlapping(ep.blocks, s, s + HOOK_SPAN)
    dia = [b for b in bs if b.kind == "dialogue"]
    act = [b for b in bs if b.kind == "action"]
    cam = [b for b in bs if b.kind == "camera"]
    dtext = " ".join(b.text for b in dia)
    atext = " ".join(b.text for b in act + cam)
    ar = [line_arousal(ep, b) for b in dia]
    ar = [a for a in ar if a is not None]
    first_line = dia[0].text if dia else ""
    prev = [b for b in ep.blocks if b.kind == "dialogue" and b.end <= s + 0.05]
    prev_gap = min(s - prev[-1].end, 5.0) if prev else 5.0
    same_spk = bool(prev and dia and prev[-1].speaker == dia[0].speaker and prev_gap < 1.5)
    est = any(re.search(r"\b(wide|establishing|exterior|aerial|panning shot across)\b", b.text, re.I) for b in cam)
    return {
        "h_has_dialogue": float(bool(dia)),
        "h_first_line_at": (dia[0].start - s) if dia else HOOK_SPAN,
        "h_action_lex": float(len(L.HOOK_ACTION.findall(atext))),
        "h_line_lex": float(len(L.HOOK_LINE.findall(dtext))),
        "h_arousal_max": max(ar) if ar else 0.0,
        "h_excl": float(dtext.count("!")),
        "h_question": float("?" in dtext),
        "h_you": float(bool(re.search(r"\byou\b", dtext, re.I))),
        "h_vader_abs": abs(vader(dtext)),
        "h_establishing": float(est and not dia),
        "h_dangling": float(bool(first_line) and bool(L.DANGLING_START.match(first_line))),
        "h_closeup": float(any(re.search(r"close-up|extreme close", b.text, re.I) for b in cam)),
        "h_empty": float(not dia and not act),
        "h_prev_gap": prev_gap,
        "h_mid_speech": float(same_spk),
        "h_relief": float(vader(dtext) >= 0.5),
    }


def cliff_features(ep: Episode, e: float) -> Dict[str, float]:
    bs = overlapping(ep.blocks, e - CLIFF_SPAN, e)
    dia = [b for b in bs if b.kind == "dialogue"]
    act = [b for b in bs if b.kind == "action"]
    last = dia[-1].text if dia else ""
    dtext = " ".join(b.text for b in dia)
    atext = masked(" ".join(b.text for b in act))
    ar = [line_arousal(ep, b) for b in dia]
    ar = [a for a in ar if a is not None]
    after = [b for b in ep.blocks if b.start >= e - 1e-6 and b.kind == "dialogue"][:1]
    gap = (after[0].start - e) if after else 99.0
    return {
        "c_has_dialogue": float(bool(dia)),
        "c_last_q": float(last.rstrip().endswith("?")),
        "c_last_ellipsis": float(last.rstrip().endswith(("...", "…", "—", "-"))),
        "c_last_excl": float(last.rstrip().endswith("!")),
        "c_line_lex": float(len(L.CLIFF_LINE.findall(dtext))),
        "c_action_lex": float(len(L.CLIFF_ACTION.findall(atext))),
        "c_resolve_lex": float(len(L.RESOLVE.findall(atext + " " + dtext))),
        "c_arousal_max": max(ar) if ar else 0.0,
        "c_arousal_last": ar[-1] if ar else 0.0,
        "c_vader": vader(dtext),
        "c_line_len": float(len(last.split())),
        "c_secs_since_line": (e - dia[-1].end) if dia else CLIFF_SPAN,
        "c_answer_gap": min(gap, 10.0),     # an answer arriving right after the cut = less suspense lost
    }


def cliff_text(ep: Episode, e: float) -> str:
    return moment_text(overlapping(ep.blocks, e - CLIFF_SPAN, e), mask=True)


def hook_text(ep: Episode, s: float) -> str:
    bs = overlapping(ep.blocks, s, s + HOOK_SPAN)
    return moment_text(bs, mask=True) + " " + " ".join(b.text for b in bs if b.kind == "camera")


_ADD = np.add.reduce


def _mean(xs) -> float:
    """Bit-identical to float(np.mean(xs)) (same SIMD reduction, then divide by n) without
    np.mean's Python-level wrapper. Note: a plain sum()/len() is NOT identical (verified)."""
    return float(_ADD(np.array(xs, dtype=float)) / len(xs))


def _relational_count(b: Block) -> int:
    """RELATIONAL only has single-token patterns, so counts over ' '.join(lines) == sum of per-line counts."""
    v = b.__dict__.get("_rel_count")
    if v is None:
        v = b.__dict__["_rel_count"] = len(L.RELATIONAL.findall(b.text))
    return v


def window_features(ep: Episode, s: float, e: float) -> Dict[str, float]:
    bs = overlapping(ep.blocks, s, e)
    dia = [b for b in bs if b.kind == "dialogue"]
    dur = e - s
    ar = [(b.start, line_arousal(ep, b)) for b in dia]
    ar = [(t, a) for t, a in ar if a is not None]
    mid = s + dur / 2
    a1 = [a for t, a in ar if t < mid]; a2 = [a for t, a in ar if t >= mid]
    speakers = {b.speaker for b in dia if not b.voiceover}
    scenes = {b.scene for b in bs}
    first = dia[0].text if dia else ""
    dia_secs = sum(min(b.end, e) - max(b.start, s) for b in dia)
    return {
        "w_dur": dur,
        "w_n_lines": float(len(dia)),
        "w_dialogue_cov": dia_secs / max(dur, 1e-6),
        "w_n_speakers": float(len(speakers)),
        "w_scene_changes": float(len(scenes) - 1),
        "w_arousal_mean": _mean([a for _, a in ar]) if ar else 0.0,
        "w_arousal_peak": float(max(a for _, a in ar)) if ar else 0.0,
        "w_escalation": (_mean(a2) - _mean(a1)) if a1 and a2 else 0.0,
        "w_relational": float(sum(_relational_count(b) for b in dia)),   # == findall over the joined text
        "w_dangling_open": float(bool(first) and bool(L.DANGLING_START.match(first))),
        "w_conflict": float(any((line_arousal(ep, b) or 0) >= 0.6 for b in dia) and len(speakers) >= 2),
    }
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

mkdir -p "promofinder"
cat > 'promofinder/models.py' <<'PROMOFINDER_V123_EOF'
"""Learned moment scorers.

* CliffhangerModel - SELF-SUPERVISED per show: the writers end (almost) every
  episode on a cliffhanger, so the final beat of each episode is a positive and
  beats far from any episode end are negatives. Writer meta-annotations
  ("cliffhanger", "cut to black", "fades out", ...) are masked out of inputs and
  positional features are excluded, so the model must learn from the *content*
  of the moment. At inference every episode is scored out-of-fold (cross-fitting)
  so a moment is never scored by a model that saw it as a training label.

* HookModel - WEAK SUPERVISION: transparent labeling functions -> generative label
  model (labelmodel.py) -> discriminative end model on text + features, also
  cross-fitted by episode.
"""
from __future__ import annotations
import numpy as np
from typing import List, Dict
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from scipy.sparse import hstack, csr_matrix
from .labelmodel import LabelModel
from . import lexicons as L

CLIFF_DENSE = ["c_has_dialogue", "c_last_q", "c_last_ellipsis", "c_last_excl", "c_line_lex",
               "c_action_lex", "c_resolve_lex", "c_arousal_max", "c_arousal_last", "c_vader", "c_line_len"]
HOOK_DENSE = ["h_has_dialogue", "h_first_line_at", "h_action_lex", "h_line_lex", "h_arousal_max",
              "h_excl", "h_question", "h_you", "h_vader_abs", "h_establishing", "h_dangling", "h_closeup", "h_empty",
              "h_prev_gap", "h_mid_speech", "h_relief"]


# Tokenisation cache (v1.2.5). Cross-fitting builds a new vectoriser per fold, and the soft-label trick
# duplicates every training text, so each text used to be tokenised ~10 times per run. The analyzer is
# the exact default sklearn one for ngram_range=(1, 2); each fold still learns its own vocabulary and IDF
# from its own training rows, so results are bit-identical (benchmarks/equivalence.py).
_ANALYZER = TfidfVectorizer(ngram_range=(1, 2)).build_analyzer()
_TOKENS: Dict[str, list] = {}


def _cached_analyzer(doc):
    toks = _TOKENS.get(doc)
    if toks is None:
        if len(_TOKENS) > 300_000:      # bound memory for very large shows
            _TOKENS.clear()
        toks = _TOKENS[doc] = _ANALYZER(doc)
    return toks


class TextFeatLR:
    """TF-IDF(text) ⊕ standardized dense features -> logistic regression."""
    def __init__(self, dense_keys, use_text=True, use_dense=True, C=1.0):
        self.dense_keys, self.use_text, self.use_dense, self.C = dense_keys, use_text, use_dense, C

    def _X(self, texts, feats, fit=False):
        mats = []
        if self.use_text:
            if fit:
                self.tf = TfidfVectorizer(analyzer=_cached_analyzer, min_df=2, sublinear_tf=True, max_features=20000)
                mats.append(self.tf.fit_transform(texts))
            else:
                mats.append(self.tf.transform(texts))
        if self.use_dense:
            D = np.array([[f[k] for k in self.dense_keys] for f in feats], dtype=float)
            if fit:
                self.sc = StandardScaler().fit(D)
            mats.append(csr_matrix(self.sc.transform(D)))
        return hstack(mats).tocsr()

    def fit(self, texts, feats, y, sample_weight=None):
        X = self._X(texts, feats, fit=True)
        self.lr = LogisticRegression(C=self.C, max_iter=2000, class_weight="balanced")
        self.lr.fit(X, y, sample_weight=sample_weight)
        return self

    def predict_proba(self, texts, feats):
        return self.lr.predict_proba(self._X(texts, feats))[:, 1]


def cliff_rule_score(f: Dict[str, float]) -> float:
    """Transparent baseline / fallback when a show is too small to self-train."""
    s = (1.2 * f["c_last_q"] + 0.8 * f["c_last_ellipsis"] + 0.4 * f["c_last_excl"]
         + 0.35 * min(f["c_line_lex"], 3) + 0.35 * min(f["c_action_lex"], 3)
         - 0.5 * min(f["c_resolve_lex"], 3) + 1.0 * f["c_arousal_last"])
    return float(1 / (1 + np.exp(-(s - 1.0))))


# ---------------- hook labeling functions ----------------
def hook_lfs(f: Dict[str, float]) -> List[int]:
    return [
        1 if f["h_action_lex"] >= 1 else 0,                       # physical shock in action/camera
        1 if f["h_line_lex"] >= 1 else 0,                         # shocking line vocabulary
        1 if f["h_arousal_max"] >= 0.8 else (-1 if f["h_has_dialogue"] and f["h_arousal_max"] <= 0.25 else 0),
        1 if f["h_excl"] >= 1 else 0,                             # exclamation
        1 if (f["h_you"] and (f["h_excl"] or f["h_question"])) else 0,  # direct confrontation
        -1 if (f["h_establishing"] and f["h_action_lex"] == 0) else 0,  # scenic opener
        -1 if f["h_empty"] else 0,                                # nothing happens
        -1 if (not f["h_has_dialogue"] and f["h_action_lex"] == 0) else 0,
        -1 if (f["h_relief"] and f["h_action_lex"] == 0 and f["h_line_lex"] == 0) else 0,  # relief/warmth
    ]

HOOK_LF_NAMES = ["action_shock", "shock_line", "arousal", "exclamation", "confrontation",
                 "establishing(-)", "empty(-)", "no_line_no_action(-)", "relief(-)"]
# NOTE (E2b error analysis): "dangling start" and "mid-speech" were removed from the hook LFs -
# they vetoed real hooks ("They arrested her!"). They now only affect the standalone score.


def cross_fit_predict(model_factory, groups, texts, feats, y, n_folds=5, sample_weight=None, seed=0):
    """Out-of-fold predictions grouped by episode. Returns np.array of probabilities."""
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    rng = np.random.RandomState(seed); rng.shuffle(uniq)
    folds = np.array_split(uniq, min(n_folds, len(uniq)))
    out = np.zeros(len(groups))
    idx_all = np.arange(len(groups))
    for fg in folds:
        te = np.isin(groups, fg); tr = ~te
        ytr = np.asarray(y)[tr]
        if len(np.unique(ytr)) < 2:
            out[te] = 0.5; continue
        m = model_factory()
        sw = None if sample_weight is None else np.asarray(sample_weight)[tr]
        m.fit([texts[i] for i in idx_all[tr]], [feats[i] for i in idx_all[tr]], ytr, sample_weight=sw)
        out[te] = m.predict_proba([texts[i] for i in idx_all[te]], [feats[i] for i in idx_all[te]])
    return out
PROMOFINDER_V123_EOF

mkdir -p "promofinder"
cat > 'promofinder/pipeline.py' <<'PROMOFINDER_V123_EOF'
"""End-to-end promo discovery: boundaries -> moment scorers -> candidates -> rank."""
from __future__ import annotations
import math, re, time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from .parser import Episode, Block, fmt_ts
from .features import (set_arousal_mode, hook_features, cliff_features, window_features, hook_text, cliff_text,
                       overlapping, HOOK_SPAN, CLIFF_SPAN)
from .models import (TextFeatLR, CLIFF_DENSE, HOOK_DENSE, cliff_rule_score, hook_lfs)
from .labelmodel import LabelModel
from .series import SeriesIndex
from . import lexicons as L

EPS = 1e-6
POS_ZONE, NEG_ZONE = 4.0, 20.0   # cliffhanger self-supervision: last 4s = pos, >20s before end = neg
VIOLENCE = re.compile(r"\b(blood\w*|branding|searing iron|stab\w*|wound\w*|lacerat\w*|whip\w*|torture\w*|"
                      r"burn\w* (?:her|you|flesh|skin)|gallows|execut\w*|hang\w*|explosion|fireball)\b", re.I)


# ---------------------------------------------------------------- boundaries
def _clip(x: float, lo: float, hi: float) -> float:
    """Same value as float(np.clip(x, lo, hi)) for finite floats, without numpy call overhead."""
    return float(min(max(x, lo), hi))


def valid_cut(ep: Episode, t: float) -> bool:
    """A cut is legal only if it does not split a line of dialogue."""
    return not any(b.kind == "dialogue" and b.start + 0.05 < t < b.end - 0.05
                   for b in overlapping(ep.blocks, t - 0.1, t + 0.1))


def boundaries(ep: Episode):
    starts = sorted({round(b.start, 2) for b in ep.blocks if b.kind in ("camera", "dialogue")})
    ends = sorted({round(b.end, 2) for b in ep.blocks if b.kind in ("camera", "dialogue")})
    starts = [s for s in starts if valid_cut(ep, s)]
    ends = [e for e in ends if valid_cut(ep, e) and e > 0]
    shot_starts = {round(b.start, 2) for b in ep.blocks if b.kind == "camera"}
    shot_ends = {round(b.end, 2) for b in ep.blocks if b.kind == "camera"}
    return starts, ends, shot_starts, shot_ends


@dataclass
class Moment:
    ep: int
    t: float
    feats: Dict[str, float]
    text: str
    score: float = 0.0
    pct: float = 0.0
    label: int = -1          # cliff self-supervision label (-1 = unlabeled)
    extra: Dict = field(default_factory=dict)


def pct_rank(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    order = x.argsort().argsort()
    return (order + 0.5) / len(x)


# ---------------------------------------------------------------- moment scoring
def build_moments(episodes: List[Episode]):
    hooks, cliffs, bnd = [], [], {}
    for ep in episodes:
        st, en, ss, se = boundaries(ep)
        bnd[ep.number] = (st, en, ss, se)
        for s in st:
            if s <= ep.duration - 2.5:
                hooks.append(Moment(ep.number, s, hook_features(ep, s), hook_text(ep, s)))
        for e in en:
            if e >= 2.5:
                lab = 1 if e >= ep.duration - POS_ZONE else (0 if e <= ep.duration - NEG_ZONE else -1)
                cliffs.append(Moment(ep.number, e, cliff_features(ep, e), cliff_text(ep, e), label=lab))
    return hooks, cliffs, bnd


def future_payoff(cliffs: List[Moment], hooks: List[Moment], episodes: List[Episode], horizon=6.0):
    """For each cut point: how strong is the moment the viewer is DENIED by cutting here?
    = best hook-score of any legal start in (t, t+horizon]. At an episode end we look into
    the next episode's opening, because the story continues there."""
    by_ep: Dict[int, List[Moment]] = {}
    for h in hooks:
        by_ep.setdefault(h.ep, []).append(h)
    dur = {e.number: e.duration for e in episodes}
    nxt = {e.number: e for e in episodes}
    for m in cliffs:
        cand = [h.score for h in by_ep.get(m.ep, []) if m.t - 0.05 <= h.t <= m.t + horizon]
        if m.t >= dur[m.ep] - 1.0 and (m.ep + 1) in nxt:
            cand += [h.score for h in by_ep.get(m.ep + 1, []) if h.t <= horizon]
        m.feats["c_payoff"] = max(cand) if cand else 0.0
        # pending answer: last line is a question and the reply comes only after the cut
        ep = nxt[m.ep]
        after = [b for b in ep.blocks if b.kind == "dialogue" and b.start >= m.t - 0.05][:1]
        if not after and (m.ep + 1) in nxt:
            after = [b for b in nxt[m.ep + 1].blocks if b.kind == "dialogue"][:1]
        last = [b for b in overlapping(ep.blocks, m.t - CLIFF_SPAN, m.t, {"dialogue"})][-1:]
        m.feats["c_pending_answer"] = float(bool(last and after and last[0].text.rstrip().endswith("?")
                                                 and after[0].speaker != last[0].speaker))


def cliff_v2_score(f: Dict[str, float]) -> float:
    """A-priori weights (not fit to any labels): open content + withheld payoff - closure."""
    v = (0.40 * cliff_rule_score(f) + 0.35 * f["c_payoff"] + 0.15 * f["c_pending_answer"]
         + 0.10 * f["c_arousal_last"] - 0.25 * min(f["c_resolve_lex"], 3) / 3)
    return _clip(v, 0, 1)


def score_cliffs(cliffs: List[Moment], mode="withheld_payoff", blend=0.7, n_folds=5, seed=0, C=1.0,
                 hooks=None, episodes=None):
    if mode == "withheld_payoff":
        future_payoff(cliffs, hooks, episodes)
        for m in cliffs:
            m.score = cliff_v2_score(m.feats); m.extra["model"] = "withheld_payoff_v2"
        return
    rules = np.array([cliff_rule_score(m.feats) for m in cliffs])
    groups = np.array([m.ep for m in cliffs]); labels = np.array([m.label for m in cliffs])
    n_pos = int((labels == 1).sum()); eps_ = np.unique(groups)
    if mode != "self_supervised" or n_pos < 8 or len(eps_) < 4:
        for m, r in zip(cliffs, rules):
            m.score = float(r); m.extra["model"] = "rules"
        return
    out = np.zeros(len(cliffs))
    rng = np.random.RandomState(seed); order = eps_.copy(); rng.shuffle(order)
    for fold in np.array_split(order, min(n_folds, len(order))):
        te = np.isin(groups, fold); tr = (~te) & (labels >= 0)
        model = TextFeatLR(CLIFF_DENSE, C=C).fit([cliffs[i].text for i in np.where(tr)[0]],
                                                [cliffs[i].feats for i in np.where(tr)[0]], labels[tr])
        idx = np.where(te)[0]
        out[idx] = model.predict_proba([cliffs[i].text for i in idx], [cliffs[i].feats for i in idx])
    final = blend * out + (1 - blend) * rules
    for m, f, o in zip(cliffs, final, out):
        m.score = float(f); m.extra["model_oof"] = float(o); m.extra["model"] = "self_supervised+rules"


def score_hooks(hooks: List[Moment], mode="weak_supervision", n_folds=5, seed=0, progress=None):
    """progress(k, n) is called after each cross-fitted fold (UI only; results are unaffected)."""
    Lm = np.array([hook_lfs(m.feats) for m in hooks])
    lm = LabelModel().fit(Lm)
    p_lm = lm.predict_proba(Lm)
    # the end model is cross-fitted by episode, so it needs >= 2 episodes to have any training data
    if mode != "weak_supervision" or len(hooks) < 50 or len({m.ep for m in hooks}) < 2:
        for m, p in zip(hooks, p_lm):
            m.score = float(p); m.extra["model"] = "label_model"
        return lm
    groups = np.array([m.ep for m in hooks]); eps_ = np.unique(groups)
    out = np.zeros(len(hooks))
    rng = np.random.RandomState(seed); order = eps_.copy(); rng.shuffle(order)
    folds = np.array_split(order, min(n_folds, len(order)))
    for k, fold in enumerate(folds):
        if progress:
            progress(k, len(folds))
        te = np.isin(groups, fold); tr = np.where(~te)[0]
        # soft labels -> duplicated rows with probability weights
        texts = [hooks[i].text for i in tr] * 2
        feats = [hooks[i].feats for i in tr] * 2
        y = np.r_[np.ones(len(tr)), np.zeros(len(tr))]
        w = np.r_[p_lm[tr], 1 - p_lm[tr]]
        m = TextFeatLR(HOOK_DENSE).fit(texts, feats, y, sample_weight=w)
        idx = np.where(te)[0]
        out[idx] = m.predict_proba([hooks[i].text for i in idx], [hooks[i].feats for i in idx])
    for m, a, b in zip(hooks, p_lm, out):
        m.score = float(0.5 * a + 0.5 * b); m.extra.update(model="ws_label+end_model", lm=float(a), end=float(b))
    return lm


# ---------------------------------------------------------------- candidates
@dataclass
class Segment:
    episode: int
    start: float
    end: float

    @property
    def dur(self):
        return self.end - self.start


@dataclass
class Candidate:
    segments: List[Segment]
    kind: str                         # single | cross_episode | cold_open
    hook: Moment
    cliff: Moment
    comps: Dict[str, float] = field(default_factory=dict)
    wfeat: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    flags: List[str] = field(default_factory=list)
    text: str = ""
    _dia: list = field(default_factory=list, repr=False)   # dialogue blocks in the clip (for exact fast paths)

    @property
    def dur(self):
        return sum(s.dur for s in self.segments)


def clear_caches():
    """Drop module-level speed-up caches (results are unaffected; they only hold references)."""
    from . import features
    features._OV_INDEX.clear(); _VIOL_CACHE.clear(); _JUNC_CACHE.clear()


_VIOL_CACHE: dict = {}


def _viol_piece(t: str) -> bool:
    v = _VIOL_CACHE.get(t)
    if v is None:
        if len(_VIOL_CACHE) > 200000:
            _VIOL_CACHE.clear()
        v = _VIOL_CACHE[t] = bool(VIOLENCE.search(t))
    return v


def violence_flag(c) -> bool:
    """== bool(VIOLENCE.search(c.text + ' ' + c.cliff.text + ' ' + c.hook.text)), computed per piece.
    Every VIOLENCE pattern spans at most two space-separated tokens, so a match either lies inside
    one piece or straddles one junction; junctions are checked with the two tokens on each side."""
    pieces = [b.text for b in c._dia] if c._dia else [""]
    pieces += [c.cliff.text, c.hook.text]
    if any(_viol_piece(p) for p in pieces):
        return True
    for a, b in zip(pieces, pieces[1:]):
        if _viol_junction(a, b):
            return True
    return False


_JUNC_CACHE: dict = {}


def _viol_junction(a: str, b: str) -> bool:
    k = (a, b)
    v = _JUNC_CACHE.get(k)
    if v is None:
        if len(_JUNC_CACHE) > 200000:
            _JUNC_CACHE.clear()
        v = _JUNC_CACHE[k] = _viol_piece(" ".join(a.split(" ")[-2:]) + " " + " ".join(b.split(" ")[:2]))
    return v


def opens_on_answer(sg, eps, max_gap=3.0) -> bool:
    """True if the clip's first line replies to a question the viewer never hears
    (asked by another speaker just before the cut - possibly at the end of the previous episode)."""
    ep = eps[sg.episode]
    first = overlapping(ep.blocks, sg.start, sg.end, {"dialogue"})[:1]
    if not first:
        return False
    prev = [b for b in ep.blocks if b.kind == "dialogue" and b.end <= sg.start + 0.05]
    gap = (first[0].start - prev[-1].end) if prev else None
    if not prev and sg.start < 1.0 and (sg.episode - 1) in eps:
        prev = [b for b in eps[sg.episode - 1].blocks if b.kind == "dialogue"]
        gap = first[0].start + (eps[sg.episode - 1].duration - prev[-1].end) if prev else None
    if not prev or gap is None:
        return False
    q = prev[-1]
    return q.text.rstrip().endswith("?") and q.speaker != first[0].speaker and gap < max_gap


def stability(picks, longlist, cfg, draws=200, spread=0.5, seed=0):
    """How much should an editor trust a pick's place? Fraction of random weight settings
    (each weight x U(1-spread, 1+spread)) under which the pick still ranks in the top-N of
    the diverse longlist. Not a probability of being 'good' - a robustness-to-our-guesses signal."""
    pool = list({id(c): c for c in list(longlist) + list(picks)}.values())
    if not pool:
        return
    W = cfg["weights"]; keys = list(W); n = cfg["top_n"]
    rng = np.random.RandomState(seed)
    logc = np.array([[math.log(max(c.comps[k], 0.02)) for k in keys] for c in pool])
    extra = np.array([c.comps["duration_fit"] * c.comps["funnel"] * (1 - c.comps.get("_penalty", 0.0)) for c in pool])
    base = np.array([W[k] for k in keys])
    def ranks(w):
        sc = np.exp(logc @ w / w.sum()) * extra
        r = np.empty(len(pool), int); r[np.argsort(-sc)] = np.arange(len(pool)); return r
    pick_idx = [i for i, c in enumerate(pool) if any(c is p for p in picks)]
    cutoff = max(ranks(base)[pick_idx]) if pick_idx else n - 1   # every pick is "in" at the default weights
    hits = np.zeros(len(pool))
    for _ in range(draws):
        hits += ranks(base * rng.uniform(1 - spread, 1 + spread, len(keys))) <= cutoff
    for c, h in zip(pool, hits / draws):
        c.comps["stability"] = round(float(h), 3)


def total_score(comps, W, funnel=True):
    """Weighted geometric mean of components x duration fit x funnel prior x edit penalty."""
    ws = sum(W.values()) or 1.0
    logs = sum(W[k] * math.log(max(comps[k], 0.02)) for k in W) / ws
    return float(math.exp(logs) * comps["duration_fit"] * (comps["funnel"] if funnel else 1.0) * (1 - comps.get("_penalty", 0.0)))


class PromoFinder:
    def __init__(self, cfg):
        self.cfg = cfg

    # -- component scores for one candidate
    def _components(self, c: Candidate, eps: Dict[int, Episode], series: SeriesIndex):
        cfg = self.cfg
        dia_all, wf_list = [], []
        for sg in c.segments:
            ep = eps[sg.episode]
            wf_list.append((window_features(ep, sg.start, sg.end), sg.dur))
            dia_all += overlapping(ep.blocks, sg.start, sg.end, {"dialogue"})
        # duration-weighted merge of window features
        keys = wf_list[0][0].keys(); tot = sum(d for _, d in wf_list)
        wf = {k: sum(f[k] * d for f, d in wf_list) / tot for k in keys}
        for k in ("w_n_lines", "w_relational", "w_scene_changes"):
            wf[k] = sum(f[k] for f, _ in wf_list)
        wf["w_arousal_peak"] = max(f["w_arousal_peak"] for f, _ in wf_list)
        wf["w_dangling_open"] = wf_list[0][0]["w_dangling_open"]
        k0 = (c.segments[0].episode, c.segments[0].start)      # depends only on where the clip starts
        ao = self._ooa_cache.get(k0)
        if ao is None:
            ao = self._ooa_cache[k0] = float(opens_on_answer(c.segments[0], eps))
        wf["w_answer_open"] = ao
        wf["w_n_speakers"] = float(len({b.speaker for b in dia_all if not b.voiceover}))
        refs = series.unintroduced_refs(c.segments[0].episode, dia_all)
        wf["w_unintroduced"] = float(len(refs))
        c.wfeat = wf
        # standalone: can a stranger follow it?
        sa = (0.55 + 0.07 * min(wf["w_relational"], 4) - 0.22 * max(wf["w_dangling_open"], wf["w_answer_open"])
              - 0.12 * min(wf["w_scene_changes"], 3) - 0.08 * min(wf["w_unintroduced"], 3)
              + 0.25 * (min(wf["w_dialogue_cov"], 0.8) - 0.4)
              + (0.05 if 2 <= wf["w_n_speakers"] <= 4 else -0.05)
              - (0.15 if wf["w_n_lines"] < 3 else 0.0))
        arc = (0.45 * wf["w_arousal_peak"] + 0.25 * wf["w_arousal_mean"]
               + 0.2 * _clip(0.5 + wf["w_escalation"], 0, 1) + 0.1 * wf["w_conflict"])
        c.comps = {"hook": c.hook.pct, "cliff": c.cliff.pct,
                   "standalone": _clip(sa, 0.02, 1), "arc": _clip(arc, 0.02, 1)}
        c.text = " ".join(b.text for b in dia_all)
        c._dia = dia_all
        if refs:
            c.flags.append("needs context: mentions " + ", ".join(sorted(refs)))
        if wf["w_answer_open"]:
            c.flags.append("opens on a reply to an unheard question")
        elif wf["w_dangling_open"]:
            c.flags.append("opens mid-exchange")
        if wf["w_scene_changes"] >= 1 and c.kind == "single":
            c.flags.append("crosses a scene/location change")

    def _finalise(self, cands: List[Candidate], series: SeriesIndex, n_eps_max: int):
        cfg = self.cfg; W = cfg["weights"]
        prem = pct_rank(series.premise_sim_windows([c._dia for c in cands])) if cands else []
        lo, hi = cfg["ideal_dur"]
        for c, p in zip(cands, prem):
            c.comps["premise"] = float(p)
            d = c.dur
            dur_fit = 1.0 if lo <= d <= hi else 1 - 0.15 * (min(abs(d - lo), abs(d - hi)) / max(lo - cfg["min_dur"], cfg["max_dur"] - hi))
            pen = 0.0
            if c.kind == "cold_open":
                pen += cfg["cold_open_penalty"]
            if c.kind == "cross_episode":
                pen += cfg["cross_episode_penalty"]
            funnel = 1.0
            if cfg["funnel"]["enabled"] and n_eps_max > 1:
                pos = (c.segments[0].episode - 1) / (n_eps_max - 1)
                funnel = 1 - cfg["funnel"]["late_episode_penalty"] * pos ** 2
            c.comps["duration_fit"] = round(dur_fit, 3); c.comps["funnel"] = round(funnel, 3)
            c.comps["_penalty"] = pen
            c.score = total_score(c.comps, W)
            if c.cliff.feats["c_resolve_lex"] >= 2 and c.cliff.feats["c_last_q"] == 0:
                c.flags.append("ending may feel resolved")
            if violence_flag(c):
                c.flags.append("ad-policy review: violence/injury")
            if (c.segments[0].episode - 1) / max(n_eps_max - 1, 1) > 0.66:
                c.flags.append("late-series: may spoil major reveals")

    def run(self, show: str, episodes: List[Episode], progress=None):
        """progress(stage_label, fraction_done) is called between stages (e.g. by the web app)."""
        cfg = self.cfg
        self._ooa_cache = {}     # per run: (episode, start) -> opens-on-answer (51,598 calls -> 2,846 distinct)
        timings, clock = {}, [time.perf_counter()]

        def stage(done_label, frac, next_label):
            now = time.perf_counter(); timings[done_label] = round(now - clock[0], 3); clock[0] = now
            if progress:
                progress(next_label, frac)

        if progress:
            progress("Indexing the series", 0.02)
        eps = {e.number: e for e in episodes}
        # delivery-tag coverage decides how line intensity is measured (v1.1, see exp5_tagfree)
        n_dia = sum(1 for e in episodes for b in e.blocks if b.kind == "dialogue")
        tag_cov = sum(1 for e in episodes for b in e.blocks if b.kind == "dialogue" and b.tags) / max(n_dia, 1)
        mode = cfg.get("arousal_mode", "auto")
        if mode == "auto":
            mode = "tags" if tag_cov >= 0.5 else "fallback"
        set_arousal_mode(mode)
        series = SeriesIndex(show, episodes)
        stage("series_index", 0.05, "Finding every legal cut point")
        hooks, cliffs, bnd = build_moments(episodes)
        stage("cut_points_and_moment_features", 0.12, "Scoring hooks (weak supervision)")
        lm = score_hooks(hooks, cfg["hook_model"], progress=(lambda k, n: progress(
            f"Scoring hooks (weak supervision) · model {k + 1} of {n}", 0.12 + 0.12 * k / n)) if progress else None)
        stage("hook_model", 0.24, "Scoring cliffhangers")
        score_cliffs(cliffs, cfg["cliff_model"], blend=cfg.get("cliff_blend", 0.7), hooks=hooks, episodes=episodes)
        for arr in (hooks, cliffs):
            p = pct_rank(np.array([m.score for m in arr]))
            for m, v in zip(arr, p):
                m.pct = float(v)
        stage("cliff_model", 0.28, "Generating candidate clips")
        H = {(m.ep, m.t): m for m in hooks}; Cm = {(m.ep, m.t): m for m in cliffs}
        cands: List[Candidate] = []
        # 1) single continuous windows
        for ep in episodes:
            st, en, ss, se = bnd[ep.number]
            for s in st:
                if (ep.number, s) not in H:
                    continue
                for e in en:
                    d = e - s
                    if d < cfg["min_dur"] or d > cfg["max_dur"]:
                        continue
                    if e > s and (ep.number, e) in Cm:
                        cands.append(Candidate([Segment(ep.number, s, e)], "single", H[(ep.number, s)], Cm[(ep.number, e)]))
        # 2) cross-episode bridges (story is continuous across episode cuts)
        if cfg["allow_cross_episode"]:
            nums = sorted(eps)
            for a, b in zip(nums, nums[1:]):
                if b != a + 1:
                    continue
                ea, eb = eps[a], eps[b]
                st_a = [s for s in bnd[a][0] if ea.duration - s >= 6 and (a, s) in H]
                en_b = [e for e in bnd[b][1] if e >= 8 and (b, e) in Cm]
                for s in st_a:
                    for e in en_b:
                        d = (ea.duration - s) + e
                        if cfg["min_dur"] <= d <= cfg["max_dur"]:
                            cands.append(Candidate([Segment(a, s, ea.duration), Segment(b, 0.0, e)],
                                                   "cross_episode", H[(a, s)], Cm[(b, e)]))
        stage("candidate_generation", 0.30, f"Scoring {len(cands):,} candidate clips")
        for i, c in enumerate(cands):
            self._components(c, eps, series)
            if progress and i % 5000 == 4999:
                progress(f"Scoring {len(cands):,} candidate clips", 0.30 + 0.45 * (i + 1) / len(cands))
        stage("clip_components", 0.75, "Premise fit and final scores")
        self._finalise(cands, series, max(eps))
        stage("premise_and_total_score", 0.82, "Cold-open edits")
        # 3) cold opens: best short hook snippet + strong body from same/adjacent episode
        if cfg["allow_cold_open"] and cands:
            cands += self._cold_opens(cands, hooks, bnd, eps, series)
        stage("cold_opens", 0.86, "Choosing a diverse top list")
        cands.sort(key=lambda c: -c.score)
        picks = self._select(cands, series, cfg["top_n"])
        longlist = self._select(cands, series, cfg["longlist_n"])
        stage("diverse_selection", 0.95, "Checking pick stability")
        stability(picks, longlist, cfg)
        stage("stability", 0.97, "Writing outputs")
        clear_caches()   # long-running servers: don't keep this show's blocks alive via speed-up caches
        return {"timings": timings, "arousal_mode": mode, "tag_coverage": round(tag_cov, 3), "show": show, "episodes": episodes, "series": series, "hooks": hooks, "cliffs": cliffs,
                "candidates": cands, "top": picks, "longlist": longlist, "label_model": lm}

    def _cold_opens(self, cands, hooks, bnd, eps, series):
        cfg = self.cfg
        top_h = sorted(hooks, key=lambda m: -m.score)[:60]
        # bodies with a strong cliffhanger/standalone story but a weaker opening benefit most
        bodies = sorted((c for c in cands if c.kind == "single"),
                        key=lambda c: -(c.comps["cliff"] * c.comps["standalone"] * c.comps["arc"]))[:600]
        out = []
        for h in top_h:
            ep = eps[h.ep]
            ends = [e for e in bnd[h.ep][1] if 2.5 <= e - h.t <= 7.0]
            if not ends:
                continue
            he = ends[-1]
            hd = overlapping(ep.blocks, h.t, he, {"dialogue"})
            hspk = {b.speaker.split()[-1] for b in hd}
            for body in bodies:
                sg = body.segments[0]
                if abs(sg.episode - h.ep) > 1 or body.comps["hook"] >= h.pct:
                    continue
                if sg.episode == h.ep and not (he <= sg.start or h.t >= sg.end):
                    continue  # snippet must not overlap the body
                if sg.dur + (he - h.t) > cfg["max_dur"]:
                    continue
                bd = overlapping(eps[sg.episode].blocks, sg.start, sg.end, {"dialogue"})
                if not hspk & {b.speaker.split()[-1] for b in bd}:
                    continue  # same characters -> coherent story
                c = Candidate([Segment(h.ep, h.t, he), Segment(sg.episode, sg.start, sg.end)], "cold_open", h, body.cliff)
                out.append(c)
                break
        for c in out:
            self._components(c, eps, series)
        self._finalise(out, series, max(eps))
        return out

    def _select(self, cands: List[Candidate], series: SeriesIndex, n: int):
        """Greedy MMR: high score, no time overlap, <=k per episode, content diversity."""
        cfg = self.cfg
        # pool = global top + top-k of every episode, so the longlist is not starved by a few episodes
        per = {}
        for c in cands:
            per.setdefault(c.segments[0].episode, []).append(c)
        keep = {id(c) for c in cands[: max(2000, n * 40)]}
        for lst in per.values():
            keep |= {id(c) for c in lst[:40]}
        pool = [c for c in cands if id(c) in keep]
        if not pool:
            return []
        E = series.embed_windows([c._dia for c in pool])
        return [pool[i] for i in mmr_select(pool, E, n, cfg["mmr_lambda"], cfg["max_per_episode"])]


def mmr_select(pool, E, n, lam, max_per_ep):
    """Vectorised greedy MMR, same rule as the original loop: among candidates whose episodes
    still have room and that do not overlap a chosen clip (0.5 s tolerance), take the first one
    maximising (1-lam)*score - lam*maxsim*score, where maxsim is the highest cosine to any chosen clip."""
    N = len(pool)
    K = max(len(c.segments) for c in pool)
    seg_ep = np.full((N, K), -1, dtype=np.int64); seg_s = np.zeros((N, K)); seg_e = np.zeros((N, K))
    for i, c in enumerate(pool):
        for k, sg in enumerate(c.segments):
            seg_ep[i, k], seg_s[i, k], seg_e[i, k] = sg.episode, sg.start, sg.end
    valid = seg_ep >= 0
    score = np.array([c.score for c in pool], dtype=float)
    blocked = np.zeros(N, dtype=bool)          # chosen or overlapping a chosen clip
    maxsim = np.full(N, -np.inf)
    ep_count = {}
    chosen = []
    while len(chosen) < n:
        full = np.zeros(N, dtype=bool)
        for ep, cnt in ep_count.items():
            if cnt >= max_per_ep:
                full |= ((seg_ep == ep) & valid).any(axis=1)
        ok = ~blocked & ~full
        if not ok.any():
            break
        sim = maxsim if chosen else np.zeros(N)
        v = np.where(ok, (1 - lam) * score - lam * sim * score, -np.inf)
        best = int(np.argmax(v))
        if not np.isfinite(v[best]) or v[best] <= -1e9:
            break
        chosen.append(best); blocked[best] = True
        for sg in pool[best].segments:
            ep_count[sg.episode] = ep_count.get(sg.episode, 0) + 1
            hit = (seg_ep == sg.episode) & valid & (seg_s < sg.end - 0.5) & (sg.start < seg_e - 0.5)
            blocked |= hit.any(axis=1)
        maxsim = np.maximum(maxsim, E @ E[best])
    return chosen


def _overlap(a: Candidate, b: Candidate) -> bool:
    for x in a.segments:
        for y in b.segments:
            if x.episode == y.episode and x.start < y.end - 0.5 and y.start < x.end - 0.5:
                return True
    return False
PROMOFINDER_V123_EOF

mkdir -p "promofinder"
cat > 'promofinder/series.py' <<'PROMOFINDER_V123_EOF'
"""Show-level context: premise vector, entity introductions, semantic space."""
from __future__ import annotations
import re
import numpy as np
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
from . import lexicons as L

NAME_RX = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b")
NOT_NAMES = {"Lady", "Lord", "Sir", "Your", "Grace", "Father", "Mother", "Duke", "Duchess", "God",
             "The", "This", "That", "What", "Why", "How", "Who", "Where", "When", "Then", "Now", "Yes", "No",
             "Please", "Madam", "Majesty", "Highness", "Tomorrow", "Tonight", "Crown", "Constable", "Ten",
             "Manor", "Hall", "House", "Abbey", "Castle", "County", "Estate", "Church", "Chapel", "Court",
             "Council", "King", "Queen", "Prince", "Princess", "Sir", "Mister", "Miss", "Mrs", "Heaven",
             "England", "London", "Monday", "Sunday", "Christmas", "Saint", "Captain", "Master", "Mistress"}


ROLE_WORDS = {"Former", "Groom", "Bride", "Bearded", "Stranger", "Mysterious", "Blond", "Nobleman", "Noblewoman",
              "Maid", "Guard", "Guards", "Royal", "Judge", "High", "Priest", "Elder", "Villager", "Peasant", "Thug",
              "Cap", "Tall", "Third", "Informant", "Official", "Police", "Housekeeper", "Matriarch", "Noble", "Woman",
              "Man", "Boy", "Girl", "Old", "Young", "Aristocratic", "Scarred", "Gown", "Gold", "Dowager", "Loyalist",
              "Scout", "Fighter", "Sentry", "Driver", "Cart", "Butler", "Servant", "Soldier", "Captain", "Doctor",
              "With", "And", "The", "Lady", "Lord", "Father"}


class SeriesIndex:
    def __init__(self, show_name, episodes):
        self.show_name = show_name
        self.episodes = {e.number: e for e in episodes}
        docs = [" ".join(b.text for b in e.blocks if b.kind in ("dialogue", "action")) for e in episodes]
        self.tfidf = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=1, ngram_range=(1, 1))
        X = self.tfidf.fit_transform(docs)
        k = max(2, min(64, X.shape[0] - 1, X.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=k, random_state=0).fit(X)
        # premise: the title is what the promo is ultimately selling
        e1 = episodes[0] if episodes else None
        prem = show_name.replace(".", " ") + " " + (e1.logline if e1 and e1.number == 1 else "")
        self.premise_text = prem
        self.premise_vec = self.tfidf.transform([prem])
        # known character names: speaker-header tokens that are also used capitalised in dialogue
        # (catches sentence-initial mentions such as "Reyes paid them!")
        spk_tokens = {w.title() for e in episodes for b in e.blocks if b.kind == "dialogue"
                      for w in re.findall(r"[A-Za-z]{3,}", b.speaker)}
        dia_caps = {t for e in episodes for b in e.blocks if b.kind == "dialogue" for t in re.findall(r"\b[A-Z][a-z]{2,}\b", b.text)}
        self.known_names = {t for t in spk_tokens & dia_caps if t not in NOT_NAMES and t not in ROLE_WORDS}
        # first appearance of proper names (speakers + capitalised mentions)
        self.first_seen = {}
        for e in episodes:
            for b in e.blocks:
                if b.kind != "dialogue":
                    continue
                for nm in self._names(b.text):
                    self.first_seen.setdefault(nm, e.number)

    def _names(self, text):
        cache = self.__dict__.setdefault("_names_cache", {})
        if text not in cache:
            cache[text] = frozenset(self._names_uncached(text))
        return cache[text]

    def _names_uncached(self, text):
        out = {t for t in re.findall(r"\b[A-Z][a-z]{2,}\b", text) if t in getattr(self, "known_names", ())}
        for sent in re.split(r"(?<=[.!?…])\s+", text):
            toks = re.findall(r"\b[A-Z][a-z]{2,}\b", sent)
            # skip the sentence-initial token (capitalised anyway)
            first = re.match(r"\W*([A-Z][a-z]{2,})", sent)
            for t in toks:
                if first and t == first.group(1) and sent.strip().startswith(t):
                    continue
                if t not in NOT_NAMES:
                    out.add(t)
        return out

    # ---- exact fast path: window TF-IDF from per-line term counts --------------------
    def _block_counts(self, blocks):
        """Term counts per dialogue line (cached). Token streams of ' '.join(lines) are the
        concatenation of each line's tokens, so a window's counts are the sum of its lines'."""
        from sklearn.feature_extraction.text import CountVectorizer
        if not hasattr(self, "_cv"):
            t = self.tfidf
            self._cv = CountVectorizer(vocabulary=t.vocabulary_, stop_words=t.stop_words, lowercase=t.lowercase,
                                       token_pattern=t.token_pattern, ngram_range=t.ngram_range)
            self._row = {}; self._rows = []
        new = list({id(b): b for b in blocks if id(b) not in self._row}.values())
        if new:
            X = self._cv.transform([b.text for b in new])
            for b, i in zip(new, range(len(self._rows), len(self._rows) + len(new))):
                self._row[id(b)] = i
            self._rows.append(X)
            from scipy.sparse import vstack
            self._C = vstack(self._rows).tocsr() if len(self._rows) > 1 else self._rows[0].tocsr()
            self._rows = [self._C]
        return self._C

    def window_tfidf(self, block_lists):
        """Exactly tfidf.transform([' '.join(b.text for b in L) for L in block_lists])."""
        from scipy.sparse import csr_matrix
        flat = [b for L in block_lists for b in L]
        C = self._block_counts(flat) if flat else None
        if C is None:
            return csr_matrix((len(block_lists), len(self.tfidf.vocabulary_)))
        rows, cols = [], []
        for i, L in enumerate(block_lists):
            for b in L:
                rows.append(i); cols.append(self._row[id(b)])
        M = csr_matrix((np.ones(len(rows), dtype=C.dtype), (rows, cols)), shape=(len(block_lists), C.shape[0]))
        counts = (M @ C).tocsr(); counts.sum_duplicates(); counts.sort_indices()
        return self.tfidf._tfidf.transform(counts)

    def embed_windows(self, block_lists):
        return normalize(self.svd.transform(self.window_tfidf(block_lists)))

    def premise_sim_windows(self, block_lists):
        V = self.window_tfidf(block_lists)
        return np.asarray((normalize(V) @ normalize(self.premise_vec).T).todense()).ravel()

    def embed(self, texts):
        return normalize(self.svd.transform(self.tfidf.transform(texts)))

    def premise_sim(self, texts):
        V = self.tfidf.transform(texts)
        return np.asarray((normalize(V) @ normalize(self.premise_vec).T).todense()).ravel()

    def unintroduced_refs(self, ep_no, dia_blocks):
        """Names mentioned in-window that were introduced in an EARLIER episode and who do
        not themselves speak in the window: a stranger will not know who they are.
        Memoised per series on the exact (episode, lines) key: clips that differ only by a camera-shot
        boundary contain the same lines (51,598 calls -> 14,958 distinct on the 50-episode pack)."""
        key = (ep_no, tuple((b.episode, b.idx) for b in dia_blocks))
        cache = self.__dict__.setdefault("_refs_cache", {})
        hit = cache.get(key)
        if hit is None:
            hit = cache[key] = frozenset(self._unintroduced_refs(ep_no, dia_blocks))
        return set(hit)

    def _unintroduced_refs(self, ep_no, dia_blocks):
        speakers = " ".join(b.speaker.title() for b in dia_blocks)
        refs = set()
        for b in dia_blocks:
            for nm in self._names(b.text):
                if self.first_seen.get(nm, ep_no) < ep_no and nm not in speakers:
                    refs.add(nm)
        return refs
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
    buildCommand: pip install -r requirements.txt && python app.py --prebuild-demo   # demo scored at build time, not on the 0.1-CPU instance
    startCommand: gunicorn -c gunicorn.conf.py app:app
    healthCheckPath: /healthz
    autoDeploy: true
    envVars:
      - key: PROMOFINDER_PUBLIC
        value: "1"
      - key: PYTHONUTF8
        value: "1"
      # one maths thread: the free instance gets 0.1 CPU, so BLAS/OpenMP threads per visible host core
      # would only compete with each other (measured: no slowdown on a normal machine)
      - key: OMP_NUM_THREADS
        value: "1"
      - key: OPENBLAS_NUM_THREADS
        value: "1"
      - key: MKL_NUM_THREADS
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


# ---- v1.2.5: deploy-time demo + diagnostics
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
PROMOFINDER_V123_EOF

mkdir -p "tests"
cat > 'tests/test_core.py' <<'PROMOFINDER_V123_EOF'
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
PROMOFINDER_V123_EOF

ok "13 files written: .dockerignore .gitignore Dockerfile app.py promofinder/__init__.py promofinder/features.py promofinder/ingest.py promofinder/models.py promofinder/pipeline.py promofinder/series.py render.yaml tests/test_app.py tests/test_core.py"

# ---------------------------------------------------------------- 5. verify every project file
say "5/8 Verifying the whole project against the v1.2.5 fingerprints"
cat > .pf_manifest.json <<'PROMOFINDER_MANIFEST_EOF'
{".dockerignore": "9a8c182e0b40fa05d2adf2b506f592a9fd562a2b4ea1d0a6c4636cb3502cb360", ".gitignore": "d2ec767d3b8e160d866b84fd84f5acaeed5132c0ece6b6b183bc32e1d8127ec1", ".python-version": "02e735b3dfe1c32833eb550b7ff8ffa17f5f2bc3fa1e7bae61a8f5a3883ce398", "Dockerfile": "c9724080f2a3ffca9a037775df279aa5af542cb9a7425e869a33e78d9b0c642e", "app.py": "f3ea274480b375c3b728788cb4ca7f81491bdd5d8d951d8f096241d22696c7f7", "benchmarks/bench.py": "1bc7582dcdf3fb922d60a0f94d94ea5d1b82991dd8c16816f66ce4b3ae6be996", "benchmarks/equivalence.py": "08d604f9c50dd1ee1b3628d84d81c0552efe1feb86d926a5a6f1933b586eb667", "config.yaml": "50312986ff9edfb1f116ce815742f18dad958b8b800c998efa257db3679c54ba", "gunicorn.conf.py": "4b559cf8b188b082637be867cb1646147ac3b7d2e9ac178b92680fe9a2726d32", "promofinder/__init__.py": "f59a5bf54685d2dd19d5cebe3a2efcd5a790a0dc41a39eea2a5fcd5c57557b61", "promofinder/__main__.py": "cf7390a2508a0fcad4777a4a629fc5212ab655cb45845975995f835676a834e3", "promofinder/cli.py": "be72fa446a776ee558875f092b28d078cede222440e4ef4d30be4448ed96d6f7", "promofinder/config.py": "8f19c0e6fa351d649dac5a3d502424cf8955e56f4f6e13bb49de1184746c7672", "promofinder/edl.py": "fb37467f71682fc6c65212ae9a42a95e8c88257ec9f091ded9881e95045f47fa", "promofinder/explain.py": "2fa1ee9193843d93070bc8d7eadf511f645623193d7f609b529a7d3079df0516", "promofinder/export.py": "d860cd881a29a2d40a48cdf5dc5fbc78bed1496462110371b44f22333ff553cd", "promofinder/features.py": "fa76886ae290d00e5edb224fb045d004ad4f6a1486261e8ac03655d97ccb27e3", "promofinder/ingest.py": "a403f3a2c5c07e900051678ae35a1fbb1b323c1ea909be0cc5ffd90dcc15c7b3", "promofinder/labelmodel.py": "52b6fcd1c324a6b5f78959f213fe90d80f1dbd6e95ea10717c023c7a1c208e57", "promofinder/learn_weights.py": "33be42323ff9f98c7fe9facb7e00761f6da07d761ecfdd81e0dce5c63996036c", "promofinder/lexicons.py": "e5f80e50bf6839512ada1f02bb82e9583c8e74da9fa7a34105424137d2473453", "promofinder/llm.py": "faef1eddacc1ccce66f932cf7473948fd17bb03703963e76ec689a02feb24e19", "promofinder/models.py": "37fa278285746a02748454184fd4455986e9a85108693991c4f1d625c88a109f", "promofinder/parser.py": "39d173d583a4fec7b388e84b1fa00f4521ac9d8abb794ee72f6cc13838bbcf0a", "promofinder/pipeline.py": "ffe5b836ee953005e408166dac6f0a4a2901a5c8f97743a138d725d564af89d4", "promofinder/report.py": "2a605ffaa2d987fad6fe71ec88b9f2169bfa69f56a94aff7e430b52e31e7a7a5", "promofinder/series.py": "1586eea1b8891cb12182df1e2feee2a427da6b3f3d476f8c69368b3f094882fd", "render.yaml": "b653282a283d97db41e796b2295c164d20d1d9d1747180a72a9e2416cbe48b15", "requirements.txt": "8177ca43ece9540df173afa04eb4a0490c6764616ad083652f338be92e5a6a0f", "run_all.sh": "999c19a59933ae0f192b516c79a8f065cefaceeaa669b5fb0bb28310dafb9879", "samples/build_sample.py": "115618cde64a4febf550fcc43847a81ee60c45869cef920f2e7d0122b5edab66", "samples/the_cleaner_was_the_heiress.zip": "0ce91ec89def20bf5656d02932346912aaa065260ddac2cfc52566f3c214e043", "samples/the_cleaner_was_the_heiress/episode-001.txt": "4250ec56fa5f92f3c4971bcdf267d17e2c6aa20e55114f7ad599c606b980ba66", "samples/the_cleaner_was_the_heiress/episode-002.txt": "bca2687664332f966ed02c1131be7d8173ccb65f65d1f95dde33a5ce72455fe6", "samples/the_cleaner_was_the_heiress/episode-003.txt": "e7ebe54c0dbeb42a4dcd34f3abd00b05b0165243c214a3c4009541821e0a080c", "samples/the_cleaner_was_the_heiress/episode-004.txt": "602c0dea65163fe5633ba81d33eed47afe458968fc172392a9915f382fcedb86", "samples/the_cleaner_was_the_heiress/episode-005.txt": "598ddd84906de0a57325c3a7674071ea29b2a5a66a1f661c01327491dae34688", "samples/the_cleaner_was_the_heiress/episode-006.txt": "09429456eda1a30332653bfff21d43d7d29d5d1fd9421a87fd74d9b67d0be00e", "tests/test_app.py": "58a0634536bb1995e685a8aea190c9d9817955e1e55c51710c096bf2e583af8a", "tests/test_core.py": "8ac8150eaae2abaa59d50e4cab165610abb06717d8554f6b20c805fe794859e4"}
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
print(f"    {len(m) - len(missing) - len(diff)}/{len(m)} files identical to v1.2.5 (README.md is yours and not checked)")
sys.exit(1 if (missing or diff) else 0)
PYCHECK
RC=$?
set -e
rm -f .pf_manifest.json
if [ $RC -ne 0 ]; then
  echo "    Some files differ from v1.2.5 (listed above). That is fine if you edited them on purpose;"
  echo "    otherwise download the latest PromoFinder_Render_public.zip and copy the listed files over."
  echo "    Continuing: the test suite below is the real check."
else
  ok "every project file matches v1.2.5"
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
    ok "nothing to commit (already on v1.2.5)"
  else
    git commit -q -m "PromoFinder v1.2.5: half the CPU-seconds on hosted CPUs (pinned maths threads, exact memoisation, demo built at deploy time); identical results"
    ok "committed: $(git log -1 --oneline)"
  fi
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git push origin "$BRANCH"
  ok "pushed to origin/$BRANCH: Render will redeploy automatically (about 3-5 min)"
  echo
  echo "Next: Render dashboard -> promofinder -> Events, wait for 'Deploy live' (the build now also scores"
  echo "the demo, so it takes ~1 min longer). Then open <your-url>/healthz and check:"
  echo '   "version":"1.2.5", "demo_source":"prebuilt", "math_threads":{"openblas":1,...}'
  echo "Upload the ZIP again; the results page shows per-stage timings under run details."
else
  echo
  echo "    Not committed. To publish:  bash $0 --push"
  echo "    (or: git add -A && git commit -m 'PromoFinder v1.2.5' && git push)"
fi
say "Done"
