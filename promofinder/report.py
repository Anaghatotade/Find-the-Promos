"""Self-contained HTML report (works offline; also served by the web app)."""
import json, html
from .theme import BASE_CSS, HEAD, BRAND, topbar

CSS = BASE_CSS + """
/* ---------- results header ---------- */
.rh{background:var(--night);color:var(--on-night)}
.rh .kicker{color:var(--night-mute)}
.hd{max-width:var(--wrap);margin:0 auto;padding:52px var(--gut) 0}
.hd h1{font-size:68px;line-height:.96;max-width:18ch}
.stats{display:flex;flex-wrap:wrap;gap:0;margin:34px 0 0;padding:0;border-top:1px solid var(--night-rule)}
.stats div{padding:16px 34px 16px 0;margin-right:34px;border-right:1px solid var(--night-rule)}
.stats div:last-child{border-right:0;margin-right:0}
.stats dt{font:500 11px/1.2 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--night-mute);margin-bottom:8px}
.stats dd{margin:0;font:400 24px/1 var(--mono);font-variant-numeric:tabular-nums;color:var(--on-night)}
nav.tabs{display:flex;gap:4px;margin-top:18px;overflow-x:auto;scrollbar-width:none}
nav.tabs button{background:none;border:0;border-bottom:2px solid transparent;color:var(--night-mute);padding:16px 18px 15px;border-radius:0;
font:500 14px/1 var(--sans);white-space:nowrap}
nav.tabs button:first-child{padding-left:0}
nav.tabs button:hover{background:none;color:var(--on-night)}
nav.tabs button.on{color:var(--on-night);border-bottom-color:var(--hook);font-weight:600}
nav.tabs button .ct{font:400 12px var(--mono);color:var(--night-mute);margin-left:7px;opacity:.75}
nav.tabs button.on .ct{color:var(--hook);opacity:1}
/* ---------- notes + exports (injected by the web app) ---------- */
.notes,.dl{max-width:var(--wrap);margin:0 auto;padding:0 var(--gut)}
.notes>div{margin-top:24px;background:var(--mark-bg);border-left:3px solid var(--mark);padding:12px 18px;color:var(--mark-ink);font-size:14px}
.notes b{font:500 11.5px/1.4 var(--mono);letter-spacing:.1em;text-transform:uppercase}
.notes ul{margin:6px 0 0;padding-left:18px}.notes li{margin:2px 0}
.dl{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:24px;font-size:13.5px}
.dl .mute,.dl .dl-label{font:500 11px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mute);margin-right:6px}
.dl a{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border:1px solid var(--rule);border-radius:var(--r);background:var(--sheet);
text-decoration:none;font-weight:500;white-space:nowrap;color:var(--ink)}
.dl a::before{content:"\\2193";font-family:var(--mono);color:var(--mute)}
.dl a:hover{border-color:var(--ink)}
.dl a.dl-primary{background:var(--ink);border-color:var(--ink);color:var(--on-night)}
.dl a.dl-primary::before{color:var(--mark)}
.dl a.dl-primary:hover{background:var(--night-2)}
/* ---------- main ---------- */
main{max-width:var(--wrap);margin:0 auto;padding:28px var(--gut) 80px}
.key{display:flex;gap:22px;flex-wrap:wrap;margin:0 0 6px;font:12px/1.4 var(--mono);color:var(--mute)}
.key span{display:inline-flex;align-items:center;gap:8px}
.key i{display:inline-block;width:22px;height:10px}
.sw-h{background:var(--hook)}.sw-c{background:var(--hatch),var(--sheet);box-shadow:inset 0 0 0 1px var(--ink)}.sw-m{background:var(--mark)}
/* ---------- promo row (ruled list, not boxed cards) ---------- */
.promo{display:grid;grid-template-columns:96px minmax(0,1fr) 252px;gap:36px;padding:40px 0 42px;border-top:1px solid var(--rule)}
#top .promo:first-child{border-top:2px solid var(--ink)}
.promo:target{background:linear-gradient(var(--mark-bg),var(--mark-bg)) no-repeat;background-size:100% 100%}
.rank{font:400 84px/.8 var(--serif);color:var(--ink);letter-spacing:-.03em}
.score{font:12px/1.3 var(--mono);color:var(--mute);margin-top:14px;font-variant-numeric:tabular-nums}
.score b{display:block;font-weight:500;font-size:17px;color:var(--ink);margin-top:2px}
.top-pick{display:inline-block;margin-top:14px;font:500 10.5px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;
background:var(--hook);color:var(--sheet);padding:5px 7px;border-radius:2px}
.tcs{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.tc{font:500 17px/1 var(--mono);font-variant-numeric:tabular-nums;color:var(--ink);background:var(--sheet);border:1px solid var(--rule);
padding:8px 11px;border-radius:var(--r);white-space:nowrap}
.tc b{font-weight:500;color:var(--hook-ink);margin-right:8px}
.tc i{font-style:normal;color:var(--faint);margin:0 3px}
.plus{font:500 15px var(--mono);color:var(--mute)}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:13.5px;color:var(--mute);margin:12px 0 18px}
.meta .d{font-family:var(--mono);color:var(--ink-2)}
.meta .sep{width:4px;height:4px;border-radius:50%;background:var(--faint)}
/* timeline strip */
.strip{position:relative;height:20px;background:var(--soft);margin:0 0 6px;overflow:hidden;border-radius:2px}
.strip .tick{position:absolute;inset:0;background-image:linear-gradient(90deg,var(--soft-2) 1px,transparent 1px)}
.strip .zh{position:absolute;top:0;bottom:0;left:0;background:var(--hook)}
.strip .zc{position:absolute;top:0;bottom:0;right:0;background:var(--hatch),var(--sheet);box-shadow:inset 1px 0 0 var(--ink)}
.strip .mk{position:absolute;top:0;bottom:0;width:3px;background:var(--mark)}
.strip .sp{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--paper)}
.scale{display:flex;justify-content:space-between;color:var(--mute);font:11px var(--mono);margin-bottom:22px;font-variant-numeric:tabular-nums}
/* hook / cut lines */
.line{display:grid;grid-template-columns:78px minmax(0,1fr);gap:16px;margin:0 0 12px;align-items:baseline}
.line>b{font:500 11px/1.6 var(--mono);letter-spacing:.1em;text-transform:uppercase;display:flex;align-items:center;gap:7px}
.line>b::before{content:"";width:8px;height:8px;flex:none}
.line.h>b{color:var(--hook-ink)}.line.h>b::before{background:var(--hook)}
.line.c>b{color:var(--ink)}.line.c>b::before{background:var(--hatch),var(--sheet);box-shadow:inset 0 0 0 1px var(--ink)}
.line>span{font-size:16.5px;line-height:1.5;color:var(--ink)}
.line .type{font:12px var(--mono);color:var(--mute);margin-left:4px;white-space:nowrap}
.withheld{margin:-2px 0 14px 94px;color:var(--mute);font-size:13.5px;padding-left:14px;border-left:1px dashed var(--faint)}
.why{margin:22px 0 8px;font:400 23px/1.3 var(--serif);color:var(--ink);max-width:40em;letter-spacing:-.005em}
.reason{color:var(--mute);font-size:13.5px;max-width:72ch;margin:0}
details{margin-top:18px;border-top:1px dashed var(--rule);padding-top:12px}
summary{cursor:pointer;font:500 12.5px var(--mono);letter-spacing:.04em;color:var(--ink-2);list-style:none;display:inline-flex;align-items:center;gap:8px}
summary::-webkit-details-marker{display:none}
summary::before{content:"+";display:inline-grid;place-items:center;width:18px;height:18px;border:1px solid var(--rule);border-radius:2px;font-size:13px;color:var(--ink)}
details[open] summary::before{content:"\\2212"}
summary:hover{color:var(--ink)}
.tx{font-size:14px;margin-top:12px;background:var(--sheet);border:1px solid var(--rule);padding:12px 16px;max-height:380px;overflow:auto}
.tx p{margin:5px 0}.tx .t{color:var(--faint);font:11.5px var(--mono);font-variant-numeric:tabular-nums;margin-right:10px}
.tx .sp{font-weight:600}.tx .tg{color:var(--mute);font-size:13px}.tx .ac{color:var(--mute);font-style:italic}
/* side column */
.side{border-left:1px solid var(--rule);padding-left:26px}
.side .bars div{display:grid;grid-template-columns:80px 1fr 36px;align-items:center;gap:10px;font-size:12.5px;color:var(--ink-2);margin:0 0 9px}
.side .bars .num{font-size:12px;text-align:right;color:var(--ink)}
.bar{height:6px;background:var(--soft);overflow:hidden}.bar i{display:block;height:100%;background:var(--ink)}
.bars div:nth-child(1) .bar i{background:var(--hook)}
.bars div:nth-child(2) .bar i{background:var(--hatch),var(--soft-2)}
.stab{display:inline-flex;align-items:center;gap:7px;margin-top:10px;font:500 12px var(--mono);padding:5px 9px;border:1px solid}
.stab::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.stab.hi{color:var(--ok);border-color:currentColor;background:var(--ok-bg)}
.stab.mid{color:var(--ink-2);border-color:var(--rule)}
.stab.lo{color:var(--hook-ink);border-color:currentColor;background:var(--hook-bg)}
.flags{margin-top:10px}
.flag{display:block;font-size:12.5px;line-height:1.4;color:var(--mark-ink);background:var(--mark-bg);border-left:3px solid var(--mark);padding:6px 10px;margin-top:6px}
.fb{display:grid;grid-template-columns:1fr 1fr;margin-top:18px;border:1px solid var(--ink);border-radius:var(--r);overflow:hidden}
.fb button{padding:10px 8px;font:600 13px/1 var(--sans);background:var(--sheet);color:var(--ink);border:0;border-radius:0;justify-content:center}
.fb button+button{border-left:1px solid var(--ink)}
.fb button:hover{background:var(--soft);color:var(--ink)}
.fb button:first-child::before{content:"\\2713";font-family:var(--mono)}
.fb button:last-child::before{content:"\\2715";font-family:var(--mono)}
.fb button.sel-up{background:var(--ink);color:var(--on-night)}
.fb button.sel-down{background:var(--hook);color:var(--sheet)}
/* longlist table */
.tbl{overflow-x:auto;border-top:2px solid var(--ink)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:760px}
th,td{padding:12px 14px 12px 0;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{font:500 11px/1.3 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mute);padding-top:14px}
td:first-child{font:400 22px/1 var(--serif);width:44px}
td.tc{font-size:13px;border:0;border-bottom:1px solid var(--rule);border-radius:0;background:none;padding:12px 14px 12px 0}
td.num{font-family:var(--mono)}
tr:hover td{background:var(--sheet)}
.hide{display:none}
/* method */
.method{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:48px;border-top:2px solid var(--ink);padding-top:30px}
.method h2{font-size:40px}
.method p:not(.kicker),.method li{font-size:16px;color:var(--ink-2);max-width:66ch}
.method ul{padding:0;list-style:none;margin:18px 0;border-top:1px solid var(--rule);max-width:66ch}
.method li{padding:12px 0;border-bottom:1px solid var(--rule);margin:0}
.method li b{color:var(--ink)}
footer.foot{margin-top:0}
@media(max-width:980px){.promo{grid-template-columns:64px minmax(0,1fr);gap:20px 22px}.side{grid-column:2;border-left:0;padding-left:0;
border-top:1px dashed var(--rule);padding-top:18px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 28px;align-items:start}
.side .bars{grid-row:span 3}.rank{font-size:56px}.method{grid-template-columns:1fr;gap:10px}}
@media(max-width:640px){.hd{padding-top:34px}.hd h1{font-size:44px}.stats{display:grid;grid-template-columns:1fr 1fr}.stats div{margin-right:0;padding:14px 12px 14px 0;border-right:0}.stats div:nth-child(odd){border-right:1px solid var(--night-rule)}.stats div:nth-child(even){padding-left:16px}.stats dd{font-size:18px}
.promo{grid-template-columns:1fr;padding:26px 0 28px}.p-rank{display:flex;align-items:baseline;gap:14px}.score{margin:0}.score b{display:inline;margin-left:4px}
.top-pick{margin:0}.rank{font-size:48px}.side{grid-column:1;display:block}.line{grid-template-columns:1fr;gap:2px}.withheld{margin-left:0}
.why{font-size:20px}.tc{font-size:15px}}
@media print{.topbar,nav.tabs,.dl,.fb,details{display:none}body{background:#fff}.promo{break-inside:avoid}}
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
 return `<div class=strip role=img aria-label="Clip timeline: first 3 s is the hook window, last 6 s is the cut" title="Clip timeline: first 3 s is the hook window, last 6 s is the cut"><span class=tick style="background-size:${tk}% 100%"></span>`+
 `<span class=zh style="width:${h.toFixed(2)}%"></span><span class=zc style="width:${c.toFixed(2)}%"></span>${sp}`+
 `<span class=mk style="left:0"></span><span class=mk style="right:0"></span></div><div class=scale><span>0 s</span><span>${T.toFixed(1)} s</span></div>`}
function card(p){
const tcs=p.segments.map(s=>`<span class=tc><b>E${s.episode}</b>${s.start}<i>&ndash;</i>${s.end}</span>`).join('<span class=plus>+</span>');
const kind={single:'Single scene',cross_episode:'Bridges two episodes',cold_open:'Cold open: hook first, then the story'}[p.type]||p.type;
const src=p.segments.map(s=>esc(s.src_file)+', lines '+s.src_lines.join('&ndash;')).join('; ');
const tx=p.transcript.map(l=>`<p><span class=t>E${l.episode} ${l.start}</span>${l.kind=='dialogue'?`<span class=sp>${esc(l.speaker)}</span> <span class=tg>(${esc(l.tags.join(', '))})</span> ${esc(l.text)}`:`<span class=ac>${esc(l.text)}</span>`} <span class=t>L${l.src_line}</span></p>`).join('');
const st=p.components.stability, f=fb[p.id]||'';
const stab=st==null?'':`<span class="stab ${st>=.9?'hi':st>=.6?'mid':'lo'}" title="Share of 200 alternative weightings that keep this pick">${st>=.9?'Robust':st>=.6?'Likely':'Borderline'} pick, ${Math.round(st*100)}%</span>`;
return `<article class=promo id="${p.id}" aria-label="Promo ${p.rank}"><div class=p-rank><div class=rank>${p.rank}</div><div class=score>score <b>${p.score.toFixed(3)}</b></div>${p.rank==1?'<span class=top-pick>Top pick</span>':''}</div>
<div class=p-main><div class=tcs>${tcs}</div><div class=meta><span class=d>${p.duration_s.toFixed(1)} s</span><span class=sep></span><span>${kind}</span></div>${strip(p)}
<div class="line h"><b>Hook</b><span>${esc(p.hook.text)} <span class=type>${esc(p.hook.type)}</span></span></div>
<div class="line c"><b>Cut on</b><span>${esc(p.cliffhanger.text)} <span class=type>${esc(p.cliffhanger.type)}</span></span></div>
${p.cliffhanger.withheld_next_beat?`<div class=withheld>The viewer doesn't get to see: ${esc(p.cliffhanger.withheld_next_beat)}</div>`:''}
<p class=why>${esc(p.why_it_works)}</p><p class=reason>${esc(p.rank_reason)}</p>
<details><summary>Transcript and source lines</summary><p class=mute style="font-size:12px;margin:10px 0 0;font-family:var(--mono)">${src}</p><div class=tx>${tx}</div></details></div>
<aside class=side aria-label="Scores for promo ${p.rank}"><div class=bars>${bars(p.components)}</div><div>${stab}<div class=flags>${p.risk_flags.map(x=>`<span class=flag>${esc(x)}</span>`).join('')}</div></div>
<div class=fb role=group aria-label="Editor vote"><button class="${f=='up'?'sel-up':''}" onclick="vote('${p.id}','up',this)">Use</button><button class="${f=='down'?'sel-down':''}" onclick="vote('${p.id}','down',this)">Reject</button></div></aside></article>`}
function vote(id,v,el){fb[id]=v;try{localStorage.setItem('pf_fb_'+D.show,JSON.stringify(fb))}catch(e){}
 if(window.PF_SERVER){fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run:D.run||'',show:D.show,id:id,vote:v,components:(D.top.concat(D.longlist)).find(p=>p.id==id).components})})}
 el.parentNode.querySelectorAll('button').forEach(b=>b.className='');el.className=v=='up'?'sel-up':'sel-down'}
function table(ps){return `<table><tr><th>#</th><th>Clip</th><th>Hook</th><th>Cut on</th><th>Score</th><th>Flags</th></tr>${ps.map(p=>`<tr><td>${p.rank}</td><td class=tc>${p.segments.map(s=>`E${s.episode} ${s.start}&ndash;${s.end}`).join('<br>')}</td><td>${esc(p.hook.text)}</td><td>${esc(p.cliffhanger.text)}</td><td class=num>${p.score.toFixed(3)}</td><td>${p.risk_flags.map(esc).join('<br>')}</td></tr>`).join('')}</table>`}
document.getElementById('top').innerHTML=D.top.map(card).join('');
document.getElementById('long').innerHTML='<div class=tbl>'+table(D.longlist)+'</div>';
const TABS=['top','long','method'];
function tab(n){TABS.forEach(x=>{const on=x==n,b=document.getElementById('b_'+x);document.getElementById(x).classList.toggle('hide',!on);
 b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false');b.tabIndex=on?0:-1});document.getElementById('key').classList.toggle('hide',n!='top')}
document.querySelector('nav.tabs').addEventListener('keydown',e=>{const cur=TABS.findIndex(x=>document.getElementById('b_'+x).classList.contains('on'));
 const i=e.key=='ArrowRight'?(cur+1)%3:e.key=='ArrowLeft'?(cur+2)%3:-1;if(i<0)return;e.preventDefault();tab(TABS[i]);document.getElementById('b_'+TABS[i]).focus()});
"""

METHOD = """<div class=method><div><p class=kicker>Method</p><h2>How these were chosen</h2></div><div>
<p>Every legal cut point in every episode is scored (a cut never splits a line of dialogue). All 20&ndash;60 s windows between cut points, plus cross-episode bridges and cold-open edits, are candidates.</p>
<ul><li><b>Hook</b> (first 3 s): weak supervision. Transparent labeling functions over action verbs, shock lines, delivery-tag intensity and confrontation, combined by a generative label model and a text classifier, cross-fitted by episode.</li>
<li><b>Cut</b> (last 6 s): open content (questions, threats, interrupted lines, reveals) plus the strength of the beat the viewer is denied, minus closure cues.</li>
<li><b>Standalone</b>: relationship words that explain the stakes, with penalties for mid-exchange openings, location jumps and names introduced in earlier episodes.</li>
<li><b>Intensity</b>: emotional peak, mean and escalation from delivery tags. <b>Premise</b>: how well the clip sells the show's title promise.</li></ul>
<p>The score is a weighted geometric mean, so a promo with no hook or no cut cannot rank high, adjusted for duration and a mild late-episode spoiler preference. Final picks don't overlap, take at most two per episode and differ in content.</p>
<p>Flags mark known failure modes. Use and Reject votes are stored and can re-fit the weights (<code>python -m promofinder.learn_weights</code>).</p></div></div>"""


def html_report(show, meta, top, longlist, server=False, run_id=""):
    data = json.dumps({"show": show, "run": run_id, "top": top, "longlist": longlist}, ensure_ascii=False).replace("</", "<\\/")
    stats = [("Episodes", f"{meta['n_episodes']}"), ("Minutes of story", f"{float(meta['runtime_minutes']):.1f}"),
             ("Clips scored", f"{meta['n_candidates']:,}"), ("Shortlisted", f"{len(top)}")]
    stats_html = "".join(f"<div><dt>{k}</dt><dd>{html.escape(v)}</dd></div>" for k, v in stats)
    right = ('<a href="/demo" class=hide-sm>Live demo</a><a href="/">New run</a>' if server
             else f'<span class=ver>{html.escape(str(meta.get("version", "")))}</span>')
    tab_btn = lambda i, label, ct, on: (f'<button id=b_{i} role=tab aria-controls={i} aria-selected={"true" if on else "false"}'
                                        f'{"" if on else " tabindex=-1"}{" class=on" if on else ""} onclick="tab(\'{i}\')">{label}'
                                        f'{f"<span class=ct>{ct}</span>" if ct != "" else ""}</button>')
    return f"""<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Promos: {html.escape(show)} · {BRAND}</title><meta name=description content="Ranked promo candidates for {html.escape(show)}, scored by {BRAND}.">{HEAD}<style>{CSS}</style></head><body>
{topbar(right, home_link=server)}
<header class=rh><div class=hd><p class=kicker><b>&#9679;</b>&nbsp; Promo candidates</p><h1>{html.escape(show)}</h1>
<dl class=stats>{stats_html}</dl>
<nav class=tabs role=tablist aria-label="Result views">{tab_btn('top', 'Top', len(top), True)}{tab_btn('long', 'Longlist', len(longlist), False)}{tab_btn('method', 'Method', '', False)}</nav></div></header>
<main><p class=key id=key><span><i class=sw-h></i>Hook window, first 3 s</span><span><i class=sw-c></i>Cut, last 6 s</span><span><i class=sw-m></i>In and out points</span></p>
<div id=top role=tabpanel aria-labelledby=b_top></div><div id=long class=hide role=tabpanel aria-labelledby=b_long></div><div id=method class=hide role=tabpanel aria-labelledby=b_method>{METHOD}</div></main>
<footer class=foot><span>{BRAND} {html.escape(str(meta.get('version', '')))}, run {html.escape(str(meta.get('run_at', '')))}</span><span>Timecodes are episode-relative. Every cut lands between lines of dialogue.</span></footer>
<script id=data type="application/json">{data}</script><script>window.PF_SERVER={'true' if server else 'false'};{JS}</script></body></html>"""
