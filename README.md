# PromoFinder

**Find the best 20–60 second promo clips in a microdrama, straight from its timestamped screenplays.**

Built for Kuku's AI Generalist Assignment, Problem 1: *Find the Promos*.

**Live demo:** [promofinder-h00l.onrender.com](https://promofinder-h00l.onrender.com). Open a sample show for instant results.

---

## What it does

Editors normally watch every episode to pick promo moments. PromoFinder reads the screenplays instead. It scores every legal cut point across the whole show and returns a ranked shortlist of promos. Each one has exact timecodes, the hook, the cliffhanger, and a one-line reason it works.

It runs on an ordinary CPU in about 8 seconds for a 50-episode show, with no API key.

## Key features

- **Ranked promos with exact cuts.** Each clip is 20–60 s and is never cut mid-line. Clips can join scenes across episodes, or open on a "cold open" hook before the story.
- **Hook and cliffhanger scoring.** It checks that the first 3 seconds stop the scroll and that the clip ends on an unresolved moment.
- **Spoiler check.** Clips that give away a twist or the ending are penalised. A reveal the title already promises is treated as the selling point.
- **Audience angles.** Rank for romance, thriller, revenge or other audiences. A Portfolio tab gives one clip per angle for ad A/B tests.
- **Scene search.** Type *"she is humiliated in front of everyone"* to get matching moments, each as a ready-to-use clip.
- **Learns from editors.** Use/Reject votes and quick A/B comparisons tune the ranking over time.
- **Optional LLM second opinion.** Works with any provider, including free ones like Gemini, Groq or a local Ollama model.
- **Multiple script formats.** Reads the production screenplay format as well as inline-timestamp, SRT/VTT subtitle and JSON scripts.

## How to run (Windows)

You need **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/); tick *Add python.exe to PATH*).

```powershell
git clone https://github.com/Anaghatotade/Find-the-Promos.git
cd Find-the-Promos
.\run.bat
```

The first launch sets everything up (about a minute), then opens **http://localhost:7860**. After that, `.\run.bat` starts it in a couple of seconds.

Upload a show's screenplays (`.zip`, `.txt`, `.srt`, `.vtt` or `.json`), choose an audience and spoiler setting, and review the ranked promos.

**Useful commands**

```powershell
.\run.bat check                                         # check the setup
.\run.bat test                                          # run the automated tests
.\run.bat cli run show.zip --out outputs\show           # run from the command line
.\run.bat cli search outputs\show "the sheriff is lying"  # search a finished run
```

**Optional LLM:** add a provider and key to the `.env` file the launcher creates, for example:

```ini
PROMOFINDER_LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

## Exports

| Output | Use |
|---|---|
| **EDL (CMX3600)** | Import straight into Premiere Pro or DaVinci Resolve |
| **Cut list (CSV)** | Frame-accurate in/out points for any editor |
| **CSV / JSON / Markdown** | Ranked promos with hook, cliffhanger, reasons and source lines |
| **Portfolio (JSON)** | One clip per audience angle |
| **HTML report** | Offline, shareable view of the results |

## Project structure

```
app.py              web app
promofinder/        parsing, scoring, spoilers, search, learning, exports
samples/            two original sample shows
tests/              automated tests
config.yaml         settings (clip length, weights, spoilers, LLM)
```

Design notes and evaluation: [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md)
