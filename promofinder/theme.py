"""Shared look for every page (home, progress, errors, results).

No web fonts, frameworks or animations: system font stacks only, so pages cost nothing to load or
render on a small host. Palette is taken from the edit suite / darkroom: crimson safelight marks the
hook window, splice-tape teal marks the cut, grease-pencil yellow marks in/out points.
"""

BASE_CSS = """
:root{--paper:#eef0eb;--sheet:#fbfbf8;--ink:#1e2421;--mute:#5f6862;--rule:#d5d9d2;--soft:#e4e7e1;
--safelight:#a61e2e;--tape:#136f7a;--pencil:#d9a900;--slate:#24302b;--slate-ink:#e8ece6;--warn:#8a5a00;--warn-bg:#f6ecd0}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif}
.display,h1,h2,.rank,.tc-big{font-family:Bahnschrift,"DIN Alternate","DIN Condensed","Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
font-stretch:87.5%;font-weight:600;letter-spacing:-.005em;font-variant-numeric:tabular-nums}
h1{font-size:34px;line-height:1.05;margin:0}
h2{font-size:22px;line-height:1.15;margin:0 0 6px}
h3{font-size:15px;margin:0 0 8px}
a{color:var(--tape);text-underline-offset:2px}
p{margin:0 0 10px}
.mute{color:var(--mute)}
.num{font-variant-numeric:tabular-nums}
button,.btn{font:inherit;font-weight:600;border-radius:6px;padding:10px 18px;cursor:pointer;border:1px solid var(--ink);background:var(--ink);color:#fff;text-decoration:none;display:inline-block}
.btn-quiet{background:transparent;color:var(--ink)}
button:disabled{opacity:.6;cursor:progress}
:focus-visible{outline:2px solid var(--tape);outline-offset:2px}
.shell{max-width:620px;margin:10vh auto;padding:0 24px}
.sheet{background:var(--sheet);border:1px solid var(--rule);border-radius:8px;padding:26px 28px}
.sheet h1{font-size:28px;margin-bottom:10px}
.sheet ul{padding-left:20px;color:var(--mute)}
code{background:var(--soft);padding:1px 5px;border-radius:4px;font-size:.92em}
"""
