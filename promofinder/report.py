"""Self-contained HTML report (works offline; also served by the web app)."""
import json, html
from .theme import BASE_CSS

CSS = BASE_CSS + """
header{background:var(--sheet);border-bottom:1px solid var(--rule)}
.hd{max-width:1120px;margin:0 auto;padding:26px 28px 0}
.hd .kicker{color:var(--mute);font-size:14px;margin:0 0 2px}
.hd h1{font-size:40px}
.facts{color:var(--mute);margin:8px 0 0;max-width:72ch}
nav{display:flex;gap:26px;margin-top:20px;align-items:flex-end;overflow-x:auto}
nav button{background:none;border:0;border-bottom:3px solid transparent;color:var(--mute);padding:0 0 10px;border-radius:0;font-weight:600;white-space:nowrap}
nav button.on{color:var(--ink);border-bottom-color:var(--ink)}
nav a{margin-left:auto;padding-bottom:10px;font-weight:600;white-space:nowrap}
main{max-width:1120px;margin:0 auto;padding:22px 28px 90px}
.key{color:var(--mute);font-size:13px;margin:0 0 16px;display:flex;gap:18px;flex-wrap:wrap}
.key i{display:inline-block;width:18px;height:8px;border-radius:2px;margin-right:6px;vertical-align:middle}
.dl,.notes{max-width:1120px;margin:14px auto 0;padding:0 28px;font-size:14px}
.dl{display:flex;flex-wrap:wrap;gap:6px 16px}.dl a{font-weight:600;white-space:nowrap}
.notes>div{background:var(--warn-bg);border-left:4px solid var(--pencil);border-radius:4px;padding:10px 16px;color:#4d3800}
.notes ul{margin:4px 0 0;padding-left:18px}
.promo{background:var(--sheet);border:1px solid var(--rule);border-radius:8px;padding:22px 24px;margin-bottom:16px;
display:grid;grid-template-columns:58px minmax(0,1fr) 220px;gap:22px}
.rank{font-size:46px;line-height:.9;color:var(--ink)}
.score{color:var(--mute);font-size:12px;margin-top:8px;font-variant-numeric:tabular-nums}
.tc-big{font-size:22px;line-height:1.2}
.tc-big .ep{color:var(--mute);margin-right:4px}
.tc-big .plus{color:var(--mute);margin:0 8px}
.meta{color:var(--mute);font-size:13px;margin:2px 0 12px}
.strip{position:relative;height:14px;background:var(--soft);border-radius:3px;margin:0 0 4px;overflow:hidden}
.strip .tick{position:absolute;inset:0;background-image:linear-gradient(90deg,rgba(30,36,33,.18) 1px,transparent 1px)}
.strip .zh{position:absolute;top:0;bottom:0;left:0;background:var(--safelight)}
.strip .zc{position:absolute;top:0;bottom:0;right:0;background:var(--tape)}
.strip .mk{position:absolute;top:0;bottom:0;width:3px;background:var(--pencil)}
.strip .sp{position:absolute;top:0;bottom:0;width:2px;background:var(--sheet)}
.scale{display:flex;justify-content:space-between;color:var(--mute);font-size:11px;margin-bottom:14px;font-variant-numeric:tabular-nums}
.line{display:grid;grid-template-columns:70px minmax(0,1fr);gap:12px;margin:8px 0;align-items:baseline}
.line>b{font-size:13px}
.line.h>b{color:var(--safelight)}
.line.c>b{color:var(--tape)}
.line .type{color:var(--mute);font-size:13px}
.withheld{margin:-2px 0 8px 82px;color:var(--mute);font-size:13px}
.why{margin:12px 0 4px;font-weight:600;max-width:75ch}
.reason{color:var(--mute);font-size:13px;max-width:75ch}
details{margin-top:12px}
summary{cursor:pointer;color:var(--tape);font-size:13px;font-weight:600}
.tx{font-size:13.5px;margin-top:8px;border-left:3px solid var(--rule);padding-left:12px;max-height:360px;overflow:auto}
.tx p{margin:4px 0}.tx .t{color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums;margin-right:8px}
.tx .sp{font-weight:600}.tx .tg{color:var(--mute)}.tx .ac{color:var(--mute);font-style:italic}
.side .bars div{display:grid;grid-template-columns:76px 1fr 32px;align-items:center;gap:8px;font-size:12px;color:var(--mute);margin:5px 0}
.bar{height:5px;background:var(--soft);border-radius:2px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ink)}
.stab{display:inline-block;margin-top:12px;font-size:12px;font-weight:600;padding:3px 9px;border-radius:4px;border:1px solid}
.stab.hi{color:var(--tape);border-color:var(--tape)}.stab.mid{color:var(--ink);border-color:var(--rule)}.stab.lo{color:var(--safelight);border-color:var(--safelight)}
.flags{margin-top:10px}.flag{display:block;font-size:12px;color:var(--warn);background:var(--warn-bg);border-radius:4px;padding:4px 8px;margin-top:5px}
.fb{display:flex;gap:8px;margin-top:14px}.fb button{flex:1;padding:7px 8px;font-size:13px;background:var(--sheet);color:var(--ink);border:1px solid var(--rule)}
.fb button.sel-up{background:var(--tape);border-color:var(--tape);color:#fff}.fb button.sel-down{background:var(--safelight);border-color:var(--safelight);color:#fff}
table{width:100%;border-collapse:collapse;background:var(--sheet);border:1px solid var(--rule);font-size:13.5px}
th,td{padding:9px 11px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{font-weight:600;color:var(--mute);background:var(--paper)}
td.tc{white-space:nowrap;font-variant-numeric:tabular-nums}
.hide{display:none}
.method{background:var(--sheet);border:1px solid var(--rule);border-radius:8px;padding:24px 28px;max-width:80ch}
.method li{margin-bottom:6px}
footer{max-width:1120px;margin:0 auto;padding:0 28px 40px;color:var(--mute);font-size:12px}
@media(max-width:860px){.promo{grid-template-columns:1fr;gap:14px;padding:18px}.rank{font-size:34px}.hd h1{font-size:30px}.withheld{margin-left:0}nav{gap:18px}.hd,main,.dl,.notes{padding-left:18px;padding-right:18px}}
"""

JS = """
const D=JSON.parse(document.getElementById('data').textContent);
const fb=JSON.parse((()=>{try{return localStorage.getItem('pf_fb_'+D.show)||'{}'}catch(e){return '{}'}})());
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
const NAMES={hook:'Hook',cliff:'Cut',standalone:'Standalone',arc:'Intensity',premise:'Premise'};
function bars(c){return Object.keys(NAMES).map(k=>`<div><span>${NAMES[k]}</span><span class=bar><i style="width:${Math.round(c[k]*100)}%"></i></span><span class=num>${c[k].toFixed(2)}</span></div>`).join('')}
function strip(p){const T=p.duration_s||1;let x=0,sp='';
 p.segments.forEach((s,i)=>{if(i){sp+=`<span class=sp style="left:${(x/T*100).toFixed(2)}%"></span>`}x+=s.duration_s});
 const h=Math.min(3,T)/T*100,c=Math.min(6,T)/T*100,tk=(5/T*100).toFixed(3);
 return `<div class=strip title="Clip timeline: first 3 s is the hook window, last 6 s is the cut"><span class=tick style="background-size:${tk}% 100%"></span>`+
 `<span class=zh style="width:${h.toFixed(2)}%"></span><span class=zc style="width:${c.toFixed(2)}%"></span>${sp}`+
 `<span class=mk style="left:0"></span><span class=mk style="right:0"></span></div><div class=scale><span>0 s</span><span>${T.toFixed(1)} s</span></div>`}
function card(p){
const tcs=p.segments.map(s=>`<span class=ep>E${s.episode}</span>${s.start}&#8202;&ndash;&#8202;${s.end}`).join('<span class=plus>+</span>');
const kind={single:'Single scene',cross_episode:'Bridges two episodes',cold_open:'Cold open: hook first, then the story'}[p.type]||p.type;
const src=p.segments.map(s=>esc(s.src_file)+', lines '+s.src_lines.join('&ndash;')).join('; ');
const tx=p.transcript.map(l=>`<p><span class=t>E${l.episode} ${l.start}</span>${l.kind=='dialogue'?`<span class=sp>${esc(l.speaker)}</span> <span class=tg>(${esc(l.tags.join(', '))})</span> ${esc(l.text)}`:`<span class=ac>${esc(l.text)}</span>`} <span class=t>L${l.src_line}</span></p>`).join('');
const st=p.components.stability, f=fb[p.id]||'';
const stab=st==null?'':`<span class="stab ${st>=.9?'hi':st>=.6?'mid':'lo'}" title="Share of 200 alternative weightings that keep this pick">${st>=.9?'Robust':st>=.6?'Likely':'Borderline'} pick, ${Math.round(st*100)}%</span>`;
return `<article class=promo id="${p.id}"><div><div class=rank>${p.rank}</div><div class=score>score ${p.score.toFixed(3)}</div></div>
<div><div class=tc-big>${tcs}</div><div class=meta>${p.duration_s.toFixed(1)} s, ${kind.toLowerCase()}</div>${strip(p)}
<div class="line h"><b>Hook</b><span>${esc(p.hook.text)} <span class=type>(${esc(p.hook.type)})</span></span></div>
<div class="line c"><b>Cut on</b><span>${esc(p.cliffhanger.text)} <span class=type>(${esc(p.cliffhanger.type)})</span></span></div>
${p.cliffhanger.withheld_next_beat?`<div class=withheld>The viewer doesn't get to see: ${esc(p.cliffhanger.withheld_next_beat)}</div>`:''}
<p class=why>${esc(p.why_it_works)}</p><p class=reason>${esc(p.rank_reason)}</p>
<details><summary>Transcript and source lines</summary><p class=mute style="font-size:12px;margin:6px 0 0">${src}</p><div class=tx>${tx}</div></details></div>
<div class=side><div class=bars>${bars(p.components)}</div>${stab}<div class=flags>${p.risk_flags.map(x=>`<span class=flag>${esc(x)}</span>`).join('')}</div>
<div class=fb><button class="${f=='up'?'sel-up':''}" onclick="vote('${p.id}','up',this)">Use</button><button class="${f=='down'?'sel-down':''}" onclick="vote('${p.id}','down',this)">Reject</button></div></div></article>`}
function vote(id,v,el){fb[id]=v;try{localStorage.setItem('pf_fb_'+D.show,JSON.stringify(fb))}catch(e){}
 if(window.PF_SERVER){fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run:D.run||'',show:D.show,id:id,vote:v,components:(D.top.concat(D.longlist)).find(p=>p.id==id).components})})}
 el.parentNode.querySelectorAll('button').forEach(b=>b.className='');el.className=v=='up'?'sel-up':'sel-down'}
function table(ps){return `<table><tr><th>#</th><th>Clip</th><th>Hook</th><th>Cut on</th><th>Score</th><th>Flags</th></tr>${ps.map(p=>`<tr><td>${p.rank}</td><td class=tc>${p.segments.map(s=>`E${s.episode} ${s.start}&ndash;${s.end}`).join('<br>')}</td><td>${esc(p.hook.text)}</td><td>${esc(p.cliffhanger.text)}</td><td class=num>${p.score.toFixed(3)}</td><td>${p.risk_flags.map(esc).join('<br>')}</td></tr>`).join('')}</table>`}
document.getElementById('top').innerHTML=D.top.map(card).join('');
document.getElementById('long').innerHTML=table(D.longlist);
function tab(n){['top','long','method'].forEach(x=>{document.getElementById(x).classList.toggle('hide',x!=n);document.getElementById('b_'+x).classList.toggle('on',x==n)});document.getElementById('key').classList.toggle('hide',n!='top')}
"""

METHOD = """<div class=method><h2>How these were chosen</h2>
<p>Every legal cut point in every episode is scored (a cut never splits a line of dialogue). All 20&ndash;60 s windows between cut points, plus cross-episode bridges and cold-open edits, are candidates.</p>
<ul><li><b>Hook</b> (first 3 s): weak supervision. Transparent labeling functions over action verbs, shock lines, delivery-tag intensity and confrontation, combined by a generative label model and a text classifier, cross-fitted by episode.</li>
<li><b>Cut</b> (last 6 s): open content (questions, threats, interrupted lines, reveals) plus the strength of the beat the viewer is denied, minus closure cues.</li>
<li><b>Standalone</b>: relationship words that explain the stakes, with penalties for mid-exchange openings, location jumps and names introduced in earlier episodes.</li>
<li><b>Intensity</b>: emotional peak, mean and escalation from delivery tags. <b>Premise</b>: how well the clip sells the show's title promise.</li></ul>
<p>The score is a weighted geometric mean, so a promo with no hook or no cut cannot rank high, adjusted for duration and a mild late-episode spoiler preference. Final picks don't overlap, take at most two per episode and differ in content.</p>
<p>Flags mark known failure modes. Use and Reject votes are stored and can re-fit the weights (<code>python -m promofinder.learn_weights</code>).</p></div>"""


def html_report(show, meta, top, longlist, server=False, run_id=""):
    data = json.dumps({"show": show, "run": run_id, "top": top, "longlist": longlist}, ensure_ascii=False).replace("</", "<\\/")
    facts = (f"{meta['n_episodes']} episodes and {float(meta['runtime_minutes']):.1f} minutes of story. "
             f"{meta['n_candidates']:,} candidate clips scored; the strongest {len(top)} are below.")
    new_run = '<a href="/">New run</a>' if server else ''
    return f"""<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Promos: {html.escape(show)}</title><style>{CSS}</style></head><body>
<header><div class=hd><p class=kicker>Promo candidates</p><h1>{html.escape(show)}</h1><p class=facts>{html.escape(facts)}</p>
<nav><button id=b_top class=on onclick="tab('top')">Top {len(top)}</button><button id=b_long onclick="tab('long')">Longlist of {len(longlist)}</button><button id=b_method onclick="tab('method')">Method</button>{new_run}</nav></div></header>
<main><p class=key id=key><span><i style="background:var(--safelight)"></i>Hook window, first 3 s</span><span><i style="background:var(--tape)"></i>Cut, last 6 s</span><span><i style="background:var(--pencil)"></i>In and out points</span></p>
<div id=top></div><div id=long class=hide></div><div id=method class=hide>{METHOD}</div></main>
<footer>PromoFinder {html.escape(str(meta.get('version', '')))}, run {html.escape(str(meta.get('run_at', '')))}</footer>
<script id=data type="application/json">{data}</script><script>window.PF_SERVER={'true' if server else 'false'};{JS}</script></body></html>"""
