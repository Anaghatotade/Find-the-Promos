"""Self-contained HTML report (works offline; also served by the web app)."""
import json, html

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e6e4df;--hook:#c2410c;--cliff:#4338ca;--ok:#15803d;--warn:#b45309}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
header{padding:22px 32px 14px;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:0;z-index:5}
h1{font-size:20px;margin:0 0 4px;letter-spacing:-.01em}.sub{color:var(--mute);font-size:13px}
nav{margin-top:12px;display:flex;gap:6px}nav button{border:1px solid var(--line);background:#fff;padding:6px 12px;border-radius:999px;cursor:pointer;font:inherit}
nav button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
main{max-width:1080px;margin:0 auto;padding:22px 24px 80px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:14px;display:grid;grid-template-columns:56px 1fr 210px;gap:18px}
.rank{font-size:30px;font-weight:700;color:#c9c6bf;line-height:1}.score{font-size:12px;color:var(--mute);margin-top:6px}
.segs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;align-items:center}
.seg{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1efe9;border-radius:6px;padding:3px 8px}
.kind{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute)}
.row{margin:6px 0;display:grid;grid-template-columns:96px 1fr;gap:0 4px}.row.t{display:block}.lab{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.lab.h{color:var(--hook)}.lab.c{color:var(--cliff)}.lab.w{color:var(--ok)}.t{color:var(--mute);font-size:12px}
.why{font-weight:500}.with{font-size:12px;color:var(--mute);margin-left:100px}
.bars div{display:grid;grid-template-columns:78px 1fr 34px;align-items:center;gap:6px;font-size:11px;color:var(--mute);margin:3px 0}
.bar{height:6px;background:#eeece6;border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ink)}
.stab{font-size:11px;border-radius:999px;padding:2px 8px;display:inline-block;margin-top:8px}.stab.hi{background:#dcfce7;color:#166534}.stab.mid{background:#e0e7ff;color:#3730a3}.stab.lo{background:#fee2e2;color:#991b1b}
.flags{margin-top:8px}.flag{display:inline-block;font-size:11px;background:#fef3c7;color:var(--warn);border-radius:999px;padding:2px 8px;margin:2px 4px 0 0}
details{margin-top:10px}summary{cursor:pointer;color:var(--mute);font-size:12px}
.tx{font-size:12.5px;margin-top:6px;border-left:2px solid var(--line);padding-left:10px;max-height:340px;overflow:auto}
.tx p{margin:3px 0}.tx .tc{font:11px ui-monospace,monospace;color:var(--mute);margin-right:6px}.tx .sp{font-weight:600}.tx .ac{color:#57534e;font-style:italic}
.fb{display:flex;gap:6px;margin-top:12px}.fb button{flex:1;border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px;cursor:pointer;font:inherit;font-size:12px}
.fb button.sel-up{background:#dcfce7;border-color:#86efac}.fb button.sel-down{background:#fee2e2;border-color:#fca5a5}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:12.5px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#faf9f6;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
.mono{font-family:ui-monospace,monospace;font-size:11.5px}.hide{display:none}
.method{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px 24px}
@media(max-width:820px){.card{grid-template-columns:1fr}}
"""

JS = """
const D=JSON.parse(document.getElementById('data').textContent);
const fb=JSON.parse((()=>{try{return localStorage.getItem('pf_fb_'+D.show)||'{}'}catch(e){return '{}'}})());
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function bars(c){return ['hook','cliff','standalone','arc','premise'].map(k=>`<div><span>${k}</span><span class=bar><i style="width:${Math.round(c[k]*100)}%"></i></span><span>${c[k].toFixed(2)}</span></div>`).join('')}
function card(p){const segs=p.segments.map(s=>`<span class=seg>E${s.episode} ${s.start} → ${s.end}</span>`).join('<span class=t>+</span>');
const tx=p.transcript.map(l=>`<p><span class=tc>E${l.episode} ${l.start}</span>${l.kind=='dialogue'?`<span class=sp>${esc(l.speaker)}</span> <span class=t>(${esc(l.tags.join(', '))})</span> ${esc(l.text)}`:`<span class=ac>[${l.kind}] ${esc(l.text)}</span>`} <span class=t>L${l.src_line}</span></p>`).join('');
const f=fb[p.id]||'';
return `<div class=card id="${p.id}"><div><div class=rank>${p.rank}</div><div class=score>${p.score.toFixed(3)}</div></div>
<div><div class=segs>${segs}<span class=kind>${p.duration_s.toFixed(1)}s · ${p.type.replace('_',' ')}</span></div>
<div class=row><span class="lab h">Hook</span><span>${esc(p.hook.text)} <span class=t>· ${p.hook.type}</span></span></div>
<div class=row><span class="lab c">Cliffhanger</span><span>${esc(p.cliffhanger.text)} <span class=t>· ${p.cliffhanger.type}</span></span></div>
${p.cliffhanger.withheld_next_beat?`<div class=with>Withheld next beat → ${esc(p.cliffhanger.withheld_next_beat)}</div>`:''}
<div class=row><span class="lab w">Why</span><span class=why>${esc(p.why_it_works)}</span></div>
<div class="row t">${esc(p.rank_reason)}</div>
<details><summary>Transcript & source lines (${p.segments.map(s=>s.src_file+' L'+s.src_lines.join('–')).join('; ')})</summary><div class=tx>${tx}</div></details></div>
<div><div class=bars>${bars(p.components)}</div>${p.components.stability!=null?`<span class="stab ${p.components.stability>=.9?'hi':p.components.stability>=.6?'mid':'lo'}" title="share of alternative weightings that keep this pick">${p.components.stability>=.9?'robust':p.components.stability>=.6?'likely':'borderline'} · ${Math.round(p.components.stability*100)}%</span>`:''}<div class=flags>${p.risk_flags.map(x=>`<span class=flag>${esc(x)}</span>`).join('')}</div>
<div class=fb><button class="${f=='up'?'sel-up':''}" onclick="vote('${p.id}','up',this)">✓ Use</button><button class="${f=='down'?'sel-down':''}" onclick="vote('${p.id}','down',this)">✗ Reject</button></div></div></div>`}
function vote(id,v,el){fb[id]=v;try{localStorage.setItem('pf_fb_'+D.show,JSON.stringify(fb))}catch(e){}
 if(window.PF_SERVER){fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run:D.run||'',show:D.show,id:id,vote:v,components:(D.top.concat(D.longlist)).find(p=>p.id==id).components})})}
 el.parentNode.querySelectorAll('button').forEach(b=>b.className='');el.className=v=='up'?'sel-up':'sel-down'}
function table(ps){return `<table><tr><th>#</th><th>Segments</th><th>Hook</th><th>Cliffhanger</th><th>Score</th><th>Flags</th></tr>${ps.map(p=>`<tr><td>${p.rank}</td><td class=mono>${p.segments.map(s=>`E${s.episode} ${s.start}-${s.end}`).join('<br>')}</td><td>${esc(p.hook.text)}</td><td>${esc(p.cliffhanger.text)}</td><td>${p.score.toFixed(3)}</td><td>${p.risk_flags.map(esc).join('<br>')}</td></tr>`).join('')}</table>`}
document.getElementById('top').innerHTML=D.top.map(card).join('');
document.getElementById('long').innerHTML=table(D.longlist);
function tab(n){['top','long','method'].forEach(x=>{document.getElementById(x).classList.toggle('hide',x!=n);document.getElementById('b_'+x).classList.toggle('on',x==n)})}
"""

METHOD = """<div class=method><h3>How these were chosen</h3>
<p>Every legal cut point in every episode is scored (a cut never splits a line of dialogue). All 20–60s windows between cut points, plus cross-episode bridges and cold-open edits, are candidates.</p>
<ul><li><b>Hook</b> (first 3s): weak supervision — transparent labeling functions over action verbs, shock lines, delivery-tag arousal and confrontation, combined by a generative label model and a text classifier (cross-fitted by episode).</li>
<li><b>Cliffhanger</b> (last 6s): open content (questions, threats, interrupted lines, reveals) + <i>withheld payoff</i> (how strong the next beat the viewer is denied is) − closure cues.</li>
<li><b>Standalone</b>: relationship words that explain the stakes, penalties for mid-exchange openings, location jumps and names introduced in earlier episodes.</li>
<li><b>Arc</b>: emotional peak, mean and escalation from delivery tags. <b>Premise</b>: how well the clip sells the show's title promise.</li></ul>
<p>Score = weighted geometric mean (a promo with no hook or no cliffhanger cannot rank high) × duration fit × mild late-episode spoiler prior. Final picks use diversity selection (no overlaps, ≤2 per episode, content-dissimilar).</p>
<p>Flags mark known failure modes. ✓/✗ votes are stored and can re-fit the weights (<code>python -m promofinder.learn_weights</code>).</p></div>"""


def html_report(show, meta, top, longlist, server=False, run_id=""):
    data = json.dumps({"show": show, "run": run_id, "top": top, "longlist": longlist}, ensure_ascii=False).replace("</", "<\\/")
    sub = (f"{meta['n_episodes']} episodes · {meta['runtime_minutes']} min of story · {meta['n_candidates']:,} candidate clips scored · "
           f"PromoFinder v{meta['version']} · {meta['run_at']}")
    return f"""<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Promos — {html.escape(show)}</title><style>{CSS}</style></head><body>
<header><h1>Promo candidates · {html.escape(show)}</h1><div class=sub>{html.escape(sub)}</div>
<nav><button id=b_top class=on onclick="tab('top')">Top {len(top)}</button><button id=b_long onclick="tab('long')">Longlist ({len(longlist)})</button><button id=b_method onclick="tab('method')">Method</button>{'<a href="/" style="margin-left:auto;align-self:center;color:#6b6b70">New run</a>' if server else ''}</nav></header>
<main><div id=top></div><div id=long class=hide></div><div id=method class=hide>{METHOD}</div></main>
<script id=data type="application/json">{data}</script><script>window.PF_SERVER={'true' if server else 'false'};{JS}</script></body></html>"""
