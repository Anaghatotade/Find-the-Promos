"""Human-readable hook / cliffhanger / why / rank explanations, derived from the
same features that produced the score (no free-text generation needed)."""
from __future__ import annotations
import re
from typing import List, Dict
from .parser import fmt_ts
from .features import overlapping, HOOK_SPAN, CLIFF_SPAN
from . import lexicons as L


PHYSICAL = re.compile(r"\b(slap\w*|strik\w*|struck|punch\w*|shov\w*|grab\w*|seiz\w*|throw\w*|threw|hurl\w*|smash\w*|"
                      r"shatter\w*|explod\w*|explosion|burst\w*|kick\w*|drag\w*|chok\w*|stab\w*|blood\w*|collaps\w*|"
                      r"crash\w*|slam\w*|lunge\w*|yank\w*|rip\w*|whip\w*|brand\w*)\b", re.I)


def _q(t, n=90):
    t = t.strip()
    return f"“{t if len(t) <= n else t[:n - 1] + '…'}”"


def hook_info(c, eps) -> Dict:
    sg = c.segments[0]; ep = eps[sg.episode]; f = c.hook.feats
    bs = overlapping(ep.blocks, sg.start, min(sg.start + HOOK_SPAN, sg.end))
    dia = [b for b in bs if b.kind == "dialogue"]
    vis = [b for b in bs if b.kind in ("action", "camera") and PHYSICAL.search(b.text)]
    if f["h_action_lex"] and vis:
        typ = "physical/visual shock"
    elif f["h_line_lex"]:
        typ = "shock line"
    elif f["h_arousal_max"] >= 0.8:
        typ = "explosive emotion"
    elif f["h_you"] and (f["h_excl"] or f["h_question"]):
        typ = "direct confrontation"
    else:
        typ = "emotional open"
    if dia:
        b = dia[0]; text = f"{b.speaker.title()}: {_q(b.text)}"
        if len(dia) > 1 and dia[1].start < sg.start + HOOK_SPAN:
            text += f" → {dia[1].speaker.title()}: {_q(dia[1].text, 60)}"
    elif vis:
        b = vis[0]; text = f"[visual] {b.text[:110]}"
    else:
        b = bs[0] if bs else None; text = f"[visual] {b.text[:110]}" if b else ""
    return {"type": typ, "at": fmt_ts(sg.start), "episode": sg.episode, "text": text,
            "score_pct": round(c.comps["hook"], 3)}


def cliff_info(c, eps) -> Dict:
    sg = c.segments[-1]; ep = eps[sg.episode]; f = c.cliff.feats
    bs = overlapping(ep.blocks, sg.end - CLIFF_SPAN, sg.end)
    dia = [b for b in bs if b.kind == "dialogue"]
    act = [b for b in bs if b.kind == "action"]
    last = dia[-1] if dia else None
    if f.get("c_pending_answer"):
        typ = "unanswered question"
    elif f["c_last_q"]:
        typ = "open question"
    elif last and re.search(r"\b(will|before|until|tomorrow|tonight|gallows|burn|execute|dead|kill|never)\b", last.text, re.I):
        typ = "threat / ticking clock"
    elif f["c_last_ellipsis"]:
        typ = "interrupted line"
    elif f["c_action_lex"]:
        typ = "reveal / sudden action"
    else:
        typ = "emotional peak"
    text = f"{last.speaker.title()}: {_q(last.text)}" if last else (f"[visual] {act[-1].text[:110]}" if act else "")
    # what the viewer is denied (next beat after the cut) - useful for the editor
    nxt = [b for b in ep.blocks if b.kind == "dialogue" and b.start >= sg.end - 0.05][:1]
    if not nxt and (sg.episode + 1) in eps:
        nxt = [b for b in eps[sg.episode + 1].blocks if b.kind == "dialogue"][:1]
    withheld = f"{nxt[0].speaker.title()}: {_q(nxt[0].text, 70)}" if nxt else ""
    return {"type": typ, "at": fmt_ts(sg.end), "episode": sg.episode, "text": text,
            "withheld_next_beat": withheld, "payoff_strength": round(f.get("c_payoff", 0.0), 3),
            "score_pct": round(c.comps["cliff"], 3)}


def why(c, h, k) -> str:
    rel = sorted({m.lower() for m in L.RELATIONAL.findall(c.text)})[:3]
    ctx = (f"stakes are legible cold ({', '.join(rel)})" if rel and c.comps["standalone"] >= 0.6
           else "stakes are legible cold" if c.comps["standalone"] >= 0.6 else "needs a little context")
    tail = {"unanswered question": "cuts before the answer",
            "open question": "cuts on an open question",
            "threat / ticking clock": "cuts on a threat",
            "interrupted line": "cuts mid-thought",
            "reveal / sudden action": "cuts on a sudden reveal",
            "emotional peak": "cuts at the emotional peak"}[k["type"]]
    co = " Cold-open edit: hook moment placed before the story beat." if c.kind == "cold_open" else ""
    return f"Opens on {h['type']} in the first 3s, {ctx}, and {tail}.{co}"


def rank_reason(c, rank, pool_med) -> str:
    strong = [k for k in ("hook", "cliff", "standalone", "arc", "premise") if c.comps[k] >= max(pool_med.get(k, 0), 0.75)]
    names = {"hook": "hook", "cliff": "cliffhanger", "standalone": "standalone clarity", "arc": "emotional intensity",
             "premise": "sells the show's premise"}
    s = ", ".join(names[k] for k in strong) or "balanced profile"
    ep = c.segments[0].episode
    funnel = " Early episode: viewers who tap through land near the start of the story." if ep <= 5 else ""
    st = c.comps.get("stability")
    conf = "" if st is None else (f" Robust pick: stays in the top list under {st:.0%} of alternative weightings." if st >= 0.9 else
                                  f" Likely pick: survives {st:.0%} of alternative weightings." if st >= 0.6 else
                                  f" Borderline: only {st:.0%} of alternative weightings keep it - worth a human look.")
    return f"Ranked #{rank}: top on {s}.{funnel}{conf}"


def transcript(c, eps, include_camera=False) -> List[Dict]:
    out = []
    for sg in c.segments:
        ep = eps[sg.episode]
        for b in overlapping(ep.blocks, sg.start, sg.end):
            if b.kind == "camera" and not include_camera:
                continue
            out.append({"episode": sg.episode, "start": fmt_ts(b.start), "end": fmt_ts(b.end), "kind": b.kind,
                        "speaker": b.speaker, "tags": b.tags, "text": b.text, "src_file": b.src_file,
                        "src_line": b.src_line})
    return out
