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
from promofinder.theme import BASE_CSS, HEAD, topbar
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
@@HEAD@@<style>@@CSS@@</style></head>
<body>@@TOPBAR@@<div class=shell><div class=sheet><p class=kicker><b style="color:var(--hook)">&#9679;</b>&nbsp; Needs attention</p><h1>{title}</h1><p>{message}</p>{details}<a class=btn href="/">Back to upload <span class=arr>&rarr;</span></a></div></div></body></html>"""
              .replace("@@CSS@@", BASE_CSS.replace("{", "{{").replace("}", "}}")).replace("@@HEAD@@", HEAD)
              .replace("@@TOPBAR@@", topbar('<a href="/demo">Live demo</a>').replace("{", "{{").replace("}", "}}")))


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

INDEX = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>PromoFinder: ranked promo clips from microdrama screenplays</title>
<meta name=description content="Upload a show's timestamped screenplays and get ranked 20-60 second promos with exact timecodes, the hook, the cut and why each one works.">
@@HEAD@@<style>@@CSS@@
.wrap{max-width:var(--wrap);margin:0 auto;padding:0 var(--gut)}
.band{background:var(--night);color:var(--on-night);--hatch:repeating-linear-gradient(135deg,var(--on-night) 0 1.5px,transparent 1.5px 5px)}
.band .kicker{color:var(--night-mute)}
.hero{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:72px;align-items:end;padding:76px 0 72px}
.hero h1{font-size:88px;line-height:.92;letter-spacing:-.025em}
.hero h1 em{color:var(--hook)}
.lede{font-size:18.5px;line-height:1.6;color:var(--night-mute);max-width:50ch;margin:28px 0 0}
.facts{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:24px;font:12.5px var(--mono);color:var(--night-mute)}
.facts span::before{content:"\\2014\\00a0";opacity:.6}
.anat{margin:0;padding:22px 0 0;border-top:1px solid var(--night-rule)}
.anat figcaption{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:18px}
.anat figcaption b{font:600 13px var(--sans)}
.anat figcaption span{font:11.5px var(--mono);color:var(--night-mute)}
.ruler{display:flex;justify-content:space-between;font:10.5px var(--mono);color:var(--night-mute);margin-bottom:6px;font-variant-numeric:tabular-nums}
.astrip{position:relative;height:46px;background:var(--night-2);
background-image:linear-gradient(90deg,var(--night-rule) 1px,transparent 1px);background-size:16.666% 100%}
.astrip span{position:absolute;top:0;bottom:0}
.astrip .h{left:0;width:10%;background:var(--hook)}
.astrip .c{right:0;width:20%;background:var(--hatch);box-shadow:inset 1px 0 0 var(--on-night)}
.astrip .m{width:4px;background:var(--mark);top:-6px;bottom:-6px}
.astrip .l{position:absolute;top:0;bottom:0;display:flex;align-items:center;font:500 11px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--night-mute)}
.anat .row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-top:22px;font-size:13.5px;color:var(--night-mute)}
.anat .row div{border-top:1px solid var(--night-rule);padding-top:12px}
.anat .row i{display:inline-block;width:10px;height:10px;margin-right:8px;vertical-align:-1px}
.anat .row b{display:block;color:var(--on-night);font-weight:600;margin-bottom:2px}
.work{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);border-bottom:1px solid var(--rule)}
.up{padding:52px 56px 56px 0;border-right:1px solid var(--rule)}
.demo{padding:52px 0 56px 56px}
.step{font:500 11.5px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:0 0 12px}
.step b{color:var(--hook)}
.up h2,.demo h2{font-size:36px}
.drop{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:6px;min-height:178px;
border:1.5px dashed var(--faint);border-radius:var(--r);padding:26px;margin:24px 0 22px;background:var(--sheet);cursor:pointer}
.drop:hover,.drop.over{border-color:var(--ink);background:var(--paper)}
.drop.over{border-style:solid;background:var(--mark-bg)}
.drop:focus-within{outline:2px solid var(--hook);outline-offset:3px}
.drop input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}
.drop .empty{display:flex;flex-direction:column;align-items:center;gap:6px;pointer-events:none}
.drop .ic{width:42px;height:30px;margin-bottom:6px}
.drop b{font-size:16px}
.drop .sub{font-size:13.5px;color:var(--mute)}
.drop .sub u{color:var(--ink);text-decoration-color:var(--hook);text-underline-offset:3px}
.drop.has{border-style:solid;border-color:var(--ink);align-items:stretch;text-align:left}
.picked{pointer-events:none;display:none;list-style:none;margin:0;padding:0;font:13px/1.4 var(--mono)}
.drop.has .picked{display:block}.drop.has .empty{display:none}
.picked li{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--rule)}
.picked li span:last-child{color:var(--mute);white-space:nowrap}
.picked .more{color:var(--mute);border:0}
.picked .chg{font-family:var(--sans);font-size:13px;color:var(--mute);border:0;padding-top:10px}
.opts{display:flex;flex-wrap:wrap;gap:12px 28px;align-items:center;font-size:14.5px;color:var(--ink-2);margin-bottom:24px}
.opts label{display:inline-flex;align-items:center;gap:10px;cursor:pointer}
.opts input[type=number]{font:500 15px var(--mono);width:72px;padding:8px 10px;border:1px solid var(--rule);border-radius:var(--r);background:var(--sheet);color:var(--ink)}
.opts input[type=number]:focus{border-color:var(--ink);outline:none;box-shadow:0 0 0 3px var(--mark-bg)}
.opts input[type=checkbox]{width:17px;height:17px;accent-color:var(--ink);margin:0}
.submit{display:flex;flex-wrap:wrap;align-items:center;gap:16px}
#busy{display:none;font-size:14px;color:var(--ink-2)}
#busy::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--hook);margin-right:8px;vertical-align:1px}
.small{font-size:13px;color:var(--mute);margin-top:22px;max-width:60ch}
.demo>p{color:var(--ink-2);max-width:46ch}
.acts{list-style:none;padding:0;margin:24px 0 0;border-top:1px solid var(--rule)}
.acts li{border-bottom:1px solid var(--rule)}
.acts a,.acts button{display:flex;width:100%;justify-content:space-between;align-items:center;gap:12px;padding:16px 2px;background:none;border:0;border-radius:0;
color:var(--ink);font:600 15.5px/1.3 var(--sans);text-decoration:none;text-align:left}
.acts a:hover,.acts button:hover{background:none;color:var(--hook-ink)}
.acts small{display:block;font:400 13px/1.4 var(--sans);color:var(--mute);margin-top:3px}
.acts .arr{font:400 18px var(--mono)}
.acts a:hover .arr,.acts button:hover .arr{color:var(--hook)}
.acts form{margin:0}
.dl{font-size:13.5px;color:var(--mute);margin-top:18px;line-height:1.9}
.dl a{font-family:var(--mono);font-size:12.5px;color:var(--ink);white-space:nowrap}
.how{padding:64px 0 24px}
.how-h{display:flex;justify-content:space-between;align-items:baseline;gap:20px;margin-bottom:24px}
.how-h h2{font-size:40px}
.how-h p{color:var(--mute);margin:0;max-width:44ch;font-size:14.5px}
.how ol{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--ink)}
.how li{padding:20px 22px 8px 0;border-right:1px solid var(--rule);margin-right:22px}
.how li:last-child{border-right:0;margin-right:0}
.how li span{font:500 12px var(--mono);color:var(--hook)}
.how li b{display:block;font:400 24px/1.15 var(--serif);margin:8px 0 8px}
.how li p{font-size:14px;color:var(--ink-2);margin:0}
.lists{padding:36px 0 56px}
.runs{margin-top:22px;border-top:2px solid var(--ink);padding-top:16px}
.runs h3{display:flex;justify-content:space-between;align-items:baseline;gap:12px;font:600 13px var(--sans);margin-bottom:6px}
.runs a{display:flex;justify-content:space-between;gap:16px;padding:13px 0;border-bottom:1px solid var(--rule);font-weight:600;text-decoration:none}
.runs a:hover{color:var(--hook-ink)}
.runs .hint{font:400 12px var(--mono);color:var(--mute)}
.runs form{margin:0;padding:10px 0;border-bottom:1px solid var(--rule)}
.runs>p{padding:12px 0;margin:0}
@media(max-width:980px){.hero{grid-template-columns:1fr;gap:44px;padding:52px 0 52px}.hero h1{font-size:64px}
.work{grid-template-columns:1fr}.up{padding:40px 0 40px;border-right:0;border-bottom:1px solid var(--rule)}.demo{padding:40px 0 44px}
.how ol{grid-template-columns:1fr 1fr}.how li:nth-child(2){border-right:0;margin-right:0}.how li{border-bottom:1px solid var(--rule)}}
@media(max-width:560px){.hero h1{font-size:48px}.lede{font-size:16.5px}.anat .row{grid-template-columns:1fr;gap:8px}.up h2,.demo h2{font-size:30px}
.how-h{display:block}.how ol{grid-template-columns:1fr}.how li{border-right:0;margin-right:0}.drop{min-height:150px}.submit button{width:100%;justify-content:center}}
</style></head><body>
@@TOPBAR@@
<div class=band><div class=wrap>
<section class=hero><div><p class=kicker><b>&#9679;</b>&nbsp; Screenplay in, promo cuts out</p>
<h1>Find the thirty seconds that <em>sell the show.</em></h1>
<p class=lede>Upload a show's timestamped screenplays and get back ranked 20&ndash;60 second promos: exact timecodes, the hook, the moment to cut, and why each one works. Runs on an ordinary CPU, no AI API needed.</p>
<div class=facts><span>EDLs for Premiere &amp; Resolve</span><span>CSV, JSON, Markdown</span><span>Deterministic results</span></div></div>
<figure class=anat aria-label="What every promo is checked for"><figcaption><b>What every clip is checked for</b><span>anatomy of a 30 s promo</span></figcaption>
<div class=ruler><span>0 s</span><span>5</span><span>10</span><span>15</span><span>20</span><span>25</span><span>30 s</span></div>
<div class=astrip><span class=h></span><span class=c></span><span class=m style="left:0"></span><span class=m style="right:0"></span><span class=l style="left:14%">story</span></div>
<div class=row><div><b><i class=sw style="background:var(--hook)"></i>Hook</b>Grabs in the first 3 s</div>
<div><b><i class=sw style="background:var(--hatch);box-shadow:inset 0 0 0 1px var(--on-night)"></i>Cut</b>Ends on an open question</div>
<div><b><i class=sw style="background:var(--mark)"></i>In / out</b>Every cut lands between lines of dialogue, never inside one.</div></div></figure>
</section></div></div>
<div class=wrap>
<section class=work id=upload>
<form class=up method=post action="/run" enctype=multipart/form-data onsubmit="document.getElementById('busy').style.display='block';const b=this.querySelector('button');b.disabled=true;b.textContent='Uploading';">
<p class=step><b>01</b>&nbsp; Your show</p><h2>Find promos in your show</h2><p class=mute>A .zip of episode screenplays, or several .txt files.</p>
<label class=drop id=drop><input type=file name=files multiple accept=".zip,.txt" required aria-describedby=dropsub>
<span class=empty><svg class=ic viewBox="0 0 42 30" aria-hidden=true><rect x=".75" y=".75" width="40.5" height="28.5" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="6" y="9" width="3" height="12" style="fill:var(--mark)"/><rect x="11" y="12" width="9" height="6" style="fill:var(--hook)"/><rect x="20" y="12" width="9" height="6" fill="none" stroke="currentColor"/><rect x="33" y="9" width="3" height="12" style="fill:var(--mark)"/></svg>
<b>Choose screenplay files</b><span class=sub id=dropsub>Drop them here or <u>browse</u> &middot; .zip or .txt</span></span>
<ul class=picked id=picked aria-live=polite></ul></label>
<div class=opts><label>Promos to return <input type=number name=top value=12 min=3 max=30></label>
<label><input type=checkbox name=funnel checked> Prefer early episodes (fewer spoilers)</label></div>
<div class=submit><button>Find promos <span class=arr>&rarr;</span></button><div id=busy>Uploading. Scoring starts as soon as the files arrive.</div></div>
<div class=small>__PRIVACY__</div></form>
<div class=demo id=demo><p class=step><b>02</b>&nbsp; Or start with a sample</p><h2>Try the live demo</h2><p>Six episodes of <i>The Cleaner Was the Heiress</i>, an original sample show written for this demo in the production screenplay format.</p>
<ul class=acts><li><a href="/demo"><span>See ranked promos<small>Opens instantly: results are precomputed</small></span><span class=arr>&rarr;</span></a></li>
<li><form method=post action="/demo/run"><button ><span>Run the pipeline live<small>Watch every stage score the sample</small></span><span class=arr>&rarr;</span></button></form></li></ul>
<div class=dl>Or download the sample and upload it yourself: <a href="/samples/sample.zip">sample .zip</a>, __EPLINKS__</div></div>
</section>
<section class=how id=how><div class=how-h><h2>How it ranks</h2><p>Transparent signals, no black box. Every pick shows the lines it was scored on.</p></div>
<ol><li><span>01</span><b>Parse</b><p>Every camera shot, action, sound cue and line of dialogue, with its timestamp and delivery tags.</p></li>
<li><span>02</span><b>Find legal cuts</b><p>A clip never starts or ends inside a line of dialogue.</p></li>
<li><span>03</span><b>Score hook &amp; cut</b><p>The first 3 s must grab; the last 6 s must leave a question the viewer needs answered.</p></li>
<li><span>04</span><b>Rank &amp; export</b><p>Diverse picks with no overlaps, ready as EDLs, cut lists, CSV, JSON or Markdown.</p></li></ol></section>
<div class=lists>__RUNS__</div></div>
<footer class=foot><span>PromoFinder @@VERSION@@</span><span>Runs on CPU &middot; no AI API key needed</span></footer>
<script>
(function(){const d=document.getElementById('drop');if(!d)return;const inp=d.querySelector('input'),ul=document.getElementById('picked');
function kb(n){return n>1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB'}
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function show(){const f=[...inp.files];d.classList.toggle('has',f.length>0);
 ul.innerHTML=f.slice(0,6).map(x=>`<li><span>${esc(x.name)}</span><span>${kb(x.size)}</span></li>`).join('')+(f.length>6?`<li class=more>+ ${f.length-6} more</li>`:'')+(f.length?'<li class=chg>Click or drop to choose different files</li>':'')}
inp.addEventListener('change',show);
['dragenter','dragover'].forEach(e=>d.addEventListener(e,()=>d.classList.add('over')));
['dragleave','drop'].forEach(e=>d.addEventListener(e,()=>d.classList.remove('over')));
window.addEventListener('pageshow',()=>{const b=document.querySelector('.up button');if(b){b.disabled=false;b.innerHTML='Find promos <span class=arr>&rarr;</span>'}document.getElementById('busy').style.display='none';show()});
})();
</script></body></html>""".replace("@@CSS@@", BASE_CSS).replace("@@HEAD@@", HEAD).replace("@@VERSION@@", __version__).replace(
    "@@TOPBAR@@", topbar('<a href="/demo">Live demo</a><a href="#how" class=hide-sm>How it ranks</a><span class="ver hide-sm">v' + __version__ + '</span>'))


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
@@HEAD@@<style>@@CSS@@
.sheet h1 span{color:var(--hook);font-style:italic}
.bar{position:relative;height:28px;background:var(--soft);overflow:hidden;margin:34px 0 14px;
background-image:linear-gradient(90deg,var(--soft-2) 1px,transparent 1px);background-size:5% 100%}
.bar i{display:block;height:100%;width:0;background:var(--ink)}
.bar::after{content:"";position:absolute;top:-4px;bottom:-4px;left:0;width:3px;background:var(--mark)}
.prog{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap}
#st{font-weight:600;font-size:16px}#el{color:var(--mute);font:13px var(--mono);font-variant-numeric:tabular-nums}
#slow{display:none;margin-top:24px;font-size:14px;color:var(--mark-ink);background:var(--mark-bg);border-left:3px solid var(--mark);padding:12px 16px}
.steps{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:30px;padding-top:16px;border-top:1px solid var(--rule);font:12px var(--mono);color:var(--mute)}
.steps span::before{content:"\\2192\\00a0";color:var(--faint)}
</style></head><body>@@TOPBAR@@<div class=shell><div class=sheet>
<p class=kicker><b style="color:var(--hook)">&#9679;</b>&nbsp; Scoring in progress</p>
<h1>Finding promos in <span>__SHOW__</span></h1><p class=mute>__N__ episode(s). Every legal cut point is being scored, and the results open by themselves when it's done.</p>
<div class=bar role=progressbar aria-label="Scoring progress"><i id=b></i></div><div class=prog><div id=st aria-live=polite>Starting</div><div id=el></div></div>
<div id=slow>Still working. This server has far less CPU than a laptop, so a full 50-episode show can take a minute or more here (about 7 s on a laptop). The progress above is live; you can leave this tab open.</div>
<div class=steps><span>Parse screenplays</span><span>Find legal cuts</span><span>Score hooks &amp; cuts</span><span>Rank &amp; write exports</span></div>
<noscript><p>JavaScript is off: <a href="/job/__JID__">refresh this page</a> to check progress.</p></noscript></div></div>
<script>
const t0=Date.now();
async function poll(){
  try{
    const r=await fetch('/job/__JID__/status',{cache:'no-store'});
    if(r.status===404){document.getElementById('st').textContent='This job is no longer available.';return}
    const j=await r.json();
    document.getElementById('b').style.width=Math.round(j.frac*100)+'%';
    document.getElementById('b').parentNode.setAttribute('aria-valuenow',Math.round(j.frac*100));
    document.getElementById('st').textContent=j.stage+' ('+Math.round(j.frac*100)+'%)';
    document.getElementById('el').textContent=Math.round((Date.now()-t0)/1000)+' s elapsed';
    if(Date.now()-t0>30000)document.getElementById('slow').style.display='block';
    if(j.status==='done'){location.replace('/r/'+j.rid);return}
    if(j.status==='error'){location.replace('/job/__JID__/error');return}
  }catch(e){document.getElementById('el').textContent='Reconnecting'}
  setTimeout(poll,500);
}
poll();
</script></body></html>""".replace("@@CSS@@", BASE_CSS).replace("@@HEAD@@", HEAD).replace("@@TOPBAR@@", topbar(""))


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
    dl = (f'<div class=dl><span class=dl-label>Export</span><a class=dl-primary href="/r/{rid}/edl.zip">EDLs for Premiere or Resolve</a>'
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
