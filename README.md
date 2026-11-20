# PromoFinder

Find the best 20–60 second promo clips in a microdrama, directly from its screenplay.

**Live demo:** [https://promofinder-h00l.onrender.com](https://promofinder-h00l.onrender.com)  
Click **Try the live demo** for instant results on the sample show.

![PromoFinder home page](docs/screenshots/home.png)

Upload a show's timestamped screenplays (`.zip` or `.txt`) and get a ranked list of promo candidates. Each candidate includes:

- Exact timecodes
- The opening hook (first 3 seconds)
- The cliffhanger at the cut
- The line the clip cuts away from, so viewers have to tap to hear it
- A short explanation of why the clip works
- Risk flags and a stability badge
- Source line numbers from the screenplay

Exports are available in JSON, CSV, Markdown, and **CMX3600 EDLs** for Premiere Pro or DaVinci Resolve. The tool runs entirely on CPU with no AI API key required. An optional LLM can re-rank the shortlist if you want.

> The sample show *The Cleaner Was the Heiress* (in `samples/`) is original fiction written for this demo in standard production screenplay format. The confidential screenplays used during development are not included.

## Screenshots

**Results page.** Show summary, exports and the ranked picks.

![Results page for the sample show](docs/screenshots/results.png)

**A single pick.** The strip is drawn to scale: red is the hook window, hatching is the cut, gold marks the in and out points. The lines it was scored on, the beat the viewer doesn't get to see, and the score breakdown sit alongside, with **Use / Reject** buttons for editor feedback.

![One promo candidate with its clip strip and scores](docs/screenshots/promo-card.png)

<table>
<tr>
<td width="38%"><img src="docs/screenshots/results-mobile.png" alt="Results page on a phone"></td>
<td><b>On a phone.</b> The same page works on small screens, so a pick can be reviewed or exported away from the edit suite.</td>
</tr>
</table>

## How it works

1. **Parse** every camera shot, action, sound cue, and line of dialogue, along with its timestamp and delivery tags.
2. **Legal cut points** - clips never start or end in the middle of a line of dialogue.
3. **Hook scorer (weak supervision)** - transparent labeling functions feed a Dawid–Skene label model and a text classifier, cross-fitted by episode. If a show has no delivery tags, intensity is inferred from the camera and action text.
4. **Cliffhanger scorer** - looks for an open question, threat, or reveal at the cut, plus the strength of the next beat the viewer is denied.
5. **Clip score** - weighted geometric mean of hook, cliffhanger, standalone clarity, emotional arc, and premise fit. Selection is diverse (no overlaps, at most 2 clips per episode). Cross-episode and cold-open edits are also generated.

On a 50-episode, 103-minute show the full pipeline takes about 7 seconds on a laptop CPU and scores 51,598 candidate clips. Settings such as clip length, number of picks and score weights live in `config.yaml`.

## Run locally

```bash
pip install -r requirements.txt
python app.py                                   # http://localhost:7860
python -m promofinder run samples/the_cleaner_was_the_heiress.zip --out outputs/demo
python -m pytest -q tests
```

## Deploy

`render.yaml` is a Render Blueprint: connect the repo under **New → Blueprint** and it builds, scores the demo at build time and serves the app with gunicorn. The free plan works but has 0.1 CPU, so a full 50-episode upload takes about a minute there. A `Dockerfile` is included for other hosts. `/healthz` reports the running version.

## AI tools

| Tool | How it was used |
|---|---|
| Claude (Anthropic) | Main coding partner: the pipeline, tests, experiments and evaluation scripts, and debugging the Render deployment. It also labelled the hook and ending samples, blind to model scores (silver labels, not editor labels). |
| Grok | Brainstorming approaches and a second opinion on ideas before building them. |
| Lovable | Frontend UI and visual design of the web app: layout, typography and colour palette. The design is implemented as plain server-rendered HTML and CSS (`promofinder/theme.py`, `promofinder/report.py`, `app.py`) with no frontend framework; `tests/test_ui.py` checks every control still works. |

I made the final calls. No suggestion was trusted until a test or a held-out number backed it. These are the mistakes that rule caught:

| What went wrong | How it showed up | Fix and how it was checked |
|---|---|---|
| First idea: writers end every episode on a cliffhanger, so learn from the endings | Held-out AUC 0.61 (CI 0.44–0.78). The top features were writing style, not suspense | Dropped it. Built a rule + withheld-payoff scorer, evaluated on 48 endings labelled before the scorer existed |
| Hook rules vetoed real hooks | On blind sample A, "They arrested her!" was penalised as a "dangling start" | Removed two veto rules, then labelled a fresh sample B so the fix was not graded on the data it was tuned on |
| First upload on Windows crashed | `UnicodeEncodeError`: cp1252 cannot store the arrows and curly quotes in the explanations | All file input/output made explicitly UTF-8; a test re-runs the export under a non-UTF-8 locale |
| ZIP uploads on Render showed a generic error page | A damaged member, Deflate64 compression or a password threw raw exceptions | Each case now shows a clear message; tests build these broken ZIPs and check the page |
| An upload on Render took 6–7 minutes | 0.1 CPU, numpy running one thread per host core, and the demo rebuilt on every wake-up | Maths pinned to one thread and repeated work cached (12.9 → 6.8 CPU-seconds); demo built at deploy time; every score checked identical |
| The live demo's "Run the pipeline live" crashed on Render | `LookupError: unknown encoding: cp437`: the host Python could not load the codec ZIP file names use | Falls back to latin-1 for file names; a test blocks cp437 and checks the sample still loads |
| Fixes that sounded right but failed when measured | A talkiness penalty could not separate weak #12 (2.88 words/s) from strong #2 (2.73); lowering the premise weight changed 6 of 12 picks | Rejected both; #12 is flagged as the least stable pick (72%) instead |

**Results on the 50-episode development show:** shipped cliffhanger scorer 0.80 AUC [0.65–0.93] vs 0.46 for VADER sentiment; hook scorer 0.77 [0.66–0.86] on a fresh blind sample vs 0.63; ±50% weight changes keep 10.9 of 12 picks and the same #1. No editor has run the blind A/B sheet yet, so these are silver-label numbers.
