"""Shared look for every page (home, progress, errors, results).

Palette ("darkroom"): green-black ink, bone paper, persimmon for the hook window, brass for
in/out points, and hatched ink for the cut. Type: Instrument Serif for headlines, IBM Plex Sans
for text, IBM Plex Mono for timecodes and numbers.

Kept deliberately light for small hosts: one font stylesheet (with system fallbacks, so an
offline report.html still renders), CSS inlined per page, no frameworks, no animations.
"""

BRAND = "PromoFinder"

# Inline favicon (in/out marks around a persimmon hook block), so it costs no request.
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='7' fill='%2313201B'/%3E"
           "%3Crect x='6' y='8' width='2.5' height='16' fill='%23C9A23A'/%3E"
           "%3Crect x='11' y='12' width='7' height='8' fill='%23D4502A'/%3E"
           "%3Crect x='19' y='12' width='4' height='8' fill='%23F0ECE3' opacity='.4'/%3E"
           "%3Crect x='23.5' y='8' width='2.5' height='16' fill='%23C9A23A'/%3E%3C/svg%3E")

# Everything in <head> besides the title and page CSS. Must contain no braces: ERROR_PAGE uses str.format.
HEAD = ('<link rel="icon" href="' + FAVICON + '">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
        '&family=IBM+Plex+Sans:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap">'
        '<meta name="theme-color" content="#13201b">')

LOGO = ('<svg class=logo viewBox="0 0 28 20" aria-hidden="true" focusable="false">'
        '<rect x="0" y="0" width="2.5" height="20" style="fill:var(--mark)"/>'
        '<rect x="5" y="5" width="9" height="10" style="fill:var(--hook)"/>'
        '<rect x="14" y="5" width="9" height="10" style="fill:url(#pf-hatch)"/>'
        '<rect x="25.5" y="0" width="2.5" height="20" style="fill:var(--mark)"/>'
        '<defs><pattern id="pf-hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<rect width="1.4" height="3" style="fill:var(--on-night)"/></pattern></defs></svg>')


def topbar(right="", home_link=True):
    """Masthead shared by every page. `right` is trusted HTML (links)."""
    brand = f'{LOGO}<span>{BRAND}</span>'
    brand_html = f'<a class=brand href="/">{brand}</a>' if home_link else f'<span class=brand>{brand}</span>'
    return f'<div class=topbar><div class=topbar-in>{brand_html}<div class=topbar-r>{right}</div></div></div>'


BASE_CSS = """
:root{
--paper:#f0ece3;--sheet:#f8f6f0;--soft:#e5e0d4;--soft-2:#d9d3c5;
--ink:#13201b;--ink-2:#34413b;--mute:#646e68;--faint:#98a099;--rule:#d5d0c3;
--night:#13201b;--night-2:#1c2b25;--on-night:#ede8dc;--night-mute:#9eaaa2;--night-rule:#2f3f38;
--hook:#d4502a;--hook-ink:#a63a1b;--hook-bg:#f6e1d7;
--mark:#c9a23a;--mark-bg:#f2eacf;--mark-ink:#584506;
--ok:#2e6248;--ok-bg:#dde9e1;
--hatch:repeating-linear-gradient(135deg,var(--ink) 0 1.5px,transparent 1.5px 5px);
--serif:"Instrument Serif","Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
--sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,"Liberation Mono",monospace;
--wrap:1160px;--gut:32px;--r:3px}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:400 15.5px/1.6 var(--sans);-webkit-font-smoothing:antialiased}
::selection{background:var(--mark);color:var(--ink)}
h1,h2,.display{font-family:var(--serif);font-weight:400;letter-spacing:-.012em;margin:0;color:inherit}
h1{font-size:44px;line-height:1.02}
h2{font-size:30px;line-height:1.08;margin:0 0 8px}
h3{font:600 13px/1.4 var(--sans);margin:0 0 10px}
p{margin:0 0 12px}
a{color:inherit;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;text-decoration-color:var(--faint)}
a:hover{text-decoration-color:var(--hook)}
.mute{color:var(--mute)}
.num,.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.kicker{font:500 11.5px/1.3 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin:0 0 16px}
.kicker b{color:var(--hook);font-weight:500}
code{font-family:var(--mono);background:var(--soft);padding:1px 6px;border-radius:2px;font-size:.88em}
button,.btn{font:600 14.5px/1 var(--sans);border-radius:var(--r);padding:14px 22px;cursor:pointer;border:1.5px solid var(--ink);
background:var(--ink);color:var(--on-night);text-decoration:none;display:inline-flex;align-items:center;gap:10px}
button:hover,.btn:hover{background:var(--night-2);border-color:var(--night-2)}
.btn-quiet,button.btn-quiet{background:transparent;color:var(--ink)}
.btn-quiet:hover,button.btn-quiet:hover{background:var(--ink);color:var(--on-night)}
.arr{font-family:var(--mono);font-weight:400}
button:disabled{opacity:.55;cursor:progress}
:focus-visible{outline:2px solid var(--hook);outline-offset:3px}
.topbar{background:var(--night);color:var(--on-night);border-bottom:1px solid var(--night-rule)}
.topbar-in{max-width:var(--wrap);margin:0 auto;padding:15px var(--gut);display:flex;align-items:center;justify-content:space-between;gap:20px}
.brand{display:inline-flex;align-items:center;gap:11px;font:600 15px/1 var(--sans);letter-spacing:.01em;color:var(--on-night);text-decoration:none}
.logo{width:28px;height:20px;flex:none}
.topbar-r{display:flex;align-items:center;gap:24px;font-size:14px}
.topbar-r a{text-decoration:none;color:var(--night-mute)}
.topbar-r a:hover{color:var(--on-night)}
.topbar-r .ver{font:400 12px var(--mono);color:var(--night-mute);opacity:.7}
.shell{max-width:680px;margin:0 auto;padding:10vh var(--gut) 80px}
.sheet{border-top:2px solid var(--ink);padding-top:26px}
.sheet h1{font-size:46px;margin-bottom:14px}
.sheet>p:not(.kicker){font-size:16.5px;color:var(--ink-2);max-width:60ch}
.sheet ul{padding-left:0;list-style:none;margin:18px 0 26px;border-top:1px solid var(--rule)}
.sheet li{font:13px/1.5 var(--mono);color:var(--ink-2);padding:9px 0;border-bottom:1px solid var(--rule)}
.sheet .btn{margin-top:10px}
.foot{max-width:calc(var(--wrap) - 2*var(--gut));margin:0 auto;padding:22px 0 40px;border-top:1px solid var(--rule);
display:flex;flex-wrap:wrap;gap:6px 24px;justify-content:space-between;font:12px/1.5 var(--mono);color:var(--mute)}
@media(max-width:1224px){.foot{margin:0 var(--gut)}}
@media(max-width:760px){:root{--gut:20px}h1{font-size:36px}.sheet h1{font-size:36px}.topbar-r{gap:16px}.topbar-r .hide-sm{display:none}}
"""
