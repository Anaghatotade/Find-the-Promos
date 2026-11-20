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
/* ---------- highlight taxonomy: one colour + glyph per hook / cut type ---------- */
:root{--t-phys:#b8321f;--t-phys-bg:#f7dcd5;--t-shock:#c2410c;--t-shock-bg:#fbe3d1;--t-emo:#a1286a;--t-emo-bg:#f5dbe8;
--t-conf:#7a3e9d;--t-conf-bg:#ebdff3;--t-open:#4f6b2c;--t-open-bg:#e4ecd6;--t-q:#1f5f8b;--t-q-bg:#d9e8f3;--t-oq:#2b7a78;--t-oq-bg:#d6eeec;
--t-threat:#8f1d1d;--t-threat-bg:#f3d6d6;--t-int:#6b5a12;--t-int-bg:#f2ebcc;--t-rev:#9a4b00;--t-rev-bg:#f8e4cc;--t-peak:#3e4b8a;--t-peak-bg:#dde1f2}
.bdg{display:inline-flex;align-items:center;gap:6px;font:600 11px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;
padding:5px 9px 5px 7px;border-radius:999px;color:var(--c);background:var(--cb);border:1px solid color-mix(in srgb,var(--c) 35%,transparent);
white-space:nowrap;vertical-align:2px;margin-left:6px;cursor:help}
.bdg .g{display:inline-grid;place-items:center;width:15px;height:15px;border-radius:50%;background:var(--c);color:var(--sheet);font-size:9px;letter-spacing:0}
.bdg.sm{font-size:9.5px;padding:3px 7px 3px 5px;margin:4px 0 0}.bdg.sm .g{width:12px;height:12px;font-size:8px}
.line.h,.line.c{padding:10px 12px;border-radius:var(--r);background:color-mix(in srgb,var(--cb) 45%,transparent);border-left:3px solid var(--c);margin-left:-15px}
/* filter + insight bar */
.ins{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:28px;margin:8px 0 26px;padding:20px 0;border-bottom:1px solid var(--rule)}
.ins h3{font:500 11px/1.3 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:0 0 10px}
.mix{display:flex;height:12px;border-radius:999px;overflow:hidden;background:var(--soft);margin-bottom:12px}
.mix i{display:block;background:var(--c)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font:500 12px/1 var(--sans);padding:7px 10px;border-radius:999px;background:var(--sheet);color:var(--ink-2);border:1px solid var(--rule);gap:6px}
.chip::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--c)}
.chip b{font:500 11px var(--mono);color:var(--mute)}
.chip:hover{background:var(--cb);color:var(--ink);border-color:var(--c)}
.chip.on{background:var(--c);color:var(--sheet);border-color:var(--c)}.chip.on::before{background:var(--sheet)}.chip.on b{color:var(--sheet)}
.fstat{font:12px var(--mono);color:var(--mute);margin:0 0 6px}.fstat a{cursor:pointer}
.promo.dim{display:none}
.tools{display:flex;gap:6px;margin-top:10px}
.tools button{padding:6px 10px;font:500 11.5px/1 var(--mono);background:transparent;color:var(--ink-2);border:1px solid var(--rule)}
.tools button:hover{background:var(--soft);color:var(--ink)}
.promo.focus{box-shadow:-6px 0 0 var(--hook)}
.kbd{font:11px var(--mono);color:var(--mute);margin:14px 0 0}.kbd kbd{font:11px var(--mono);border:1px solid var(--rule);border-bottom-width:2px;border-radius:3px;padding:1px 5px;background:var(--sheet)}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--ink);color:var(--on-night);font:13px var(--mono);padding:10px 16px;border-radius:var(--r);opacity:0;transition:opacity .2s;pointer-events:none}
.toast.on{opacity:1}
th.so{cursor:pointer}th.so:hover{color:var(--ink)}
@media(max-width:760px){.ins{grid-template-columns:1fr}.line.h,.line.c{margin-left:0}}
/* ---------- v2: angle chip, spoiler meter, measured results, search, compare, portfolio ---------- */
.ang{display:inline-flex;align-items:center;gap:6px;font:500 11.5px/1 var(--mono);letter-spacing:.04em;padding:5px 9px;border-radius:999px;
border:1px solid var(--rule);background:var(--sheet);color:var(--ink-2)}
.ang::before{content:"\\25C6";font-size:9px;color:var(--hook)}
.meas{display:block;margin-top:10px;font:500 12px var(--mono);padding:6px 9px;border:1px solid var(--ok);color:var(--ok);background:var(--ok-bg)}
.llmn{color:var(--ink-2);font-size:13.5px;margin:6px 0 0}.llmn b{font:500 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
.lstat{font:12.5px var(--mono);color:var(--mute);margin:0 0 18px;padding:10px 14px;border-left:3px solid var(--mark);background:var(--mark-bg)}
.lstat button{margin-left:10px;padding:5px 10px;font:500 12px var(--mono)}
.sbox{display:flex;gap:8px;margin:6px 0 10px}.sbox input{flex:1;font:16px var(--sans);padding:12px 14px;border:1px solid var(--ink);border-radius:var(--r);background:var(--sheet);color:var(--ink)}
.sugg{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:18px}.sugg button{padding:6px 10px;font:500 12px var(--sans);background:var(--sheet);color:var(--ink-2);border:1px solid var(--rule)}
.hit{display:grid;grid-template-columns:110px minmax(0,1fr) 220px;gap:20px;padding:18px 0;border-top:1px solid var(--rule)}
.hit .t{font:500 15px var(--mono)}.hit .t small{display:block;color:var(--mute);font-size:11.5px;margin-top:4px}
.hit .q{font-size:16px}.hit .w{font:12px var(--mono);color:var(--mute);margin-top:6px}
.hit .cl{font:13px var(--mono);border-left:1px solid var(--rule);padding-left:16px}.hit .cl button{margin-top:8px;padding:5px 9px;font:500 11.5px var(--mono)}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:10px}
.cmp>div{border:1px solid var(--rule);background:var(--sheet);padding:18px 20px}
.cmp h3{font:400 30px var(--serif);margin:0 0 8px}.cmp .tx{max-height:260px}
.cmpb{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}.cmpb button{padding:12px 18px}
.cmpb .q{background:var(--sheet);color:var(--ink);border:1px solid var(--rule)}
.pfh{font:500 12px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--hook-ink);margin:34px 0 -18px}
@media(max-width:760px){.hit{grid-template-columns:1fr;gap:6px}.hit .cl{border:0;padding:0}.cmp{grid-template-columns:1fr}}
@media print{.ins,.tools,.kbd{display:none}}
"""

JS = """
const D=JSON.parse(document.getElementById('data').textContent);
const fb=JSON.parse((()=>{try{return localStorage.getItem('pf_fb_'+D.show)||'{}'}catch(e){return '{}'}})());
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

const TYPES={
'physical/visual shock':{c:'phys',g:'\u26A1',l:'Visual shock',d:'Opens on a physical, on-screen action (slap, crash, grab) - reads with the sound off.'},
'shock line':{c:'shock',g:'!',l:'Shock line',d:'Opens on a line of dialogue built to startle - a confession, accusation or reveal.'},
'explosive emotion':{c:'emo',g:'\u2665',l:'Explosive emotion',d:'Opens at maximum emotional delivery (screaming, sobbing, rage).'},
'direct confrontation':{c:'conf',g:'\u2194',l:'Confrontation',d:'Opens with one character directly challenging another ("you...!").'},
'emotional open':{c:'open',g:'\u25CB',l:'Emotional open',d:'A softer open that builds feeling rather than shock - may need a strong cut.'},
'unanswered question':{c:'q',g:'?',l:'Unanswered question',d:'Cuts after a question whose answer the viewer is denied - strongest click-through driver.'},
'open question':{c:'oq',g:'?',l:'Open question',d:'Ends on a question, though the answer may be partly implied.'},
'threat / ticking clock':{c:'threat',g:'\u23F1',l:'Threat / ticking clock',d:'Ends on a threat or deadline - the viewer needs to know if it happens.'},
'interrupted line':{c:'int',g:'\u2026',l:'Interrupted line',d:'Cuts mid-sentence, so the thought is left hanging.'},
'reveal / sudden action':{c:'rev',g:'\u2737',l:'Reveal',d:'Cuts on a sudden reveal or action beat.'},
'emotional peak':{c:'peak',g:'\u25B2',l:'Emotional peak',d:'Cuts at the highest emotional moment rather than an open loop.'}};
function tv(t){const x=TYPES[t]||{c:'open',g:'\u2022',l:t,d:''};return `--c:var(--t-${x.c});--cb:var(--t-${x.c}-bg)`}
function badge(t,sm){const x=TYPES[t]||{g:'\u2022',l:t,d:''};return `<span class="bdg${sm?' sm':''}" style="${tv(t)}" title="${esc(x.d)}"><span class=g>${x.g}</span>${esc(x.l)}</span>`}
const F={hook:null,cut:null};
function insights(ps){const grp=(k,key)=>{const m={};ps.forEach(p=>{const t=p[k].type;m[t]=(m[t]||0)+1});
 const e=Object.entries(m).sort((a,b)=>b[1]-a[1]);
 return `<div class=mix>${e.map(([t,n])=>`<i style="${tv(t)};width:${n/ps.length*100}%" title="${esc((TYPES[t]||{l:t}).l)}: ${n}"></i>`).join('')}</div><div class=chips>${e.map(([t,n])=>`<button class="chip${F[key]==t?' on':''}" style="${tv(t)}" title="${esc((TYPES[t]||{d:''}).d)}" onclick="setF('${key}','${t.replace(/'/g,"\\\\'")}')">${esc((TYPES[t]||{l:t}).l)} <b>${n}</b></button>`).join('')}</div>`};
 return `<div class=ins><div><h3>How they open &middot; hook mix</h3>${grp('hook','hook')}</div><div><h3>How they end &middot; cut mix</h3>${grp('cliffhanger','cut')}</div></div><p class=fstat id=fstat></p>`}
function setF(k,t){F[k]=F[k]==t?null:t;renderTop()}
function copyTc(id){const p=D.top.find(x=>x.id==id);const t=p.segments.map(s=>`E${s.episode} ${s.start}-${s.end}`).join(' + ');
 (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>toast('Copied '+t),()=>toast(t))}
function toast(m){let e=document.getElementById('toast');if(!e){e=document.createElement('div');e.id='toast';e.className='toast';document.body.appendChild(e)}
 e.textContent=m;e.classList.add('on');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('on'),1800)}
const NAMES={hook:'Hook',cliff:'Cut',standalone:'Standalone',arc:'Intensity',premise:'Premise',spoiler_safe:'Spoiler-safe'};
function bars(c){return Object.keys(NAMES).filter(k=>k!='spoiler_safe'||c.spoiler_risk!=null).map(k=>{const v=k=='spoiler_safe'?1-c.spoiler_risk:c[k];
 return `<div title="${k=='spoiler_safe'?'1 = gives nothing away; low = shows a twist or the ending':''}"><span>${NAMES[k]}</span><span class=bar><i style="width:${Math.round(v*100)}%"></i></span><span class=num>${v.toFixed(2)}</span></div>`}).join('')}
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
return `<article class=promo id="${p.id}" aria-label="Promo ${p.rank}"><div class=p-rank><div class=rank>${p.rank}</div><div class=score>score <b>${p.score.toFixed(3)}</b></div>${p.rank==1&&!p.portfolio_angle?'<span class=top-pick>Top pick</span>':''}</div>
<div class=p-main><div class=tcs>${tcs}</div><div class=tools><button onclick="copyTc('${p.id}')" title="Copy timecodes for your edit">Copy timecodes</button><button onclick="location.hash='${p.id}';toast('Link set in address bar')">Link</button></div><div class=meta><span class=d>${p.duration_s.toFixed(1)} s</span><span class=sep></span><span>${kind}</span>${p.angle?`<span class=sep></span><span class=ang title="Strongest promo angle in this clip">${esc(p.angle.label)}</span>`:''}</div>${strip(p)}
<div class="line h" style="${tv(p.hook.type)}"><b>Hook</b><span>${esc(p.hook.text)} ${badge(p.hook.type)}</span></div>
<div class="line c" style="${tv(p.cliffhanger.type)}"><b>Cut on</b><span>${esc(p.cliffhanger.text)} ${badge(p.cliffhanger.type)}</span></div>
${p.cliffhanger.withheld_next_beat?`<div class=withheld>The viewer doesn't get to see: ${esc(p.cliffhanger.withheld_next_beat)}</div>`:''}
<p class=why>${esc(p.why_it_works)}</p><p class=reason>${esc(p.rank_reason)}</p>${p.llm_note?`<p class=llmn><b>LLM second opinion</b> ${esc(p.llm_note)}</p>`:''}
<details><summary>Transcript and source lines</summary><p class=mute style="font-size:12px;margin:10px 0 0;font-family:var(--mono)">${src}</p><div class=tx>${tx}</div></details></div>
<aside class=side aria-label="Scores for promo ${p.rank}"><div class=bars>${bars(p.components)}</div><div>${stab}<div class=flags>${p.risk_flags.map(x=>`<span class=flag>${esc(x)}</span>`).join('')}</div>${p.measured?`<span class=meas title="Measured on a real ad run (imported), not a model estimate">Measured: CTR ${(p.measured.ctr*100).toFixed(2)}% on ${Math.round(p.measured.impressions).toLocaleString()} impressions</span>`:''}</div>
<div class=fb role=group aria-label="Editor vote"><button class="${f=='up'?'sel-up':''}" onclick="vote('${p.id}','up',this)">Use</button><button class="${f=='down'?'sel-down':''}" onclick="vote('${p.id}','down',this)">Reject</button></div></aside></article>`}
function vote(id,v,el){fb[id]=v;try{localStorage.setItem('pf_fb_'+D.show,JSON.stringify(fb))}catch(e){}
 if(window.PF_SERVER){fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run:D.run||'',show:D.show,id:id,vote:v,components:(D.top.concat(D.longlist,D.portfolio||[])).find(p=>p.id==id).components})}).then(r=>r.json()).then(j=>{if(j.learning)toast(j.learning.message)}).catch(()=>{})}
 el.parentNode.querySelectorAll('button').forEach(b=>b.className='');el.className=v=='up'?'sel-up':'sel-down'}
// ---------- portfolio: best clip per angle, for A/B creative tests
function renderPortfolio(){const el=document.getElementById('port');if(!el)return;const ps=D.portfolio||[];
 el.innerHTML=ps.length?'<p class=reason style="margin:0 0 6px">One strong clip per angle, not overlapping each other: a ready set of creatives to A/B test against different audiences.</p>'+
 ps.map(p=>`<h3 class=pfh>${esc(p.angle.label)}</h3>`+card(p).replace('class=rank>'+p.rank+'<','class=rank>&#9670;<')).join(''):'<p class=mute>No portfolio in this run (made by an older version).</p>'}
// ---------- search
const SUGG=['betrayal','strong emotional confrontation','humiliation in public','tender romantic moment','a shocking reveal','someone threatens her','a rescue'];
function renderSearch(){const el=document.getElementById('search');if(!el)return;
 el.innerHTML=`<p class=reason style="margin:0 0 10px">Describe a moment in plain words. Each result comes with a promo-ready 20&ndash;60 s clip around it, cut at legal points and scored like the main list.</p>
 <form class=sbox onsubmit="doSearch(this.q.value);return false"><input name=q id=sq placeholder="e.g. she is humiliated in front of everyone" aria-label="Search the show"><button>Search</button></form>
 <div class=sugg>${SUGG.map(q=>`<button onclick="document.getElementById('sq').value='${q}';doSearch('${q}')">${q}</button>`).join('')}</div><div id=hits></div>`}
async function doSearch(q){const h=document.getElementById('hits');h.innerHTML='<p class=mute>Searching&hellip;</p>';
 try{const r=await fetch(`/r/${encodeURIComponent(D.run)}/search?q=${encodeURIComponent(q)}&k=10`);const j=await r.json();
  if(j.error){h.innerHTML=`<p class=mute>${esc(j.error)}</p>`;return}
  h.innerHTML=j.hits.length?j.hits.map(x=>{const c=x.clip;const tc=c?`E${c.episode} ${c.start}-${c.end}`:'';
   return `<div class=hit><div class=t>E${x.episode} ${x.at}<small>match ${x.score.toFixed(2)}</small></div><div><div class=q>${x.speaker?`<b>${esc(x.speaker)}</b>: `:''}${esc(x.text)}</div><div class=w>${esc(x.matched.join(' · '))}</div></div>
   <div class=cl>${c?`Promo clip<br><b>${esc(tc)}</b><br>${c.duration_s}s &middot; hook ${c.hook_pct.toFixed(2)} &middot; cut ${c.cliff_pct.toFixed(2)}<br><button onclick="navigator.clipboard&&navigator.clipboard.writeText('${tc}');toast('Copied ${tc}')">Copy timecodes</button>`:'<span class=mute>No legal 20-60 s window here</span>'}</div></div>`}).join(''):'<p class=mute>No matching moments. Try other words.</p>'}
 catch(e){h.innerHTML='<p class=mute>Search failed.</p>'}}
// ---------- A/B compare (active learning) + re-rank
let PAIR=null;
function mini(p,lab){return `<div><h3>${lab}</h3><div class=tcs>${p.segments.map(s=>`<span class=tc><b>E${s.episode}</b>${s.start}<i>&ndash;</i>${s.end}</span>`).join('<span class=plus>+</span>')}</div>
 <div class="line h" style="${tv(p.hook.type)};margin-top:14px"><b>Hook</b><span>${esc(p.hook.text)}</span></div><div class="line c" style="${tv(p.cliffhanger.type)}"><b>Cut on</b><span>${esc(p.cliffhanger.text)}</span></div>
 <div class=tx>${p.transcript.filter(l=>l.kind!='camera').slice(0,40).map(l=>`<p><span class=t>${l.start}</span>${l.kind=='dialogue'?`<span class=sp>${esc(l.speaker)}</span> ${esc(l.text)}`:`<span class=ac>${esc(l.text)}</span>`}</p>`).join('')}</div></div>`}
async function loadPair(){const el=document.getElementById('cmpbody');if(!el)return;el.innerHTML='<p class=mute>Choosing the most informative pair&hellip;</p>';
 try{const j=await (await fetch(`/r/${encodeURIComponent(D.run)}/pair`,{cache:'no-store'})).json();
  if(j.done){el.innerHTML='<p>You have compared every useful pair in this run. Thank you.</p>';return}
  PAIR=j;el.innerHTML=`<div class=cmp>${mini(j.a,'A')}${mini(j.b,'B')}</div><div class=cmpb><button onclick="judge('a')">A is the better promo</button><button onclick="judge('b')">B is the better promo</button><button class=q onclick="judge('tie')">About the same</button><button class=q onclick="loadPair()">Skip</button></div>
  <p class=mute style="font-size:12.5px">Keys: <kbd>1</kbd> A &middot; <kbd>2</kbd> B &middot; <kbd>0</kbd> same. The model currently thinks A wins with p=${j.p_a}; pairs are chosen where it is least sure, so each answer teaches the most.</p>`}
 catch(e){el.innerHTML='<p class=mute>Could not load a pair.</p>'}}
async function judge(w){if(!PAIR)return;const P=PAIR;PAIR=null;
 const r=await fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'pair',run:D.run,show:D.show,profile:(D.meta.audience_profile||{}).key||'general',winner:w,a:{id:P.a.id,components:P.a.components},b:{id:P.b.id,components:P.b.components}})});
 try{const j=await r.json();if(j.learning){document.getElementById('lstat').firstChild.textContent=j.learning.message}}catch(e){}loadPair()}
async function rerankNow(){const j=await (await fetch(`/r/${encodeURIComponent(D.run)}/rerank`,{cache:'no-store'})).json();
 const byId={};D.longlist.concat(D.top).forEach(p=>byId[p.id]=p);
 const ord=j.order.map(o=>Object.assign({},byId[o.id],{score:o.score,rank:0,prior_rank:o.prior_rank}));ord.forEach((p,i)=>p.rank=i+1);
 D.top=ord.slice(0,D.top.length);renderTop();tab('top');
 const W=j.learning.fitted,Dw=j.learning.default;toast('Re-ranked: '+Object.keys(W).map(k=>`${k} ${Dw[k]}\u2192${W[k]}`).join(', '))}
function renderCompare(){const el=document.getElementById('cmp');if(!el)return;const L=(D.meta.learned_weights||{});
 el.innerHTML=`<p class=lstat id=lstat><span>${esc(L.message||'Teach the ranking: pick the better promo of each pair.')}</span><button onclick="rerankNow()">Re-rank this run with what it has learned</button></p><div id=cmpbody></div>`;loadPair()}
document.addEventListener('keydown',e=>{if(!PAIR||e.target.matches('input,textarea')||document.getElementById('cmp').classList.contains('hide'))return;
 if(e.key=='1')judge('a');else if(e.key=='2')judge('b');else if(e.key=='0')judge('tie')});
function table(ps){return `<table><tr><th>#</th><th>Clip</th><th>Hook</th><th>Cut on</th><th>Angle</th><th class=so onclick="sortL()" title="Sort by score">Score &#8645;</th><th>Flags</th></tr>${ps.map(p=>`<tr><td>${p.rank}</td><td class=tc>${p.segments.map(s=>`E${s.episode} ${s.start}&ndash;${s.end}`).join('<br>')}</td><td>${esc(p.hook.text)}<br>${badge(p.hook.type,1)}</td><td>${esc(p.cliffhanger.text)}<br>${badge(p.cliffhanger.type,1)}</td><td>${p.angle?esc(p.angle.label):''}</td><td class=num>${p.score.toFixed(3)}</td><td>${p.risk_flags.map(esc).join('<br>')}</td></tr>`).join('')}</table>`}
function renderTop(){const vis=D.top.filter(p=>(!F.hook||p.hook.type==F.hook)&&(!F.cut||p.cliffhanger.type==F.cut));
 document.getElementById('top').innerHTML=insights(D.top)+vis.map(card).join('')+'<p class=kbd>Shortcuts: <kbd>J</kbd>/<kbd>K</kbd> next / previous promo &middot; <kbd>U</kbd> use &middot; <kbd>R</kbd> reject &middot; <kbd>C</kbd> copy timecodes</p>';
 const n=F.hook||F.cut;document.getElementById('fstat').innerHTML=n?`Showing ${vis.length} of ${D.top.length} promos &middot; <a onclick="F.hook=F.cut=null;renderTop()">clear filters</a>`:'Tap a colour to filter promos by how they open or end. Hover a badge to see what it means.'}
renderTop();
let LA=-1;function sortL(){LA=-LA;const l=D.longlist.slice().sort((a,b)=>LA*(a.score-b.score));document.getElementById('long').innerHTML='<div class=tbl>'+table(l)+'</div>'}
document.getElementById('long').innerHTML='<div class=tbl>'+table(D.longlist)+'</div>';
renderPortfolio();renderSearch();if(window.PF_SERVER&&document.getElementById('cmp'))renderCompare();
let FI=-1;document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea')||e.metaKey||e.ctrlKey)return;
 const cs=[...document.querySelectorAll('#top .promo')];if(!cs.length||document.getElementById('top').classList.contains('hide'))return;const k=e.key.toLowerCase();
 if(k=='j'||k=='k'){FI=Math.max(0,Math.min(cs.length-1,FI+(k=='j'?1:-1)));cs.forEach((c,i)=>c.classList.toggle('focus',i==FI));cs[FI].scrollIntoView({behavior:'smooth',block:'start'})}
 else if(FI>=0&&cs[FI]&&(k=='u'||k=='r')){const b=cs[FI].querySelectorAll('.fb button')[k=='u'?0:1];b.click();toast(k=='u'?'Marked: use':'Marked: reject')}
 else if(FI>=0&&cs[FI]&&k=='c')copyTc(cs[FI].id)});
const TABS=[...document.querySelectorAll('nav.tabs button')].map(b=>b.id.slice(2));
function tab(n){TABS.forEach(x=>{const on=x==n,b=document.getElementById('b_'+x);document.getElementById(x).classList.toggle('hide',!on);
 b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false');b.tabIndex=on?0:-1});document.getElementById('key').classList.toggle('hide',n!='top')}
document.querySelector('nav.tabs').addEventListener('keydown',e=>{const cur=TABS.findIndex(x=>document.getElementById('b_'+x).classList.contains('on'));
 const N=TABS.length;const i=e.key=='ArrowRight'?(cur+1)%N:e.key=='ArrowLeft'?(cur+N-1)%N:-1;if(i<0)return;e.preventDefault();tab(TABS[i]);document.getElementById('b_'+TABS[i]).focus()});
"""

METHOD = """<div class=method><div><p class=kicker>Method</p><h2>How these were chosen</h2></div><div>
<p>Every legal cut point in every episode is scored (a cut never splits a line of dialogue). All 20&ndash;60 s windows between cut points, plus cross-episode bridges and cold-open edits, are candidates.</p>
<ul><li><b>Hook</b> (first 3 s): weak supervision. Transparent labeling functions over action verbs, shock lines, delivery-tag intensity and confrontation, combined by a generative label model and a text classifier, cross-fitted by episode.</li>
<li><b>Cut</b> (last 6 s): open content (questions, threats, interrupted lines, reveals) plus the strength of the beat the viewer is denied, minus closure cues.</li>
<li><b>Standalone</b>: relationship words that explain the stakes, with penalties for mid-exchange openings, location jumps and names introduced in earlier episodes.</li>
<li><b>Intensity</b>: emotional peak, mean and escalation from delivery tags. <b>Premise</b>: how well the clip sells the show's title promise.</li></ul>
<p>The score is a weighted geometric mean, so a promo with no hook or no cut cannot rank high, adjusted for duration and a mild late-episode spoiler preference. Final picks don't overlap, take at most two per episode and differ in content.</p>
<ul><li><b>Spoiler-safe</b>: reveal cues (identity, culprit, "alive", confessions, arrests near the end) anchored to the episode loglines. Reveals the <i>title</i> already promises are treated as a premise payoff, not a spoiler. Your spoiler setting decides how hard clear reveals are penalised.</li>
<li><b>Angle and audience</b>: each clip gets an angle (romance, revenge, power reveal, danger, mystery, family, humor). An audience profile nudges close calls toward its angles (at most &plusmn;15%); the Portfolio tab gives one clip per angle for A/B tests.</li>
<li><b>Learning</b>: Use/Reject votes and A/B comparisons fit the weights of this same formula (Bradley&ndash;Terry with a prior at the defaults). Learned weights are applied automatically once there are enough judgments.</li></ul>
<p>Flags mark known failure modes. Scores are model estimates of promo quality, not predicted click-through: only imported ad results (marked <i>Measured</i>) are real audience data.</p></div></div>"""


def html_report(show, meta, top, longlist, server=False, run_id="", portfolio=None, searchable=False):
    slim_meta = {k: meta.get(k) for k in ("audience_profile", "spoiler_tolerance", "learned_weights", "llm_used", "weights_used")}
    data = json.dumps({"show": show, "run": run_id, "top": top, "longlist": longlist, "portfolio": portfolio or [], "meta": slim_meta},
                      ensure_ascii=False).replace("</", "<\\/")
    stats = [("Episodes", f"{meta['n_episodes']}"), ("Minutes of story", f"{float(meta['runtime_minutes']):.1f}"),
             ("Clips scored", f"{meta['n_candidates']:,}"), ("Shortlisted", f"{len(top)}")]
    if meta.get("audience_profile"):
        stats.append(("Audience", (meta["audience_profile"] or {}).get("label", "General").split(" (")[0]))
    if meta.get("spoiler_tolerance"):
        stats.append(("Spoilers", str(meta["spoiler_tolerance"]).title()))
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
<nav class=tabs role=tablist aria-label="Result views">{tab_btn('top', 'Top', len(top), True)}{tab_btn('long', 'Longlist', len(longlist), False)}{tab_btn('port', 'Portfolio', len(portfolio or []), False) if portfolio else ''}{tab_btn('search', 'Search', '', False) if (server and searchable) else ''}{tab_btn('cmp', 'Compare A/B', '', False) if server else ''}{tab_btn('method', 'Method', '', False)}</nav></div></header>
<main><p class=key id=key><span><i class=sw-h></i>Hook window, first 3 s</span><span><i class=sw-c></i>Cut, last 6 s</span><span><i class=sw-m></i>In and out points</span></p>
<div id=top role=tabpanel aria-labelledby=b_top></div><div id=long class=hide role=tabpanel aria-labelledby=b_long></div>{'<div id=port class=hide role=tabpanel aria-labelledby=b_port></div>' if portfolio else ''}{'<div id=search class=hide role=tabpanel aria-labelledby=b_search></div>' if (server and searchable) else ''}{'<div id=cmp class=hide role=tabpanel aria-labelledby=b_cmp></div>' if server else ''}<div id=method class=hide role=tabpanel aria-labelledby=b_method>{METHOD}</div></main>
<footer class=foot><span>{BRAND} {html.escape(str(meta.get('version', '')))}, run {html.escape(str(meta.get('run_at', '')))}</span><span>Timecodes are episode-relative. Every cut lands between lines of dialogue.</span></footer>
<script id=data type="application/json">{data}</script><script>window.PF_SERVER={'true' if server else 'false'};{JS}</script></body></html>"""
