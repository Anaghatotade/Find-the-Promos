# PromoFinder

Find the best 20–60 second promo clips in a microdrama, directly from its screenplay.

Upload a show's timestamped screenplays (`.zip` or `.txt`) and get a ranked list of promo candidates. Each candidate includes:

- Exact timecodes
- The opening hook (first 3 seconds)
- The cliffhanger at the cut
- The beat the viewer is denied
- A short explanation of why the clip works
- Risk flags and a stability badge
- Source line numbers from the screenplay

Exports are available in JSON, CSV, Markdown, and **CMX3600 EDLs** for Premiere Pro or DaVinci Resolve. The tool runs entirely on CPU with no AI API key required. An optional LLM can re-rank the shortlist if you want.

**Live demo:** [https://promofinder-h00l.onrender.com](https://promofinder-h00l.onrender.com)  
Click **Try the live demo** for instant results on the sample show.

> The sample show *The Cleaner Was the Heiress* (in `samples/`) is original fiction written for this demo in standard production screenplay format. The confidential screenplays used during development are not included.

## How it works

1. **Parse** every camera shot, action, sound cue, and line of dialogue, along with its timestamp and delivery tags.
2. **Legal cut points** — clips never start or end in the middle of a line of dialogue.
3. **Hook scorer (weak supervision)** — transparent labeling functions feed a Dawid–Skene label model and a text classifier, cross-fitted by episode. If a show has no delivery tags, intensity is inferred from the camera and action text.
4. **Cliffhanger scorer** — looks for an open question, threat, or reveal at the cut, plus the strength of the next beat the viewer is denied.
5. **Clip score** — weighted geometric mean of hook, cliffhanger, standalone clarity, emotional arc, and premise fit. Selection is diverse (no overlaps, at most 2 clips per episode). Cross-episode and cold-open edits are also generated.

On a 50-episode, 103-minute show the full pipeline takes about 8 seconds on a laptop CPU and scores 51,598 candidate clips.

## Run locally

```bash
pip install -r requirements.txt
python app.py                                   # http://localhost:7860
python -m promofinder run samples/the_cleaner_was_the_heiress.zip --out outputs/demo
python -m pytest -q tests
```