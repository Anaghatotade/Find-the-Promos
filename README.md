# PromoFinder

**Find the best 20–60 s promo clips in a microdrama, straight from its screenplay.**
Upload a show's timestamped screenplays (`.zip` or `.txt`) and get ranked promo candidates. Each comes with exact
timecodes, the hook (first 3 s), the cliffhanger (the cut), the beat the viewer is denied, a "why it works"
line, risk flags, a stability badge, and the source line numbers. Exports include JSON, CSV, Markdown and
**CMX3600 EDLs** for Premiere Pro or DaVinci Resolve. It runs on CPU with no AI API key; an LLM can optionally re-rank the shortlist.

**Live demo:** _(add your Render URL here, e.g. `https://promofinder.onrender.com`)_. Click **Try the live demo** for instant results on an original sample
show, run the pipeline live, or download the sample files and upload them yourself.

> The sample show *The Cleaner Was the Heiress* (`samples/`) is original fiction written for this demo in the
> production screenplay format. The confidential screenplays this tool was developed on are not included.

## How it works
1. **Parse** every camera shot, action, sound cue and line of dialogue, with its timestamp and delivery tags.
2. **Legal cut points:** a clip never starts or ends inside a line of dialogue.
3. **Hook scorer (weak supervision):** transparent labeling functions → Dawid–Skene label model + text classifier,
   cross-fitted by episode. If a show has no delivery tags, intensity is inferred from the camera/action text.
4. **Cliffhanger scorer:** open question, threat or reveal at the cut, plus the strength of the next beat the viewer is denied.
5. **Clip score:** weighted geometric mean of hook, cliffhanger, standalone clarity, emotional arc and premise fit.
   Diverse selection (no overlaps, ≤2 per episode). Cross-episode and cold-open edits are also generated.

Measured on a 50-episode, 103-minute show: about 8 s end to end on a laptop CPU, scoring 51,598 candidate clips.

## Run locally
```
pip install -r requirements.txt
python app.py                                   # http://localhost:7860
python -m promofinder run samples/the_cleaner_was_the_heiress.zip --out outputs/demo
python -m pytest -q tests
```

## Deploy on Render (recommended)
1. Push this folder to a GitHub repository.
2. On render.com: **New → Blueprint**, select the repository. `render.yaml` sets up a Python web service
   (gunicorn, one worker, `/healthz` health check, public mode). The first build takes a few minutes.
3. Open the `https://<name>.onrender.com` URL.

What to expect, honestly:
- **Free plan** (512 MB RAM, 0.1 CPU): fits in memory (PromoFinder peaks at about 360 MB on a 50-episode show), but
  scoring is CPU-bound, so a full 50-episode upload takes roughly 10× the laptop time (about a minute or more; estimated,
  not measured on Render). The bundled demo is precomputed, so **See ranked promos** opens instantly once the service is
  awake. Free services sleep after 15 min idle and take about a minute to wake: open the URL a minute before you present.
- **Starter plan** ($7/month, 0.5 CPU, never sleeps): about 2× the laptop time; the right choice for a live demo.
- Live progress shows each pipeline stage, so a slow run is never a blank page.

**Other hosts.** The `Dockerfile` runs on any container host (Render's Docker runtime, Railway, Koyeb, Google Cloud
Run, a small VPS). Keep a single gunicorn worker: background jobs and their progress live in that worker's memory.
Serverless platforms such as **Vercel** are not a good fit: requests are short-lived and the background job and its
progress page need one long-running process.

**Public mode** (`PROMOFINDER_PUBLIC=1`):
- Visitors never see each other's runs; result links are unguessable.
- Uploads are capped at 20 MB, and decompressed ZIP size is capped too.
- At most 3 jobs run or queue at once; old runs are deleted automatically.
